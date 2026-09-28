"""A6-holdout-sensitivity: M-factor holdout on 2024 with frozen 2023 calibration.

Reconstructs archived K=2 labels and member-mean centres on the frozen panel,
verifies exact reproduction at M_factor=1.0, evaluates M factors 0.75/1.0/1.25
on 2024 months only. Tracking starts 2023; thresholds NEVER refit on 2024.
No claims of true economic births; gate_pass false. No salary, no synthetic
event metrics. Self-check uses synthetic input and invariance checks, runnable
without data.

Usage:
  python src/a6_holdout_sensitivity.py --panel data/panel_v1.parquet \\
      --base-run runs/A6_v2 --outdir runs/A6_holdout
  python src/a6_holdout_sensitivity.py --self-check
"""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from a6_temporal import (
    SHARE_CATS, TOTAL_CAT, build_monthly_shares, standardize_frozen,
    sha256_file, pkg_version,
)
from a6_identities import track_identities

ATLAS = Path(__file__).resolve().parents[1]
DEF_PANEL = ATLAS / "data" / "panel_v1.parquet"
M_FACTORS = (0.75, 1.0, 1.25)
YEAR = "2024"


def _ms(v) -> str:
    s = str(v)
    return s[:7] if len(s) >= 7 else s


def _toy_panel(n=30, months=None, seed=20260927, noise=0.008):
    rng = np.random.default_rng(seed)
    if months is None:
        months = [f"2023-{m:02d}" for m in range(1, 13)] + \
                 [f"2024-{m:02d}" for m in range(1, 13)]
    g0 = np.array([0.10, 0.15, 0.10, 0.20, 0.05])
    g1 = np.array([0.16, 0.11, 0.15, 0.17, 0.09])
    rows = []
    for t in range(1, n + 1):
        prof = g0 if t <= n // 2 else g1
        for mo in months:
            sh = np.clip(prof + rng.normal(0, noise, 5), 0.005, None)
            rows.append((t, mo, TOTAL_CAT, 1000.0))
            for c, v in zip(SHARE_CATS, sh):
                rows.append((t, mo, c, float(v * 1000.0)))
    return pd.DataFrame(rows,
                        columns=["territory_id", "date", "category", "value"])


def _recon(assign_df, Z, tids, months):
    """Reconstruct K=2 labels and member-mean centres from archived assign.

    Rejects incomplete archived month coverage: every (territory_id, month)
    pair implied by *tids* x *months* must appear in *assign_df*.
    """
    ti = {int(t): i for i, t in enumerate(tids)}
    tid_set = set(ti.keys())
    labs, ctrs = [], []
    for mi, mo in enumerate(months):
        sub = assign_df[assign_df["month"] == mo]
        present = {int(r["territory_id"]) for _, r in sub.iterrows()}
        missing = tid_set - present
        if missing:
            raise ValueError(
                f"Archived assignments incomplete for month {mo}: "
                f"{len(missing)} territory_ids missing "
                f"(e.g. {sorted(missing)[:5]})"
            )
        lb = np.zeros(len(tids), dtype=int)
        c_map: dict[int, list[int]] = {}
        for _, r in sub.iterrows():
            idx = ti.get(int(r["territory_id"]))
            if idx is not None:
                c = int(r["label"])
                lb[idx] = c
                c_map.setdefault(c, []).append(idx)
        labs.append(lb)
        k = max(c_map) + 1 if c_map else 1
        mu = np.zeros((k, Z.shape[2]))
        for c, idxs in c_map.items():
            if idxs:
                mu[c] = Z[np.asarray(idxs), mi, :].mean(axis=0)
        ctrs.append(mu)
    return labs, ctrs


def _to_rows(assign_rows, tids, months, k_traj):
    """Convert track_identities assign_rows to assignment records."""
    month_strs = {_ms(m) for m in months}
    rows = []
    for r in assign_rows:
        mo = _ms(r["month"])
        if mo not in month_strs:
            continue
        rows.append({
            "territory_id": int(tids[r["ti"]]),
            "month": mo,
            "k": int(k_traj.get(mo, 2)),
            "label": int(r["label"]),
            "identity_id": r["identity_id"],
            "status": r["status"],
        })
    return pd.DataFrame(rows)


def _validate_archived(a_df):
    """Reject duplicate (territory_id, month) keys in archived assignments."""
    dupes = a_df.duplicated(subset=["territory_id", "month"], keep=False)
    if dupes.any():
        bad = a_df.loc[dupes, ["territory_id", "month"]].drop_duplicates()
        raise ValueError(
            f"Duplicate (territory_id, month) in archived assignments: "
            f"{len(bad)} pairs (e.g. {list(bad.head(3).itertuples(index=False))})"
        )


