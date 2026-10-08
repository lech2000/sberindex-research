"""M2/M3 geometry v3: full covariance ellipsoids >=10 members.

Separate implementation: legacy sphere runner and archives are never overwritten.
Read the preregistered geometry-v3.1 protocol before execution. All identities
and split/merge events remain algorithmic candidates, not economic truth.
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
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A6_geometry_v3_20261007"
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
    """RMS diagnostic plus SPD covariance; >=10 members use an ellipsoid."""
    pts = np.asarray(pts, dtype=float)
    centre = np.asarray(centre, dtype=float)
    if pts.ndim != 2 or centre.shape != (pts.shape[1],) or len(pts) == 0:
        raise ValueError("nonempty member matrix and matching centre required")
    if not np.isfinite(pts).all() or not np.isfinite(centre).all():
        raise ValueError("nonfinite geometry, no imputation permitted")
    F = pts.shape[1]
    rms = float(np.sqrt(np.mean(np.sum((pts-centre)**2, axis=1))))
    if len(pts) < 10:
        return rms, np.eye(F)*max(rms*rms/F, VAR_FLOOR)
    # Covariance is centred at the member mean; supplied centre is the fitted
    # cluster centre. Both are recorded and normally equal for k-means/replay.
    raw = np.atleast_2d(np.cov(pts, rowvar=False, ddof=1))
    vals, vecs = np.linalg.eigh((raw+raw.T)/2)
    floor = max(VAR_FLOOR, float(np.trace(raw))/F*1e-8)
    cov = (vecs*np.maximum(vals, floor)) @ vecs.T
    return rms, (cov+cov.T)/2


def covariance_audit(pts, cov):
    F = cov.shape[0]
    raw = np.atleast_2d(np.cov(pts, rowvar=False, ddof=1)) if len(pts)>=10 else np.eye(F)*float(np.trace(cov))/F
    vals = np.linalg.eigvalsh(raw)
    floor = max(VAR_FLOOR, float(np.trace(raw))/F*1e-8)
    return {"geometry": "ellipsoid" if len(pts)>=10 else "small_cluster_sphere",
            "cov_eigenvalues_floored": int(np.count_nonzero(vals<floor)) if len(pts)>=10 else 0,
            "cov_eigenvalue_floor": floor,
            "cov_min_eigenvalue_raw": float(vals.min()),
            "cov_condition_number": float(np.linalg.cond(cov))}


def bc_cov(mu1, cov1, mu2, cov2):
    """Gaussian Bhattacharyya coefficient with full SPD covariance."""
    mu1, mu2 = np.asarray(mu1,dtype=float), np.asarray(mu2,dtype=float)
    cov1, cov2 = np.asarray(cov1,dtype=float), np.asarray(cov2,dtype=float)
    if mu1.shape != mu2.shape or cov1.shape != (mu1.size,mu1.size) or cov2.shape != cov1.shape:
        raise ValueError("incompatible Gaussian dimensions")
    for cov in (cov1,cov2):
        if not np.isfinite(cov).all() or not np.allclose(cov,cov.T,rtol=0,atol=1e-12):
            raise ValueError("finite symmetric covariance required")
        np.linalg.cholesky(cov)  # reject non-SPD; never abs(det) repair
    if not np.isfinite(mu1).all() or not np.isfinite(mu2).all():
        raise ValueError("nonfinite centres")
    avg=(cov1+cov2)/2
    delta=mu1-mu2
    logbc=-.125*float(delta@np.linalg.solve(avg,delta))-.5*np.linalg.slogdet(avg)[1]+.25*(np.linalg.slogdet(cov1)[1]+np.linalg.slogdet(cov2)[1])
    return float(np.exp(min(0.,logbc)))


def mahalanobis_inside(points, centre, cov, kappa):
    """Strict promised distance criterion; no Euclidean RMS multiplier."""
    points=np.asarray(points,dtype=float); centre=np.asarray(centre,dtype=float); cov=np.asarray(cov,dtype=float)
    if not np.isfinite(points).all() or not np.isfinite(centre).all() or not np.isfinite(cov).all():
        raise ValueError("nonfinite geometry")
    np.linalg.cholesky(cov)
    delta=points-centre
    d2=np.einsum("ij,ij->i",delta,np.linalg.solve(cov,delta.T).T)
    return d2 < float(kappa)**2


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
    paired_margins: list[float] = []
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
                own = bc_cov(bmu, bvar, mu, var)
                self_scores.append(own)
                competitors = []
                for o, (omu, ovar) in full.items():
                    if o != c:
                        competitor = bc_cov(bmu, bvar, omu, ovar)
                        other_scores.append(competitor)
                        competitors.append(competitor)
                if competitors:
                    paired_margins.append(own-max(competitors))
    qs = _quantiles(np.array(self_scores))
    qo = _quantiles(np.array(other_scores))
    fallback = not (len(self_scores) and len(other_scores))
    if fallback:
        T, M, Tc = 0.5, 0.0, 0.25
    else:
        T = qo["q95"]
        M = max(0.0, float(np.quantile(paired_margins,.05)))
        Tc = qo["q50"]
    ambiguity = bool(
        len(self_scores) and len(other_scores) and qs["q05"] < qo["q95"])
    return {
        "geometry_version": "geometry-v3.1",
        "paired_margin_quantiles": _quantiles(np.array(paired_margins)),
        "n_paired_margins": len(paired_margins),
        "margin_method": "q05(own bootstrap overlap minus max other overlap), clipped at0; tracker best-minus-second differs",
        "method": "full covariance bootstrap self-vs-other, B=%d, months=2023 only, "
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
            regs[c] = {"mu": mu, "rms": rms, "var": var, "size": int(len(pts)), "audit": covariance_audit(pts,var)}
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
                      "radius": regs[c]["rms"], "var": float(np.trace(regs[c]["var"])/F)}
                for f in range(F):
                    rr[f"centre_{f}"] = float(regs[c]["mu"][f])
                rr.update(regs[c]["audit"])
                for i in range(F):
                    for j in range(F):
                        rr[f"cov_{i}_{j}"] = float(regs[c]["var"][i,j])
                region_rows.append(rr)
                ev(month, "initial", iid, c, "", "", None, None,
                   "month-0 cluster; never counted as birth")
            continue

        eligible = [iid for iid, inf in identities.items()
                    if inf["misses"] <= DORMANT_MAX_MISSES]
        ov: dict[int, list[tuple[str, float]]] = {}
        for c in clusters:
            lst = [(iid, bc_cov(regs[c]["mu"], regs[c]["var"],
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
                    status = "birth_candidate"
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
                    status = "birth"
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
                  "radius": regs[c]["rms"], "var": float(np.trace(regs[c]["var"])/F)}
            for f in range(F):
                rr[f"centre_{f}"] = float(regs[c]["mu"][f])
            rr.update(regs[c]["audit"])
            for i in range(F):
                for j in range(F):
                    rr[f"cov_{i}_{j}"] = float(regs[c]["var"][i,j])
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
                np.array([[r[f"cov_{i}_{j}"] for j in range(F)] for i in range(F)]), float(r["radius"]))

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
                        mu_p, cov_p, _ = centre_var(prev, int(pc))
                        geo = float(np.mean(mahalanobis_inside(X[mc_arr],mu_p,cov_p,kappa)))
                        comp = len(pa_set.intersection(mc)) / len(mc)
                        if geo > cont and comp > cont:
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
                                    "parent ellipsoid + parent-origin composition "
                                    "%s; not a verified economic change" % (
                                        {str(c): round(v, 3)
                                         for c, v in kids},),
                                })
                for c in cur_clusters:
                    mc = members(cur_m, c)
                    if not mc:
                        continue
                    mc_set = set(mc)
                    mu, cov, _ = centre_var(cur_m, c)
                    pars = []
                    for A in prev_iids:
                        pa = imembers(prev, A)
                        if not pa:
                            continue
                        pa_arr = np.asarray(pa, dtype=int)
                        geo = float(np.mean(mahalanobis_inside(Xp[pa_arr],mu,cov,kappa)))
                        comp = len(set(pa).intersection(mc_set)) / len(pa)
                        if geo > cont and comp > cont:
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


def run_pipeline(panel: pd.DataFrame, outdir: Path, seed: int, archived_assignments=None) -> dict:
    if outdir.exists():
        raise FileExistsError("new output directory required")
    tids, months, S, share_audit = build_monthly_shares(panel)
    n_tids, n_months = S.shape[0], S.shape[1]
    if archived_assignments is not None and (set(archived_assignments.month)!=set(months) or len(archived_assignments)!=n_tids*n_months):
        raise ValueError("archived assignments full key/coverage mismatch")
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
        if archived_assignments is None:
            best_k, rows, note = select_k_for_month(Z[:, m, :], m, seed)
            lab, centres = fit_month(Z[:, m, :], m, seed, best_k)
        else:
            slice_ = archived_assignments[archived_assignments.month==month]
            if slice_.territory_id.duplicated().any() or set(slice_.territory_id)!=set(tids):
                raise ValueError("archived assignments key mismatch")
            lab=slice_.set_index("territory_id").loc[tids,"label"].to_numpy(dtype=int)
            codes=sorted(set(lab))
            if codes != list(range(len(codes))): raise ValueError("noncontiguous labels")
            centres=np.stack([Z[lab==c,m,:].mean(axis=0) for c in codes])
            best_k=len(codes); rows=[]; note="conditional replay of archived labels, no new clustering fit"

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
              "var","geometry","cov_eigenvalues_floored","cov_eigenvalue_floor","cov_min_eigenvalue_raw","cov_condition_number"] + [f"centre_{f}" for f in range(F)] + [f"cov_{i}_{j}" for i in range(F) for j in range(F)])
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
        "component": "identities_geometry_v3",
        "geometry_version": "geometry-v3.1",
        "replay_mode": "archived_labels" if archived_assignments is not None else "fresh_monthly_fits",
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
        "k_policy": K_POLICY if archived_assignments is None else "archived labels; K trajectory inherited, no selection replay",
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
            "strict Mahalanobis<kappa and geometric/composition fraction>containment; "
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
        "component": "identities_geometry_v3",
        "geometry_version": "geometry-v3.1",
        "replay_mode": "archived_labels" if archived_assignments is not None else "fresh_monthly_fits",
        "status": "PARTIAL_NOT_GATE_PASS",
        "gate_pass": False,
        "completes_case06": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {
            "a6_geometry_v3.py": sha256_file(Path(__file__)),
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
            "region": "n>=10 full sample covariance ellipsoid with fixed spectral floor; n<10 explicit isotropic sphere; RMS diagnostic only",
            "overlap": "full covariance Gaussian Bhattacharyya coefficient, slogdet/solve",
            "recognition": "overlap>=T and (best-second)>M, one-to-one "
                           "greedy by overlap; losers ambiguous",
            "split_merge": "strict Mahalanobis<kappa, containment>cont and composition>cont; "
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



def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel",type=Path,required=True)
    p.add_argument("--outdir",type=Path,required=True)
    p.add_argument("--seed",type=int,default=DEFAULT_SEED)
    p.add_argument("--archived-assignments",type=Path)
    args=p.parse_args(argv)
    if args.outdir.exists(): p.error("new output directory required")
    panel=pd.read_parquet(args.panel)
    archived=pd.read_parquet(args.archived_assignments) if args.archived_assignments else None
    result=run_pipeline(panel,args.outdir,args.seed,archived)
    man=result["manifest"]
    man["inputs"]={"panel":{"path":str(args.panel),"sha256":sha256_file(args.panel),"rows":len(panel)}}
    if archived is not None:
        man["inputs"]["archived_assignments"]={"path":str(args.archived_assignments),"sha256":sha256_file(args.archived_assignments),"rows":len(archived)}
    protocol=ATLAS_DIR/"protocol/geometry-v3-20261007/protocol.json"
    man["protocol_sha256"]=sha256_file(protocol)
    (args.outdir/"manifest.json").write_text(json.dumps(man,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"outdir":str(args.outdir),"replay_mode":man["replay_mode"],"scientific_pass":False}))
    return 0

if __name__=="__main__": raise SystemExit(main())
