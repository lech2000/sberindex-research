"""A6-holdout-bootstrap: cluster bootstrap on 2024 holdout sensitivity.

Resamples MUNICIPALITIES (not rows) from archived base and variant
(M_factor=0.75/1.25) assignments. M_factor=1.0 must exactly reproduce base.
Each replicate: 1896 municipalities with replacement, ALL 12 months each.
Hard reject: duplicate or missing (territory_id, month) keys.

Usage:
  python src/a6_holdout_bootstrap.py --panel data/panel_v1.parquet \\
      --base-run runs/A6_v2 --outdir runs/A6_bootstrap
  python src/a6_holdout_bootstrap.py --self-check
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from a6_temporal import build_monthly_shares, sha256_file, pkg_version
from a6_holdout_sensitivity import run_holdout, _ms, _validate_archived, \
    _toy_panel

ATLAS = Path(__file__).resolve().parents[1]
DEF_PANEL = ATLAS / "data" / "panel_v1.parquet"
M_FACTORS = (0.75, 1.0, 1.25)
YEAR = "2024"
N_MUNI = 1896
N_MONTHS = 12
EXPECTED_ROWS = N_MUNI * N_MONTHS


def _join_variant_to_base(base_24, var_df):
    _validate_archived(base_24)
    _validate_archived(var_df)
    b = base_24[["territory_id", "month", "status", "identity_id"]].copy()
    b = b.rename(columns={"status": "status_base",
                           "identity_id": "identity_id_base"})
    v = var_df[["territory_id", "month", "status", "identity_id"]].copy()
    v = v.rename(columns={"status": "status_var",
                           "identity_id": "identity_id_var"})
    for d in (b, v):
        d["territory_id"] = d["territory_id"].astype(int)
        d["month"] = d["month"].astype(str)
    b_keys = set(zip(b["territory_id"], b["month"]))
    v_keys = set(zip(v["territory_id"], v["month"]))
    miss_v = b_keys - v_keys
    miss_b = v_keys - b_keys
    if miss_v:
        raise ValueError(f"variant missing {len(miss_v)} keys "
                         f"(e.g. {sorted(miss_v)[:5]})")
    if miss_b:
        raise ValueError(f"base missing {len(miss_b)} keys "
                         f"(e.g. {sorted(miss_b)[:5]})")
    m = b.merge(v, on=["territory_id", "month"], how="inner")
    if len(m) != len(b):
        raise ValueError(f"join rows {len(m)} != base {len(b)}")
    m["changed_status"] = (m["status_base"] != m["status_var"]).astype(int)
    m["changed_identity_id"] = (
        m["identity_id_base"] != m["identity_id_var"]).astype(int)
    m["changed_either"] = (
        (m["changed_status"] | m["changed_identity_id"]) > 0).astype(int)
    return m


def _fractions(m):
    n = len(m)
    return {"n": int(n),
            "frac_changed_status": float(m["changed_status"].sum()) / n,
            "frac_changed_id": float(m["changed_identity_id"].sum()) / n,
            "frac_changed_either": float(m["changed_either"].sum()) / n,
            "count_changed_status": int(m["changed_status"].sum()),
            "count_changed_id": int(m["changed_identity_id"].sum()),
            "count_changed_either": int(m["changed_either"].sum())}


def _per_month(m):
    return {mo: {"n": len(g),
                 "count_changed_status": int(g["changed_status"].sum()),
                 "count_changed_id": int(g["changed_identity_id"].sum()),
                 "count_changed_either": int(g["changed_either"].sum())}
            for mo, g in m.groupby("month")}


def _muni_dist(m):
    vals, counts = np.unique(
        m.groupby("territory_id")["changed_either"].sum().values,
        return_counts=True)
    return {str(int(k)): int(v) for k, v in zip(vals, counts)}


def _bootstrap_ci(merged, n_boot, seed):
    rng = np.random.default_rng(seed)
    tid_list = sorted(merged["territory_id"].unique())
    n_c = len(tid_list)
    grp = merged.groupby("territory_id")
    muni_cs = grp["changed_status"].sum().reindex(tid_list).values
    muni_ci = grp["changed_identity_id"].sum().reindex(tid_list).values
    muni_ce = grp["changed_either"].sum().reindex(tid_list).values
    muni_n = grp.size().reindex(tid_list).values
    # sample municipality indices with replacement, sum counts & denominators
    idx = rng.choice(n_c, size=(n_boot, n_c), replace=True)
    n_per = muni_n[idx].sum(axis=1).astype(float)
    fs = muni_cs[idx].sum(axis=1) / n_per
    fi = muni_ci[idx].sum(axis=1) / n_per
    fe = muni_ce[idx].sum(axis=1) / n_per

    def _ci(a):
        return {"p2.5": float(np.percentile(a, 2.5)),
                "p97.5": float(np.percentile(a, 97.5)),
                "mean": float(np.mean(a)), "std": float(np.std(a))}
    return {"n_clusters": int(n_c), "n_bootstrap": int(n_boot),
            "seed": int(seed),
            "method": "resample municipalities with replacement, "
                      "take ALL 12 months per sampled municipality",
            "changed_status": _ci(fs), "changed_id": _ci(fi),
            "changed_either": _ci(fe)}


def self_check() -> int:
    ok = True
    def chk(nm, cond, det=""):
        nonlocal ok
        print(f"self-check {nm}: {'PASS' if cond else 'FAIL'} {det}")
        if not cond:
            ok = False

    rng = np.random.default_rng(20260928)
    tids = list(range(1, 31))
    months = [f"2024-{m:02d}" for m in range(1, 13)]
    rb, rv = [], []
    for tid in tids:
        for mo in months:
            rb.append({"territory_id": tid, "month": mo, "k": 2,
                        "label": 0, "identity_id": f"ID{tid:04d}",
                        "status": "continuing"})
            s = "birth" if rng.random() < 0.10 else "continuing"
            iid = (f"ID9{tid:03d}" if rng.random() < 0.05
                   else f"ID{tid:04d}")
            rv.append({"territory_id": tid, "month": mo, "k": 2,
                        "label": 0, "identity_id": iid, "status": s})
    base_df, var_df = pd.DataFrame(rb), pd.DataFrame(rv)

    # 1. join
    merged = _join_variant_to_base(base_df, var_df)
    chk("join_rows", len(merged) == len(tids) * len(months),
        f"got={len(merged)}")
    frac = _fractions(merged)
    chk("indicators_status", frac["count_changed_status"] > 0,
        f"cs={frac['count_changed_status']}")
    chk("indicators_id", frac["count_changed_id"] > 0,
        f"ci={frac['count_changed_id']}")

    # 2. M=1 exact reproduction
    ms = _join_variant_to_base(base_df, base_df.copy())
    chk("m1_zero", ms["changed_either"].sum() == 0)
    fs = _fractions(ms)
    chk("m1_frac_zero", fs["frac_changed_either"] == 0.0)

    # 3. duplicate rejection
    try:
        _join_variant_to_base(pd.concat([base_df.head(1)]*2), var_df)
        chk("dup_rejected", False)
    except ValueError:
        chk("dup_rejected", True)

    # 4. missing key rejection
    try:
        _join_variant_to_base(base_df, var_df.iloc[1:].copy())
        chk("missing_rejected", False)
    except ValueError:
        chk("missing_rejected", True)

    # 5. cluster bootstrap (not row), deterministic
    ci = _bootstrap_ci(merged, 50, 20260928)
    ci2 = _bootstrap_ci(merged, 50, 20260928)
    chk("boot_n_clusters", ci["n_clusters"] == 30,
        f"got={ci['n_clusters']}")
    chk("boot_cluster_method",
        "municipalit" in ci["method"].lower())
    chk("boot_nonzero_std", ci["changed_status"]["std"] > 0,
        f"std={ci['changed_status']['std']:.4f}")
    chk("boot_deterministic",
        ci["changed_status"]["p2.5"] == ci2["changed_status"]["p2.5"])

    # 6. per-month and distribution
    pm = _per_month(merged)
    chk("per_month_12", len(pm) == 12)
    dist = _muni_dist(merged)
    chk("muni_dist_nonempty", len(dist) > 0)

    # 7. full pipeline with synthetic archived data
    from a6_temporal import standardize_frozen
    from a6_identities import track_identities
    from a6_holdout_sensitivity import _recon, _to_rows
    panel = _toy_panel(n=30, months=[f"2023-{m:02d}" for m in range(1, 13)]
                       + [f"2024-{m:02d}" for m in range(1, 13)],
                       seed=7, noise=0.01)
    tids_, months_, S_, _ = build_monthly_shares(panel)
    Z_, _ = standardize_frozen(S_, months_)
    T, Tc, base_M = 0.10, 0.05, 0.60
    labs_b, ctrs_b = [], []
    for mi in range(len(months_)):
        lb = np.array([0 if t < 15 else 1
                       for t in range(len(tids_))], dtype=int)
        labs_b.append(lb)
        mu = np.zeros((2, Z_.shape[2]))
        for c in range(2):
            idx = np.where(lb == c)[0]
            if len(idx):
                mu[c] = Z_[idx, mi, :].mean(axis=0)
        ctrs_b.append(mu)
    ar_b, _, _ = track_identities(months_, labs_b, ctrs_b, Z_, tids_,
                                  T, base_M, Tc)
    bf = _to_rows(ar_b, tids_, months_, {mo: 2 for mo in months_})
    b24 = bf[bf["month"].str.startswith("2024")].copy()
    b24 = b24.sort_values(
        ["territory_id", "month"]).reset_index(drop=True)
    chk("pipe_m1_exact",
        _join_variant_to_base(b24, b24.copy())["changed_either"].sum() == 0)
    ar75, _, _ = track_identities(months_, labs_b, ctrs_b, Z_, tids_,
                                  T, base_M * 0.75, Tc)
    v75 = _to_rows(ar75, tids_, months_, {mo: 2 for mo in months_})
    v75_24 = v75[v75["month"].str.startswith("2024")].copy()
    v75_24 = v75_24.sort_values(
        ["territory_id", "month"]).reset_index(drop=True)
    m75 = _join_variant_to_base(b24, v75_24)
    chk("pipe_m075_join", len(m75) == len(b24))
    ci_p = _bootstrap_ci(m75, 20, 42)
    chk("pipe_boot_clusters", ci_p["n_clusters"] == len(tids_))

    # 8. vectorized bootstrap correctness: 3-cluster toy, varying sizes
    _toy_rows = []
    for _tid, _nr, _cs, _ci_v, _ce in [(1, 4, 2, 1, 3),
                                        (2, 2, 0, 0, 1),
                                        (3, 5, 3, 2, 4)]:
        for _m in range(_nr):
            _toy_rows.append({
                "territory_id": _tid, "month": f"m{_m}",
                "changed_status": 1 if _m < _cs else 0,
                "changed_identity_id": 1 if _m < _ci_v else 0,
                "changed_either": 1 if _m < _ce else 0})
    _toy_df = pd.DataFrame(_toy_rows)
    _SV, _NBV = 42, 100
    _rng_s = np.random.default_rng(_SV)
    _tids_s = sorted(_toy_df["territory_id"].unique())
    _nc_s = len(_tids_s)
    _bts = {t: _toy_df[_toy_df["territory_id"] == t].sort_values("month")
            for t in _tids_s}
    _fs_s = np.empty(_NBV)
    _fi_s = np.empty(_NBV)
    _fe_s = np.empty(_NBV)
    for _bi in range(_NBV):
        _s = _rng_s.choice(_tids_s, size=_nc_s, replace=True)
        _blk = pd.concat([_bts[int(t)] for t in _s], ignore_index=True)
        _nn = len(_blk)
        _fs_s[_bi] = _blk["changed_status"].sum() / _nn
        _fi_s[_bi] = _blk["changed_identity_id"].sum() / _nn
        _fe_s[_bi] = _blk["changed_either"].sum() / _nn
    _ci_f = _bootstrap_ci(_toy_df, _NBV, _SV)
    chk("vec_status_p2.5",
        abs(_ci_f["changed_status"]["p2.5"]
            - float(np.percentile(_fs_s, 2.5))) < 1e-10)
    chk("vec_status_p97.5",
        abs(_ci_f["changed_status"]["p97.5"]
            - float(np.percentile(_fs_s, 97.5))) < 1e-10)
    chk("vec_id_mean",
        abs(_ci_f["changed_id"]["mean"]
            - float(np.mean(_fi_s))) < 1e-10)
    chk("vec_either_std",
        abs(_ci_f["changed_either"]["std"]
            - float(np.std(_fe_s))) < 1e-10)

    print("self-check: ALL PASS" if ok else "self-check: FAILURES")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEF_PANEL))
    p.add_argument("--base-run", default=str(ATLAS / "runs" / "A6_v2"))
    p.add_argument("--outdir", default=str(ATLAS / "runs" / "A6_bootstrap"))
    p.add_argument("--n-bootstrap", type=int, default=2000)
    p.add_argument("--seed", type=int, default=20260928)
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args(argv)
    if args.self_check:
        return self_check()

    panel = pd.read_parquet(Path(args.panel))
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    results, ci_results = {}, {}

    for mf in M_FACTORS:
        print(f"Running M_factor={mf} ...")
        var_df, a_df, cal, man = run_holdout(
            panel, args.base_run, outdir, mf)
        a24 = a_df[a_df["month"].str.startswith(YEAR)].copy()
        _validate_archived(a24)
        if len(a24) != EXPECTED_ROWS:
            print(f"FAIL: archived 2024 rows {len(a24)} != {EXPECTED_ROWS}")
            return 1
        if a24["territory_id"].nunique() != N_MUNI:
            print(f"FAIL: archived muni "
                  f"{a24['territory_id'].nunique()} != {N_MUNI}")
            return 1
        if a24["month"].nunique() != N_MONTHS:
            print(f"FAIL: archived months "
                  f"{a24['month'].nunique()} != {N_MONTHS}")
            return 1
        merged = _join_variant_to_base(a24, var_df)
        frac = _fractions(merged)
        pm = _per_month(merged)
        dist = _muni_dist(merged)
        if mf == 1.0:
            v24s = var_df.sort_values(
                ["territory_id", "month"]).reset_index(drop=True)
            a24s = a24.sort_values(
                ["territory_id", "month"]).reset_index(drop=True)
            for col in ("label", "k", "status", "identity_id"):
                if not (a24s[col].values == v24s[col].values).all():
                    mism = int((a24s[col] != v24s[col]).sum())
                    print(f"FAIL M=1.0: {col} mismatch {mism}")
                    return 1
            if frac["frac_changed_either"] != 0.0:
                print(f"FAIL M=1.0: frac_changed_either="
                      f"{frac['frac_changed_either']}")
                return 1
            print(f"  M=1.0 exact reproduction: {frac['n']} rows, "
                  "label/k/status/ID all match")
        results[mf] = {"margin": cal["candidate_margin"] * mf,
                       "overall": frac, "per_month": pm,
                       "muni_distribution": dist}
        if mf != 1.0:
            ci = _bootstrap_ci(merged, args.n_bootstrap, args.seed)
            ci_results[mf] = ci
            for tag in ("changed_status", "changed_id", "changed_either"):
                c = ci[tag]
                print(f"  M={mf} {tag}: CI [{c['p2.5']:.4f}, "
                      f"{c['p97.5']:.4f}]")

    p_sha = sha256_file(Path(args.panel))
    c_sha = sha256_file(Path(__file__))
    dep_shas = {n: sha256_file(SRC / n) for n in [
        "a6_holdout_sensitivity.py", "a6_temporal.py", "a6_identities.py"]}
    bdir = Path(args.base_run)
    arch_shas = {
        "assignments_parquet": sha256_file(bdir / "assignments.parquet"),
        "calibration_json": sha256_file(bdir / "calibration.json"),
        "manifest_json": sha256_file(bdir / "manifest.json"),
    }

    metrics = {
        "gate": "A6_holdout_bootstrap",
        "gate_pass": False,
        "gate_pass_reason": "sensitivity to margin factor is not "
        "true-event error rate; no economic claims",
        "frozen_calibration": {
            "overlap_threshold": cal["overlap_threshold"],
            "candidate_margin": cal["candidate_margin"],
            "resemblance_floor": cal["resemblance_floor"],
            "source": str(args.base_run)},
        "n_clusters": N_MUNI, "expected_rows": EXPECTED_ROWS,
        "holdout_bootstrap": {str(mf): {
            "margin_factor": mf, "margin": r["margin"],
            "overall": r["overall"], "per_month": r["per_month"],
            "muni_distribution": r["muni_distribution"]}
            for mf, r in results.items()},
        "bootstrap_ci": {str(mf): ci for mf, ci in ci_results.items()},
        "limitations": [
            "Sensitivity to margin factor is not true-event error rate.",
            "No claims of true economic births; gate_pass false.",
            "Thresholds frozen from 2023 calibration; never refit on 2024."]}
    manifest = {
        "gate": "A6_holdout_bootstrap", "gate_pass": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv), "code_sha256": c_sha,
        "seed": args.seed, "n_bootstrap": args.n_bootstrap,
        "m_factors": list(M_FACTORS), "base_run": str(args.base_run),
        "n_clusters": N_MUNI, "expected_rows": EXPECTED_ROWS,
        "archived_sha256": arch_shas,
        "inputs": {"panel": {"sha256": p_sha, "rows": int(len(panel))},
                   "dependencies": dep_shas},
        "versions": {"python": sys.version.split()[0],
                     "numpy": pkg_version("numpy"),
                     "pandas": pkg_version("pandas"),
                     "scipy": pkg_version("scipy"),
                     "scikit-learn": pkg_version("scikit-learn")},
        "limitations": metrics["limitations"]}
    for name, obj in [("metrics.json", metrics), ("manifest.json", manifest)]:
        (outdir / name).write_text(
            json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       indent=2) + "\n", encoding="utf-8")
    print(f"outdir={outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())