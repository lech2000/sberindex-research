"""A6-identities: variable-K monthly typology + M2 identity tracking + M3 split/merge.

Reads the frozen panel (data/panel_v1.parquet) and advances A6 past the fixed-K
sensitivity analysis in a6_temporal.py:

  shares      reused verbatim from a6_temporal.build_monthly_shares: share =
              value(cat)/value('Все категории'), denominator never sum6, no
              fillna(0), whole-tid exclusion audited there.
  scaler      reused frozen pooled-2023 z-score from a6_temporal
              (standardize_frozen): mu/std pooled over mask tids x 2023 months
              only, applied to all months. Fitting on ALL 2023 months makes
              2023 outputs retrospective (later-2023 months inform early-2023
              z-scores); the causality-relevant check concerns 2024 months,
              which come strictly after the frozen fit. Audited in metrics.
  K select    EACH month independently over grid K=2..8 (n_init=10,
              random_state = seed + month_index + k). Selection = largest
              silhouette on a deterministic at-most-400 sample of the CURRENT
              month only (rng seeded by seed+month, identical subsample across
              k). Ties -> smallest k. The policy is fixed in advance; the
              chosen K is NEVER called optimal. No fixed K=5 anywhere.
  M2 regions  isotropic Gaussian per cluster: centre = fitted k-means centre,
              RMS radius r = sqrt(mean ||x-mu||^2), per-coordinate variance =
              r^2/F floored at VAR_FLOOR. Overlap = Bhattacharyya coefficient
              for isotropic Gaussians (exact closed form, see bc_iso).
  M2 calib    overlap threshold T and candidate margin M from bootstrap
              self-vs-other in 2023 ONLY: resample members (B=200), BC(boot,
              own region) vs BC(boot, other same-month regions). T = q95 of
              other-scores; M = max(0, q5(self) - q95(other)). If the self/other
              distributions overlap the calibration reports ambiguity (measured
              quantiles) instead of a fake-clean separation. Frozen T/M apply
              to all months (2023 application is retrospective, audited).
  M2 track    recognition requires overlap >= T AND margin (best-second) > M.
              One-to-one conflicts (two clusters, one identity) resolve
              explicitly: higher overlap wins, losers become ambiguous with
              recorded provenance. Live identity unseen -> dormant (misses
              1..3); recognised dormant -> reemergence; unseen a 4th month ->
              disappearance/retirement. Cluster statuses: initial (month 0,
              never a birth), continuing, reemergence, birth (clean new, the
              ONLY confirmed-birth status), birth_candidate (new cluster with
              sub-threshold resemblance, NOT confirmed), ambiguous (never
              counted as confirmed birth).
  M3 events   split/merge CANDIDATES from geometric containment only:
              containment = fraction of member points inside sphere(mu_c,
              kappa*r_c). Split: parent identity -> >=2 current children each
              with child-composition containment >= threshold AND the parent
              has no single recognised continuation (proximity alone never
              suffices). Merge: >=2 previous parents each with >= threshold of
              their members inside the child sphere. Operating point
              kappa=2.5 / containment=0.6 plus sensitivity grid
              kappa in {1.5,2.0,2.5} x containment in {0.6,0.75}. Every event
              is labelled an algorithmic candidate, never a verified economic
              change; no case closure is claimed.

Outputs in --outdir: assignments.parquet, regions.csv, events.csv,
calibration.json, k_grid.csv, metrics.json, manifest.json.

--self-check runs toy-data controls only (no inputs needed): independent
tracker test on known region memberships (cluster-count truth never feeds the
economic pipeline), part-whole split/merge vs proximity negative control,
ambiguous twins, future-prefix invariance after the 2023 fit, determinism and
K-grid honesty. Every control COMPUTES detected counts/recall/false positives
from the machinery output; failures are reported measured, never hidden.

Deps: numpy, pandas, scipy, scikit-learn. (parquet IO via the pandas engine,
same as a6_temporal.)
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

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from a6_temporal import (  # noqa: E402  (same-dir sibling, reused frozen pieces)
    FIT_YEAR,
    SHARE_CATS,
    TOTAL_CAT,
    build_monthly_shares,
    pkg_version,
    sha256_file,
    standardize_frozen,
)

ATLAS_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PANEL = ATLAS_DIR / "data" / "panel_v1.parquet"
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A6_v2"
DEFAULT_SEED = 20260926

K_MIN, K_MAX = 2, 8
N_INIT = 10
SIL_CAP = 400
VAR_FLOOR = 1e-6
DORMANT_MAX_MISSES = 3
OP_KAPPA = 2.5
OP_CONT = 0.6
KAPPA_GRID = (1.5, 2.0, 2.5)
CONT_GRID = (0.6, 0.75)
BOOT_B = 200
CAL_MIN_SIZE = 8

ASSIGN_COLUMNS = ["territory_id", "month", "k", "label", "identity_id", "status"]
K_GRID_COLUMNS = ["month", "k", "silhouette", "n_sample", "chosen"]
EVENT_COLUMNS = [
    "month",
    "kind",
    "identity_id",
    "cluster",
    "month_from",
    "extra_ids",
    "overlap",
    "margin",
    "kappa",
    "containment",
    "note",
]

K_POLICY = (
    "per-month argmax silhouette over K=2..8 (n_init=10, "
    "random_state=seed+month+k) on a deterministic at-most-400 subsample "
    "(rng seeded by seed+month, identical subsample across k) of the CURRENT "
    "month only; ties -> smallest k. Fixed in advance; chosen K is never "
    "claimed optimal."
)

LIMITATIONS = [
    "2023 outputs are retrospective: the frozen scaler pools ALL 2023 months "
    "and the calibration pools ALL 2023 months, so later-2023 months inform "
    "early-2023 z-scores, thresholds and labels. Causality-relevant months "
    "are 2024+, strictly after the frozen fit/calibration.",
    "Chosen K is a silhouette-argmax heuristic on a <=400 subsample, not an "
    "optimal cluster count; K trajectory must be read as-is.",
    "Identity events (birth/dormant/disappearance/reemergence/split/merge) "
    "are algorithmic candidates from geometric overlap/containment, never "
    "verified economic changes; ambiguous clusters are never confirmed "
    "births; month-0 clusters are 'initial', never births.",
    "Recognition uses frozen 2023-calibrated T/M; if calibration reports "
    "self/other ambiguity the separation is uncertain by measurement.",
]


def _f(x) -> float:
    return float(np.asarray(x, dtype=float).ravel()[0])


def select_k_for_month(X: np.ndarray, month_idx: int, seed: int):
    """Variable-K selection for one month. Returns (best_k, rows, note).

    rows: list of (k, silhouette-or-nan, n_sample). Uses current-month X only.
    """
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    N = int(X.shape[0])
    n = min(N, SIL_CAP)
    if n < N:
        rng = np.random.default_rng(seed + 100003 * month_idx + 17)
        idx = rng.choice(N, size=n, replace=False)
    else:
        idx = np.arange(N)
    Xs = X[idx]
    rows = []
    for k in range(K_MIN, K_MAX + 1):
        if k > N:
            rows.append((k, float("nan"), n))
            continue
        km = KMeans(n_clusters=k, n_init=N_INIT,
                    random_state=seed + month_idx + k)
        lab = km.fit_predict(X)
        try:
            sil = float(silhouette_score(Xs, lab[idx]))
        except ValueError:
            sil = float("nan")
        rows.append((k, sil, n))
    finite = [(k, s) for k, s, _ in rows if np.isfinite(s)]
    note = ""
    if finite:
        best_s = max(s for _, s in finite)
        best = min(k for k, s in finite if s == best_s)
    else:
        best = K_MIN
        note = "all silhouette scores nan (degenerate month); fallback k=2 audited"
    return best, rows, note


def fit_month(X: np.ndarray, month_idx: int, seed: int, k: int):
    """Independent k-means fit for one month. Returns (labels, centres)."""
    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=k, n_init=N_INIT, random_state=seed + month_idx + k)
    return km.fit_predict(X).astype(int), np.asarray(km.cluster_centers_)


def region_of_members(pts: np.ndarray, centre: np.ndarray):
    """Isotropic Gaussian region: RMS radius -> per-coordinate variance."""
    F = int(pts.shape[1]) if pts.ndim == 2 else int(len(centre))
    if len(pts) == 0:
        return 0.0, VAR_FLOOR
    d2 = ((pts - centre[None, :]) ** 2).sum(axis=1)
    rms = float(np.sqrt(np.mean(d2)))
    var = max(rms * rms / F, VAR_FLOOR)
    return rms, float(var)


def bc_iso(mu1: np.ndarray, v1: float, mu2: np.ndarray, v2: float) -> float:
    """Bhattacharyya coefficient for N(mu1,v1*I) vs N(mu2,v2*I).

    BC = [2*s1*s2/(v1+v2)]^(F/2) * exp(-||d||^2 / (4*(v1+v2))).
    """
    mu1 = np.asarray(mu1, dtype=float)
    mu2 = np.asarray(mu2, dtype=float)
    F = int(mu1.shape[0])
    s1, s2 = float(np.sqrt(v1)), float(np.sqrt(v2))
    denom = float(v1 + v2)
    if denom <= 0:
        return 0.0
    d2 = float(((mu1 - mu2) ** 2).sum())
    pref = (2.0 * s1 * s2 / denom) ** (F / 2.0)
    return float(pref * np.exp(-d2 / (4.0 * denom)))


def _quantiles(xs: np.ndarray) -> dict:
    q = {}
    for level, name in ((0.01, "q01"), (0.05, "q05"), (0.25, "q25"),
                        (0.50, "q50"), (0.75, "q75"), (0.95, "q95"),
                        (0.99, "q99")):
        q[name] = float(np.quantile(xs, level)) if len(xs) else float("nan")
    return q


def calibrate_thresholds(Z: np.ndarray,
                         labels_per_month: list[np.ndarray],
                         cal_months: list[int], seed: int) -> dict:
    """Bootstrap self-vs-other calibration on 2023 months only.

    Z is the (N, months, F) cube; month m uses Z[:, m, :] (rows align with
    labels_per_month[m]; stable tid order).
    Returns dict with quantiles, overlap_threshold T, candidate_margin M,
    resemblance floor T_cand (=q50 other), ambiguity flag and audit counts.
    """
    self_scores: list[float] = []
    other_scores: list[float] = []
    skipped = 0
    rng = np.random.default_rng(seed + 555555)
    for m in cal_months:
        X = np.asarray(Z[:, m, :], dtype=float)
        lab = np.asarray(labels_per_month[m])
        clusters = sorted(int(c) for c in set(lab.tolist()))
        full = {}
        for c in clusters:
            pts = X[lab == c]
            if len(pts) < CAL_MIN_SIZE:
                skipped += 1
                continue
            mu = pts.mean(axis=0)
            rms, var = region_of_members(pts, mu)
            full[c] = (mu, var)
        for c, (mu, var) in full.items():
            pts = X[lab == c]
            n = len(pts)
            for _ in range(BOOT_B):
                bidx = rng.integers(0, n, size=n)
                bpts = pts[bidx]
                bmu = bpts.mean(axis=0)
                _, bvar = region_of_members(bpts, bmu)
                self_scores.append(bc_iso(bmu, bvar, mu, var))
                for o, (omu, ovar) in full.items():
                    if o != c:
                        other_scores.append(bc_iso(bmu, bvar, omu, ovar))
    qs = _quantiles(np.array(self_scores))
    qo = _quantiles(np.array(other_scores))
    fallback = not (len(self_scores) and len(other_scores))
    if fallback:
        T, M, Tc = 0.5, 0.0, 0.25
    else:
        T = qo["q95"]
        M = max(0.0, qs["q05"] - qo["q95"])
        Tc = qo["q50"]
    ambiguity = bool(
        len(self_scores) and len(other_scores) and qs["q05"] < qo["q95"])
    return {
        "method": "bootstrap self-vs-other, B=%d, months=2023 only, "
                  "min_cluster_size=%d" % (BOOT_B, CAL_MIN_SIZE),
        "cal_months": [int(m) for m in cal_months],
        "n_self_scores": len(self_scores),
        "n_other_scores": len(other_scores),
        "n_clusters_skipped_small": int(skipped),
        "quantiles_self": qs,
        "quantiles_other": qo,
        "overlap_threshold": float(T),
        "candidate_margin": float(M),
        "resemblance_floor": float(Tc),
        "ambiguity": ambiguity,
        "ambiguity_note": "self q05 < other q95: bootstrapped self-overlap "
                          "and cross-cluster overlap distributions overlap; "
                          "separation is uncertain by measurement, not clean."
        if ambiguity else "self q05 >= other q95 at measured quantiles.",
        "fallback": bool(fallback),
        "fallback_note": "no eligible 2023 clusters; fixed T=0.5/M=0.0 used, "
                         "recognition evidence weak by construction."
        if fallback else "",
    }


def _new_iid(counter: int) -> str:
    return f"ID{counter:04d}"


def track_identities(months: list[str], labels_per_month: list[np.ndarray],
                     centres_per_month: list[np.ndarray],
                     Z: np.ndarray,
                     tids: np.ndarray, T: float, M: float, Tc: float):
    """M2 identity tracking. Returns (assign_rows, region_rows, events).

    Z is the (N, months, F) cube; month m uses Z[:, m, :]. Assign rows carry
    "ti", the row index into Z[:, m, :] (real pipeline: stable tid order).
    """
    N = len(tids)
    identities: dict[str, dict] = {}
    counter = 1
    assign_rows: list[dict] = []
    region_rows: list[dict] = []
    events: list[dict] = []

    def ev(month, kind, iid="", cluster=None, month_from="", extra="",
           overlap=None, margin=None, note=""):
        events.append({
            "month": month, "kind": kind, "identity_id": iid,
            "cluster": cluster, "month_from": month_from, "extra_ids": extra,
            "overlap": overlap, "margin": margin, "kappa": None,
            "containment": None, "note": note,
        })

    for m, month in enumerate(months):
        X = np.asarray(Z[:, m, :], dtype=float)
        lab = np.asarray(labels_per_month[m]).astype(int)
        clusters = sorted(int(c) for c in set(lab.tolist()))
        regs = {}
        for c in clusters:
            pts = X[lab == c]
            mu = np.asarray(centres_per_month[m][c], dtype=float)
            rms, var = region_of_members(pts, mu)
            regs[c] = {"mu": mu, "rms": rms, "var": var, "size": int(len(pts))}
        F = int(X.shape[1])
        if m == 0:
            for c in clusters:
                iid = _new_iid(counter)
                counter += 1
                identities[iid] = {"misses": 0, "last": 0,
                                   "mu": regs[c]["mu"], "var": regs[c]["var"]}
                for ti in np.where(lab == c)[0].tolist():
                    assign_rows.append({"ti": int(ti), "month": month,
                                        "label": c, "identity_id": iid,
                                        "status": "initial"})
                rr = {"month": month, "cluster": c, "identity_id": iid,
                      "status": "initial", "size": regs[c]["size"],
                      "radius": regs[c]["rms"], "var": regs[c]["var"]}
                for f in range(F):
                    rr[f"centre_{f}"] = float(regs[c]["mu"][f])
                region_rows.append(rr)
                ev(month, "initial", iid, c, "", "", None, None,
                   "month-0 cluster; never counted as birth")
            continue

        eligible = [iid for iid, inf in identities.items()
                    if inf["misses"] <= DORMANT_MAX_MISSES]
        ov: dict[int, list[tuple[str, float]]] = {}
        for c in clusters:
            lst = [(iid, bc_iso(regs[c]["mu"], regs[c]["var"],
                                identities[iid]["mu"], identities[iid]["var"]))
                   for iid in eligible]
            lst.sort(key=lambda t: -t[1])
            ov[c] = lst

        recog: dict[int, tuple[str, float, float]] = {}
        for c in clusters:
            if not ov[c]:
                continue
            best_iid, best = ov[c][0]
            second = ov[c][1][1] if len(ov[c]) > 1 else 0.0
            margin = best - second
            if best >= T and margin > M:
                recog[c] = (best_iid, float(best), float(margin))

        order = sorted(recog.items(), key=lambda kv: -kv[1][1])
        winner: dict[int, str] = {}
        used_iid: set[str] = set()
        for c, (iid, best, margin) in order:
            if iid in used_iid:
                ev(month, "conflict", iid, c, months[m - 1], "", best,
                   margin, "lost one-to-one conflict; marked ambiguous, "
                   "never a confirmed birth")
                continue
            winner[c] = iid
            used_iid.add(iid)

        matched: set[str] = set()
        for c in clusters:
            if c in winner:
                iid = winner[c]
                was_dormant = identities[iid]["misses"] > 0
                identities[iid].update({"misses": 0, "last": m,
                                        "mu": regs[c]["mu"],
                                        "var":regs[c]["var"]})
                matched.add(iid)
                status = "reemergence" if was_dormant else "continuing"
                _, best, margin = recog[c]
                for ti in np.where(lab == c)[0].tolist():
                    assign_rows.append({"ti": int(ti), "month": month,
                                        "label": c, "identity_id": iid,
                                        "status": status})
                ev(month, status, iid, c, "", "", best, margin,
                   "recognised %s identity (overlap>=T and margin>M)" %
                   ("dormant" if was_dormant else "live"))
            else:
                best = ov[c][0][1] if ov[c] else 0.0
                second = ov[c][1][1] if len(ov.get(c, [])) > 1 else 0.0
                margin = float(best - second)
                if best >= T:
                    status = "ambiguous"
                    for ti in np.where(lab == c)[0].tolist():
                        assign_rows.append({"ti": int(ti), "month": month,
                                            "label": c, "identity_id": "",
                                            "status": status})
                    ev(month, "ambiguous", "", c, "", "", float(best),
                       margin, "overlap>=T but margin failed or conflict "
                       "lost; never counted as confirmed birth")
                elif best >= Tc:
                    iid = _new_iid(counter)
                    counter += 1
                    identities[iid] = {"misses": 0, "last": m,
                                       "mu": regs[c]["mu"],
                                       "var": regs[c]["var"]}
                    for ti in np.where(lab == c)[0].tolist():
                        assign_rows.append({"ti": int(ti), "month": month,
                                            "label": c, "identity_id": iid,
                                            "status": "birth_candidate"})
                    ev(month, "birth_candidate", iid, c, "", "", float(best),
                       margin, "new cluster with sub-threshold resemblance "
                       "(T_cand<=overlap<T); NOT a confirmed birth")
                else:
                    iid = _new_iid(counter)
                    counter += 1
                    identities[iid] = {"misses": 0, "last": m,
                                       "mu": regs[c]["mu"],
                                       "var": regs[c]["var"]}
                    for ti in np.where(lab == c)[0].tolist():
                        assign_rows.append({"ti": int(ti), "month": month,
                                            "label": c, "identity_id": iid,
                                            "status": "birth"})
                    ev(month, "birth", iid, c, "", "", float(best), margin,
                       "clean new cluster (overlap<T_cand); confirmed birth")
            rr = {"month": month, "cluster": c,
                  "identity_id": winner.get(c, "") if c in winner else
                  (assign_rows[-1]["identity_id"] if assign_rows else ""),
                  "status": status, "size": regs[c]["size"],
                  "radius": regs[c]["rms"], "var": regs[c]["var"]}
            for f in range(F):
                rr[f"centre_{f}"] = float(regs[c]["mu"][f])
            region_rows.append(rr)

        for iid, inf in list(identities.items()):
            if iid in matched or inf["last"] == m:
                continue
            inf["misses"] += 1
            if inf["misses"] <= DORMANT_MAX_MISSES:
                ev(month, "dormant", iid, None, "", "", None, None,
                   "unseen %d month(s); re-emergence possible within %d" %
                   (inf["misses"], DORMANT_MAX_MISSES))
            else:
                ev(month, "disappearance", iid, None, "", "", None, None,
                   "retired after %d consecutive missed months" %
                   (DORMANT_MAX_MISSES + 1,))
                inf["retired"] = True
        identities = {i: v for i, v in identities.items()
                      if not v.get("retired")}
    return assign_rows, region_rows, events


def detect_split_merge(months: list[str], labels_per_month: list[np.ndarray],
                       Z: np.ndarray, assign_rows: list[dict],
                       region_rows: list[dict]):
    """M3 containment split/merge candidates + sensitivity grid.

    Returns (op_events, sens_counts). op_events use kappa=2.5/cont=0.6.
    """
    from collections import defaultdict

    lab_of = {(r["month"], r["ti"]): r["label"] for r in assign_rows}
    iid_of = {(r["month"], r["ti"]): r["identity_id"] for r in assign_rows}
    reg = {(r["month"], r["cluster"]): r for r in region_rows}
    cont_of_cluster = {(r["month"], r["cluster"]): r["status"]
                       for r in region_rows}

    def members(month, cluster):
        return sorted(ti for (mo, ti), lb in lab_of.items()
                      if mo == month and lb == cluster)

    def imembers(month, iid):
        return sorted(ti for (mo, ti), ii in iid_of.items()
                      if mo == month and ii == iid)

    iid_cluster = {(r["month"], r["identity_id"]): r["cluster"]
                   for r in region_rows if r["identity_id"]}

    def centre_var(month, cluster):
        r = reg[(month, cluster)]
        F = sum(1 for k in r if k.startswith("centre_"))
        return (np.array([r[f"centre_{f}"] for f in range(F)]),
                float(r["var"]), float(r["radius"]))

    op_events: list[dict] = []
    sens_counts: dict[str, dict[str, int]] = {}
    for kappa in KAPPA_GRID:
        for cont in CONT_GRID:
            n_split = n_merge = 0
            cur: list[dict] = []
            for m in range(1, len(months)):
                prev, cur_m = months[m - 1], months[m]
                X = np.asarray(Z[:, m, :], dtype=float)
                Xp = np.asarray(Z[:, m - 1, :], dtype=float)
                prev_labels = np.asarray(labels_per_month[m - 1])
                cur_labels = np.asarray(labels_per_month[m])
                prev_clusters = sorted(int(c)
                                       for c in set(prev_labels.tolist()))
                cur_clusters = sorted(int(c)
                                      for c in set(cur_labels.tolist()))
                prev_iids = sorted({iid_of[(prev, ti)]
                                    for ti in range(len(prev_labels))
                                    if iid_of[(prev, ti)]})
                for A in prev_iids:
                    pa = imembers(prev, A)
                    if not pa:
                        continue
                    pa_set = set(pa)
                    kids = []
                    for c in cur_clusters:
                        mc = members(cur_m, c)
                        if not mc:
                            continue
                        mc_arr = np.asarray(mc, dtype=int)
                        pc = iid_cluster.get((prev, A))
                        if pc is None:
                            pc = lab_of.get((prev, pa[0]))
                        mu_p, _, r_p = centre_var(prev, int(pc))
                        dp = np.linalg.norm(
                            X[mc_arr] - mu_p[None, :], axis=1)
                        geo = float(np.mean(dp <= kappa * r_p)) if len(
                            mc_arr) else 0.0
                        comp = len(pa_set.intersection(mc)) / len(mc)
                        if geo >= cont and comp >= cont:
                            kids.append((c, min(geo, comp)))
                    if len(kids) >= 2:
                        continued = any(
                            cont_of_cluster.get((cur_m, c)) in
                            ("continuing", "reemergence")
                            and iid_of.get((cur_m, members(
                                cur_m, c)[0])) == A
                            for c, _ in kids if members(cur_m, c))
                        if not continued:
                            n_split += 1
                            if kappa == OP_KAPPA and cont == OP_CONT:
                                cur.append({
                                    "month": cur_m, "kind": "split_candidate",
                                    "identity_id": A, "cluster": None,
                                    "month_from": prev,
                                    "extra_ids": ";".join(
                                        str(c) for c, _ in kids),
                                    "overlap": None, "margin": None,
                                    "kappa": kappa,
                                    "containment": max(v for _, v in kids),
                                    "note": "algorithmic candidate: parent "
                                    "has no single recognised continuation; "
                                    "child CURRENT points inside PREVIOUS "
                                    "parent sphere + parent-origin composition "
                                    "%s; not a verified economic change" % (
                                        {str(c): round(v, 3)
                                         for c, v in kids},),
                                })
                for c in cur_clusters:
                    mc = members(cur_m, c)
                    if not mc:
                        continue
                    mc_set = set(mc)
                    mu, _, r = centre_var(cur_m, c)
                    pars = []
                    for A in prev_iids:
                        pa = imembers(prev, A)
                        if not pa:
                            continue
                        pa_arr = np.asarray(pa, dtype=int)
                        dp = np.linalg.norm(
                            Xp[pa_arr] - mu[None, :], axis=1)
                        geo = float(np.mean(dp <= kappa * r)) if len(
                            pa_arr) else 0.0
                        comp = len(set(pa).intersection(mc_set)) / len(pa)
                        if geo >= cont and comp >= cont:
                            pars.append((A, min(geo, comp)))
                    if len(pars) >= 2:
                        n_merge += 1
                        if kappa == OP_KAPPA and cont == OP_CONT:
                            coinc = cont_of_cluster.get((cur_m, c)) in (
                                "continuing", "reemergence")
                            cur.append({
                                "month": cur_m, "kind": "merge_candidate",
                                "identity_id": "", "cluster": c,
                                "month_from": prev,
                                "extra_ids": ";".join(a for a, _ in pars),
                                "overlap": None, "margin": None,
                                "kappa": kappa,
                                "containment": max(v for _, v in pars),
                                "note": "algorithmic candidate: >=2 parents "
                                "with member containment %s%s; proximity "
                                "alone never suffices; not a verified "
                                "economic change" % (
                                    {a: round(v, 3) for a, v in pars},
                                    "; coincides with a recognised "
                                    "continuation" if coinc else ""),
                            })
            sens_counts[f"kappa={kappa}_cont={cont}"] = {
                "n_split_candidates": n_split, "n_merge_candidates": n_merge}
            if kappa == OP_KAPPA and cont == OP_CONT:
                op_events = cur
    return op_events, sens_counts


def run_pipeline(panel: pd.DataFrame, outdir: Path, seed: int) -> dict:
    tids, months, S, share_audit = build_monthly_shares(panel)
    n_tids, n_months = S.shape[0], S.shape[1]
    Z, std_audit = standardize_frozen(S, months)
    std_audit["retrospective_note"] = (
        "fit pools ALL 2023 months, so 2023 z-scores/labels are retrospective "
        "(later-2023 months inform early-2023 transforms); the "
        "causality-relevant check concerns 2024 months, strictly after the "
        "frozen fit.")

    labels_per_month: list[np.ndarray] = []
    centres_per_month: list[np.ndarray] = []
    k_traj: list[int] = []
    k_grid_rows: list[dict] = []
    k_notes: dict[str, str] = {}
    for m, month in enumerate(months):
        best_k, rows, note = select_k_for_month(Z[:, m, :], m, seed)
        lab, centres = fit_month(Z[:, m, :], m, seed, best_k)
        labels_per_month.append(lab)
        centres_per_month.append(centres)
        k_traj.append(int(best_k))
        if note:
            k_notes[month] = note
        for k, sil, n in rows:
            k_grid_rows.append({"month": month, "k": int(k),
                                "silhouette": sil, "n_sample": int(n),
                                "chosen": bool(k == best_k)})

    cal_months = [i for i, mo in enumerate(months)
                  if mo.startswith(FIT_YEAR)]
    if not cal_months:
        raise ValueError("identities: no 2023 months for frozen calibration")
    cal = calibrate_thresholds(Z, labels_per_month, cal_months, seed)
    cal["retrospective_note"] = (
        "calibration pools ALL 2023 months; 2023 recognition is retrospective, "
        "2024 recognition is strictly after the frozen calibration.")
    T, M, Tc = (cal["overlap_threshold"], cal["candidate_margin"],
                cal["resemblance_floor"])

    assign_rows, region_rows, track_events = track_identities(
        months, labels_per_month, centres_per_month, Z, tids, T, M, Tc)
    m3_events, sens_counts = detect_split_merge(
        months, labels_per_month, Z, assign_rows, region_rows)
    events = track_events + m3_events

    outdir.mkdir(parents=True, exist_ok=True)
    k_of = {mo: k for mo, k in zip(months, k_traj)}
    arecs = [{"territory_id": int(tids[r["ti"]]), "month": r["month"],
              "k": int(k_of[r["month"]]), "label": int(r["label"]),
              "identity_id": r["identity_id"], "status": r["status"]}
             for r in assign_rows]
    assignments = pd.DataFrame(arecs, columns=ASSIGN_COLUMNS)
    assignments.to_parquet(outdir / "assignments.parquet", index=False)

    F = int(Z.shape[2])
    rcols = (["month", "cluster", "identity_id", "status", "size", "radius",
              "var"] + [f"centre_{f}" for f in range(F)])
    regions = pd.DataFrame(region_rows)
    for c in rcols:
        if c not in regions.columns:
            regions[c] = np.nan
    regions = regions[rcols]
    regions.to_csv(outdir / "regions.csv", index=False)

    evdf = pd.DataFrame(events)
    for c in EVENT_COLUMNS:
        if c not in evdf.columns:
            evdf[c] = None
    evdf = evdf[EVENT_COLUMNS]
    evdf.to_csv(outdir / "events.csv", index=False)

    with open(outdir / "calibration.json", "w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    kgrid = pd.DataFrame(k_grid_rows, columns=K_GRID_COLUMNS)
    kgrid.to_csv(outdir / "k_grid.csv", index=False)

    def count(kind):
        return int(sum(1 for e in events if e["kind"] == kind))

    metrics = {
        "gate": "A6",
        "component": "identities",
        "status": "PARTIAL_NOT_GATE_PASS",
        "gate_pass": False,
        "gate_pass_reason": "identity/split/merge outputs are algorithmic "
        "candidates from geometric overlap/containment, never verified "
        "economic changes; no case closure is claimed",
        "completed_components": ["variable_K_typology", "M2_tracking",
                                 "M3_candidates", "frozen_2023_calibration"],
        "pending_components": ["economic_verification_of_events",
                               "case_closure"],
        "completes_case06": False,
        "seed": seed,
        "k_policy": K_POLICY,
        "no_fixed_k": True,
        "k_trajectory": {mo: k for mo, k in zip(months, k_traj)},
        "k_selection_notes": k_notes,
        "frozen_panel": {
            "n_tids": int(n_tids), "n_months": int(n_months),
            "n_cats": len(SHARE_CATS) + 1, "months": months,
            "expected_shape": [1896, 24, 6],
            "frozen_shape_ok": bool(n_tids == 1896 and n_months == 24),
        },
        "mask": {"n": int(n_tids),
                 "n_excluded": share_audit["n_excluded"],
                 "excluded_tids": share_audit["excluded_tids"]},
        "share_audit": share_audit,
        "standardization": std_audit,
        "calibration_summary": {
            "overlap_threshold": T, "candidate_margin": M,
            "resemblance_floor": Tc, "ambiguity": cal["ambiguity"],
            "n_self_scores": cal["n_self_scores"],
            "n_other_scores": cal["n_other_scores"],
        },
        "identity_counts": {
            "initial": count("initial"), "continuing": count("continuing"),
            "reemergence": count("reemergence"), "birth": count("birth"),
            "birth_candidate": count("birth_candidate"),
            "ambiguous": count("ambiguous"), "dormant": count("dormant"),
            "disappearance": count("disappearance"),
            "conflict": count("conflict"),
            "confirmed_births": count("birth"),
            "ambiguous_never_confirmed": True,
        },
        "m3": {
            "operating_point": {"kappa": OP_KAPPA, "containment": OP_CONT},
            "n_split_candidates": count("split_candidate"),
            "n_merge_candidates": count("merge_candidate"),
            "sensitivity": sens_counts,
            "provenance": "containment of member points inside "
            "sphere(mu_c, kappa*r_c); proximity alone never suffices; "
            "split additionally requires no single recognised continuation; "
            "all events are algorithmic candidates, not verified changes.",
        },
        "synthetic_control": {
            "status": "separate_toy_only_run_under_self_check",
            "observed_labels_used": False,
            "provenance": "no synthetic truth in real-run outputs",
        },
    }
    with open(outdir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    manifest = {
        "gate": "A6",
        "component": "identities",
        "status": "PARTIAL_NOT_GATE_PASS",
        "gate_pass": False,
        "completes_case06": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {
            "a6_identities.py": sha256_file(Path(__file__)),
            "a6_temporal.py": sha256_file(SRC_DIR / "a6_temporal.py"),
        },
        "seed": seed,
        "params": {"k_grid": [K_MIN, K_MAX], "n_init": N_INIT,
                   "silhouette_cap": SIL_CAP, "var_floor": VAR_FLOOR,
                   "dormant_max_misses": DORMANT_MAX_MISSES,
                   "kappa_grid": list(KAPPA_GRID),
                   "containment_grid": list(CONT_GRID),
                   "bootstrap_B": BOOT_B,
                   "k_policy": K_POLICY},
        "inputs": {"panel": {"sha256": "see-operator-run",
                             "rows": "see-operator-run"}},
        "formulas": {
            "share": share_audit["formula"],
            "standardization": std_audit["formula"],
            "region": "isotropic Gaussian: centre=fitted k-means centre, "
                      "rms=sqrt(mean||x-mu||^2), var=rms^2/F floored",
            "overlap": "Bhattacharyya coefficient, isotropic closed form",
            "recognition": "overlap>=T and (best-second)>M, one-to-one "
                           "greedy by overlap; losers ambiguous",
            "split_merge": "member-point containment in sphere(mu,kappa*r); "
                           "split needs >=2 children + no recognised "
                           "continuation; merge needs >=2 parents",
        },
        "versions": {
            "python": sys.version.split()[0],
            "numpy": pkg_version("numpy"), "pandas": pkg_version("pandas"),
            "scipy": pkg_version("scipy"),
            "scikit-learn": pkg_version("scikit-learn"),
        },
        "mask": {"n": int(n_tids)},
        "limitations": LIMITATIONS,
    }
    with open(outdir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return {"metrics": metrics, "manifest": manifest, "outdir": str(outdir),
            "assignments": assignments, "regions": regions,
            "events": evdf, "calibration": cal}


def _toy_panel(n_tid=36, months=None, seed=DEFAULT_SEED, noise=0.01,
               total=1000.0):
    """Toy panel builder for self-check ONLY (synthetic assumptions).

    Assumptions (documented, never observed truth): two well-separated
    5-share profiles (g0/g1) with iid Gaussian noise; every tid has a full
    grid and positive totals. Used solely to exercise the economic pipeline
    (shares -> frozen scaler -> K-select -> calibrate -> track); no truth
    labels exist or are written anywhere.
    """
    rng = np.random.default_rng(seed)
    if months is None:
        months = [f"2023-{m:02d}" for m in range(1, 13)]
    g0 = np.array([0.10, 0.15, 0.10, 0.20, 0.05])
    g1 = np.array([0.16, 0.11, 0.15, 0.17, 0.09])
    rows = []
    for t in range(1, n_tid + 1):
        prof = g0 if t <= n_tid // 2 else g1
        for m in months:
            shares = np.clip(prof + rng.normal(0, noise, size=5), 0.005, None)
            rows.append((t, m, TOTAL_CAT, total))
            for c, v in zip(SHARE_CATS, shares):
                rows.append((t, m, c, float(v * total)))
    return pd.DataFrame(rows,
                        columns=["territory_id", "date", "category", "value"])


def _synth_blobs(rng, centre, n, std, F=2):
    return rng.normal(0, std, size=(n, F)) + np.asarray(centre, dtype=float)


def self_check() -> int:
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        print(f"self-check {name}: {'PASS' if cond else 'FAIL'} {detail}")
        if not cond:
            ok = False

    # A. Independent tracker test on known region memberships.
    # SYNTHETIC ASSUMPTION (explicit, toy-only): F=2 Gaussian blobs, std 0.3,
    # centres >=5 apart; stable N=170 members (A50/B40/C40/D40) with STABLE
    # row indices across all 8 months; an absent group's rows stay in the A
    # region, moving to its true blob on appearance; labels rebuilt per month
    # from actual positions (A-region rows share label 0). Identity A
    # persists 8 months, B last seen m2 (disappearance m6 after 3 dormant
    # months + retirement), C born m4, D absent m2-4 (reemergence m5).
    # Labels are GIVEN (cluster-count truth never feeds any K-selection).
    # Tracking uses documented fixed T=0.55/M=0.3/Tc=0.25 for these known
    # separated blobs; bootstrap calibration on months [0,1] (the documented
    # 2023-only analogue) is recorded SEPARATELY and never claimed validated.
    rng = np.random.default_rng(DEFAULT_SEED)
    _CFG = {"A": (0.0, 0.0), "B": (5.0, 0.0), "C": (0.0, 5.0),
           "D": (5.0, 5.0)}
    presence = {"A": [1] * 8, "B": [1, 1, 1, 0, 0, 0, 0, 0],
                "C": [0, 0, 0, 0, 1, 1, 1, 1],
                "D": [1, 1, 0, 0, 0, 1, 1, 1]}
    sizes = {"A": 50, "B": 40, "C": 40, "D": 40}
    M_A = 8
    N_A = 170
    _SL = {"A": (0, 50), "B": (50, 90), "C": (90, 130), "D": (130, 170)}
    Z_A = np.zeros((N_A, M_A, 2))
    labs_A: list[np.ndarray] = []
    for m in range(M_A):
        drift = np.array([0.05 * m, 0.0])
        blocks = {}
        for iid in ["A", "B", "C", "D"]:
            if presence[iid][m]:
                cen = np.asarray(_CFG[iid], dtype=float) + (
                    drift if iid == "A" else 0.0)
            else:
                cen = np.asarray(_CFG["A"], dtype=float) + drift
            blocks[iid] = _synth_blobs(rng, cen, sizes[iid], 0.3)
        for iid in ["A", "B", "C", "D"]:
            a, b = _SL[iid]
            Z_A[a:b, m, :] = blocks[iid]
        lab = np.empty(N_A, dtype=int)
        lab[_SL["A"][0]:_SL["A"][1]] = 0
        off = 1
        for iid in ["B", "C", "D"]:
            a, b = _SL[iid]
            if presence[iid][m]:
                lab[a:b] = off
                off += 1
            else:
                lab[a:b] = 0
        labs_A.append(lab)
    ctrs_A = []
    for m in range(M_A):
        X = Z_A[:, m, :]
        k = len(set(labs_A[m].tolist()))
        ctrs_A.append(np.stack([X[labs_A[m] == c].mean(axis=0)
                                for c in range(k)]))
    months_A = [f"2023-{m + 1:02d}" for m in range(M_A)]
    cal_A = calibrate_thresholds(Z_A, labs_A, [0, 1], DEFAULT_SEED)
    print("self-check tracker_calib_record: T=%.4f M=%.4f Tc=%.4f "
          "ambiguity=%s n_self=%d n_other=%d (recorded only, calibration "
          "NOT claimed validated)" % (
              cal_A["overlap_threshold"], cal_A["candidate_margin"],
              cal_A["resemblance_floor"], cal_A["ambiguity"],
              cal_A["n_self_scores"], cal_A["n_other_scores"]))
    ar, rr, evA = track_identities(
        months_A, labs_A, ctrs_A, Z_A, np.arange(N_A), 0.55, 0.3, 0.25)

    def evcount(ev, kind, **kw):
        return sum(1 for e in ev if e["kind"] == kind and all(
            e.get(k) == v for k, v in kw.items()))

    n_cont_A = evcount(evA, "continuing", identity_id="ID0001") \
        if any(e["kind"] == "continuing" for e in evA) else 0
    a_ids = {e["identity_id"] for e in evA if e["kind"] == "initial"}
    a_iid = sorted(a_ids)[0] if a_ids else "?"
    n_cont_A = evcount(evA, "continuing", identity_id=a_iid)
    n_birth_C = evcount(evA, "birth")
    n_disapp = evcount(evA, "disappearance")
    n_dorm = evcount(evA, "dormant")
    n_reem = evcount(evA, "reemergence")
    n_amb = evcount(evA, "ambiguous")
    amb_as_birth = sum(1 for e in evA if e["kind"] == "birth"
                       and e.get("note", "").startswith("overlap"))
    n_conflict = evcount(evA, "conflict")
    fp_A = sum(1 for e in evA if e["kind"] not in (
        "initial", "continuing", "dormant", "disappearance", "birth",
        "reemergence", "ambiguous", "birth_candidate", "conflict"))
    check("tracker_A_continuing", n_cont_A == 7, f"continuing(A)={n_cont_A}")
    check("tracker_birth_C", n_birth_C == 1, f"birth={n_birth_C}")
    check("tracker_disappearance_B", n_disapp == 1,
          f"disappearance={n_disapp}")
    check("tracker_dormant_D", n_dorm == 6,
          f"dormant={n_dorm} (B:3 + D:3 expected)")
    check("tracker_reemergence_D", n_reem == 1, f"reemergence={n_reem}")
    check("tracker_no_ambiguity", n_amb == 0 and n_conflict == 0,
          f"ambiguous={n_amb} conflict={n_conflict}")
    check("tracker_no_amb_birth", amb_as_birth == 0,
          f"ambiguous-as-birth={amb_as_birth}")
    check("tracker_no_fp", fp_A == 0, f"unexpected_kinds={fp_A}")

    # B. Part-whole split/merge vs proximity negative control.
    # Identity control uses documented fixed T=0.55/M=0.3/Tc=0.25 for known
    # separated blobs; bootstrap calibration is recorded separately above.
    # SYNTHETIC ASSUMPTION (explicit, toy-only): broad parent = two
    # separated lobes (std 0.3, centres +-2); split children reuse the SAME
    # member points; regions derived from actual points (no handset blobs).
    rng = np.random.default_rng(DEFAULT_SEED + 1)
    L1 = _synth_blobs(rng, (-2, 0), 30, 0.3)
    L2 = _synth_blobs(rng, (2, 0), 30, 0.3)
    P0 = np.vstack([L1, L2])
    mu_P0 = P0.mean(axis=0)
    r_P0, v_P0 = region_of_members(P0, mu_P0)
    mu_C1 = L1.mean(axis=0)
    r_C1, v_C1 = region_of_members(L1, mu_C1)
    mu_C2 = L2.mean(axis=0)
    r_C2, v_C2 = region_of_members(L2, mu_C2)
    Z_sp = np.zeros((60, 2, 2))
    Z_sp[:, 0, :] = P0
    Z_sp[:, 1, :] = P0
    labs_sp = [np.zeros(60, dtype=int),
               np.concatenate([np.zeros(30, dtype=int),
                               np.ones(30, dtype=int)])]
    ar_sp = [{"ti": t, "month": "m0", "label": 0, "identity_id": "ID0001",
              "status": "initial"} for t in range(60)]
    ar_sp += [{"ti": t, "month": "m1", "label": int(t >= 30),
               "identity_id": "", "status": "birth"} for t in range(60)]
    rr_sp = [
        {"month": "m0", "cluster": 0, "identity_id": "ID0001",
         "status": "initial", "size": 60,
         "radius": float(r_P0), "var": float(v_P0),
         "centre_0": float(mu_P0[0]), "centre_1": float(mu_P0[1])},
        {"month": "m1", "cluster": 0, "identity_id": "", "status": "birth",
         "size": 30, "radius": float(r_C1), "var": float(v_C1),
         "centre_0": float(mu_C1[0]), "centre_1": float(mu_C1[1])},
        {"month": "m1", "cluster": 1, "identity_id": "", "status": "birth",
         "size": 30, "radius": float(r_C2), "var": float(v_C2),
         "centre_0": float(mu_C2[0]), "centre_1": float(mu_C2[1])},
    ]
    op_sp, sens_sp = detect_split_merge(
        ["m0", "m1"], labs_sp, Z_sp, ar_sp, rr_sp)
    n_split_sp = sum(1 for e in op_sp if e["kind"] == "split_candidate")
    check("split_detected", n_split_sp == 1, f"split={n_split_sp}")
    print("self-check split_counts: detected=%d (expected 1)" % n_split_sp)

    Z_mg = np.zeros((60, 2, 2))
    Z_mg[:, 0, :] = P0
    Z_mg[:, 1, :] = P0
    labs_mg = [np.concatenate([np.zeros(30, dtype=int),
                               np.ones(30, dtype=int)]),
               np.zeros(60, dtype=int)]
    ar_mg = [{"ti": t, "month": "m0", "label": int(t >= 30),
              "identity_id": "ID0001" if t < 30 else "ID0002",
              "status": "initial"} for t in range(60)]
    ar_mg += [{"ti": t, "month": "m1", "label": 0, "identity_id": "",
               "status": "birth"} for t in range(60)]
    rr_mg = [
        {"month": "m0", "cluster": 0, "identity_id": "ID0001",
         "status": "initial", "size": 30, "radius": float(r_C1),
         "var": float(v_C1),
         "centre_0": float(mu_C1[0]), "centre_1": float(mu_C1[1])},
        {"month": "m0", "cluster": 1, "identity_id": "ID0002",
         "status": "initial", "size": 30, "radius": float(r_C2),
         "var": float(v_C2),
         "centre_0": float(mu_C2[0]), "centre_1": float(mu_C2[1])},
        {"month": "m1", "cluster": 0, "identity_id": "", "status": "birth",
         "size": 60, "radius": float(r_P0), "var": float(v_P0),
         "centre_0": float(mu_P0[0]), "centre_1": float(mu_P0[1])},
    ]
    op_mg, _ = detect_split_merge(["m0", "m1"], labs_mg, Z_mg, ar_mg, rr_mg)
    n_merge_mg = sum(1 for e in op_mg if e["kind"] == "merge_candidate")
    check("merge_detected", n_merge_mg == 1, f"merge={n_merge_mg}")
    print("self-check merge_counts: detected=%d (expected 1)" % n_merge_mg)
    # Wrong-geometry guard: same composition mapping, but child CURRENT
    # points far outside the previous parent sphere -> must NOT split
    # (catches the old proximity-only bug).
    Wf = _synth_blobs(rng, (10, 0), 30, 0.3)
    Wg = _synth_blobs(rng, (-10, 0), 30, 0.3)
    Z_wg = np.zeros((60, 2, 2))
    Z_wg[:, 0, :] = P0
    Z_wg[:, 1, :] = np.vstack([Wf, Wg])
    op_wg, _ = detect_split_merge(
        ["m0", "m1"], labs_sp, Z_wg, ar_sp, rr_sp)
    n_wg = sum(1 for e in op_wg if e["kind"] == "split_candidate")
    check("wrong_geometry_no_split", n_wg == 0, f"split={n_wg}")

    # Proximity negative control: two adjacent stable blobs (centres 1.2
    # apart, std 0.3); containment must stay below threshold -> no events.
    Q0a = _synth_blobs(rng, (0, 0), 40, 0.3)
    Q0b = _synth_blobs(rng, (1.2, 0), 40, 0.3)
    Q1a = _synth_blobs(rng, (0, 0), 40, 0.3)
    Q1b = _synth_blobs(rng, (1.2, 0), 40, 0.3)
    Z_px = np.zeros((80, 2, 2))
    Z_px[:, 0, :] = np.vstack([Q0a, Q0b])
    Z_px[:, 1, :] = np.vstack([Q1a, Q1b])
    labs_px = [np.concatenate([np.zeros(40, dtype=int),
                               np.ones(40, dtype=int)])] * 2
    ar_px, rr_px = [], []
    for mi, mo in enumerate(["m0", "m1"]):
        for c, iid, n0 in ((0, "ID0001", 0), (1, "ID0002", 40)):
            blk = (Q0a if (mi, c) == (0, 0) else Q0b if (mi, c) == (0, 1)
                   else Q1a if (mi, c) == (1, 0) else Q1b)
            mu = blk.mean(axis=0)
            rms = float(np.sqrt(((blk - mu) ** 2).sum(axis=1).mean()))
            for t in range(n0, n0 + 40):
                ar_px.append({"ti": t, "month": mo, "label": c,
                              "identity_id": iid,
                              "status": "initial" if mi == 0
                              else "continuing"})
            rr_px.append({"month": mo, "cluster": c, "identity_id": iid,
                          "status": "initial" if mi == 0 else "continuing",
                          "size": 40, "radius": rms,
                          "var": max(rms * rms / 2, VAR_FLOOR),
                          "centre_0": float(mu[0]),
                          "centre_1": float(mu[1])})
    op_px, _ = detect_split_merge(["m0", "m1"], labs_px, Z_px, ar_px, rr_px)
    check("proximity_clean", len(op_px) == 0,
          f"proximity_events={len(op_px)} (false positives)")

    # C. Ambiguous twins: two near-identical children of one prior identity.
    # Both overlap the parent above T with ~zero margin -> ambiguous, and no
    # confirmed birth may come out of ambiguity.
    rng = np.random.default_rng(DEFAULT_SEED + 2)
    W0 = _synth_blobs(rng, (0, 0), 50, 0.5)
    W1 = _synth_blobs(rng, (0.1, 0), 50, 0.5)
    W2 = _synth_blobs(rng, (-0.1, 0), 50, 0.5)
    Z_tw = np.zeros((100, 2, 2))
    Z_tw[:50, 0, :] = W0[:50]
    Z_tw[50:, 0, :] = W0[50:] if len(W0) > 50 else W0[:50]
    Z_tw[:, 1, :] = np.vstack([W1, W2])
    labs_tw = [np.zeros(100, dtype=int),
               np.concatenate([np.zeros(50, dtype=int),
                               np.ones(50, dtype=int)])]
    ctrs_tw = [Z_tw[:, 0, :].mean(axis=0, keepdims=True),
               np.stack([W1.mean(axis=0), W2.mean(axis=0)])]
    months_tw = ["2023-01", "2023-02"]
    ar_tw, rr_tw, ev_tw = track_identities(
        months_tw, labs_tw, ctrs_tw, Z_tw, np.arange(100),
        0.5, 0.1, 0.25)
    n_amb_tw = sum(1 for e in ev_tw if e["kind"] == "ambiguous")
    n_birth_tw = sum(1 for e in ev_tw if e["kind"] == "birth")
    check("twins_ambiguous", n_amb_tw >= 1,
          f"ambiguous={n_amb_tw} birth={n_birth_tw}")
    check("twins_no_birth", n_birth_tw == 0, f"birth={n_birth_tw}")

    # D. Economic pipeline: determinism, K-grid honesty, prefix invariance.
    panel = _toy_panel()
    with tempfile.TemporaryDirectory() as t1, \
            tempfile.TemporaryDirectory() as t2:
        r1 = run_pipeline(panel, Path(t1), seed=DEFAULT_SEED)
        r2 = run_pipeline(panel, Path(t2), seed=DEFAULT_SEED)
        a1 = pd.read_parquet(Path(t1) / "assignments.parquet")
        a2 = pd.read_parquet(Path(t2) / "assignments.parquet")
        check("pipe_determinism", a1.equals(a2))
        m1 = json.dumps(r1["metrics"], sort_keys=True)
        check("pipe_metrics_repro",
              m1 == json.dumps(r2["metrics"], sort_keys=True))
        kg = pd.read_csv(Path(t1) / "k_grid.csv")
        honest = True
        for mo, g in kg.groupby("month"):
            finite = g[np.isfinite(g["silhouette"].to_numpy())]
            if len(finite):
                s_max = finite["silhouette"].max()
                want = finite[finite["silhouette"] == s_max]["k"].min()
                got = g[g["chosen"]]["k"].to_numpy()
                if not (len(got) == 1 and got[0] == want):
                    honest = False
        check("kgrid_honest_argmax", honest,
              f"months={kg['month'].nunique()}")
        check("pipe_status_partial",
              r1["metrics"].get("status") == "PARTIAL_NOT_GATE_PASS"
              and r1["metrics"].get("gate_pass") is False)
        check("pipe_no_case06",
              r1["metrics"].get("completes_case06") is False)
        check("pipe_events_candidates",
              all("candidate" in (e.get("note") or "") or e["kind"] in (
                  "initial", "continuing", "dormant", "disappearance",
                  "reemergence", "ambiguous", "conflict", "birth",
                  "birth_candidate") for e in r1["events"].to_dict("records"))
              if len(r1["events"]) else True)

    full_months = [f"2023-{m:02d}" for m in range(1, 13)] + [
        f"2024-{m:02d}" for m in range(1, 7)]
    prefix_months = full_months[:15]
    last_prefix = prefix_months[-1]
    panel_full = _toy_panel(n_tid=24, months=full_months, seed=7)
    panel_prefix = panel_full[panel_full["date"].isin(prefix_months)].copy()
    panel_edited = panel_full.copy()
    fut = panel_edited["date"] > last_prefix
    panel_edited.loc[fut, "value"] = panel_edited.loc[fut, "value"] * 1.5 \
        + 10.0
    with tempfile.TemporaryDirectory() as t1, \
            tempfile.TemporaryDirectory() as t2, \
            tempfile.TemporaryDirectory() as t3:
        rf = run_pipeline(panel_full, Path(t1), seed=DEFAULT_SEED)
        rp = run_pipeline(panel_prefix, Path(t2), seed=DEFAULT_SEED)
        re_ = run_pipeline(panel_edited, Path(t3), seed=DEFAULT_SEED)
        af = pd.read_parquet(Path(t1) / "assignments.parquet")
        ap = pd.read_parquet(Path(t2) / "assignments.parquet")
        ae = pd.read_parquet(Path(t3) / "assignments.parquet")
        past_f = af[af["month"].isin(prefix_months)].sort_values(
            ["territory_id", "month"]).reset_index(drop=True)
        past_p = ap.sort_values(
            ["territory_id", "month"]).reset_index(drop=True)
        check("prefix_past_unchanged", past_f.equals(past_p),
              f"rows={len(past_p)}")
        past_e = ae[ae["month"].isin(prefix_months)].sort_values(
            ["territory_id", "month"]).reset_index(drop=True)
        check("prefix_edited_future_past_unchanged", past_f.equals(past_e),
              f"rows={len(past_e)}")
        mu_f = rf["metrics"]["standardization"]["mu"]
        mu_p = rp["metrics"]["standardization"]["mu"]
        mu_e = re_["metrics"]["standardization"]["mu"]
        check("prefix_same_2023_fit",
              json.dumps(mu_f, sort_keys=True)
              == json.dumps(mu_p, sort_keys=True))
        check("prefix_edited_future_same_2023_fit",
              json.dumps(mu_f, sort_keys=True)
              == json.dumps(mu_e, sort_keys=True))
        kg_f = pd.read_csv(Path(t1) / "k_grid.csv")
        kg_e = pd.read_csv(Path(t3) / "k_grid.csv")
        past_kf = kg_f[kg_f["month"].isin(prefix_months)].reset_index(
            drop=True)
        past_ke = kg_e[kg_e["month"].isin(prefix_months)].reset_index(
            drop=True)
        check("prefix_kgrid_unchanged", past_kf.equals(past_ke))

    print("self-check: ALL PASS" if ok else
          "self-check: FAILURES (measured above; PARTIAL_NOT_GATE_PASS)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--panel", default=str(DEFAULT_PANEL))
    p.add_argument("--outdir", default=str(DEFAULT_OUTDIR))
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args(argv)

    if args.self_check:
        return self_check()

    outdir = Path(args.outdir)
    if outdir.exists() and any(outdir.iterdir()):
        p.error(f"refusing to overwrite nonempty existing archive: {outdir}")

    panel_path = Path(args.panel)
    panel = pd.read_parquet(panel_path)
    res = run_pipeline(panel, outdir, seed=args.seed)
    man_path = outdir / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["inputs"] = {
        "panel": {"path": str(panel_path),
                  "sha256": sha256_file(panel_path),
                  "rows": int(len(panel))},
    }
    man_path.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True,
                                   indent=2) + "\n", encoding="utf-8")
    m = res["metrics"]
    print(f"A6-identities done: mask_n={m['mask']['n']} "
          f"months={m['frozen_panel']['n_months']} "
          f"frozen_shape_ok={m['frozen_panel']['frozen_shape_ok']}")
    print(f"  k_trajectory={[m['k_trajectory'][mo] for mo in m['frozen_panel']['months']]}")
    c = m["calibration_summary"]
    print(f"  calibration2023: T={c['overlap_threshold']:.4f} "
          f"M={c['candidate_margin']:.4f} ambiguity={c['ambiguity']} "
          f"n_self={c['n_self_scores']} n_other={c['n_other_scores']}")
    ic = m["identity_counts"]
    print(f"  identities: continuing={ic['continuing']} birth={ic['birth']} "
          f"birth_candidate={ic['birth_candidate']} ambiguous={ic['ambiguous']} "
          f"reemergence={ic['reemergence']} dormant={ic['dormant']} "
          f"disappearance={ic['disappearance']}")
    print(f"  m3: split={m['m3']['n_split_candidates']} "
          f"merge={m['m3']['n_merge_candidates']}")
    print(f"outdir={outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