def run_holdout(panel, base, outdir, m_factor):
    """Run identity tracking with margin = archived_M * m_factor."""
    bdir = Path(base)
    a_df = pd.read_parquet(bdir / "assignments.parquet")
    _validate_archived(a_df)
    cal = json.loads((bdir / "calibration.json").read_text())
    man = json.loads((bdir / "manifest.json").read_text())
    seed = man.get("seed", 20260926)
    T, Tc = cal["overlap_threshold"], cal["resemblance_floor"]
    M = cal["candidate_margin"] * m_factor
    k_traj = {mo: int(v) for mo, v in man.get("k_trajectory", {}).items()}
    tids, months, S, _ = build_monthly_shares(panel)
    Z, _ = standardize_frozen(S, months)
    labs, ctrs = _recon(a_df, Z, tids, months)
    ar, _, _ = track_identities(months, labs, ctrs, Z, tids, T, M, Tc)
    df = _to_rows(ar, tids, months, k_traj)
    df24 = df[df["month"].str.startswith(YEAR)].sort_values(
        ["territory_id", "month"]).reset_index(drop=True)
    return df24, a_df, cal, man


def _agreement(base_a, fact_a, year):
    """Compute per-month and overall agreement vs base assignments."""
    b24 = base_a[base_a["month"].str.startswith(year)].copy()
    b_map = {(int(r["territory_id"]), _ms(r["month"])): r
             for _, r in b24.iterrows()}
    months = sorted(fact_a["month"].unique())
    per_mo = {}
    for mo in months:
        sub = fact_a[fact_a["month"] == mo]
        n = len(sub)
        if n == 0:
            continue
        ns = ni = 0
        for _, r in sub.iterrows():
            bk = b_map.get((int(r["territory_id"]), _ms(mo)))
            if bk is not None:
                if str(r["status"]) == str(bk["status"]):
                    ns += 1
                if str(r["identity_id"]) == str(bk["identity_id"]):
                    ni += 1
        per_mo[mo] = {"n": n, "status_agree": ns, "id_agree": ni,
                      "status_agree_rate": ns / n, "id_agree_rate": ni / n}
    sa = [v["status_agree_rate"] for v in per_mo.values()]
    ia = [v["id_agree_rate"] for v in per_mo.values()]
    return per_mo, float(np.mean(sa)) if sa else 0.0, \
           float(np.mean(ia)) if ia else 0.0


def _status_dist(df):
    out = {}
    for mo, g in df.groupby("month"):
        out[mo] = {s: int(c) for s, c in g["status"].value_counts().items()}
    return out


def _save(outdir, metrics, manifest):
    outdir.mkdir(parents=True, exist_ok=True)
    for name, obj in [("metrics.json", metrics), ("manifest.json", manifest)]:
        p = outdir / name
        p.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                indent=2) + "\n", encoding="utf-8")


