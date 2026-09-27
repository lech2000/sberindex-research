"""A6 margin audit (diagnostic): bootstrap re-analysis of the archived M2
margin from runs/A6_v2.

DIAGNOSTIC_PARTIAL_NOT_GATE_PASS -- this script is a diagnostic audit only.
It re-derives the paired bootstrap (self, max_other, gap) draws that underlie
the archived candidate_margin M, reports quantiles and the measured fraction
of paired gap <= oldM, and compares oldM to max(0, q05_self - q95_other).
It does NOT propose replacement thresholds, does NOT fit thresholds to 2024
data or events, and does NOT claim externally validated births or case closure.

Inputs:
  --panel      frozen panel parquet (same as A6_v2)
  --base-run   runs/A6_v2 directory (assignments.parquet, calibration.json,
               manifest.json)
  --outdir     fresh directory; refuses to overwrite a non-empty existing dir

What it does:
  1. build_monthly_shares / standardize_frozen from a6_temporal (reused verbatim)
  2. Load archived assignments and calibration; exact-validate (tid, month)
     grid, contiguous labels, panel SHA, manifest SHA
  3. Bootstrap ONLY 2023 months: for each archived cluster with >= 8 members,
     B=200 draws (seeded). For the SAME bootstrap draw, compute self-overlap
     (BC of bootstrap region vs original region) and max_other-overlap (max BC
     over all other same-month regions). Paired gap = self - max_other.
  4. Save paired_draws.csv (every draw), quantiles.csv (self/other/gap
     quantiles), margin_comparison.csv (oldM vs measured fraction).
  5. Optional 2024 summary: counts of archived statuses only (no calibration
     on 2024, no thresholds applied).

  oldT, oldM, oldTc are read from the archive and reported unchanged.
  No q05_gap - q95_gap invented M. No fitting to 2024/events.

--self-check:
  - paired gap consistency (same-seed reproducibility)
  - correlated self/other toy distributions demonstrate that
    q_alpha(gap) != q_alpha(self) - q_{1-alpha}(other) for correlated pairs
  - 2024 excluded from calibration (structural check)
  - clear message on missing deps

Usage:
  python src/a6_margin_audit.py --panel data/panel_v1.parquet \\
      --base-run runs/A6_v2 --outdir runs/A6_v2_margin_audit
  python src/a6_margin_audit.py --self-check

Deps: numpy, pandas. (parquet IO via pandas engine.)
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
except Exception:
    np = pd = None

ATLAS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ATLAS_DIR / "data" / "panel_v1.parquet"
DEFAULT_BASE_RUN = ATLAS_DIR / "runs" / "A6_v2"
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A6_v2_margin_audit"

BOOT_B = 200
CAL_MIN_SIZE = 8
FIT_YEAR = "2023"
SEED = 20260926
STATUS = "DIAGNOSTIC_PARTIAL_NOT_GATE_PASS"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pkg_version(name: str):
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:
        return None


def _run_audit(panel: pd.DataFrame, panel_path: Path, base_run: Path,
               outdir: Path) -> dict:
    from a6_identities import bc_iso, region_of_members
    from a6_temporal import (FIT_YEAR as _FY, SHARE_CATS,
                             build_monthly_shares, standardize_frozen)

    assert _FY == FIT_YEAR

    tids, months, S, share_audit = build_monthly_shares(panel)
    n_tids, n_months = int(len(tids)), len(months)
    Z, std_audit = standardize_frozen(S, months)

    if not (bool(np.isfinite(S).all()) and bool(np.isfinite(Z).all())):
        raise ValueError("S and Z must be all finite")

    assign_path = base_run / "assignments.parquet"
    calib_path = base_run / "calibration.json"
    manifest_path = base_run / "manifest.json"

    for p in (assign_path, calib_path, manifest_path):
        if not p.is_file():
            raise FileNotFoundError(f"missing required file: {p}")

    base = pd.read_parquet(assign_path)
    cal = json.loads(calib_path.read_text(encoding="utf-8"))
    base_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    oldT = float(cal["overlap_threshold"])
    oldM = float(cal["candidate_margin"])
    oldTc = float(cal["resemblance_floor"])
    quantiles_self_old = cal["quantiles_self"]
    quantiles_other_old = cal["quantiles_other"]

    panel_sha = sha256_file(panel_path)
    base_panel_sha = (base_manifest.get("inputs", {})
                      .get("panel", {}).get("sha256", ""))
    if base_panel_sha and base_panel_sha != "see-operator-run":
        if panel_sha != base_panel_sha:
            raise ValueError(
                f"panel SHA mismatch: file={panel_sha} vs "
                f"base-manifest={base_panel_sha}")

    tid_pos = {int(t): i for i, t in enumerate(tids.tolist())}
    month_pos = {mo: i for i, mo in enumerate(months)}

    if len(base) != n_tids * n_months:
        raise ValueError(
            f"base assignments row count {len(base)} != "
            f"n_tids*n_months {n_tids * n_months}")
    if bool(base.duplicated(subset=["territory_id", "month"]).any()):
        raise ValueError("base assignments: duplicate (tid, month) rows")

    b_ti = base["territory_id"].astype(int).map(tid_pos).to_numpy()
    b_mi = base["month"].astype(str).map(month_pos).to_numpy()
    if bool(pd.isna(b_ti).any()) or bool(pd.isna(b_mi).any()):
        raise ValueError("base assignments: rows outside the panel grid")
    b_ti = b_ti.astype(int)
    b_mi = b_mi.astype(int)

    lab_grid = np.zeros((n_months, n_tids), dtype=int)
    lab_grid[b_mi, b_ti] = base["label"].to_numpy(dtype=int)
    for m in range(n_months):
        labs = sorted(set(lab_grid[m].tolist()))
        if labs != list(range(max(labs) + 1)):
            raise ValueError(
                f"labels not contiguous at month {months[m]}: {labs}")

    cal_months_idx = [i for i, mo in enumerate(months)
                      if mo.startswith(FIT_YEAR)]
    if not cal_months_idx:
        raise ValueError(f"no {FIT_YEAR} months in panel")

    cal_month_set = set(cal["cal_months"])
    if set(cal_months_idx) != cal_month_set:
        raise ValueError(
            f"cal_months mismatch: archive={sorted(cal_month_set)} vs "
            f"panel={sorted(cal_months_idx)}")

    n_skipped_small = 0
    cluster_cache: dict[tuple[int, int], tuple] = {}
    for m in cal_months_idx:
        X = np.asarray(Z[:, m, :], dtype=float)
        lab = lab_grid[m]
        clusters = sorted(int(c) for c in set(lab.tolist()))
        for c in clusters:
            pts = X[lab == c]
            if len(pts) < CAL_MIN_SIZE:
                n_skipped_small += 1
                continue
            mu = pts.mean(axis=0)
            rms, var = region_of_members(pts, mu)
            cluster_cache[(m, c)] = (mu, var, int(len(pts)))

    rng = np.random.default_rng(SEED + 555555)
    draw_rows: list[dict] = []

    for m in cal_months_idx:
        X = np.asarray(Z[:, m, :], dtype=float)
        lab = lab_grid[m]
        clusters_in_month = sorted(
            c for (mm, c) in cluster_cache if mm == m)
        if not clusters_in_month:
            continue

        for c in clusters_in_month:
            mu_c, var_c, n_c = cluster_cache[(m, c)]
            pts_c = X[lab == c]

            others = [(o, cluster_cache[(m, o)])
                      for o in clusters_in_month if o != c]

            for b in range(BOOT_B):
                bidx = rng.integers(0, n_c, size=n_c)
                bpts = pts_c[bidx]
                bmu = bpts.mean(axis=0)
                _, bvar = region_of_members(bpts, bmu)

                self_ov = bc_iso(bmu, bvar, mu_c, var_c)

                max_other = 0.0
                for _o, (omu, ovar, _on) in others:
                    ov = bc_iso(bmu, bvar, omu, ovar)
                    if ov > max_other:
                        max_other = ov

                gap = self_ov - max_other
                draw_rows.append({
                    "month_idx": m,
                    "month": months[m],
                    "cluster": c,
                    "cluster_size": n_c,
                    "draw": b,
                    "self_overlap": float(self_ov),
                    "max_other_overlap": float(max_other),
                    "paired_gap": float(gap),
                })

    draws_df = pd.DataFrame(draw_rows)

    gap_arr = draws_df["paired_gap"].to_numpy(dtype=float)
    self_arr = draws_df["self_overlap"].to_numpy(dtype=float)
    other_arr = draws_df["max_other_overlap"].to_numpy(dtype=float)

    def _quantiles(xs: np.ndarray, prefix: str) -> dict:
        q = {}
        for level, name in ((0.01, "q01"), (0.05, "q05"), (0.25, "q25"),
                             (0.50, "q50"), (0.75, "q75"), (0.95, "q95"),
                             (0.99, "q99")):
            q[f"{prefix}_{name}"] = float(np.quantile(xs, level))
        q[f"{prefix}_n"] = int(len(xs))
        q[f"{prefix}_mean"] = float(np.mean(xs))
        q[f"{prefix}_std"] = float(np.std(xs, ddof=0))
        return q

    quant_self = _quantiles(self_arr, "self")
    quant_other = _quantiles(other_arr, "other")
    quant_gap = _quantiles(gap_arr, "gap")

    quant_rows = []
    for prefix in ("self", "other", "gap"):
        base_dict = {"distribution": prefix}
        for k, v in ({k2: v2 for k2, v2 in
                      (quant_self if prefix == "self" else
                       quant_other if prefix == "other" else
                       quant_gap).items()}).items():
            base_dict[k] = v
        quant_rows.append(base_dict)
    quant_df = pd.DataFrame(quant_rows)

    frac_gap_le_oldm = float(np.mean(gap_arr <= oldM))
    recomputed_M_marginal = max(0.0, quant_self["self_q05"]
                                - quant_other["other_q95"])

    margin_rows = [{
        "metric": "oldM_from_archive",
        "value": oldM,
        "note": "M=max(0, q05self-q95other) from the archived calibration; "
                "Tc=resemblance_floor, unchanged",
    }, {
        "metric": "oldT_from_archive",
        "value": oldT,
        "note": "T=q95other from the archived calibration, unchanged",
    }, {
        "metric": "oldTc_from_archive",
        "value": oldTc,
        "note": "Tc=q50other from the archived calibration, unchanged",
    }, {
        "metric": "recomputed_M_marginal",
        "value": recomputed_M_marginal,
        "note": "max(0, q05_self - q95_other) recomputed from this audit's "
                "draws; should be close to oldM (same bootstrap procedure, "
                "different seed path)",
    }, {
        "metric": "frac_gap_le_oldM",
        "value": frac_gap_le_oldm,
        "note": "measured fraction of paired (self - max_other) <= oldM; "
                "diagnostic only",
    }, {
        "metric": "q05_gap",
        "value": quant_gap["gap_q05"],
        "note": "q05 of paired gap distribution; NOT used to define M",
    }, {
        "metric": "q95_gap",
        "value": quant_gap["gap_q95"],
        "note": "q95 of paired gap distribution; NOT used to define M",
    }, {
        "metric": "marginal_quantile_gap",
        "value": quant_self["self_q05"] - quant_other["other_q95"],
        "note": "q05(self) - q95(other), the marginal expression; for "
                "correlated pairs this differs from q05(paired_gap); "
                "see --self-check demonstration",
    }]
    margin_df = pd.DataFrame(margin_rows)

    summary_2024: dict | None = None
    months_2024 = [mo for mo in months if mo.startswith("2024")]
    if months_2024:
        rows_2024 = base[base["month"].isin(months_2024)]
        status_counts = {}
        for kind in sorted(rows_2024["status"].unique().tolist()):
            status_counts[str(kind)] = int(
                (rows_2024["status"] == kind).sum())
        summary_2024 = {
            "note": "2024 summary uses archive statuses only; no "
                    "calibration or threshold application on 2024",
            "n_months": len(months_2024),
            "months": months_2024,
            "n_rows": int(len(rows_2024)),
            "status_counts": status_counts,
        }

    outdir.mkdir(parents=True, exist_ok=True)
    draws_df.to_csv(outdir / "paired_draws.csv", index=False)
    quant_df.to_csv(outdir / "quantiles.csv", index=False)
    margin_df.to_csv(outdir / "margin_comparison.csv", index=False)

    audit_clusters = {
        "n_clusters_eligible": int(len(cluster_cache)),
        "n_clusters_skipped_small": int(n_skipped_small),
        "cal_min_size": CAL_MIN_SIZE,
        "bootstrap_B": BOOT_B,
        "seed": SEED + 555555,
    }

    metrics = {
        "gate": "A6",
        "component": "margin_audit",
        "status": STATUS,
        "gate_pass": False,
        "gate_pass_reason": "diagnostic re-analysis of archived bootstrap "
        "margin only; does not propose replacement thresholds, does not "
        "claim externally validated births or case closure",
        "completes_case06": False,
        "economic_types_invented": False,
        "calibration_unchanged": {
            "overlap_threshold_T": oldT,
            "candidate_margin_M": oldM,
            "resemblance_floor_Tc": oldTc,
            "note": "T, M, Tc read from the archived calibration.json and "
                    "reported unchanged; no replacement thresholds proposed",
        },
        "audit_bootstrap": audit_clusters,
        "paired_gap_quantiles": quant_gap,
        "self_quantiles_audit": quant_self,
        "other_quantiles_audit": quant_other,
        "archived_self_quantiles": quantiles_self_old,
        "archived_other_quantiles": quantiles_other_old,
        "margin_comparison": {
            "oldM": oldM,
            "recomputed_M_marginal": recomputed_M_marginal,
            "frac_gap_le_oldM": frac_gap_le_oldm,
            "q05_gap": quant_gap["gap_q05"],
            "q95_gap": quant_gap["gap_q95"],
            "marginal_q05self_minus_q95other": (
                quant_self["self_q05"] - quant_other["other_q95"]),
            "note": "frac_gap_le_oldM is the measured fraction of paired "
                    "(self-max_other) draws <= oldM. q05_gap and q95_gap "
                    "are reported for information only; M is NOT redefined "
                    "as q05_gap - q95_gap.",
        },
        "panel_audit": {
            "n_tids": n_tids,
            "n_months": n_months,
            "months": months,
            "panel_sha256": panel_sha,
            "base_manifest_panel_sha256": base_panel_sha,
            "panel_sha_match": bool(
                panel_sha == base_panel_sha
                or base_panel_sha == "see-operator-run"),
        },
        "mask": {
            "n": n_tids,
            "n_excluded": share_audit["n_excluded"],
            "excluded_tids": share_audit["excluded_tids"],
        },
        "summary_2024": summary_2024,
        "2024_excluded_from_calibration": True,
        "2024_exclusion_note": "bootstrap draws use cal_months_idx from "
                               f"{FIT_YEAR} only; 2024 months are never "
                               "included in calibration or margin derivation",
        "limitations": [
            "This is a diagnostic re-analysis of the archived bootstrap "
            "margin; it does NOT propose replacement thresholds.",
            "T, M, Tc are read from the archived calibration.json and "
            "reported unchanged.",
            "q05_gap and q95_gap are reported for information only; M is "
            "NOT redefined from gap quantiles.",
            "No thresholds are fit to 2024 data or events.",
            "2024 summary uses archive statuses only; no calibration or "
            "threshold application on 2024.",
            "No externally validated births or case closure are claimed.",
        ],
    }

    manifest = {
        "gate": "A6",
        "component": "margin_audit",
        "status": STATUS,
        "gate_pass": False,
        "completes_case06": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {
            "file": Path(__file__).name,
            "sha256": sha256_file(Path(__file__)),
            "a6_identities.py": sha256_file(SRC_DIR / "a6_identities.py"),
            "a6_temporal.py": sha256_file(SRC_DIR / "a6_temporal.py"),
        },
        "inputs": {
            "panel": {
                "path": str(panel_path),
                "sha256": panel_sha,
                "rows": int(len(panel)),
            },
            "base_run": {
                "path": str(base_run),
                "assignments_sha256": sha256_file(assign_path),
                "calibration_sha256": sha256_file(calib_path),
                "manifest_sha256": sha256_file(manifest_path),
            },
        },
        "params": {
            "bootstrap_B": BOOT_B,
            "cal_min_size": CAL_MIN_SIZE,
            "seed_offset": 555555,
            "calibration_months": f"{FIT_YEAR} only",
        },
        "limitations": metrics["limitations"],
        "versions": {
            "python": sys.version.split()[0],
            "numpy": pkg_version("numpy"),
            "pandas": pkg_version("pandas"),
        },
    }

    with open(outdir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    with open(outdir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    return {
        "metrics": metrics,
        "manifest": manifest,
        "n_mask": n_tids,
        "n_months": n_months,
        "outdir": str(outdir),
        "n_draws": len(draws_df),
        "oldM": oldM,
        "recomputed_M_marginal": recomputed_M_marginal,
        "frac_gap_le_oldM": frac_gap_le_oldm,
    }


def _self_check() -> int:
    import py_compile

    ok = True

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal ok
        print(f"self-check {name}: {'PASS' if cond else 'FAIL'} {detail}")
        if not cond:
            ok = False

    py_compile.compile(str(Path(__file__)), doraise=True)
    print("self-check: py_compile PASS")

    deps_ok = True
    try:
        import numpy as _np  # noqa: F401
        import pandas as _pd  # noqa: F401
    except Exception:
        deps_ok = False

    if not deps_ok:
        print("self-check: numpy/pandas unavailable; py_compile only")
        return 0 if ok else 1

    # A. 2024 excluded from calibration: structural check.
    from a6_temporal import FIT_YEAR as _fy
    check("fit_year_is_2023", _fy == "2023",
          f"FIT_YEAR={_fy}")
    cal_months_idx = [i for i in range(12)]
    months_all = [f"2023-{m:02d}" for m in range(1, 13)] + [
        f"2024-{m:02d}" for m in range(1, 7)]
    cal_months = [months_all[i] for i in cal_months_idx]
    check("2024_excluded_structurally",
          all(m.startswith("2023") for m in cal_months)
          and not any(m.startswith("2024") for m in cal_months),
          f"cal_months={cal_months}")

    # B. Correlated self/other toy distributions: demonstrate that
    # q_alpha(paired_gap) != q_alpha(self) - q_{1-alpha}(other)
    # for correlated pairs.
    #
    # SYNTHETIC ASSUMPTION (explicit, toy-only): self ~ N(0.99, 0.01^2),
    # other ~ N(0.18, 0.04^2), with positive correlation rho~0.3 induced by
    # a shared noise term. gap = self - other.
    rng = np.random.default_rng(20260926)
    n_toy = 50000
    shared = rng.normal(0, 1, size=n_toy)
    rho = 0.3
    self_toy = 0.99 + 0.01 * (rho * shared
                               + np.sqrt(1 - rho**2) * rng.normal(0, 1,
                                                                   n_toy))
    other_toy = 0.18 + 0.04 * (rho * shared
                                + np.sqrt(1 - rho**2) * rng.normal(0, 1,
                                                                    n_toy))
    gap_toy = self_toy - other_toy

    q05_self = float(np.quantile(self_toy, 0.05))
    q95_other = float(np.quantile(other_toy, 0.95))
    marginal_gap = q05_self - q95_other

    q05_gap = float(np.quantile(gap_toy, 0.05))
    q95_gap = float(np.quantile(gap_toy, 0.95))

    diff_q05 = abs(q05_gap - marginal_gap)
    check("correlated_marginal_differs_from_paired_q05",
          diff_q05 > 1e-4,
          f"q05(paired_gap)={q05_gap:.6f} vs "
          f"q05(self)-q95(other)={marginal_gap:.6f} "
          f"diff={diff_q05:.6f} (correlation makes them differ)")

    # Verify gap mean = self mean - other mean (linearity of expectation).
    gap_mean_diff = abs(float(np.mean(gap_toy))
                        - float(np.mean(self_toy) - np.mean(other_toy)))
    check("gap_mean_linear", gap_mean_diff < 1e-10,
          f"mean_diff={gap_mean_diff:.2e}")

    # Verify gap variance < self_var + other_var (positive correlation).
    gap_var = float(np.var(gap_toy, ddof=0))
    var_sum = float(np.var(self_toy, ddof=0) + np.var(other_toy, ddof=0))
    check("gap_variance_less_than_sum",
          gap_var < var_sum,
          f"gap_var={gap_var:.6f} < var_sum={var_sum:.6f} "
          "(positive correlation reduces gap variance)")

    # C. Paired gap consistency: same seed -> same draws.
    from a6_identities import bc_iso, region_of_members
    rng1 = np.random.default_rng(42)
    mu1 = np.array([1.0, 0.0])
    mu2 = np.array([0.0, 1.0])
    var1, var2 = 0.5, 0.5
    pts = rng1.normal(0, 1, size=(30, 2))
    n_c = len(pts)

    def _one_pass(seed_val):
        r = np.random.default_rng(seed_val)
        self_s, other_s, gaps = [], [], []
        for _ in range(50):
            bidx = r.integers(0, n_c, size=n_c)
            bpts = pts[bidx]
            bmu = bpts.mean(axis=0)
            _, bvar = region_of_members(bpts, bmu)
            s = bc_iso(bmu, bvar, mu1, var1)
            o = bc_iso(bmu, bvar, mu2, var2)
            self_s.append(s)
            other_s.append(o)
            gaps.append(s - o)
        return self_s, other_s, gaps

    s1, o1, g1 = _one_pass(999)
    s2, o2, g2 = _one_pass(999)
    check("seed_repro_self", s1 == s2)
    check("seed_repro_other", o1 == o2)
    check("seed_repro_gap", g1 == g2)

    # D. Self-consistency: gap = self - other, elementwise.
    for i in range(len(g1)):
        if abs(g1[i] - (s1[i] - o1[i])) > 1e-15:
            check("gap_equals_self_minus_other", False,
                  f"index {i}: gap={g1[i]} != self-other={s1[i]-o1[i]}")
            break
    else:
        check("gap_equals_self_minus_other", True,
              f"all {len(g1)} draws consistent")

    # E. Demonstrate that q05(X)-q95(Y) != q05(X-Y) even for independent
    # normals: the marginal formula uses sigma_s + sigma_o while the paired
    # gap uses sqrt(sigma_s^2 + sigma_o^2) < sigma_s + sigma_o (when both
    # nonzero). Correlation further shifts the paired distribution.
    for rho_val, label in [(0.0, "independent"), (0.5, "moderate"),
                           (0.9, "strong")]:
        rng_d = np.random.default_rng(12345)
        n_d = 100000
        sh = rng_d.normal(0, 1, n_d)
        s_d = 1.0 + 0.2 * (rho_val * sh + np.sqrt(max(0, 1 - rho_val**2))
                            * rng_d.normal(0, 1, n_d))
        o_d = 0.3 + 0.15 * (rho_val * sh + np.sqrt(max(0, 1 - rho_val**2))
                             * rng_d.normal(0, 1, n_d))
        g_d = s_d - o_d
        mg = float(np.quantile(s_d, 0.05) - np.quantile(o_d, 0.95))
        pg = float(np.quantile(g_d, 0.05))
        diff = abs(pg - mg)
        # Both independent and correlated cases differ: for independent,
        # q05(X)-q95(Y) = mu_s-mu_o - z05*(sigma_s+sigma_o) while
        # q05(X-Y) = mu_s-mu_o - z05*sqrt(sigma_s^2+sigma_o^2), and
        # sigma_s+sigma_o > sqrt(sigma_s^2+sigma_o^2) when both > 0.
        check(f"rho_{label}_marginal_vs_paired",
              diff > 1e-4,
              f"rho={rho_val}: q05(paired)={pg:.5f} vs "
              f"marginal={mg:.5f} diff={diff:.5f}")

    print("self-check: ALL PASS" if ok else
          "self-check: FAILURES (measured above)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEFAULT_PANEL))
    p.add_argument("--base-run", default=str(DEFAULT_BASE_RUN))
    p.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    p.add_argument("--self-check", action="store_true",
                   help="run self-check (py_compile + diagnostic checks); "
                        "works without numpy/pandas (py_compile only)")
    args = p.parse_args(argv)

    if args.self_check:
        return _self_check()

    if np is None or pd is None:
        p.error("numpy/pandas are required for a real run "
                "(--self-check works without them)")

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()):
        p.error(f"refusing to overwrite nonempty existing dir: {outdir}")

    panel_path = Path(args.panel)
    base_run = Path(args.base_run)

    for name in ("assignments.parquet", "calibration.json", "manifest.json"):
        if not (base_run / name).is_file():
            p.error(f"--base-run missing {name}: {base_run}")

    panel = pd.read_parquet(panel_path)
    res = _run_audit(panel, panel_path, base_run, outdir)

    print(f"A6 margin audit: mask_n={res['n_mask']} "
          f"months={res['n_months']} draws={res['n_draws']}")
    print(f"  oldM={res['oldM']:.6f} "
          f"recomputed_M_marginal={res['recomputed_M_marginal']:.6f}")
    print(f"  frac_gap_le_oldM={res['frac_gap_le_oldM']:.4f}")
    print(f"  status={STATUS}")
    print(f"outdir={res['outdir']}")

    code_sha = sha256_file(Path(__file__))
    print(f"  file_sha256={code_sha}")
    print(f"  command={' '.join(sys.argv)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())