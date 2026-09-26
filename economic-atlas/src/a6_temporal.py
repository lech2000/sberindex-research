"""A6: temporal stability / sensitivity of the monthly typology (economic-atlas).

Reads the frozen panel (data/panel_v1.parquet, 1896 tid x 24 months x 6 cats)
and studies how month-by-month cluster structure persists across time:

  shares      share(cat,tid,m) = value(cat,tid,m) / value('Все категории',tid,m)
              for the 5 non-total categories (A3 FROZEN v1, same as A5).
              The 'Все категории' row is a separate total, NOT the sum of the
              five -- never divide by sum6. No fillna(0): any non-finite cell
              or non-positive total excludes the whole tid (audited).
  standardise fit mean/std on 2023 months ONLY (mask tids x 2023 months,
              pooled, population std); the frozen transform is applied to ALL
              months. Zero-variance features get std=1.0 (z=0), audited.
              NOTE: fitting on ALL 2023 months makes 2023 labels
              retrospective (later-2023 months inform early-2023 z-scores);
              the causality-relevant check concerns 2024 months, which come
              strictly after the frozen fit.
  cluster     EACH month independently with k-means (k=5, n_init=10,
              random_state = seed + month_index). Per-month seeds make past
              outputs independent of future months (prefix invariance).
  align       label IDs across months with the Hungarian algorithm on squared
              centroid distance (month m raw labels -> month m-1 ALIGNED
              labels; month 0 keeps raw IDs). Empty raw clusters reuse the
              previous aligned centroid (audited count).
  smooth      temporal linkage is an EXPLICIT post-assignment penalty with
              FIXED centres (no refitting, no transition model):
                post(tid,m) = argmin_c ||z - C(m,c)||^2 + lambda*[c != post(tid,m-1)]
              for lambda in {0, 0.5, 2}. lambda=0 reproduces aligned labels
              exactly. THIS IS NOT A JOINT DYNAMIC MODEL: centres are fixed
              per-month k-means centres, and the penalty is applied
              deterministically after assignment. Never call it otherwise.

A6 is a SENSITIVITY analysis, not cluster biographies. At fixed K,
births/disappearances cannot be distinguished from relabelling, so they are
NEVER reported. Only split/merge CANDIDATES between aligned neighbouring
clusters are listed (overlap(a,b) = |a cap b| / min(|a|,|b|) >= 0.2), and E04
(emergence/disappearance) is marked incomplete by design at fixed K.

The synthetic abrupt-shift positive control (2 groups, 60 nodes, 12 months,
20 members changing group at month 7, with labels_truth) lives ONLY in
--self-check: it never touches observed data and its truth labels are never
written to any output file. Predicted->truth renaming is a FIXED one-to-one
mapping learned ONCE on the initial month (Hungarian assignment on the
pred x truth contingency table) and applied unchanged to ALL months and ALL
lambdas; no truth is used per month, so truth can never mask a real shift
(per-month remapping would let movers count as detected even when the
clusterer never moved them). Measured evidence: recall of the change and
movement delay per lambda -- strong smoothing CAN hide true changes.
Evidence is MEASURED (recall/time), stored under
metrics.synthetic_control.measured with provenance "synthetic_assumption",
never "observed_labels".

Usage (run from economic-atlas/ or anywhere; defaults resolve from here):
  python src/a6_temporal.py --panel data/panel_v1.parquet \\
      --outdir runs/A6 --seed 20260921
  python src/a6_temporal.py --self-check   # toy-data checks, no inputs needed

Outputs in --outdir: transitions.parquet, metrics.json, temporal_manifest.json
(plus an identical manifest.json copy: the gate driver reads manifest.json).

Deps: numpy, pandas, scipy, scikit-learn.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ATLAS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ATLAS_DIR / "data" / "panel_v1.parquet"
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A6"

TOTAL_CAT = "Все категории"
SHARE_CATS = [
    "Здоровье",
    "Маркетплейсы",
    "Общественное питание",
    "Продовольствие",
    "Транспорт",
]
ALL_CATS = [TOTAL_CAT] + SHARE_CATS

TID_CANDS = ["territory_id", "tid", "mo", "municipality_id"]
DATE_CANDS = ["date", "month", "ym", "period"]
CAT_CANDS = ["category", "cat", "category_15"]

FIT_YEAR = "2023"
OVERLAP_THRESHOLD = 0.2
DEFAULT_LAMBDAS = (0.0, 0.5, 2.0)

TRANSITION_COLUMNS = [
    "territory_id",
    "month",
    "independent_label",
    "aligned_label",
    "lambda",
    "post_label",
]

NOT_JOINT_DYNAMIC = (
    "Temporal linkage is an explicit post-assignment penalty with FIXED "
    "per-month k-means centres (no refitting, no transition matrix, no "
    "shared temporal objective). It is NOT a joint dynamic model and must "
    "never be described as one."
)

E04_NOTE = (
    "E04 (emergence/disappearance) is incomplete by design at fixed K: "
    "births/disappearances cannot be distinguished from relabelling, so "
    "they are never reported. A6 lists only split/merge CANDIDATES "
    "(overlap >= 0.2) between aligned neighbouring clusters. A6 is a "
    "sensitivity analysis of temporal linkage, not cluster biographies."
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def pkg_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _pick(columns, candidates: list[str], what: str) -> str:
    for c in candidates:
        if c in columns:
            return c
    raise ValueError(
        f"panel: no {what} column among {candidates}; got {list(columns)}"
    )


def build_monthly_shares(panel: pd.DataFrame):
    """Monthly 5-share cube. Returns (tids, months, S, audit).

    S: float array (n_tid, n_month, 5). Tids with an incomplete grid, any
    non-finite cell, or any non-positive total are excluded whole (no
    fillna(0)) and named in the audit.
    """
    tid_c = _pick(panel.columns, TID_CANDS, "territory id")
    date_c = _pick(panel.columns, DATE_CANDS, "date")
    cat_c = _pick(panel.columns, CAT_CANDS, "category")
    if "value" not in panel.columns:
        raise ValueError("panel: missing 'value' column")

    df = panel[[tid_c, date_c, cat_c, "value"]].copy()
    df["tid"] = df[tid_c].astype(int)
    df["month"] = pd.to_datetime(df[date_c]).dt.strftime("%Y-%m")
    df["value"] = df["value"].astype(float)
    months = sorted(df["month"].unique().tolist())

    dup_mask = df.duplicated(subset=["tid", "month", cat_c], keep=False)
    if bool(dup_mask.any()):
        bad = df.loc[dup_mask, ["tid", "month", cat_c]].head().to_dict(
            orient="records"
        )
        raise ValueError(
            f"panel: duplicate (tid, month, category) rows rejected: {bad}"
        )

    pivot = df.pivot_table(
        index=["tid", "month"], columns=df[cat_c], values="value", aggfunc="mean"
    )
    missing_cats = [c for c in ALL_CATS if c not in pivot.columns]
    if missing_cats:
        raise ValueError(f"panel: missing categories {missing_cats}")

    exclusions: dict[str, str] = {}
    rows = []
    for tid, g in pivot.groupby(level=0):
        tid = int(tid)
        if len(g) != len(months) or g.isna().any(axis=None):
            exclusions[str(tid)] = "incomplete_grid_or_nan_no_fillna"
            continue
        block = g[ALL_CATS]
        total = block[TOTAL_CAT].to_numpy(dtype=float)
        if not np.all(np.isfinite(total)) or np.any(total <= 0):
            exclusions[str(tid)] = "nonpositive_or_nonfinite_total"
            continue
        vals = block[SHARE_CATS].to_numpy(dtype=float)
        if not np.all(np.isfinite(vals)):
            exclusions[str(tid)] = "nonfinite_category_value_no_fillna"
            continue
        shares = vals / total[:, None]
        if not np.all(np.isfinite(shares)):
            exclusions[str(tid)] = "nonfinite_share"
            continue
        rows.append((tid, shares))

    if not rows:
        raise ValueError("panel: no tid passed monthly share validation")

    tids = np.array([t for t, _ in rows], dtype=int)
    order = np.argsort(tids)
    tids = tids[order]
    S = np.stack([s for _, s in rows], axis=0)[order]

    audit = {
        "formula": "share(cat,tid,m)=value(cat,tid,m)/value('Все категории',tid,m). "
        "Denominator is the 'Все категории' row, never sum6. No fillna(0).",
        "n_months": len(months),
        "months": months,
        "n_mask": int(len(tids)),
        "n_excluded": len(exclusions),
        "excluded_tids": exclusions,
    }
    return tids, months, S, audit


def standardize_frozen(S: np.ndarray, months: list[str]):
    """Z-score with a fit on 2023 months only; frozen transform of all months.

    Returns (Z, audit). Z has the same shape as S.
    """
    fit_idx = [i for i, m in enumerate(months) if m.startswith(FIT_YEAR)]
    if not fit_idx:
        raise ValueError(f"standardize: no {FIT_YEAR} months to fit on")
    pool = S[:, fit_idx, :].reshape(-1, S.shape[2])
    mu = pool.mean(axis=0)
    sigma = pool.std(axis=0, ddof=0)
    zero_std = sigma == 0
    sigma_safe = np.where(zero_std, 1.0, sigma)
    Z = (S - mu[None, None, :]) / sigma_safe[None, None, :]
    Z[:, :, zero_std] = 0.0
    audit = {
        "formula": f"z=(share-mu)/std, mu/std pooled over mask tids x "
        f"{FIT_YEAR} months only (ddof=0), frozen transform of all months.",
        "fit_months": [months[i] for i in fit_idx],
        "mu": {c: float(mu[i]) for i, c in enumerate(SHARE_CATS)},
        "sigma": {c: float(sigma[i]) for i, c in enumerate(SHARE_CATS)},
        "zero_variance_features": [
            c for i, c in enumerate(SHARE_CATS) if zero_std[i]
        ],
    }
    return Z, audit


def kmeans_per_month(Z: np.ndarray, k: int, seed: int):
    """Independent k-means per month. Returns (labels, centres).

    labels: (M, N) int; centres: (M, k, F) float. random_state = seed +
    month_index, so past months never depend on future months.
    """
    from sklearn.cluster import KMeans

    N, M, _ = Z.shape
    labels = np.empty((M, N), dtype=int)
    centres = np.empty((M, k, Z.shape[2]), dtype=float)
    for m in range(M):
        km = KMeans(n_clusters=k, n_init=10, random_state=seed + m)
        labels[m] = km.fit_predict(Z[:, m, :])
        centres[m] = km.cluster_centers_
    return labels, centres


def align_labels(labels: np.ndarray, centres: np.ndarray):
    """Hungarian alignment of raw label IDs to previous aligned IDs.

    Cost = squared centroid distance. Month 0 keeps raw IDs. Returns
    (aligned, aligned_centres, empty_reused) where empty_reused counts
    months x clusters whose raw cluster was empty (previous aligned
    centroid reused).
    """
    from scipy.optimize import linear_sum_assignment

    M, N = labels.shape
    k = centres.shape[1]
    aligned = np.empty((M, N), dtype=int)
    aligned_centres = np.empty_like(centres)
    empty_reused = 0
    aligned[0] = labels[0]
    aligned_centres[0] = centres[0]
    for m in range(1, M):
        prev = aligned_centres[m - 1]
        cur = centres[m]
        cost = ((cur[:, None, :] - prev[None, :, :]) ** 2).sum(axis=2)
        row_ind, col_ind = linear_sum_assignment(cost)
        mapping = dict(zip(row_ind.tolist(), col_ind.tolist()))
        lab = np.empty(N, dtype=int)
        for raw_i in range(k):
            members = labels[m] == raw_i
            j = mapping[raw_i]
            lab[members] = j
            if bool(members.any()):
                aligned_centres[m, j] = cur[raw_i]
            else:
                aligned_centres[m, j] = prev[j]
                empty_reused += 1
        aligned[m] = lab
    return aligned, aligned_centres, int(empty_reused)


def apply_penalty(
    Z: np.ndarray,
    aligned_centres: np.ndarray,
    aligned: np.ndarray,
    lambdas: tuple[float, ...],
):
    """Explicit post-assignment penalty with FIXED centres.

    post(tid,m) = argmin_c ||z - C(m,c)||^2 + lambda*[c != post(tid,m-1)].
    Month 0: post = aligned. Returns {lambda: (M, N) int}. NOT a joint
    dynamic model: centres are never refit.
    """
    N, M = Z.shape[0], Z.shape[1]
    k = aligned_centres.shape[1]
    posts: dict[float, np.ndarray] = {}
    for lam in lambdas:
        post = np.empty((M, N), dtype=int)
        post[0] = aligned[0]
        for m in range(1, M):
            d2 = ((Z[:, m, :][:, None, :] - aligned_centres[m][None, :, :]) ** 2).sum(
                axis=2
            )
            prev = post[m - 1]
            penalty = lam * (np.arange(k)[None, :] != prev[:, None])
            post[m] = np.argmin(d2 + penalty, axis=1)
        posts[float(lam)] = post
    return posts


def neighbour_overlap(aligned: np.ndarray, k: int, threshold: float = OVERLAP_THRESHOLD):
    """Overlap between aligned neighbouring clusters + split/merge candidates.

    overlap(a@m, b@m+1) = |a cap b| / min(|a|, |b|). A split candidate is a
    month-m cluster reaching >= 2 month-(m+1) clusters at overlap >=
    threshold; a merge candidate is the mirror image. Candidates only --
    never births/disappearances at fixed K.
    """
    M, N = aligned.shape
    splits = []
    merges = []
    for m in range(1, M):
        a_lab, b_lab = aligned[m - 1], aligned[m]
        inter = np.zeros((k, k), dtype=int)
        for a in range(k):
            for b in range(k):
                inter[a, b] = int(((a_lab == a) & (b_lab == b)).sum())
        size_a = np.array([(a_lab == a).sum() for a in range(k)], dtype=float)
        size_b = np.array([(b_lab == b).sum() for b in range(k)], dtype=float)
        denom = np.minimum(size_a[:, None], size_b[None, :])
        with np.errstate(invalid="ignore", divide="ignore"):
            ov = np.where(denom > 0, inter / denom, 0.0)
        for a in range(k):
            targets = [b for b in range(k) if ov[a, b] >= threshold]
            if len(targets) >= 2:
                splits.append(
                    {
                        "kind": "split_candidate",
                        "month_from": m - 1,
                        "cluster_from": int(a),
                        "month_to": m,
                        "clusters_to": [int(b) for b in targets],
                        "overlaps": [float(ov[a, b]) for b in targets],
                    }
                )
        for b in range(k):
            sources = [a for a in range(k) if ov[a, b] >= threshold]
            if len(sources) >= 2:
                merges.append(
                    {
                        "kind": "merge_candidate",
                        "month_from": m - 1,
                        "clusters_from": [int(a) for a in sources],
                        "month_to": m,
                        "cluster_to": int(b),
                        "overlaps": [float(ov[a, b]) for a in sources],
                    }
                )
    return splits, merges


def switch_rate(lab: np.ndarray) -> float:
    """Mean fraction of tids changing label between consecutive months."""
    M = lab.shape[0]
    if M < 2:
        return 0.0
    return float(np.mean([np.mean(lab[m] != lab[m - 1]) for m in range(1, M)]))


def run_pipeline(
    panel: pd.DataFrame,
    outdir: Path,
    seed: int,
    k: int,
    lambdas: tuple[float, ...] = DEFAULT_LAMBDAS,
) -> dict:
    from sklearn.metrics import (
        adjusted_rand_score,
        normalized_mutual_info_score,
        silhouette_score,
    )

    tids, months, S, share_audit = build_monthly_shares(panel)
    n_tids, n_months = S.shape[0], S.shape[1]
    Z, std_audit = standardize_frozen(S, months)
    std_audit["retrospective_note"] = (
        "fit pools ALL 2023 months, so 2023 labels are retrospective "
        "(later-2023 months inform early-2023 z-scores); the "
        "causality-relevant check concerns 2024 months, which come strictly "
        "after the frozen fit."
    )

    independent, centres = kmeans_per_month(Z, k, seed)
    aligned, aligned_centres, empty_reused = align_labels(independent, centres)
    posts = apply_penalty(Z, aligned_centres, aligned, lambdas)

    M, N = aligned.shape
    sil_aligned = [float(silhouette_score(Z[:, m, :], aligned[m])) for m in range(M)]

    per_lambda = {}
    for lam in lambdas:
        lam = float(lam)
        post = posts[lam]
        sil = [float(silhouette_score(Z[:, m, :], post[m])) for m in range(M)]
        ari = [
            float(adjusted_rand_score(aligned[m], post[m])) for m in range(M)
        ]
        nmi = [
            float(normalized_mutual_info_score(aligned[m], post[m]))
            for m in range(M)
        ]
        per_lambda[str(lam)] = {
            "switch_rate": switch_rate(post),
            "silhouette_mean": float(np.mean(sil)),
            "silhouette_per_month": sil,
            "agreement_vs_aligned_ARI_mean": float(np.mean(ari)),
            "agreement_vs_aligned_NMI_mean": float(np.mean(nmi)),
            "sizes_per_month": [
                [int((post[m] == c).sum()) for c in range(k)] for m in range(M)
            ],
        }

    splits, merges = neighbour_overlap(aligned, k)

    outdir.mkdir(parents=True, exist_ok=True)
    recs = []
    for ti, tid in enumerate(tids.tolist()):
        for mi, month in enumerate(months):
            for lam in lambdas:
                lam = float(lam)
                recs.append(
                    {
                        "territory_id": int(tid),
                        "month": month,
                        "independent_label": int(independent[mi, ti]),
                        "aligned_label": int(aligned[mi, ti]),
                        "lambda": lam,
                        "post_label": int(posts[lam][mi, ti]),
                    }
                )
    transitions = pd.DataFrame(recs, columns=TRANSITION_COLUMNS)
    transitions.to_parquet(outdir / "transitions.parquet", index=False)

    metrics = {
        "gate": "A6",
        "status": "PARTIAL_NOT_GATE_PASS",
        "gate_pass": False,
        "gate_pass_reason": "A6 is a temporal sensitivity analysis at fixed K, "
        "not a gate pass: E04 is incomplete by design and case06 completion "
        "is never claimed",
        "e04_incomplete": True,
        "e04_incomplete_reason": "fixed K: births/disappearances are "
        "indistinguishable from relabelling",
        "completed_components": ["temporal_sensitivity"],
        "pending_components": ["e04_emergence_disappearance", "case06_completion"],
        "completes_case06": False,
        "seed": seed,
        "k": k,
        "lambdas": [float(l) for l in lambdas],
        "frozen_panel": {
            "n_tids": int(n_tids),
            "n_months": int(n_months),
            "n_cats": len(ALL_CATS),
            "months": months,
            "expected_shape": [1896, 24, 6],
            "frozen_shape_ok": bool(
                n_tids == 1896 and n_months == 24 and len(ALL_CATS) == 6
            ),
        },
        "mask": {
            "n": int(n_tids),
            "rule": "tids with a complete 24-month x 6-category grid, all "
            "finite values, all totals positive; no fillna(0)",
            "n_excluded": share_audit["n_excluded"],
            "excluded_tids": share_audit["excluded_tids"],
        },
        "share_audit": share_audit,
        "standardization": std_audit,
        "clustering": {
            "method": "per-month k-means",
            "n_init": 10,
            "per_month_seed": "seed + month_index (prefix invariance: "
            "future months never alter past outputs)",
            "alignment": "Hungarian on squared centroid distance to previous "
            "aligned centroids; month 0 keeps raw IDs",
            "empty_raw_clusters_reused_previous_centroid": empty_reused,
        },
        "temporal_linkage": {
            "formula": "post(tid,m)=argmin_c ||z-C(m,c)||^2 + "
            "lambda*[c != post(tid,m-1)], fixed centres",
            "note": NOT_JOINT_DYNAMIC,
        },
        "sensitivity": {
            "aligned_switch_rate": switch_rate(aligned),
            "aligned_silhouette_mean": float(np.mean(sil_aligned)),
            "per_lambda": per_lambda,
        },
        "neighbours": {
            "overlap_formula": "overlap(a@m,b@m+1)=|a cap b|/min(|a|,|b|)",
            "overlap_threshold": OVERLAP_THRESHOLD,
            "split_candidates": splits,
            "merge_candidates": merges,
            "note": "Candidates only. Births/disappearances are never "
            "reported at fixed K.",
        },
        "e04": E04_NOTE,
        "synthetic_control": {
            "status": "separate_toy_only_run_under_self_check",
            "design": "2 groups, 60 nodes, 12 months, 20 members change "
            "group at month 7, labels_truth kept in memory only",
            "mapping": "fixed one-to-one predicted->truth mapping learned "
            "ONCE on the initial month (Hungarian assignment on the pred x "
            "truth contingency table), applied unchanged to ALL months and "
            "ALL lambdas; no truth is used per month, so truth can never "
            "mask a real shift",
            "never_in_outputs": True,
            "observed_labels_used": False,
            "provenance": "synthetic_assumption",
            "measured": None,
            "measured_note": "measured recall/time evidence lives only in "
            "self-check stdout (toy), never in real-run outputs",
            "finding": "strong smoothing can hide true changes; "
            "lambda=0 must recover the shift with ~0 delay",
        },
    }
    with open(outdir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    manifest = {
        "gate": "A6",
        "status": "PARTIAL_NOT_GATE_PASS",
        "gate_pass": False,
        "e04_incomplete": True,
        "completes_case06": False,
        "completed_components": ["temporal_sensitivity"],
        "pending_components": ["e04_emergence_disappearance", "case06_completion"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {"file": Path(__file__).name, "sha256": sha256_file(Path(__file__))},
        "seed": seed,
        "params": {"k": k, "lambdas": [float(l) for l in lambdas]},
        "inputs": {
            "panel": {"sha256": "see-operator-run", "rows": "see-operator-run"},
        },
        "formulas": {
            "share": share_audit["formula"],
            "standardization": std_audit["formula"],
            "temporal_linkage": metrics["temporal_linkage"]["formula"],
            "overlap": metrics["neighbours"]["overlap_formula"],
        },
        "versions": {
            "python": sys.version.split()[0],
            "numpy": pkg_version("numpy"),
            "pandas": pkg_version("pandas"),
            "scipy": pkg_version("scipy"),
            "scikit-learn": pkg_version("scikit-learn"),
        },
        "mask": {"n": int(n_tids)},
        "e04": E04_NOTE,
    }
    with open(outdir / "temporal_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    with open(outdir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return {
        "metrics": metrics,
        "manifest": manifest,
        "outdir": str(outdir),
        "transitions": transitions,
    }


def _toy_panel(
    n_tid: int = 30,
    months: list[str] | None = None,
    seed: int = 20260921,
    movers: tuple[int, ...] = (),
    move_month_idx: int | None = None,
    noise: float = 0.008,
):
    """Structured toy panel: 2 well-separated share groups (5 cats + total).

    movers: tids (1-based) that switch group at move_month_idx. Returns
    (panel, truth) where truth is (n_tid, n_month) int -- toy only, never
    written to outputs.
    """
    rng = np.random.default_rng(seed)
    if months is None:
        months = [f"2023-0{m}" for m in range(1, 7)]
    g0 = np.array([0.10, 0.15, 0.10, 0.20, 0.05])
    g1 = np.array([0.16, 0.11, 0.15, 0.17, 0.09])
    rows = []
    truth = np.zeros((n_tid, len(months)), dtype=int)
    for t in range(1, n_tid + 1):
        base_group = 0 if t <= n_tid // 2 else 1
        for mi, m in enumerate(months):
            grp = base_group
            if (
                move_month_idx is not None
                and t in movers
                and mi >= move_month_idx
            ):
                grp = 1 - base_group
            truth[t - 1, mi] = grp
            shares = (g0 if grp == 0 else g1) + rng.normal(0, noise, size=5)
            shares = np.clip(shares, 0.005, None)
            total = 1000.0
            rows.append((t, m, TOTAL_CAT, total))
            for c, v in zip(SHARE_CATS, shares):
                rows.append((t, m, c, float(v * total)))
    panel = pd.DataFrame(rows, columns=["territory_id", "date", "category", "value"])
    return panel, truth


def _fixed_pred_to_truth_mapping(
    pred_m0: np.ndarray, truth_m0: np.ndarray
) -> dict[int, int]:
    """One-to-one predicted->truth mapping learned ONCE on the initial month.

    Hungarian assignment on the pred x truth contingency table (max overlap).
    Pred labels left unassigned (non-square case) fall back to the majority
    truth of the INITIAL month only -- never of any later month.
    """
    from scipy.optimize import linear_sum_assignment

    pred_vals = sorted(set(pred_m0.tolist()))
    truth_vals = sorted(set(truth_m0.tolist()))
    cont = np.zeros((len(pred_vals), len(truth_vals)), dtype=int)
    for i, p in enumerate(pred_vals):
        for j, t in enumerate(truth_vals):
            cont[i, j] = int(((pred_m0 == p) & (truth_m0 == t)).sum())
    row_ind, col_ind = linear_sum_assignment(-cont)
    mapping = {int(pred_vals[i]): int(truth_vals[j])
               for i, j in zip(row_ind.tolist(), col_ind.tolist())}
    for p in pred_vals:
        if int(p) not in mapping:
            sel = pred_m0 == p
            vals, counts = np.unique(truth_m0[sel], return_counts=True)
            mapping[int(p)] = int(vals[int(np.argmax(counts))])
    return mapping


def _apply_fixed_mapping(
    pred: np.ndarray, mapping: dict[int, int], default: int
) -> np.ndarray:
    """Rename predicted labels with a FIXED mapping (no truth consulted)."""
    mapped = np.empty_like(pred)
    for p in sorted(set(pred.tolist())):
        mapped[pred == p] = mapping.get(int(p), default)
    return mapped


def _synthetic_control(seed: int = 20260921):
    """Abrupt-shift positive control: 2 groups, 60 nodes, 12 months.

    20 members of group 0 move to group 1 at month 7 (index 6).
    labels_truth stays in memory and is never written anywhere. A FIXED
    one-to-one predicted->truth mapping is learned ONCE on the initial
    month (Hungarian assignment on the pred x truth contingency) from the
    lambda=0 run, then applied unchanged to ALL months and ALL lambdas --
    no truth is consulted per month. Returns evidence dict: recall of the
    shift + movement delay per lambda, with provenance synthetic_assumption.
    """
    n_tid, n_month = 60, 12
    months = [f"2023-{m:02d}" for m in range(1, 13)]
    movers = tuple(range(1, 21))
    panel, truth = _toy_panel(
        n_tid=n_tid, months=months, seed=seed, movers=movers,
        move_month_idx=6, noise=0.008,
    )
    tids, ms, S, _ = build_monthly_shares(panel)
    assert ms == months and len(tids) == n_tid
    Z, _ = standardize_frozen(S, ms)
    lambdas = (0.0, 2.0, 50.0)
    independent, centres = kmeans_per_month(Z, 2, seed)
    aligned, aligned_centres, _ = align_labels(independent, centres)
    posts = apply_penalty(Z, aligned_centres, aligned, lambdas)
    movers_idx = np.array([t - 1 for t in movers])
    base_m0 = posts[0.0][0]
    mapping = _fixed_pred_to_truth_mapping(base_m0, truth[:, 0])
    default_t = int(np.unique(truth[:, 0])[0])
    measured: dict[str, dict] = {}
    for lam in lambdas:
        post = posts[float(lam)]
        mapped = np.stack(
            [_apply_fixed_mapping(post[m], mapping, default_t)
             for m in range(n_month)]
        ).T
        rec7 = float(np.mean(mapped[movers_idx, 6] == truth[movers_idx, 6]))
        delays = []
        for i in movers_idx.tolist():
            det = next(
                (m for m in range(6, n_month) if mapped[i, m] == truth[i, m]),
                n_month,
            )
            delays.append(det - 6)
        measured[str(float(lam))] = {
            "recall_movers_month7": rec7,
            "mean_movement_delay_months": float(np.mean(delays)),
        }
    return {
        "measured": measured,
        "mapping": {
            "method": "hungarian_contingency_initial_month_only",
            "fixed_mapping_pred_to_truth": {str(k): v for k, v in mapping.items()},
        },
        "provenance": "synthetic_assumption",
        "provenance_note": "measured recall/time evidence only; never observed_labels",
    }


def self_check() -> int:
    ok = True

    def check(name: str, cond: bool, detail: str = ""):
        nonlocal ok
        print(f"self-check {name}: {'PASS' if cond else 'FAIL'} {detail}")
        if not cond:
            ok = False

    # 1. Stable toy: determinism, full mask, tight groups, no switching.
    panel, _ = _toy_panel()
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2:
        r1 = run_pipeline(panel, Path(t1), seed=20260921, k=2)
        r2 = run_pipeline(panel, Path(t2), seed=20260921, k=2)
        tr1 = pd.read_parquet(Path(t1) / "transitions.parquet")
        tr2 = pd.read_parquet(Path(t2) / "transitions.parquet")
        check("toy_columns", list(tr1.columns) == TRANSITION_COLUMNS,
              f"{list(tr1.columns)}")
        check("toy_mask", sorted(tr1["territory_id"].unique().tolist())
              == list(range(1, 31)), f"n_tid={tr1['territory_id'].nunique()}")
        check("toy_determinism", tr1.equals(tr2))
        m1 = json.dumps(r1["metrics"], sort_keys=True)
        check("toy_metrics_repro", m1 == json.dumps(r2["metrics"], sort_keys=True))
        sens = r1["metrics"]["sensitivity"]["per_lambda"]
        check("toy_no_switch_l0", sens["0.0"]["switch_rate"] == 0.0,
              f"switch={sens['0.0']['switch_rate']}")
        check("toy_no_switch_l2", sens["2.0"]["switch_rate"] == 0.0)
        check("toy_silhouette", sens["0.0"]["silhouette_mean"] > 0.5,
              f"sil={sens['0.0']['silhouette_mean']:.3f}")
        check("toy_l0_is_aligned",
              bool((tr1[tr1["lambda"] == 0.0]["post_label"].to_numpy()
                    == tr1[tr1["lambda"] == 0.0]["aligned_label"].to_numpy()).all()))
        check("toy_frozen_shape_flag_false",
              r1["metrics"]["frozen_panel"]["frozen_shape_ok"] is False)
        check("toy_no_truth_leak", "labels_truth" not in tr1.columns
              and "truth" not in " ".join(tr1.columns).lower())
        check("toy_status_partial", r1["metrics"].get("status")
              == "PARTIAL_NOT_GATE_PASS" and r1["metrics"].get("gate_pass") is False)
        check("toy_e04_incomplete", r1["metrics"].get("e04_incomplete") is True)
        check("toy_no_case06",
              r1["metrics"].get("completes_case06") is False
              and r1["metrics"].get("completed_components") == ["temporal_sensitivity"])
        check("toy_manifest_partial", r1["manifest"].get("status")
              == "PARTIAL_NOT_GATE_PASS" and r1["manifest"].get("e04_incomplete") is True
              and r1["manifest"].get("completes_case06") is False)
        check("toy_synth_measured_slot",
              "measured" in r1["metrics"].get("synthetic_control", {})
              and r1["metrics"]["synthetic_control"].get("provenance")
              == "synthetic_assumption")
        m1t = json.loads((Path(t1) / "temporal_manifest.json").read_text(encoding="utf-8"))
        m1m = json.loads((Path(t1) / "manifest.json").read_text(encoding="utf-8"))
        check("toy_manifest_copy_identical", m1t == m1m)
        check("toy_hash_inputs_equal",
              m1t.get("inputs") == m1m.get("inputs"))

    # 2. Prefix invariance: past outputs must not depend on future months.
    # NOTE: the prefix panel is sliced from panel_full (date in prefix),
    # NEVER regenerated with a new RNG and a shorter month list: a fresh
    # RNG stream with different length changes draws for later tids and
    # would alter the "past" itself. A third panel edits ONLY future
    # months (date > last prefix month) by scaling values; past rows and
    # the frozen 2023 fit must stay identical (2023 labels are
    # retrospective by construction -- all-2023 fit -- so the
    # causality-relevant check concerns 2024 months after the frozen fit).
    full_months = [f"2023-{m:02d}" for m in range(1, 13)] + [
        f"2024-{m:02d}" for m in range(1, 7)
    ]
    prefix_months = full_months[:15]
    last_prefix = prefix_months[-1]
    panel_full, _ = _toy_panel(n_tid=24, months=full_months, seed=7)
    panel_prefix = panel_full[panel_full["date"].isin(prefix_months)].copy()
    panel_edited = panel_full.copy()
    fut_mask = panel_edited["date"] > last_prefix
    panel_edited.loc[fut_mask, "value"] = (
        panel_edited.loc[fut_mask, "value"] * 1.5 + 10.0
    )
    with tempfile.TemporaryDirectory() as t1, tempfile.TemporaryDirectory() as t2, \
            tempfile.TemporaryDirectory() as t3:
        rf = run_pipeline(panel_full, Path(t1), seed=20260921, k=2)
        rp = run_pipeline(panel_prefix, Path(t2), seed=20260921, k=2)
        re_ = run_pipeline(panel_edited, Path(t3), seed=20260921, k=2)
        tf = pd.read_parquet(Path(t1) / "transitions.parquet")
        tp = pd.read_parquet(Path(t2) / "transitions.parquet")
        te = pd.read_parquet(Path(t3) / "transitions.parquet")
        check("prefix_same_mask",
              sorted(tf["territory_id"].unique()) == sorted(tp["territory_id"].unique()))
        past_f = tf[tf["month"].isin(prefix_months)].sort_values(
            ["territory_id", "month", "lambda"]).reset_index(drop=True)
        past_p = tp.sort_values(
            ["territory_id", "month", "lambda"]).reset_index(drop=True)
        check("prefix_past_unchanged", past_f.equals(past_p),
              f"rows={len(past_p)}")
        past_e = te[te["month"].isin(prefix_months)].sort_values(
            ["territory_id", "month", "lambda"]).reset_index(drop=True)
        check("prefix_edited_future_past_unchanged", past_f.equals(past_e),
              f"rows={len(past_e)}")
        mu_f = rf["metrics"]["standardization"]["mu"]
        mu_p = rp["metrics"]["standardization"]["mu"]
        mu_e = re_["metrics"]["standardization"]["mu"]
        check("prefix_same_2023_fit",
              json.dumps(mu_f, sort_keys=True) == json.dumps(mu_p, sort_keys=True))
        check("prefix_edited_future_same_2023_fit",
              json.dumps(mu_f, sort_keys=True) == json.dumps(mu_e, sort_keys=True))

    # 3. Synthetic abrupt-shift positive control (truth in memory only).
    ev = _synthetic_control()
    mev = ev["measured"]
    check("synth_detect_l0", mev["0.0"]["recall_movers_month7"] >= 0.95
          and mev["0.0"]["mean_movement_delay_months"] == 0.0, f"{mev['0.0']}")
    check("synth_smoothing_hides",
          mev["50.0"]["recall_movers_month7"] < mev["0.0"]["recall_movers_month7"],
          f"recall0={mev['0.0']['recall_movers_month7']} "
          f"recall50={mev['50.0']['recall_movers_month7']} "
          f"delay50={mev['50.0']['mean_movement_delay_months']}")
    check("synth_provenance_assumption",
          ev.get("provenance") == "synthetic_assumption")
    check("synth_fixed_mapping",
          ev.get("mapping", {}).get("method")
          == "hungarian_contingency_initial_month_only")
    print(f"self-check synthetic evidence: {json.dumps(ev, sort_keys=True)}")

    print("self-check: ALL PASS" if ok else "self-check: FAILURES")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEFAULT_PANEL))
    p.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    p.add_argument("--seed", type=int, default=20260921)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--lambdas", default="0,0.5,2",
                   help="comma-separated post-assignment penalties")
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args(argv)

    if args.self_check:
        return self_check()

    lambdas = tuple(float(x) for x in args.lambdas.split(",") if x.strip())
    if not lambdas:
        p.error("--lambdas must list at least one value")

    panel_path = Path(args.panel)
    outdir = Path(args.outdir)
    panel = pd.read_parquet(panel_path)
    res = run_pipeline(panel, outdir, seed=args.seed, k=args.k, lambdas=lambdas)
    inputs = {
        "panel": {"path": str(panel_path), "sha256": sha256_file(panel_path),
                  "rows": int(len(panel))},
    }
    for name in ("temporal_manifest.json", "manifest.json"):
        man_path = outdir / name
        man = json.loads(man_path.read_text(encoding="utf-8"))
        man["inputs"] = inputs
        man_path.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                            encoding="utf-8")
    m = res["metrics"]
    print(f"A6 done: mask_n={m['mask']['n']} months={m['frozen_panel']['n_months']} "
          f"frozen_shape_ok={m['frozen_panel']['frozen_shape_ok']}")
    print(f"  aligned_switch_rate={m['sensitivity']['aligned_switch_rate']:.4f}")
    for lam, mm in m["sensitivity"]["per_lambda"].items():
        print(f"  lambda={lam}: switch={mm['switch_rate']:.4f} "
              f"sil={mm['silhouette_mean']:.4f} "
              f"ARI={mm['agreement_vs_aligned_ARI_mean']:.4f}")
    print(f"  split_candidates={len(m['neighbours']['split_candidates'])} "
          f"merge_candidates={len(m['neighbours']['merge_candidates'])}")
    print(f"outdir={outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
