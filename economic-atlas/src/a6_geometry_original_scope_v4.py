"""Original-scope prospective M2/M3 v4: member centres, rolling regions, geometric-only M3.

Separate implementation: legacy sphere runner and archives are never overwritten.
Read the preregistered geometry-original-scope-v4.0 protocol before execution. All identities
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
DEFAULT_OUTDIR = ATLAS_DIR / "runs" / "A6_geometry_original_scope_v4_20261008"
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
    "missing/overlapping distributions, recognition is INCONCLUSIVE; no identity or birth claim.",
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
    if pts.ndim != 2 or len(pts) == 0:
        raise ValueError("nonempty member matrix required")
    centre = pts.mean(axis=0)
    if centre.shape != (pts.shape[1],):
        raise ValueError("nonempty member matrix and matching centre required")
    if not np.isfinite(pts).all() or not np.isfinite(centre).all():
        raise ValueError("nonfinite geometry, no imputation permitted")
    F = pts.shape[1]
    rms = float(np.sqrt(np.mean(np.sum((pts-centre)**2, axis=1))))
    if len(pts) < 10:
        return rms, np.eye(F)*max(rms*rms, VAR_FLOOR)
    # Supplied fitted centre is ignored: centre and covariance use final members.
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


def threshold_summary(self_scores, other_scores, positive_gaps, negative_gaps):
    """Frozen prospective midpoint policy; missing/nonfinite/equality fail closed."""
    pools = {"self": self_scores, "other": other_scores,
             "positive_gap": positive_gaps, "negative_gap": negative_gaps}
    valid = {k: bool(len(v) and all(isinstance(x, (int, float, np.integer, np.floating))
                and not isinstance(x, (bool, np.bool_)) and np.isfinite(x) for x in v))
                for k,v in pools.items()}
    quantiles = {k: (_quantiles(np.asarray(v, float)) if len(v) and
                 all(not isinstance(x, (bool, np.bool_)) and isinstance(x, (int,float,np.integer,np.floating)) and np.isfinite(x) for x in v)
                 else {q: None for q in _quantiles(np.array([]))}) for k,v in pools.items()}
    tsep = bool(valid["self"] and valid["other"] and quantiles["self"]["q05"] > quantiles["other"]["q95"])
    msep = bool(valid["positive_gap"] and valid["negative_gap"] and quantiles["positive_gap"]["q05"] > quantiles["negative_gap"]["q95"])
    qualified = tsep and msep
    return {"geometry_version": "geometry-original-scope-v4.0.4",
            "calibration_status": "SEPARATED" if qualified else "INCONCLUSIVE",
            "recognition_qualified": qualified, "strict_T_separation": tsep,
            "strict_M_separation": msep, "quantiles_self": quantiles["self"],
            "quantiles_other": quantiles["other"],
            "quantiles_positive_gap": quantiles["positive_gap"],
            "quantiles_negative_gap": quantiles["negative_gap"],
            "raw_distributions": {k: [float(x) if isinstance(x,(int,float,np.integer,np.floating)) and not isinstance(x,(bool,np.bool_)) and np.isfinite(x) else None for x in v] for k,v in pools.items()},
            "counts": {k: len(v) for k,v in pools.items()},
            "n_self_scores": len(self_scores), "n_other_scores": len(other_scores),
            "n_paired_margins": len(positive_gaps), "n_negative_margins": len(negative_gaps),
            "overlap_threshold": (quantiles["self"]["q05"]+quantiles["other"]["q95"])/2 if tsep else None,
            "candidate_margin": (quantiles["positive_gap"]["q05"]+quantiles["negative_gap"]["q95"])/2 if msep else None,
            "resemblance_floor": quantiles["other"]["q50"],
            "ambiguity": not qualified, "fallback": False,
            "ambiguity_note": "Strict separation required for BOTH distributions; no fallback scientific threshold",
            "margin_method": "positive=own-maxother; negative=maxother-secondother, true identity excluded, second0 for one competitor; midpoint q05positive/q95negative",
            "reference_universe_note": "calibration competitors exclude source identity; tracker best-minus-second includes all eligible identities; counts differ"}



def validate_calibration(cal):
    """Receipt semantics must reproduce frozen policy from all raw pools."""
    if cal.get("geometry_version")!="geometry-original-scope-v4.0.4" or cal.get("cal_months")!=list(range(12)):
        raise ValueError("exact new 2023 calibration required")
    raw=cal.get("raw_distributions",{})
    if set(raw)!={"self","other","positive_gap","negative_gap"}:raise ValueError("missing raw bootstrap pools")
    if not all(isinstance(v,list) for v in raw.values()):raise ValueError("invalid raw pools")
    expected=threshold_summary(raw["self"],raw["other"],raw["positive_gap"],raw["negative_gap"])
    for key,value in expected.items():
        if key=="raw_distributions":continue
        if cal.get(key)!=value:raise ValueError("calibration receipt policy mismatch: "+key)
    return cal["calibration_status"]


def calibrate_thresholds(Z, labels_per_month, cal_months, seed):
    """2023 bootstrap; preserve raw distributions, never retune by controls."""
    self_scores=[];other_scores=[];positive_gaps=[];negative_gaps=[];skipped=0
    rng=np.random.default_rng(seed+555555)
    for m in cal_months:
        X=np.asarray(Z[:,m,:],float);lab=np.asarray(labels_per_month[m]);full={}
        for c in sorted(int(c) for c in set(lab.tolist())):
            pts=X[lab==c]
            if len(pts)<CAL_MIN_SIZE:skipped+=1;continue
            mu=pts.mean(axis=0);_,var=region_of_members(pts,mu);full[c]=(mu,var)
        for c,(mu,var) in full.items():
            pts=X[lab==c];n=len(pts)
            for _ in range(BOOT_B):
                bpts=pts[rng.integers(0,n,size=n)];bmu=bpts.mean(axis=0)
                _,bvar=region_of_members(bpts,bmu);own=bc_cov(bmu,bvar,mu,var)
                self_scores.append(own)
                competitors=sorted([bc_cov(bmu,bvar,omu,ovar) for o,(omu,ovar) in full.items() if o!=c],reverse=True)
                other_scores.extend(competitors)
                if competitors:
                    positive_gaps.append(own-competitors[0])
                    negative_gaps.append(competitors[0]-(competitors[1] if len(competitors)>1 else 0.0))
    result=threshold_summary(self_scores,other_scores,positive_gaps,negative_gaps)
    result.update(cal_months=[int(m) for m in cal_months],n_clusters_skipped_small=skipped,
                  method="full covariance B=%d/bootstrap 2023 only min_cluster_size=%d"%(BOOT_B,CAL_MIN_SIZE))
    return result


def rolling_region(old, new):
    """Fixed prospective EWMA alpha=.5; width was unspecified in KB74."""
    radius=.5*old["radius"]+.5*new["rms"]
    cov=(np.eye(len(new["mu"]))*max(radius*radius,VAR_FLOOR) if new["size"]<10 else .5*old["var"]+.5*new["var"])
    return {"mu": .5*old["mu"]+.5*new["mu"], "var": cov, "radius": radius}


def region_inside(points, centre, cov, radius, size, kappa):
    """Original small sphere Euclidean kappa*r, large ellipsoid Mahalanobis."""
    if size < 10:
        return np.sum((np.asarray(points)-np.asarray(centre))**2,axis=1) < (float(kappa)*float(radius))**2
    return mahalanobis_inside(points, centre, cov, kappa)


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
            mu = pts.mean(axis=0)
            rms, var = region_of_members(pts, mu)
            regs[c] = {"mu": mu, "rms": rms, "var": var, "size": int(len(pts)), "audit": covariance_audit(pts,var)}
        F = int(X.shape[1])
        if T is None or M is None:
            # Undefined calibration does not license invented identities or births.
            for c in clusters:
                for ti in np.where(lab == c)[0].tolist():
                    assign_rows.append({"ti":int(ti),"month":month,"label":c,
                                        "identity_id":"","status":"calibration_unknown"})
                rr={"month":month,"cluster":c,"identity_id":"","status":"calibration_unknown",
                    "size":regs[c]["size"],"radius":regs[c]["rms"],"var":float(np.trace(regs[c]["var"])/F)}
                rr.update(regs[c]["audit"])
                rr.update({f"centre_{i}":float(regs[c]["mu"][i]) for i in range(F)})
                rr.update({f"cov_{i}_{j}":float(regs[c]["var"][i,j]) for i in range(F) for j in range(F)})
                region_rows.append(rr)
                ev(month,"calibration_unknown",cluster=c,note="Full-mask geometry retained; undefined T/M, no identity/birth/death claim")
            continue
        if m == 0:
            for c in clusters:
                iid = _new_iid(counter)
                counter += 1
                identities[iid] = {"misses": 0, "last": 0,
                                   "mu": regs[c]["mu"], "var": regs[c]["var"], "radius": regs[c]["rms"]}
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
            if best >= T and margin >= M:
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
                updated = rolling_region(identities[iid], regs[c])
                identities[iid].update({"misses": 0, "last": m, **updated})
                matched.add(iid)
                status = "reemergence" if was_dormant else "continuing"
                _, best, margin = recog[c]
                for ti in np.where(lab == c)[0].tolist():
                    assign_rows.append({"ti": int(ti), "month": month,
                                        "label": c, "identity_id": iid,
                                        "status": status})
                ev(month, status, iid, c, "", "", best, margin,
                   "recognised %s identity (overlap>=T and margin>=M)" %
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
                else:
                    status = "birth"
                    iid = _new_iid(counter)
                    counter += 1
                    identities[iid] = {"misses": 0, "last": m,
                                       "mu": regs[c]["mu"],
                                       "var": regs[c]["var"], "radius": regs[c]["rms"]}
                    for ti in np.where(lab == c)[0].tolist():
                        assign_rows.append({"ti": int(ti), "month": month,
                                            "label": c, "identity_id": iid,
                                            "status": "birth"})
                    ev(month, "birth", iid, c, "", "", float(best), margin,
                       "new cluster (overlap<T); Tc retained as diagnostic only")
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


def detect_split_merge(months, labels_per_month, Z, assign_rows, region_rows, T):
    """Original geometric-only M3, all previous clusters, no composition gate."""
    reg={(r['month'],int(r['cluster'])):r for r in region_rows}
    if T is not None and (not np.isfinite(T) or not 0<=T<=1):raise ValueError('explicit finite frozen overlap threshold required')
    def gaussian(r):
        F=sum(k.startswith('centre_') for k in r)
        return np.array([r[f'centre_{i}'] for i in range(F)]),np.array([[r[f'cov_{i}_{j}'] for j in range(F)] for i in range(F)])
    def inside(points,r,kappa):
        F=sum(k.startswith('centre_') for k in r)
        mu=np.array([r[f'centre_{i}'] for i in range(F)])
        cov=np.array([[r[f'cov_{i}_{j}'] for j in range(F)] for i in range(F)])
        return region_inside(points,mu,cov,r['radius'],r['size'],kappa)
    sensitivity={};primary=[]
    for kappa in KAPPA_GRID:
        for cont in CONT_GRID:
            events=[]
            for m in range(1,len(months)):
                prev,cur=months[m-1],months[m]
                lp=np.asarray(labels_per_month[m-1]);lc=np.asarray(labels_per_month[m])
                xp=np.asarray(Z[:,m-1]);xc=np.asarray(Z[:,m])
                pcs=sorted(set(map(int,lp)));ccs=sorted(set(map(int,lc)))
                for pc in pcs:
                    parent=reg[prev,pc];kids=[]
                    for cc in ccs:
                        fraction=float(np.mean(inside(xc[lc==cc],parent,kappa)))
                        if fraction>cont:kids.append((cc,fraction))
                    continued=T is not None and any(bc_cov(*gaussian(reg[cur,cc]),*gaussian(parent))>=T for cc,_ in kids)
                    if len(kids)>=2 and not continued:
                        events.append({'month':cur,'kind':('split_candidate' if T is not None else 'split_geometry_unqualified'),'identity_id':parent['identity_id'],'cluster':pc,'month_from':prev,'extra_ids':';'.join(str(cc) for cc,_ in kids),'overlap':None,'margin':None,'kappa':kappa,'containment':min(v for _,v in kids),'note':'Original geometric-only candidate; all previous clusters eligible; no economic identity claim'})
                for cc in ccs:
                    child=reg[cur,cc];parents=[]
                    for pc in pcs:
                        fraction=float(np.mean(inside(xp[lp==pc],child,kappa)))
                        if fraction>cont:parents.append((pc,fraction))
                    if len(parents)>=2:
                        events.append({'month':cur,'kind':('merge_candidate' if T is not None else 'merge_geometry_unqualified'),'identity_id':'','cluster':cc,'month_from':prev,'extra_ids':';'.join(f'previous_cluster:{pc}' for pc,_ in parents),'overlap':None,'margin':None,'kappa':kappa,'containment':min(v for _,v in parents),'note':'Original geometric-only candidate; cluster labels in fallback are not recognised identities; no composition gate'})
            sensitivity[f'kappa={kappa}_cont={cont}']={'calibration_status':'SEPARATED' if T is not None else 'INCONCLUSIVE','n_unqualified_geometry_candidates':sum(e['kind'].endswith('_unqualified') for e in events),'n_split_candidates':sum(e['kind']=='split_candidate' for e in events),'n_merge_candidates':sum(e['kind']=='merge_candidate' for e in events)}
            if kappa==OP_KAPPA and cont==OP_CONT:primary=events
    return primary,sensitivity


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
        months, labels_per_month, Z, assign_rows, region_rows, T)
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
        "component": "identities_original_scope_v4",
        "geometry_version": "geometry-original-scope-v4.0.4",
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
            "status": cal["calibration_status"], "recognition_qualified": cal["recognition_qualified"],
            "overlap_threshold": T, "candidate_margin": M,
            "resemblance_floor": Tc, "ambiguity": cal["ambiguity"],
            "n_self_scores": cal["n_self_scores"],
            "n_other_scores": cal["n_other_scores"],
        },
        "identity_counts": {
            "calibration_unknown": count("calibration_unknown"), "initial": count("initial"), "continuing": count("continuing"),
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
            "n_unqualified_geometry_candidates": count("split_geometry_unqualified")+count("merge_geometry_unqualified"), "n_split_candidates": count("split_candidate"),
            "n_merge_candidates": count("merge_candidate"),
            "sensitivity": sens_counts,
            "provenance": "containment of member points inside "
            "ellipse Mahalanobis<kappa or sphere Euclidean<kappa*r; geometric fraction>containment; "
            "split veto is current/previous member-Gaussian overlap>=T, independent margin/conflict/IDs; "
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
        "component": "identities_original_scope_v4",
        "geometry_version": "geometry-original-scope-v4.0.4",
        "replay_mode": "archived_labels" if archived_assignments is not None else "fresh_monthly_fits",
        "status": "PARTIAL_NOT_GATE_PASS",
        "gate_pass": False,
        "completes_case06": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "code": {
            "a6_geometry_original_scope_v4.py": sha256_file(Path(__file__)),
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
            "region": "n>=10 full sample covariance ellipsoid with fixed spectral floor; n<10 isotropic RMS sphere r²I; current member means; fixed EWMA alpha=.5 identity drift",
            "overlap": "full covariance Gaussian Bhattacharyya coefficient, slogdet/solve",
            "recognition": "overlap>=T and (best-second)>=M, one-to-one "
                           "greedy by overlap; losers ambiguous",
            "split_merge": "ellipse Mahalanobis<kappa or small-sphere Euclidean<kappa*r; geometric containment>cont; "
                           "split needs >=2 children + no overlap>=T "
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
    protocol=ATLAS_DIR/"protocol/geometry-original-scope-v4-20261008.json"
    if sha256_file(protocol)!="728358b214a1a2c8b50cf35c6c197c6e36bf704c80c77d172c35f65d47050494":raise ValueError("prospective protocol changed")
    panel=pd.read_parquet(args.panel)
    archived=pd.read_parquet(args.archived_assignments) if args.archived_assignments else None
    result=run_pipeline(panel,args.outdir,args.seed,archived)
    man=result["manifest"]
    man["inputs"]={"panel":{"path":str(args.panel),"sha256":sha256_file(args.panel),"rows":len(panel)}}
    if archived is not None:
        man["inputs"]["archived_assignments"]={"path":str(args.archived_assignments),"sha256":sha256_file(args.archived_assignments),"rows":len(archived)}
    protocol=ATLAS_DIR/"protocol/geometry-original-scope-v4-20261008.json"
    man["protocol_sha256"]=sha256_file(protocol)
    (args.outdir/"manifest.json").write_text(json.dumps(man,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"outdir":str(args.outdir),"replay_mode":man["replay_mode"],"scientific_pass":False}))
    return 0

if __name__=="__main__": raise SystemExit(main())