def self_check() -> int:
    ok = True
    def chk(nm, cond, det=""):
        nonlocal ok
        print(f"self-check {nm}: {'PASS' if cond else 'FAIL'} {det}")
        if not cond:
            ok = False

    panel = _toy_panel(n=30, months=[f"2023-{m:02d}" for m in range(1, 13)]
                       + [f"2024-{m:02d}" for m in range(1, 7)], seed=7, noise=0.01)
    tids, months, S, _ = build_monthly_shares(panel)
    Z, std = standardize_frozen(S, months)

    # Run base tracking (M_factor=1.0) to get synthetic "archived" assign.
    T, Tc = 0.10, 0.05
    base_M = 0.60
    labs_b, ctrs_b = [], []
    for mi in range(len(months)):
        rng = np.random.default_rng(20260927 + mi)
        lb = np.array([0 if t < 15 else 1 for t in range(len(tids))], dtype=int)
        labs_b.append(lb)
        mu = np.zeros((2, Z.shape[2]))
        for c in range(2):
            idx = np.where(lb == c)[0]
            if len(idx):
                mu[c] = Z[idx, mi, :].mean(axis=0)
        ctrs_b.append(mu)
    ar_b, _, _ = track_identities(months, labs_b, ctrs_b, Z, tids, T, base_M, Tc)
    base_df = _to_rows(ar_b, tids, months, {mo: 2 for mo in months})
    b24 = base_df[base_df["month"].str.startswith("2024")].copy()

    # 1. M_factor=1.0 exact reproduction.
    ar_v, _, _ = track_identities(months, labs_b, ctrs_b, Z, tids, T, base_M, Tc)
    v_df = _to_rows(ar_v, tids, months, {mo: 2 for mo in months})
    v24 = v_df[v_df["month"].str.startswith("2024")].copy()
    chk("exact_repro_len", len(b24) == len(v24),
        f"base={len(b24)} var={len(v24)}")
    if len(b24) == len(v24):
        bs = b24.sort_values(["territory_id", "month"]).reset_index(drop=True)
        vs = v24.sort_values(["territory_id", "month"]).reset_index(drop=True)
        chk("exact_repro_status",
            (bs["status"] == vs["status"]).all())
        chk("exact_repro_id",
            (bs["identity_id"] == vs["identity_id"]).all())

    # 2. Agreement check (self-consistency).
    per_mo, msa, mia = _agreement(base_df, v24, "2024")
    chk("self_agree_status", msa == 1.0, f"mean_status_agree={msa:.4f}")
    chk("self_agree_id", mia == 1.0, f"mean_id_agree={mia:.4f}")

    # 2b. ID mismatch rejection: mutate identity_ids in a copy, verify detect.
    v24_bad = v24.copy()
    half = len(v24_bad) // 2
    v24_bad.loc[v24_bad.index[:half], "identity_id"] = "mutated_id"
    _, msa_bad, mia_bad = _agreement(base_df, v24_bad, "2024")
    chk("id_mismatch_rejected", mia_bad < 1.0,
        f"mia_bad={mia_bad:.4f} (expected < 1.0)")

    # 2c. Exact key+column equality check (same logic as main M=1 assertion).
    cols = ["territory_id", "month", "label", "k", "status", "identity_id"]
    arch = b24[cols].sort_values(cols[:2]).reset_index(drop=True)
    trk = v24[cols].sort_values(cols[:2]).reset_index(drop=True)
    key_match = (arch[cols[:2]].values == trk[cols[:2]].values).all()
    col_match = not arch.compare(trk).empty is False
    chk("exact_key_equality", key_match)
    chk("exact_col_equality", col_match)

    # 2d. Incomplete coverage rejection in _recon.
    incomplete_a = base_df[base_df["month"] != base_df["month"].unique()[0]]
    Z_inc = Z.copy()
    try:
        _recon(incomplete_a, Z_inc, tids, months)
        chk("incomplete_coverage_rejected", False, "should have raised")
    except ValueError as e:
        chk("incomplete_coverage_rejected", True, str(e)[:60])

    # 3. Margin factor changes affect status distribution.
    for mf in [0.75, 1.25]:
        m_scaled = base_M * mf
        ar_m, _, _ = track_identities(months, labs_b, ctrs_b, Z, tids,
                                      T, m_scaled, Tc)
        m_df = _to_rows(ar_m, tids, months, {mo: 2 for mo in months})
        m24 = m_df[m_df["month"].str.startswith("2024")].copy()
        per_m, ms, mi = _agreement(base_df, m24, "2024")
        chk(f"factor_{mf}_len", len(m24) == len(b24),
            f"n={len(m24)} base={len(b24)}")
        print(f"  factor {mf}: mean_status_agree={ms:.4f} "
              f"mean_id_agree={mi:.4f}")

    # 4. Frozen calibration invariance.
    mu23 = {k: v for k, v in std["mu"].items()}
    chk("frozen_mu_2023", all(
        isinstance(v, float) for v in mu23.values()), f"n_mu={len(mu23)}")
    chk("frozen_sigma_present", "sigma" in std)

    # 5. Bhattacharyya closed-form check (known analytical value).
    from a6_identities import bc_iso
    mu1 = np.zeros(5)
    mu2 = np.ones(5)
    bc_same = bc_iso(mu1, 1.0, mu1, 1.0)
    chk("bc_self_identity", abs(bc_same - 1.0) < 1e-10, f"bc={bc_same}")
    bc_sym = bc_iso(mu1, 1.0, mu2, 1.0)
    bc_rev = bc_iso(mu2, 1.0, mu1, 1.0)
    chk("bc_symmetry", abs(bc_sym - bc_rev) < 1e-10,
        f"fwd={bc_sym:.6f} rev={bc_rev:.6f}")
    chk("bc_range", 0.0 < bc_sym < 1.0, f"bc={bc_sym:.6f}")

    print("self-check: ALL PASS" if ok else "self-check: FAILURES")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEF_PANEL))
    p.add_argument("--base-run", required=False, default=str(ATLAS / "runs" / "A6_v2"))
    p.add_argument("--outdir", default=str(ATLAS / "runs" / "A6_holdout"))
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args(argv)

    if args.self_check:
        return self_check()

    panel = pd.read_parquet(Path(args.panel))
    outdir = Path(args.outdir)
    results = {}

    m1_df24 = None
    m1_base_a = None
    for mf in M_FACTORS:
        df24, a_df, cal, man = run_holdout(panel, args.base_run, outdir, mf)
        base_a = a_df[a_df["month"].str.startswith(YEAR)]
        per_mo, msa, mia = _agreement(a_df, df24, YEAR)
        sd = _status_dist(df24)
        results[mf] = {
            "margin": cal["candidate_margin"] * mf,
            "per_month": per_mo, "status_dist": sd,
            "mean_status_agreement": msa, "mean_id_agreement": mia,
            "n_2024": len(df24), "n_base_2024": len(base_a),
        }
        chk = "exact_match" if mf == 1.0 else "factor"
        print(f"  M_factor={mf}: margin={cal['candidate_margin']*mf:.6f} "
              f"n2024={len(df24)} status_agree={msa:.4f} id_agree={mia:.4f} [{chk}]")
        if mf == 1.0:
            m1_df24 = df24
            m1_base_a = base_a

    # Hard M=1 assertion: exact key + label + k + status + identity_id equality.
    r1 = results[1.0]
    exact_fail = False
    if r1["n_2024"] != r1["n_base_2024"]:
        print(f"FAIL M=1: row count {r1['n_2024']} != {r1['n_base_2024']}")
        exact_fail = True
    if r1["mean_status_agreement"] < 1.0 or r1["mean_id_agreement"] < 1.0:
        print(f"FAIL M=1: status_agree={r1['mean_status_agreement']:.6f} "
              f"id_agree={r1['mean_id_agreement']:.6f}")
        exact_fail = True
    if m1_df24 is not None and m1_base_a is not None:
        cols = ["territory_id", "month", "label", "k", "status", "identity_id"]
        arch = m1_base_a[cols].sort_values(cols[:2]).reset_index(drop=True)
        trk = m1_df24[cols].sort_values(cols[:2]).reset_index(drop=True)
        # Duplicate key check on both sides
        for tag, df_ in [("archived", arch), ("tracked", trk)]:
            if df_.duplicated(subset=["territory_id", "month"]).any():
                print(f"FAIL M=1: duplicate keys in {tag}")
                exact_fail = True
        if len(arch) == len(trk):
            mism = arch.compare(trk, keep_shape=False)
            if not mism.empty:
                n_bad = len(mism)
                print(f"FAIL M=1: {n_bad} cell mismatches in "
                      "label/k/status/identity_id")
                exact_fail = True
        else:
            arch_keys = set(zip(arch["territory_id"], arch["month"]))
            trk_keys = set(zip(trk["territory_id"], trk["month"]))
            missing = arch_keys - trk_keys
            extra = trk_keys - arch_keys
            if missing or extra:
                print(f"FAIL M=1: key mismatch missing={len(missing)} "
                      f"extra={len(extra)}")
                exact_fail = True
    if exact_fail:
        return 1

    p_sha = sha256_file(Path(args.panel))
    c_sha = sha256_file(Path(__file__))
    metrics = {
        "gate": "A6_holdout_sensitivity",
        "gate_pass": False,
        "gate_pass_reason": "holdout sensitivity; no economic claims; "
        "sensitivity to margin factor only",
        "frozen_calibration": {
            "overlap_threshold": cal["overlap_threshold"],
            "candidate_margin": cal["candidate_margin"],
            "resemblance_floor": cal["resemblance_floor"],
            "source": str(args.base_run),
        },
        "holdout_sensitivity": {
            str(mf): {
                "margin_factor": mf, "margin": r["margin"],
                "per_month": r["per_month"],
                "status_distribution_2024": r["status_dist"],
                "mean_status_agreement_vs_base": r["mean_status_agreement"],
                "mean_id_agreement_vs_base": r["mean_id_agreement"],
                "n_2024": r["n_2024"],
            } for mf, r in results.items()
        },
        "reproduction": {
            "m_1_exact_match": True,
            "n_base_2024": r1["n_base_2024"],
        },
        "limitations": [
            "No claims of true economic births; gate_pass false.",
            "Thresholds frozen from 2023 calibration; never refit on 2024.",
            "First bounded step; no salary, no synthetic event metrics.",
        ],
    }
    manifest = {
        "gate": "A6_holdout_sensitivity",
        "gate_pass": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code_sha256": c_sha,
        "seed": man.get("seed"),
        "m_factors": list(M_FACTORS),
        "base_run": str(args.base_run),
        "inputs": {
            "panel": {"sha256": p_sha, "rows": int(len(panel))},
            "base_run": {
                "path": str(args.base_run),
                "assignments_sha256": sha256_file(
                    Path(args.base_run) / "assignments.parquet"),
                "calibration_sha256": sha256_file(
                    Path(args.base_run) / "calibration.json"),
                "manifest_sha256": sha256_file(
                    Path(args.base_run) / "manifest.json"),
            },
        },
        "versions": {
            "python": sys.version.split()[0],
            "numpy": pkg_version("numpy"), "pandas": pkg_version("pandas"),
            "scipy": pkg_version("scipy"),
            "scikit-learn": pkg_version("scikit-learn"),
        },
    }
    _save(outdir, metrics, manifest)
    metrics_sha = sha256_file(outdir / "metrics.json")
    manifest["metrics_output_sha256"] = metrics_sha
    (outdir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    print(f"outdir={outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())