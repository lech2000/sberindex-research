"""A6 threshold review (offline): sensitivity of the M2 recognition
thresholds and a K=5 look at the archived K=2.

Input: frozen panel (--panel) + one archived base run (--base-run holding
assignments.parquet, calibration.json). Shares/z come from a6_temporal
build_monthly_shares / standardize_frozen; the archived per-month labels are
aligned to the (tid, month) grid of the panel mask; centres are MEMBER MEANS
of Z over each archived cluster's members (the fitted k-means centres up to
floating point).

1) Sweep: a6_identities.track_identities re-run with overlap_threshold T and
candidate_margin M times {0.75, 1, 1.25} (9 settings). The base resemblance
floor Tc is read from the archive calibration and kept CONSTANT on all 9
settings (hard-asserted equal to the expected base value
0.17395474720266485 = q50 of the 2023 cross-cluster bootstrap scores) and is
never swept; every setting must satisfy 0 <= Tc < T. Per-row statuses and
identity IDs are compared to the archive; the (1, 1) setting must match the
archive EXACTLY, and a mismatch raises before any output is written.
threshold_sweep.csv: 9 rows -- event-kind counts, ambiguous assignment rows,
assignment_jaccard (Jaccard of (territory_id, month, status, identity_id)
tuple sets vs the archive), ambiguous_jaccard (Jaccard of the ambiguous-only
(territory_id, month) coordinate sets vs the archive), status-match and
ID-match fractions.

2) K5 vs K2: each month refit with a6_identities.fit_month (k=5, seed
20260926; random_state = seed + month_idx + k per the fit_month source) on
the same Z (the archived grid chose K=2 in all 24 months). Silhouettes of
BOTH labelings on the same <=400-row subsample per month (rng seeded
20260926+m); ARI/NMI on all rows; per-month values and means in metrics.json
and comparison2vs5.csv. raw_s_profiles.csv: per month x grouping (2/5) x
group -- member count and 5 raw-share feature means; groups stay anonymous
integers and no economic type is invented.

Status: PARTIAL_NOT_GATE_PASS -- sensitivity evidence only: no gate pass, no
case closure, every tracked event stays an algorithmic candidate.

Outputs in --outdir (fresh dir only, nonempty refused): threshold_sweep.csv,
comparison2vs5.csv, raw_s_profiles.csv, metrics.json, manifest.json.

Usage:
  python src/a6_threshold_review.py --panel data/panel_v1.parquet \\
      --base-run runs/A6_v2 --outdir runs/A6_threshold_review
  python src/a6_threshold_review.py --self-check

Deps: numpy, pandas, scikit-learn. --self-check is dependency-light
(constant threshold / ambiguous-set invariants); if deps are unavailable it
degrades to py_compile only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    import numpy as np
    import pandas as pd
except Exception:  # --self-check must load even without the data stack
    np = pd = None

ATLAS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ATLAS_DIR / "data" / "panel_v1.parquet"
DEFAULT_BASE_RUN = ATLAS_DIR / "runs" / "A6_v2"
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A6_threshold_review"
SEED, SIL_CAP, K_REVIEW = 20260926, 400, 5
RESEMBLANCE_FLOOR = 0.17395474720266485
EXPECTED_OVERLAP_THRESHOLD = 0.27716275979336036
SWEEP_FACTORS = (0.75, 1.0, 1.25)
STATUS = "PARTIAL_NOT_GATE_PASS"
EVENT_KINDS = ("initial", "continuing", "reemergence", "birth",
               "birth_candidate", "ambiguous", "conflict", "dormant",
               "disappearance")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _jaccard(a: set, b: set) -> float:
    union = len(a | b)
    return float(len(a & b) / union) if union else 1.0


def pkg_ver(name: str):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def run_review(panel: pd.DataFrame, panel_path: Path, base_run: Path,
               outdir: Path) -> dict:
    from a6_identities import fit_month, track_identities
    from a6_temporal import (SHARE_CATS, build_monthly_shares,
                             standardize_frozen)
    from sklearn.metrics import (adjusted_rand_score,
                                 normalized_mutual_info_score,
                                 silhouette_score)

    tids, months, S, share_audit = build_monthly_shares(panel)
    n_tids, n_months = int(len(tids)), len(months)
    Z, _std_audit = standardize_frozen(S, months)
    features = list(SHARE_CATS)
    if len(features) != int(S.shape[2]):
        raise ValueError("a6_temporal SHARE_CATS must name every S feature")
    if not (bool(np.isfinite(S).all()) and bool(np.isfinite(Z).all())):
        raise ValueError("S and Z must be all finite")

    assign_path = base_run / "assignments.parquet"
    calib_path = base_run / "calibration.json"
    base = pd.read_parquet(assign_path)
    cal = json.loads(calib_path.read_text(encoding="utf-8"))
    T0, M0 = float(cal["overlap_threshold"]), float(cal["candidate_margin"])
    tc = float(cal["resemblance_floor"])
    if tc != RESEMBLANCE_FLOOR:
        raise ValueError(f"base run: resemblance_floor {tc!r} != expected "
                         f"base value {RESEMBLANCE_FLOOR!r}")
    for ft in SWEEP_FACTORS:
        if not (0.0 <= tc < T0 * ft):
            raise ValueError(f"resemblance floor must satisfy 0 <= Tc < T on "
                             f"all settings; Tc={tc} vs T={T0 * ft} "
                             f"(f_overlap={ft})")

    tid_pos = {int(t): i for i, t in enumerate(tids.tolist())}
    month_pos = {mo: i for i, mo in enumerate(months)}
    if len(base) != n_tids * n_months or bool(base.duplicated(
            subset=["territory_id", "month"]).any()):
        raise ValueError("base run: assignments must cover each (tid, month) "
                         "of the panel mask exactly once")
    if "k" not in base.columns or not (
            base["k"].astype(int).to_numpy() == 2).all():
        raise ValueError("base run: k column must be exactly 2 in every row")
    b_ti = base["territory_id"].astype(int).map(tid_pos).to_numpy()
    b_mi = base["month"].astype(str).map(month_pos).to_numpy()
    if bool(pd.isna(b_ti).any()) or bool(pd.isna(b_mi).any()):
        raise ValueError("base run: assignment rows outside the panel grid")
    b_ti, b_mi = b_ti.astype(int), b_mi.astype(int)

    lab2 = np.zeros((n_months, n_tids), dtype=int)
    base_status = np.full((n_months, n_tids), "", dtype=object)
    base_iid = np.full((n_months, n_tids), "", dtype=object)
    lab2[b_mi, b_ti] = base["label"].to_numpy(dtype=int)
    base_status[b_mi, b_ti] = base["status"].fillna("").astype(str).to_numpy()
    base_iid[b_mi, b_ti] = base["identity_id"].fillna("").astype(str).to_numpy()
    for m in range(n_months):
        labs = sorted(set(lab2[m].tolist()))
        if labs != [0, 1]:
            raise ValueError(f"base run: labels must be contiguous 0..1 for "
                             f"k=2 every month; {months[m]} has {labs}")

    labels_per_month = [lab2[m] for m in range(n_months)]
    centres_per_month = []
    for m in range(n_months):
        X, lab = Z[:, m, :], labels_per_month[m]
        cent = np.zeros((int(lab.max()) + 1, X.shape[1]), dtype=float)
        for c in range(cent.shape[0]):
            mem = lab == c
            if bool(mem.any()):
                cent[c] = X[mem].mean(axis=0)
        centres_per_month.append(cent)

    base_tuples = {(int(ti), months[mi], base_status[mi, ti], base_iid[mi, ti])
                   for mi in range(n_months) for ti in range(n_tids)}
    base_ambiguous = {(int(ti), months[mi]) for mi in range(n_months)
                      for ti in range(n_tids)
                      if base_status[mi, ti] == "ambiguous"}
    sweep_rows, baseline_exact = [], False
    for ft in SWEEP_FACTORS:
        for fm in SWEEP_FACTORS:
            rows, _regions, events = track_identities(
                months, labels_per_month, centres_per_month, Z, tids,
                T0 * ft, M0 * fm, tc)
            if len(rows) != n_tids * n_months:
                raise ValueError("track_identities: incomplete (tid, month) "
                                 "grid")
            run_status = np.full((n_months, n_tids), "", dtype=object)
            run_iid = np.full((n_months, n_tids), "", dtype=object)
            for r in rows:
                mi = month_pos[r["month"]]
                run_status[mi, int(r["ti"])] = r["status"]
                run_iid[mi, int(r["ti"])] = r["identity_id"] or ""
            run_tuples = {(int(ti), months[mi], run_status[mi, ti],
                           run_iid[mi, ti])
                          for mi in range(n_months) for ti in range(n_tids)}
            run_ambiguous = {(int(ti), months[mi]) for mi in range(n_months)
                             for ti in range(n_tids)
                             if run_status[mi, ti] == "ambiguous"}
            rec = {"f_overlap": float(ft), "f_margin": float(fm),
                   "overlap_threshold": T0 * ft, "candidate_margin": M0 * fm,
                   "resemblance_floor": tc}
            for kind in EVENT_KINDS:
                rec[f"n_{kind}"] = int(sum(1 for e in events
                                           if e["kind"] == kind))
            rec["ambiguous_rows"] = int(np.sum(run_status == "ambiguous"))
            rec["assignment_jaccard"] = _jaccard(run_tuples, base_tuples)
            rec["ambiguous_jaccard"] = _jaccard(run_ambiguous, base_ambiguous)
            rec["status_match"] = float(np.mean(run_status == base_status))
            rec["id_match"] = float(np.mean(run_iid == base_iid))
            exact = rec["status_match"] == 1.0 and rec["id_match"] == 1.0
            rec["exact_vs_archive"] = bool(exact)
            if ft == 1.0 and fm == 1.0:
                baseline_exact = bool(exact)
                if not baseline_exact:
                    raise RuntimeError(
                        "baseline (1, 1) does not reproduce the archive "
                        "exactly; aborting before any output is written")
            sweep_rows.append(rec)

    k_compare, k5_per_month = [], []
    for m, month in enumerate(months):
        lab5, _ = fit_month(Z[:, m, :], m, SEED, K_REVIEW)
        k5_per_month.append(lab5)
        n = min(n_tids, SIL_CAP)
        rng = np.random.default_rng(SEED + m)
        idx = (rng.choice(n_tids, size=n, replace=False) if n < n_tids
               else np.arange(n_tids))
        Xs = Z[idx, m, :]
        try:
            sil2 = float(silhouette_score(Xs, labels_per_month[m][idx]))
            sil5 = float(silhouette_score(Xs, lab5[idx]))
        except ValueError:
            sil2 = sil5 = float("nan")
        k_compare.append({"month": month, "sil_k2_archive": sil2, "sil_k5": sil5,
                          "ari_k2_vs_k5": float(adjusted_rand_score(
                              labels_per_month[m], lab5)),
                          "nmi_k2_vs_k5": float(normalized_mutual_info_score(
                              labels_per_month[m], lab5)),
                          "n_sil_rows": int(n)})

    prof_rows = []
    for k_val, labs in ((2, labels_per_month), (K_REVIEW, k5_per_month)):
        for m, month in enumerate(months):
            for g in sorted(set(labs[m].tolist())):
                mem = labs[m] == g
                rec = {"month": month, "k": int(k_val), "group": int(g),
                       "n": int(mem.sum())}
                for fi, fname in enumerate(features):
                    rec[f"mean_{fname}"] = float(S[mem, m, fi].mean())
                prof_rows.append(rec)

    outdir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(sweep_rows).to_csv(outdir / "threshold_sweep.csv", index=False)
    pd.DataFrame(k_compare).to_csv(outdir / "comparison2vs5.csv", index=False)
    pd.DataFrame(prof_rows).to_csv(outdir / "raw_s_profiles.csv", index=False)

    def mean_of(key):
        return float(np.nanmean([row[key] for row in k_compare]))

    metrics = {
        "gate": "A6", "component": "threshold_review", "status": STATUS,
        "gate_pass": False,
        "gate_pass_reason": "offline threshold-sensitivity review; statuses "
        "and events remain algorithmic candidates from geometric overlap, "
        "never verified economic changes; no case closure",
        "completes_case06": False, "economic_types_invented": False,
        "seed": SEED,
        "mask": {"n": n_tids, "n_months": n_months,
                 "n_excluded": share_audit["n_excluded"]},
        "calibration_base": {
            "overlap_threshold": T0, "candidate_margin": M0,
            "resemblance_floor_constant": tc,
            "resemblance_floor_expected_base": RESEMBLANCE_FLOOR,
            "resemblance_floor_preserved": bool(tc == RESEMBLANCE_FLOOR),
            "resemblance_floor_rule": "Tc read from the base calibration.json "
            "and kept constant on all settings; hard-asserted equal to the "
            "expected base value; 0 <= Tc < T enforced per setting"},
        "sweep": {
            "factors": [float(f) for f in SWEEP_FACTORS],
            "n_settings": len(sweep_rows),
            "baseline_exact_repro": bool(baseline_exact),
            "assignment_jaccard_definition": "Jaccard of (territory_id, "
            "month, status, identity_id) tuple sets, sweep vs archive",
            "ambiguous_jaccard_definition": "Jaccard of ambiguous-only "
            "(territory_id, month) coordinate sets, sweep vs archive",
            "settings": sweep_rows},
        "k5_vs_k2": {
            "archive_k": 2, "review_k": K_REVIEW,
            "fit": "a6_identities.fit_month on the same frozen Z, "
            "random_state = seed + month_idx + k per the fit_month source "
            "(checked 2026-09-27; the variant seed+month_idx*137+k*1009 is "
            "not present in the helper), seed 20260926",
            "silhouette_rows": "same <=400-row subsample per month for both "
            "labelings, rng seeded 20260926+m",
            "ari_nmi_rows": "all rows of the month",
            "per_month": k_compare,
            "per_month_csv": "comparison2vs5.csv",
            "sil_k2_mean": mean_of("sil_k2_archive"),
            "sil_k5_mean": mean_of("sil_k5"),
            "ari_mean": mean_of("ari_k2_vs_k5"),
            "nmi_mean": mean_of("nmi_k2_vs_k5")},
        "raw_s_profiles": "raw_s_profiles.csv: per month x grouping (2/5) x "
        "group member counts and 5 raw-share feature means; groups are "
        "anonymous integers",
    }
    with open(outdir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    manifest = {
        "gate": "A6", "component": "threshold_review", "status": STATUS,
        "gate_pass": False, "completes_case06": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {"file": Path(__file__).name,
                 "sha256": sha256_file(Path(__file__)),
                 "a6_identities.py": sha256_file(SRC_DIR / "a6_identities.py"),
                 "a6_temporal.py": sha256_file(SRC_DIR / "a6_temporal.py")},
        "inputs": {
            "panel": {"path": str(panel_path), "rows": int(len(panel)),
                      "sha256": sha256_file(panel_path)},
            "base_assignments": {"path": str(assign_path),
                                 "rows": int(len(base)),
                                 "sha256": sha256_file(assign_path)},
            "base_calibration": {"path": str(calib_path),
                                 "sha256": sha256_file(calib_path)}},
        "limitations": [
            "2023 outputs are retrospective vs the frozen-2024 check: the "
            "frozen scaler pools ALL 2023 months and the calibration pools "
            "ALL 2023 months, so later-2023 months inform early-2023 "
            "z-scores, thresholds and labels; causality-relevant months are "
            "2024+, strictly after the frozen fit/calibration (base "
            "calibration.json retrospective_note)."],
        "versions": {"python": sys.version.split()[0],
                     "numpy": pkg_ver("numpy"), "pandas": pkg_ver("pandas"),
                     "scipy": pkg_ver("scipy"),
                     "scikit-learn": pkg_ver("scikit-learn")},
        "params": {"seed": SEED,
                   "sweep_factors": [float(f) for f in SWEEP_FACTORS],
                   "overlap_threshold_base": T0, "candidate_margin_base": M0,
                   "resemblance_floor_constant": tc,
                   "resemblance_floor_expected_base": RESEMBLANCE_FLOOR,
                   "resemblance_floor_rule": "Tc read from the base "
                   "calibration.json, kept constant on all settings; "
                   "0 <= Tc < T enforced per setting",
                   "fit_month_seed": "a6_identities.fit_month random_state = "
                   "seed + month_idx + k (read from the helper source "
                   "2026-09-27; seed+month_idx*137+k*1009 not present)",
                   "review_k": K_REVIEW, "silhouette_cap": SIL_CAP,
                   "silhouette_subsample_seed": "20260926 + month_index",
                   "centres": "member means of Z over archived members"},
        "baseline_exact_repro": bool(baseline_exact),
    }
    with open(outdir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return {"sweep_rows": sweep_rows, "baseline_exact_repro": baseline_exact,
            "k_compare_summary": {k: metrics["k5_vs_k2"][k] for k in (
                "sil_k2_mean", "sil_k5_mean", "ari_mean", "nmi_mean")},
            "n_mask": n_tids, "n_months": n_months, "outdir": str(outdir)}


def self_check() -> int:
    import py_compile

    deps_ok = True
    try:
        import numpy  # noqa: F401
        import pandas  # noqa: F401
        import sklearn  # noqa: F401
    except Exception:
        deps_ok = False
    if not deps_ok:
        py_compile.compile(str(Path(__file__)), doraise=True)
        print("self-check: deps unavailable -> py_compile only")
        return 0

    fails = []

    def check(name: str, cond: bool) -> None:
        if not cond:
            fails.append(name)

    check("tc_unit_interval", 0.0 <= RESEMBLANCE_FLOOR < 1.0)
    check("sweep_factors_positive", all(f > 0 for f in SWEEP_FACTORS))
    check("baseline_factor_present", 1.0 in SWEEP_FACTORS)
    check("tc_below_T_all_settings", all(
        0.0 <= RESEMBLANCE_FLOOR < EXPECTED_OVERLAP_THRESHOLD * f
        for f in SWEEP_FACTORS))
    check("jaccard_self", _jaccard({(1, "m"), (2, "m")},
                                   {(1, "m"), (2, "m")}) == 1.0)
    check("jaccard_disjoint", _jaccard({(1, "m")}, {(2, "m")}) == 0.0)
    check("jaccard_both_empty", _jaccard(set(), set()) == 1.0)
    check("jaccard_one_empty", _jaccard({(1, "m")}, set()) == 0.0)
    check("jaccard_partial", abs(
        _jaccard({(1, "m"), (2, "m")}, {(2, "m"), (3, "m")}) - 1 / 3) < 1e-12)

    for name in fails:
        print(f"self-check FAIL: {name}")
    print(f"self-check: {len(fails)} FAIL" if fails else "self-check: ALL PASS")
    return 1 if fails else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEFAULT_PANEL))
    p.add_argument("--base-run", default=str(DEFAULT_BASE_RUN))
    p.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    p.add_argument("--self-check", action="store_true",
                   help="dependency-light constant threshold / ambiguous-set "
                        "invariants; py_compile only if deps are unavailable")
    args = p.parse_args(argv)
    if args.self_check:
        return self_check()
    if np is None or pd is None:
        p.error("numpy/pandas are required for a real run (--self-check "
                "works without them)")

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()):
        p.error(f"refusing to overwrite nonempty existing archive: {outdir}")
    panel_path, base_run = Path(args.panel), Path(args.base_run)
    if not (base_run / "assignments.parquet").is_file() or not (
            base_run / "calibration.json").is_file():
        p.error(f"--base-run must hold assignments.parquet and "
                f"calibration.json: {base_run}")

    res = run_review(pd.read_parquet(panel_path), panel_path, base_run, outdir)
    print(f"A6 threshold review: mask_n={res['n_mask']} "
          f"months={res['n_months']}")
    print(f"  baseline (1,1) exact vs archive: {res['baseline_exact_repro']}")
    for row in res["sweep_rows"]:
        print(f"  T*{row['f_overlap']:.2f} M*{row['f_margin']:.2f}: "
              f"status_match={row['status_match']:.4f} "
              f"id_match={row['id_match']:.4f} "
              f"assignment_jaccard={row['assignment_jaccard']:.4f} "
              f"ambiguous_jaccard={row['ambiguous_jaccard']:.4f} "
              f"ambiguous_rows={row['ambiguous_rows']}")
    kc = res["k_compare_summary"]
    print(f"  k5 vs archived k2: sil2={kc['sil_k2_mean']:.4f} "
          f"sil5={kc['sil_k5_mean']:.4f} ARI={kc['ari_mean']:.4f} "
          f"NMI={kc['nmi_mean']:.4f}")
    print(f"outdir={res['outdir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
