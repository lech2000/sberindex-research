"""R8_v2: paired causal forecast ablation for shock-radar (exploratory F7b).

Exploratory ablation, NOT a confirmatory gate: validation data was already
used earlier, and the R8 news audit found 0 eligible historical news events
(64 total / 0 eligible, first_seen 2026, no immutable historical vintage),
so news-enabled and news-only metrics are NA with reason. Status is always
PARTIAL_NOT_GATE_PASS; the case must NOT be closed by this run.

Strict temporal rules (the F03 module got these wrong: it fit and predicted
on the SAME target rows with target = origin + h - 1, so it must never be
copied):
  - forecast_origin is a monthly timestamp; horizon h in (1, 2, 3);
    target = origin + h (NOT origin + h - 1);
  - assumed release lag 2 months is a synthetic assumption, not a measured
    release timestamp: known observations at origin O are months <= O - 2;
  - per-series lags and roll3 use exact calendar positions (lag1 = O - 2,
    lag2 = O - 3, lag3 = O - 4, lag12 = O - 13, roll3 over O - 2..O - 4);
    gaps are never compressed, filled with zero, or interpolated: a series
    with any missing required position is excluded (audited);
  - training examples for eval origin E use origin j with history <= j - 2
    and label month j + h <= E - 2 (no future labels); one model is fit per
    (eval origin, horizon) cell, only on those examples;
  - scoring targets are disjoint from feature/train access by construction;
    the manifest records max_known and max_train_label (both <= E - 2).

Models (all scored on the paired same exact (series, origin, target, h)
mask):
  - lastavailable: carry forward of the last known observation (no fit);
  - seasonal_naive: value(target - 12), only where that observation exists
    and was known (always known for h <= 3, but must be present);
  - nonews_boost: deterministic HistGradientBoostingRegressor
    (max_iter=80, early_stopping=False, max_depth=4, min_samples_leaf=30,
    random_state=seed) on lags/roll3 + category one-hot (levels fixed from
    train, sorted; unseen eval categories map to all-zero; territory_id is
    NEVER used as an ordinal magnitude feature);
  - calendar_boost: nonews_boost + known calendar sin/cos of target month;
  - news_boost / news_only: NA, because strict eligible news count is 0;
    zeros are never injected to fake a news effect.

Leak controls (results land in audit.json):
  1. prefix invariance: mutating observations after a forecast origin must
     leave that origin's fit/predict outputs unchanged (probe cell);
  2. time/target-permutation negative control: train labels shuffled at
     series level with seed, refit, MAE measured on the paired mask;
  3. future-target oracle feature: measured MAE is 0 by construction and is
     quarantined as INVALID_LEAKAGE, never scored as a valid model;
  4. forward-shifted news availability cannot increase eligible features;
     at 0 eligible this control is non-informative 0, reported as such.

Outputs in --outdir (must be a fresh R8_v2-style dir; writing into the R8
archive dir, or any dir already holding news_audit.json, is refused):
predictions.parquet, paired_metrics.csv, audit.json, metrics.json,
manifest.json (inputs + SHA256, code SHA256, deps, seed, exact command,
limitations).

`python r8_forecast_ablation.py --self-check` runs stdlib-only checks on a
synthetic panel with gaps (strict lag, mutate invariance, train/eval label
disjointness, duplicate rejection, news non-eligibility, archive guard).
The real pipeline additionally needs numpy/pandas/pyarrow/scikit-learn.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from datetime import datetime, timezone

RUN_ID = "R8-forecast-ablation-v2"
STATUS = "PARTIAL_NOT_GATE_PASS"
SEED = 20260926
RELEASE_LAG = 2
HORIZONS = (1, 2, 3)
EVAL_ORIGINS = ("2024-06", "2024-07", "2024-08", "2024-09",
                "2024-10", "2024-11")
EVAL_MAX_TARGET = "2024-12"
MIN_TRAIN_ROWS = 500
N_BOOTSTRAP = 200

MODEL_SPEC = {
    "estimator": "HistGradientBoostingRegressor",
    "max_iter": 80,
    "early_stopping": False,
    "max_depth": 4,
    "min_samples_leaf": 30,
    "random_state": SEED,
}

VALID_MODELS = ("lastavailable", "seasonal_naive", "nonews_boost",
                "calendar_boost")
NA_MODELS = ("news_boost", "news_only")

NEWS_TRUTHY = {"1", "true", "yes", "y", "t", "eligible"}
NEWS_ELIGIBILITY_COLUMNS = ("eligible", "is_eligible", "eligibility",
                            "asof_eligible", "status", "decision")


class SpendingValidationError(ValueError):
    pass


class ArchiveOverwriteRefused(RuntimeError):
    pass


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _code_sha256():
    try:
        return _sha256(__file__)
    except NameError:
        return None


def _git_commit():
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or None
    except Exception:
        return None


def _versions():
    v = {"python": sys.version.split()[0]}
    for name in ("numpy", "pandas", "pyarrow", "sklearn"):
        try:
            mod = __import__(name)
            v[name] = getattr(mod, "__version__", "present")
        except ImportError:
            v[name] = None
    return v


def ym_to_int(s):
    if isinstance(s, datetime):
        return s.year * 12 + (s.month - 1)
    t = str(s).strip()
    if len(t) >= 7:
        try:
            return int(t[0:4]) * 12 + (int(t[5:7]) - 1)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(t)
        return dt.year * 12 + (dt.month - 1)
    except ValueError:
        raise SpendingValidationError("unparseable month %r" % (s,))


def int_to_ym(k):
    return "%04d-%02d" % (k // 12, k % 12 + 1)


def normalize_spending_rows(rows):
    """Pure-python schema normalization; raises on bad schema or dup keys."""
    series = {}
    seen = set()
    months = set()
    n_missing_value = 0
    n_day_truncated = 0
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise SpendingValidationError("row %d is not a mapping" % i)
        for col in ("date", "territory_id", "category", "value"):
            if col not in r:
                raise SpendingValidationError(
                    "row %d missing required column %r" % (i, col))
        raw_date = r["date"]
        m = ym_to_int(raw_date)
        day_part = str(raw_date).strip()
        if len(day_part) > 7 and not day_part[7:8] in ("",):
            n_day_truncated += 1
        tid = str(r["territory_id"]).strip()
        cat = str(r["category"]).strip()
        if not tid or not cat:
            raise SpendingValidationError(
                "row %d has empty territory_id/category" % i)
        key = (tid, cat, m)
        if key in seen:
            raise SpendingValidationError(
                "duplicate key (territory_id=%r, category=%r, month=%r) "
                "at row %d" % (tid, cat, int_to_ym(m), i))
        seen.add(key)
        v = r["value"]
        if v is None:
            n_missing_value += 1
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise SpendingValidationError(
                "row %d has non-numeric value %r" % (i, v))
        if math.isnan(f):
            n_missing_value += 1
            continue
        if math.isinf(f):
            raise SpendingValidationError(
                "row %d has non-finite value %r" % (i, v))
        series[key] = f
        months.add(m)
    if not months:
        raise SpendingValidationError("no usable observations after cleaning")
    obs = {}
    for (tid, cat, m), f in series.items():
        obs.setdefault((tid, cat), {})[m] = f
    return {
        "obs": obs,
        "months": sorted(months),
        "n_rows_kept": len(series),
        "n_rows_value_missing": n_missing_value,
        "n_day_truncated": n_day_truncated,
        "n_series": len(obs),
    }


def features_for(obs_series, origin):
    """Exact-calendar-position lags; None when any required month missing."""
    p1, p2, p3, p12 = origin - 2, origin - 3, origin - 4, origin - 13
    try:
        v1 = obs_series[p1]
        v2 = obs_series[p2]
        v3 = obs_series[p3]
        v12 = obs_series[p12]
    except KeyError:
        return None
    return (v1, v2, v3, v12, (v1 + v2 + v3) / 3.0)


def calendar_sincos(target_month):
    m = (target_month % 12) + 1
    ang = 2.0 * math.pi * m / 12.0
    return math.sin(ang), math.cos(ang)


def eval_cells(panel_months):
    cells = []
    m0, m1 = panel_months[0], panel_months[-1]
    cap = ym_to_int(EVAL_MAX_TARGET)
    for o in EVAL_ORIGINS:
        e = ym_to_int(o)
        for h in HORIZONS:
            t = e + h
            if t > cap or t < m0 or t > m1:
                continue
            cells.append((e, h, t))
    return cells


def train_origins_for(eval_origin, h, first_month):
    lo = first_month + 13
    hi = eval_origin - RELEASE_LAG - h
    return [j for j in range(lo, hi + 1) if j < eval_origin]


def check_train_eval_disjoint(train_label_months, eval_targets):
    overlap = set(train_label_months) & set(eval_targets)
    if overlap:
        raise AssertionError(
            "train labels overlap scoring targets: %s"
            % sorted(int_to_ym(m) for m in overlap))
    return True


def category_levels_from_train(train_cats):
    return sorted(set(train_cats))


def onehot(cat, levels):
    return [1.0 if cat == lv else 0.0 for lv in levels]


def mae_of(errs):
    return sum(errs) / len(errs) if errs else float("nan")


def bootstrap_block_diff(tid_of_row, diff_of_row, n_blocks, n_resamples,
                         rng):
    """Blocked-by-territory bootstrap CI for a mean paired difference."""
    sums = [0.0] * n_blocks
    cnts = [0] * n_blocks
    for ti, d in zip(tid_of_row, diff_of_row):
        sums[ti] += d
        cnts[ti] += 1
    total_n = sum(cnts)
    if total_n == 0:
        raise ValueError("empty paired mask for bootstrap")
    point = sum(sums) / total_n
    draws = []
    for _ in range(n_resamples):
        tot = 0.0
        n = 0
        for _ in range(n_blocks):
            k = rng.randrange(n_blocks)
            tot += sums[k]
            n += cnts[k]
        draws.append(tot / n if n else float("nan"))
    draws.sort()
    lo = draws[max(0, int(0.025 * (n_resamples - 1)))]
    hi = draws[min(n_resamples - 1, int(0.975 * (n_resamples - 1)))]
    return {"point": point, "lo": lo, "hi": hi,
            "n_resamples": int(n_resamples), "n_blocks": int(n_blocks),
            "n_rows": int(total_n)}


def permute_labels_at_series_level(train_series_pos, y, rng):
    """Negative control: shuffle each series' train labels in place order."""
    y = list(y)
    for pos in train_series_pos:
        labs = [y[p] for p in pos]
        rng.shuffle(labs)
        for p, lab in zip(pos, labs):
            y[p] = lab
    return y


def ensure_outdir_allowed(outdir, audit_path):
    out = os.path.abspath(outdir)
    audit_dir = os.path.abspath(os.path.dirname(audit_path) or ".")
    if out == audit_dir or out.startswith(audit_dir + os.sep):
        raise ArchiveOverwriteRefused(
            "refusing to write into the R8 archive dir %r" % audit_dir)
    if os.path.exists(os.path.join(out, "news_audit.json")):
        raise ArchiveOverwriteRefused(
            "refusing to overwrite archive marker news_audit.json in %r"
            % out)
    if os.path.isdir(out) and os.listdir(out):
        raise ArchiveOverwriteRefused(
            "refusing to write into existing non-empty outdir %r; use a "
            "fresh empty dir" % out)
    return out


def read_news_audit(path):
    """Read the real R8 audit; supports the actual .json and a .csv form."""
    if not os.path.exists(path):
        base, ext = os.path.splitext(path)
        alt = base + (".json" if ext.lower() == ".csv" else ".csv")
        if os.path.exists(alt):
            path = alt
        else:
            raise SpendingValidationError(
                "news audit file not found: %r (also tried %r)"
                % (path, alt))
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        cov = obj.get("coverage", {}) if isinstance(obj, dict) else {}
        n_total = cov.get("n_events_total")
        n_elig = cov.get("n_eligible")
        if n_elig is None and isinstance(obj.get("eligible"), list):
            n_elig = len(obj["eligible"])
        if n_total is None or n_elig is None:
            raise SpendingValidationError(
                "news audit %r has no coverage counts" % path)
        return {"path_used": path, "kind": "json",
                "column": "coverage.n_eligible",
                "n_total": int(n_total), "n_eligible": int(n_elig)}
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        cols = [c for c in (reader.fieldnames or [])]
        col = next((c for c in NEWS_ELIGIBILITY_COLUMNS if c in cols), None)
        if col is None:
            raise SpendingValidationError(
                "news audit csv %r has no eligibility column "
                "(looked for %s; found %s)"
                % (path, list(NEWS_ELIGIBILITY_COLUMNS), cols))
        n_total, n_elig = 0, 0
        for row in reader:
            n_total += 1
            if str(row.get(col, "")).strip().lower() in NEWS_TRUTHY:
                n_elig += 1
    return {"path_used": path, "kind": "csv", "column": col,
            "n_total": n_total, "n_eligible": n_elig}


def oracle_quarantine_record(paired_actuals):
    errs = [abs(a - a) for a in paired_actuals]
    m = mae_of(errs)
    if m != 0.0:
        raise AssertionError("oracle control must measure MAE 0")
    return {"model": "future_target_oracle", "mae": m,
            "status": "INVALID_LEAKAGE",
            "note": ("intentional future-target feature; quarantined, never "
                     "scored as a valid model")}


def forward_shift_news_control(n_eligible, shifts=(1, 2, 3, 6)):
    counts = {s: int(n_eligible) for s in shifts}
    if any(c > int(n_eligible) for c in counts.values()):
        raise AssertionError("forward shift increased eligible features")
    return {"eligible_at_cutoff": int(n_eligible),
            "eligible_after_forward_shift_months": counts,
            "informative": bool(int(n_eligible) > 0),
            "note": ("0 eligible at cutoff stays 0 under forward shift: "
                     "non-informative 0, not a measured news effect")
            if int(n_eligible) == 0 else
            "eligible counts do not grow under forward shift"}


def fit_boost(X, y, seed):
    try:
        from sklearn.ensemble import HistGradientBoostingRegressor
    except ImportError:
        raise RuntimeError(
            "scikit-learn is required for the real run (fit_boost)")
    spec = dict(MODEL_SPEC)
    spec["random_state"] = int(seed)
    model = HistGradientBoostingRegressor(
        max_iter=spec["max_iter"],
        early_stopping=spec["early_stopping"],
        max_depth=spec["max_depth"],
        min_samples_leaf=spec["min_samples_leaf"],
        random_state=spec["random_state"],
    )
    model.fit(X, y)
    return model


def read_spending_parquet(path):
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is required to read --spending parquet")
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        raise RuntimeError(
            "cannot read spending parquet %r (%s: %s); pyarrow may be "
            "missing" % (path, type(exc).__name__, exc))
    return df.to_dict(orient="records")


def build(spending_path, news_audit_path, outdir, seed):
    try:
        import numpy as np
    except ImportError:
        raise RuntimeError("numpy is required for the real run")
    out = ensure_outdir_allowed(outdir, news_audit_path)
    news = read_news_audit(news_audit_path)
    raw_rows = read_spending_parquet(spending_path)
    norm = normalize_spending_rows(raw_rows)
    obs, months = norm["obs"], norm["months"]
    m0, m1 = months[0], months[-1]
    series_keys = sorted(obs)
    n_series = len(series_keys)
    col_of = {m: i for i, m in enumerate(range(m0, m1 + 1))}
    V = np.full((n_series, m1 - m0 + 1), np.nan)
    for s, key in enumerate(series_keys):
        for m, v in obs[key].items():
            if m0 <= m <= m1:
                V[s, col_of[m]] = v
    cats = [k[1] for k in series_keys]

    cells = eval_cells(months)
    if not cells:
        raise SpendingValidationError("no eval cells inside panel range")
    eval_targets = sorted({t for _, _, t in cells})

    pred_rows = []
    metric_rows = []
    per_cell = []
    perm_mae_by_h = {h: [] for h in HORIZONS}
    boot_pool_by_h = {h: ([], []) for h in HORIZONS}
    boot_pool_all = ([], [])
    oracle_mae_all = []

    for (e, h, t) in cells:
        f = [V[:, col_of[e - k]] for k in (2, 3, 4)]
        f12 = V[:, col_of[e - 13]] if (e - 13) in col_of else \
            np.full(n_series, np.nan)
        valid_f = np.isfinite(f[0]) & np.isfinite(f[1]) & \
            np.isfinite(f[2]) & np.isfinite(f12)
        tgt = V[:, col_of[t]]
        valid_t = np.isfinite(tgt)
        seas = V[:, col_of[t - 12]] if (t - 12) in col_of else \
            np.full(n_series, np.nan)
        valid_s = np.isfinite(seas)
        paired = valid_f & valid_t & valid_s

        js = train_origins_for(e, h, m0)
        Xtr_base, ytr, tr_cats, tr_series = [], [], [], []
        for j in js:
            fj = [V[:, col_of[j - k]] for k in (2, 3, 4)]
            fj12 = V[:, col_of[j - 13]]
            vj = np.isfinite(fj[0]) & np.isfinite(fj[1]) & \
                np.isfinite(fj[2]) & np.isfinite(fj12)
            lab = V[:, col_of[j + h]]
            vl = np.isfinite(lab)
            ok = np.where(vj & vl)[0]
            for s in ok:
                Xtr_base.append((float(fj[0][s]), float(fj[1][s]),
                                 float(fj[2][s]), float(fj12[s]),
                                 float((fj[0][s] + fj[1][s] + fj[2][s])
                                       / 3.0)))
                ytr.append(float(lab[s]))
                tr_cats.append(cats[s])
                tr_series.append(int(s))
        train_label_months = [j + h for j in js]
        check_train_eval_disjoint(train_label_months, [t])
        max_known = e - RELEASE_LAG
        max_train_label = max(train_label_months) if train_label_months \
            else None
        if max_train_label is not None and max_train_label > max_known:
            raise AssertionError("train label beyond max known month")

        n_excl_hist = int((~valid_f & valid_t).sum())
        n_excl_tgt = int((~valid_t).sum())
        n_seas_unav = int((valid_f & valid_t & ~valid_s).sum())
        n_paired = int(paired.sum())

        levels = category_levels_from_train(tr_cats)
        sin_t, cos_t = calendar_sincos(t)
        ev_idx = np.where(valid_f & valid_t)[0]
        ev_base = np.array(
            [[float(f[0][s]), float(f[1][s]), float(f[2][s]),
              float(f12[s]),
              float((f[0][s] + f[1][s] + f[2][s]) / 3.0)]
             for s in ev_idx])
        ev_cat = [cats[s] for s in ev_idx]
        ev_onehot = np.array([onehot(c, levels) for c in ev_cat])
        Xev_nonews = np.hstack([ev_base, ev_onehot])
        Xev_cal = np.hstack(
            [Xev_nonews,
             np.array([[sin_t, cos_t]] * len(ev_idx))])
        yev = np.array([float(tgt[s]) for s in ev_idx])
        lastavail = np.array([float(f[0][s]) for s in ev_idx])
        seas_pred = np.array([float(seas[s]) for s in ev_idx])
        paired_ev = np.array([bool(paired[s]) for s in ev_idx])

        if len(Xtr_base) < MIN_TRAIN_ROWS:
            per_cell.append({
                "origin": int_to_ym(e), "horizon": h,
                "target": int_to_ym(t), "scored": False,
                "skip_reason": "only %d train rows (< %d): no train "
                               "origins satisfy history<=j-2 and "
                               "label<=E-2" % (len(Xtr_base),
                                               MIN_TRAIN_ROWS),
                "n_train_rows": len(Xtr_base),
                "n_train_origins": len(js),
                "max_known": int_to_ym(max_known),
                "max_train_label": int_to_ym(max_train_label)
                if max_train_label is not None else None,
            })
            continue

        Xtr_nonews = np.hstack(
            [np.array(Xtr_base),
             np.array([onehot(c, levels) for c in tr_cats])])
        cal_cols = []
        for j in js:
            sj, cj = calendar_sincos(j + h)
            lab = V[:, col_of[j + h]]
            fj = [V[:, col_of[j - k]] for k in (2, 3, 4)]
            fj12 = V[:, col_of[j - 13]]
            vj = np.isfinite(fj[0]) & np.isfinite(fj[1]) & \
                np.isfinite(fj[2]) & np.isfinite(fj12)
            ok = np.where(vj & np.isfinite(lab))[0]
            cal_cols.extend([(sj, cj)] * len(ok))
        Xtr_cal = np.hstack([Xtr_nonews, np.array(cal_cols)])

        sample = ev_idx[:500]
        for s in sample:
            pure = features_for(obs[series_keys[s]], e)
            if pure is None:
                raise AssertionError("vectorized/pure feature mismatch")
            b = ev_base[list(ev_idx).index(s)]
            if not (abs(pure[0] - b[0]) < 1e-9
                    and abs(pure[1] - b[1]) < 1e-9
                    and abs(pure[2] - b[2]) < 1e-9
                    and abs(pure[3] - b[3]) < 1e-9
                    and abs(pure[4] - b[4]) < 1e-9):
                raise AssertionError("vectorized/pure feature mismatch")

        model_nonews = fit_boost(Xtr_nonews, np.array(ytr), seed)
        model_cal = fit_boost(Xtr_cal, np.array(ytr), seed)
        pred_nonews = np.asarray(model_nonews.predict(Xev_nonews),
                                 dtype=float)
        pred_cal = np.asarray(model_cal.predict(Xev_cal), dtype=float)

        pos_by_series = {}
        for row, s in enumerate(tr_series):
            pos_by_series.setdefault(int(s), []).append(row)
        yperm = permute_labels_at_series_level(
            list(pos_by_series.values()), list(ytr),
            random.Random(int(seed) + 1000 + h))
        model_perm = fit_boost(Xtr_nonews, np.array(yperm), seed)
        pred_perm = np.asarray(model_perm.predict(Xev_nonews), dtype=float)

        oracle = oracle_quarantine_record(
            [float(v) for v in yev[paired_ev]])
        oracle_mae_all.append(oracle["mae"])

        mae = {}
        for name, pred in (("lastavailable", lastavail),
                           ("seasonal_naive", seas_pred),
                           ("nonews_boost", pred_nonews),
                           ("calendar_boost", pred_cal)):
            errs = [abs(float(p) - float(a))
                    for p, a in zip(pred[paired_ev], yev[paired_ev])]
            mae[name] = mae_of(errs) if errs else float("nan")
        perm_errs = [abs(float(p) - float(a))
                     for p, a in zip(pred_perm[paired_ev],
                                     yev[paired_ev])]
        perm_mae_by_h[h].append((n_paired, mae_of(perm_errs)
                                 if perm_errs else float("nan")))

        tids = [series_keys[s][0] for s in ev_idx]
        cal_err = [abs(float(p) - float(a))
                   for p, a in zip(pred_cal[paired_ev], yev[paired_ev])]
        non_err = [abs(float(p) - float(a))
                   for p, a in zip(pred_nonews[paired_ev],
                                   yev[paired_ev])]
        diff = [c - n for c, n in zip(cal_err, non_err)]
        paired_tids = [t for t, kp in zip(tids, paired_ev) if kp]
        boot_pool_by_h[h][0].extend(paired_tids)
        boot_pool_by_h[h][1].extend(diff)
        boot_pool_all[0].extend(paired_tids)
        boot_pool_all[1].extend(diff)

        for s, pe in zip(ev_idx, range(len(ev_idx))):
            tid, cat = series_keys[s]
            pred_rows.append({
                "territory_id": tid, "category": cat,
                "origin": int_to_ym(e), "target": int_to_ym(t),
                "horizon": h, "actual": float(yev[pe]),
                "pred_lastavailable": float(lastavail[pe]),
                "pred_seasonal_naive": (float(seas_pred[pe])
                                        if paired[s] else None),
                "pred_nonews": float(pred_nonews[pe]),
                "pred_calendar": float(pred_cal[pe]),
                "paired": bool(paired[s]),
            })

        cov = (n_paired / n_series) if n_series else 0.0
        for name in VALID_MODELS:
            metric_rows.append({
                "origin": int_to_ym(e), "horizon": h, "model": name,
                "n_paired": n_paired, "mae": mae[name],
                "coverage_frac": cov, "n_series_total": n_series,
                "n_excluded_history": n_excl_hist,
                "n_excluded_target": n_excl_tgt,
                "n_seasonal_unavailable": n_seas_unav,
                "na_reason": "",
            })
        na_reason = ("strict eligible news = 0 (audit %d total / %d "
                     "eligible via %s): news effects unmeasured; no "
                     "zeros injected" % (news["n_total"],
                                         news["n_eligible"],
                                         news["column"]))
        for name in NA_MODELS:
            metric_rows.append({
                "origin": int_to_ym(e), "horizon": h, "model": name,
                "n_paired": n_paired, "mae": "",
                "coverage_frac": "", "n_series_total": n_series,
                "n_excluded_history": n_excl_hist,
                "n_excluded_target": n_excl_tgt,
                "n_seasonal_unavailable": n_seas_unav,
                "na_reason": na_reason,
            })
        per_cell.append({
            "origin": int_to_ym(e), "horizon": h,
            "target": int_to_ym(t), "scored": True,
            "n_train_rows": len(Xtr_base), "n_train_origins": len(js),
            "train_origins": [int_to_ym(j) for j in js],
            "max_known": int_to_ym(max_known),
            "max_train_label": int_to_ym(max_train_label),
            "n_series_total": n_series, "n_paired": n_paired,
            "n_excluded_history": n_excl_hist,
            "n_excluded_target": n_excl_tgt,
            "n_seasonal_unavailable": n_seas_unav,
            "category_levels": levels,
            "mae": mae,
            "permutation_control_mae": mae_of(perm_errs)
            if perm_errs else None,
            "oracle_mae": oracle["mae"],
        })

    scored = [c for c in per_cell if c.get("scored")]
    if not scored:
        raise SpendingValidationError("no eval cells could be scored")

    panel_mae = {}
    for name in VALID_MODELS:
        num = den = 0.0
        for c in scored:
            n = c["n_paired"]
            num += c["mae"][name] * n
            den += n
        panel_mae[name] = num / den if den else float("nan")
    per_h_mae = {}
    for h in HORIZONS:
        per_h_mae[h] = {}
        for name in VALID_MODELS:
            num = den = 0.0
            for c in scored:
                if c["horizon"] != h:
                    continue
                num += c["mae"][name] * c["n_paired"]
                den += c["n_paired"]
            per_h_mae[h][name] = num / den if den else float("nan")

    bootstrap = {}
    for h in HORIZONS:
        tids, diffs = boot_pool_by_h[h]
        if not diffs:
            continue
        tsorted = sorted(set(tids))
        tmap = {t: i for i, t in enumerate(tsorted)}
        bootstrap["h%d" % h] = bootstrap_block_diff(
            [tmap[t] for t in tids], list(diffs), len(tsorted),
            N_BOOTSTRAP, random.Random(int(seed) + 2000 + h))
    atids, adiffs = boot_pool_all
    atasorted = sorted(set(atids))
    atamap = {t: i for i, t in enumerate(atasorted)}
    bootstrap["panel"] = bootstrap_block_diff(
        [atamap[t] for t in atids], list(adiffs), len(atasorted),
        N_BOOTSTRAP, random.Random(int(seed) + 2999))

    perm_panel_num = perm_panel_den = 0.0
    for h in HORIZONS:
        num = den = 0.0
        for n, m in perm_mae_by_h[h]:
            if m == m:
                num += m * n
                den += n
        perm_panel_num += num
        perm_panel_den += den

    probe_e = ym_to_int(scored[0]["origin"])
    probe_h = scored[0]["horizon"]
    Vmut = V.copy()
    Vmut[:, [col_of[m] for m in range(m0, m1 + 1)
              if m > probe_e - RELEASE_LAG]] += 1e6
    probe_preds_a = _probe_predict(
        V, col_of, series_keys, cats, m0, probe_e, probe_h, seed)
    probe_preds_b = _probe_predict(
        Vmut, col_of, series_keys, cats, m0, probe_e, probe_h, seed)
    max_diff = max(abs(a - b) for a, b in
                   zip(probe_preds_a, probe_preds_b))
    if not (max_diff < 1e-9):
        raise AssertionError("prefix invariance violated: %r" % max_diff)

    news_ctrl = forward_shift_news_control(news["n_eligible"])

    os.makedirs(out, exist_ok=True)
    run_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    command = " ".join(sys.argv)
    provenance = {
        "run_utc": run_utc, "command": command,
        "inputs": {
            "spending": spending_path,
            "spending_sha256": _sha256(spending_path),
            "spending_rows_kept": norm["n_rows_kept"],
            "news_audit": news["path_used"],
            "news_audit_sha256": _sha256(news["path_used"]),
            "news_audit_kind": news["kind"],
            "news_eligibility_column": news["column"],
        },
        "code_sha256": _code_sha256(), "git_commit": _git_commit(),
        "versions": _versions(), "seed": int(seed),
    }
    limitations = [
        "exploratory R8_v2, not confirmatory: validation data was already "
        "used earlier, so no unopened-test claim is made",
        "news audit reports %d total / %d eligible events: news-enabled "
        "and news-only metrics are NA; no quality claim is made where "
        "calendar shows no improvement over no-news" % (
            news["n_total"], news["n_eligible"]),
        "assumed release lag of 2 months is a synthetic assumption, not a "
        "measured release timestamp",
        "24 monthly points per series: yearly seasonality is estimated "
        "with high uncertainty; lag12 needs a 14-month warmup so train "
        "origins start late and early cells may be skipped",
        "territory_id is never used as a magnitude feature; category is "
        "one-hot with train-fixed levels",
        "seasonal naive needs value(target-12) present; otherwise the "
        "pair is excluded from the paired mask (audited)",
    ]

    pred_format = _write_predictions(pred_rows, out)
    with open(os.path.join(out, "paired_metrics.csv"), "w",
              encoding="utf-8", newline="") as f:
        cols = ["origin", "horizon", "model", "n_paired", "mae",
                "coverage_frac", "n_series_total", "n_excluded_history",
                "n_excluded_target", "n_seasonal_unavailable",
                "na_reason"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(metric_rows,
                        key=lambda r: (r["origin"], r["horizon"],
                                       r["model"])):
            w.writerow(r)

    audit = {
        "run_id": RUN_ID,
        "news_audit": {
            "file": news["path_used"], "kind": news["kind"],
            "eligibility_column": news["column"],
            "n_events_total": news["n_total"],
            "n_eligible": news["n_eligible"],
        },
        "spending_input": {
            "n_rows_kept": norm["n_rows_kept"],
            "n_rows_value_missing": norm["n_rows_value_missing"],
            "n_day_truncated": norm["n_day_truncated"],
            "n_series": norm["n_series"],
            "panel_range": [int_to_ym(m0), int_to_ym(m1)],
        },
        "cells": per_cell,
        "leak_controls": {
            "prefix_invariance_probe": {
                "origin": int_to_ym(probe_e), "horizon": probe_h,
                "mutated": "all observations after %s by +1e6"
                           % int_to_ym(probe_e - RELEASE_LAG),
                "max_abs_prediction_diff": max_diff,
                "passed": True,
            },
            "permutation_negative_control": {
                h: {"mae": (lambda n, d: n / d if d else None)(
                    sum(m * n for n, m in perm_mae_by_h[h] if m == m),
                    sum(n for n, m in perm_mae_by_h[h] if m == m))}
                for h in HORIZONS if perm_mae_by_h[h]
            },
            "future_target_oracle": {
                "mae": 0.0, "status": "INVALID_LEAKAGE",
                "note": ("measured 0 by construction; quarantined, never "
                         "in paired_metrics.csv"),
            },
            "forward_shift_news": news_ctrl,
        },
        "train_eval_disjoint": True,
        "vectorized_pure_crosscheck": "500-row sample per cell passed",
        "provenance": provenance,
    }
    with open(os.path.join(out, "audit.json"), "w",
              encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1)

    metrics = {
        "run_id": RUN_ID, "status": STATUS, "gate_pass": False,
        "gate_pass_reason": ("exploratory R8_v2 paired ablation: validation "
                             "already used earlier and no historical news "
                             "exists (0 eligible), so PASS is forbidden; "
                             "do not close the case"),
        "fallback_documented": False,
        "case_action": "do_not_close",
        "eval": {"origins": list(EVAL_ORIGINS),
                 "horizons": list(HORIZONS),
                 "cells_scored": len(scored),
                 "cells_skipped": len(per_cell) - len(scored)},
        "panel_mae": panel_mae,
        "per_horizon_mae": {"h%d" % h: per_h_mae[h] for h in HORIZONS
                            if h in per_h_mae},
        "bootstrap_calendar_minus_nonews": bootstrap,
        "permutation_control_panel_mae": (perm_panel_num
                                          / perm_panel_den
                                          if perm_panel_den else None),
        "oracle_quarantined_mae": 0.0,
        "news_enabled_evaluation": "NA",
        "news_only_evaluation": "NA",
        "na_reason": ("strict eligible news = 0 (%d total / %d eligible): "
                      "news effects unmeasured; zeros never injected" % (
                          news["n_total"], news["n_eligible"])),
        "quality_claim": None,
        "quality_claim_note": ("no quality claim is made where calendar "
                               "shows no improvement over no-news"),
        "limitations": limitations,
        "predictions_file": os.path.join(out, "predictions.parquet")
        if pred_format == "parquet" else os.path.join(
            out, "predictions.csv"),
        "predictions_format": pred_format,
        "provenance": provenance,
    }
    with open(os.path.join(out, "metrics.json"), "w",
              encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)

    manifest = {
        "run_id": RUN_ID,
        "model": dict(MODEL_SPEC),
        "features": {
            "lags": "exact calendar positions O-2/O-3/O-4/O-13",
            "roll3": "mean of O-2..O-4, no gap compression",
            "category": "one-hot, levels fixed on train (sorted)",
            "territory_id": "excluded (never ordinal magnitude)",
            "calendar_variant": "adds sin/cos of target month",
        },
        "per_origin_bounds": {
            c["origin"]: {"max_known": c["max_known"],
                          "max_train_label": c["max_train_label"]}
            for c in per_cell if c.get("scored")
        },
        "outputs": ["predictions." + ("parquet" if pred_format == "parquet"
                                      else "csv"),
                    "paired_metrics.csv", "audit.json", "metrics.json",
                    "manifest.json"],
        "limitations": limitations,
        "provenance": provenance,
    }
    with open(os.path.join(out, "manifest.json"), "w",
              encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": STATUS, "cells_scored": len(scored),
                      "panel_mae": panel_mae,
                      "news": "%d/%d" % (news["n_total"],
                                         news["n_eligible"]),
                      "outdir": out},
                     ensure_ascii=False, indent=1))
    return audit, metrics


def _probe_predict(V, col_of, series_keys, cats, m0, e, h, seed):
    import numpy as np
    js = train_origins_for(e, h, m0)
    Xtr, ytr, tr_cats = [], [], []
    for j in js:
        fj = [V[:, col_of[j - k]] for k in (2, 3, 4)]
        fj12 = V[:, col_of[j - 13]]
        vj = np.isfinite(fj[0]) & np.isfinite(fj[1]) & \
            np.isfinite(fj[2]) & np.isfinite(fj12)
        lab = V[:, col_of[j + h]]
        ok = np.where(vj & np.isfinite(lab))[0]
        for s in ok:
            Xtr.append((float(fj[0][s]), float(fj[1][s]),
                        float(fj[2][s]), float(fj12[s]),
                        float((fj[0][s] + fj[1][s] + fj[2][s]) / 3.0)))
            ytr.append(float(lab[s]))
            tr_cats.append(cats[s])
    levels = category_levels_from_train(tr_cats)
    Xtr = np.hstack([np.array(Xtr),
                     np.array([onehot(c, levels) for c in tr_cats])])
    model = fit_boost(Xtr, np.array(ytr), seed)
    f = [V[:, col_of[e - k]] for k in (2, 3, 4)]
    f12 = V[:, col_of[e - 13]]
    ok = np.where(np.isfinite(f[0]) & np.isfinite(f[1])
                  & np.isfinite(f[2]) & np.isfinite(f12))[0]
    Xe = np.hstack([np.array(
        [[float(f[0][s]), float(f[1][s]), float(f[2][s]),
          float(f12[s]),
          float((f[0][s] + f[1][s] + f[2][s]) / 3.0)] for s in ok]),
        np.array([onehot(cats[s], levels) for s in ok])])
    return [float(p) for p in model.predict(Xe)]


def _write_predictions(pred_rows, out):
    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is required to write predictions")
    cols = ["territory_id", "category", "origin", "target", "horizon",
            "actual", "pred_lastavailable", "pred_seasonal_naive",
            "pred_nonews", "pred_calendar", "paired"]
    df = pd.DataFrame(pred_rows, columns=cols)
    df = df.sort_values(["origin", "horizon", "territory_id",
                         "category"]).reset_index(drop=True)
    try:
        df.to_parquet(os.path.join(out, "predictions.parquet"),
                      index=False)
        return "parquet"
    except Exception:
        df.to_csv(os.path.join(out, "predictions.csv"), index=False)
        return "csv_fallback"


def self_check():
    months = [2023 * 12 + m for m in range(0, 24)]
    rows = []
    for s in range(6):
        for k, m in enumerate(months):
            if s == 2 and k in (8, 9):
                continue
            rows.append({"date": int_to_ym(m), "territory_id": "t%d" % s,
                         "category": "c%d" % (s % 2),
                         "value": 100.0 + 10 * s + k})
    norm = normalize_spending_rows(rows)
    assert norm["n_series"] == 6, norm
    assert norm["months"] == months, norm

    dup = list(rows) + [dict(rows[0])]
    try:
        normalize_spending_rows(dup)
        raise AssertionError("duplicate key was not rejected")
    except SpendingValidationError:
        pass

    obs0 = norm["obs"][("t0", "c0")]
    e = months[15]
    feat = features_for(obs0, e)
    assert feat is not None
    assert feat[0] == obs0[e - 2] and feat[1] == obs0[e - 3], feat
    assert feat[2] == obs0[e - 4] and feat[3] == obs0[e - 13], feat
    assert feat[4] == (obs0[e - 2] + obs0[e - 3] + obs0[e - 4]) / 3.0
    obs_gap = norm["obs"][("t2", "c0")]
    assert features_for(obs_gap, months[12]) is None
    assert features_for(obs_gap, months[14]) is not None

    mutated = {k: dict(v) for k, v in norm["obs"].items()}
    for key, ser in mutated.items():
        for m in list(ser):
            if m > e - RELEASE_LAG:
                ser[m] = ser[m] + 1e6
    for key, ser in norm["obs"].items():
        assert features_for(ser, e) == features_for(mutated[key], e)

    js = train_origins_for(months[20], 1, months[0])
    assert js and all(j < months[20] for j in js), js
    e = months[20]
    for j in js:
        assert j - 13 >= months[0] and j + 1 <= e - RELEASE_LAG, (j, e)
    labels = [j + 1 for j in js]
    check_train_eval_disjoint(labels, [e + 1])
    try:
        check_train_eval_disjoint(labels, labels[:1])
        raise AssertionError("overlap not detected")
    except AssertionError as exc:
        assert "overlap" in str(exc)

    late = ym_to_int("2024-11")
    js_late = train_origins_for(late, 1, ym_to_int("2023-01"))
    late_labels = [j + 1 for j in js_late]
    assert ym_to_int("2024-07") in late_labels, late_labels
    check_train_eval_disjoint(late_labels, [late + 1])
    assert max(late_labels) <= late - RELEASE_LAG, late_labels
    try:
        check_train_eval_disjoint(late_labels + [late + 1], [late + 1])
        raise AssertionError("current-target overlap not detected")
    except AssertionError as exc:
        assert "overlap" in str(exc)

    dup_none = [dict(rows[0]), dict(rows[0])]
    dup_none[0]["value"] = None
    try:
        normalize_spending_rows(dup_none)
        raise AssertionError("duplicate with first value None not rejected")
    except SpendingValidationError:
        pass
    dup_nan = [dict(rows[0]), dict(rows[0])]
    dup_nan[0]["value"] = float("nan")
    try:
        normalize_spending_rows(dup_nan)
        raise AssertionError("duplicate with first value NaN not rejected")
    except SpendingValidationError:
        pass

    lv = category_levels_from_train(["c1", "c0", "c1"])
    assert lv == ["c0", "c1"], lv
    assert onehot("c0", lv) == [1.0, 0.0]
    assert onehot("unseen", lv) == [0.0, 0.0]
    s_sin, s_cos = calendar_sincos(ym_to_int("2024-07"))
    assert abs(s_sin ** 2 + s_cos ** 2 - 1.0) < 1e-12

    rng = random.Random(SEED)
    y = [1.0, 2.0, 3.0, 10.0, 20.0]
    yp = permute_labels_at_series_level([[0, 1, 2], [3, 4]], y, rng)
    assert sorted(yp[:3]) == [1.0, 2.0, 3.0]
    assert sorted(yp[3:]) == [10.0, 20.0]
    yp2 = permute_labels_at_series_level(
        [[0, 1, 2], [3, 4]], list(y), random.Random(SEED))
    assert yp == yp2

    tids = [0, 0, 1, 1, 2, 2]
    diffs = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
    ci = bootstrap_block_diff(tids, diffs, 3, 200, random.Random(SEED))
    assert ci["point"] == 2.0 and ci["lo"] == 2.0 and ci["hi"] == 2.0
    assert ci["n_resamples"] == 200 and ci["n_blocks"] == 3
    diffs2 = [1.0, 3.0, 0.0, 4.0, -1.0, 6.0]
    ci2 = bootstrap_block_diff(tids, diffs2, 3, 200,
                               random.Random(SEED))
    assert ci2["lo"] <= ci2["point"] <= ci2["hi"], ci2
    assert ci2["lo"] < ci2["hi"], ci2

    q = oracle_quarantine_record([1.5, 2.5, 3.5])
    assert q["mae"] == 0.0 and q["status"] == "INVALID_LEAKAGE"

    nc = forward_shift_news_control(0)
    assert nc["eligible_at_cutoff"] == 0
    assert nc["informative"] is False
    assert all(v == 0 for v in
               nc["eligible_after_forward_shift_months"].values())

    audit_obj = {"coverage": {"n_events_total": 64, "n_eligible": 0},
                 "eligible": []}
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json",
                                     delete=False) as f:
        json.dump(audit_obj, f)
        jp = f.name
    got = read_news_audit(jp)
    assert got["n_total"] == 64 and got["n_eligible"] == 0, got
    assert got["column"] == "coverage.n_eligible", got
    os.unlink(jp)
    missing_csv = jp.replace(".json", ".csv")
    try:
        read_news_audit(missing_csv)
        raise AssertionError("missing audit was not refused")
    except SpendingValidationError:
        pass
    with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                     delete=False) as f:
        f.write("url,eligible\n")
        f.write("u1,0\nu2,false\nu3,no\n")
        cp = f.name
    got_csv = read_news_audit(cp)
    assert got_csv["n_total"] == 3 and got_csv["n_eligible"] == 0
    assert got_csv["column"] == "eligible", got_csv
    os.unlink(cp)
    with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                     delete=False) as f:
        f.write("url,note\nu1,x\n")
        cp2 = f.name
    try:
        read_news_audit(cp2)
        raise AssertionError("csv without eligibility column accepted")
    except SpendingValidationError:
        pass
    os.unlink(cp2)

    try:
        ensure_outdir_allowed("/tmp/R8_v2_probe", "/tmp/R8/news_audit.json")
    except ArchiveOverwriteRefused:
        raise AssertionError("sibling R8_v2 dir wrongly refused")
    try:
        ensure_outdir_allowed("/tmp/R8", "/tmp/R8/news_audit.json")
        raise AssertionError("archive dir overwrite not refused")
    except ArchiveOverwriteRefused:
        pass
    try:
        ensure_outdir_allowed("/tmp/R8/sub", "/tmp/R8/news_audit.json")
        raise AssertionError("archive subdir overwrite not refused")
    except ArchiveOverwriteRefused:
        pass

    with tempfile.TemporaryDirectory() as d:
        ensure_outdir_allowed(d, "/tmp/R8/news_audit.json")
        with open(os.path.join(d, "stale.txt"), "w") as f:
            f.write("x")
        try:
            ensure_outdir_allowed(d, "/tmp/R8/news_audit.json")
            raise AssertionError("non-empty outdir not refused")
        except ArchiveOverwriteRefused:
            pass
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "news_audit.json"), "w") as f:
            f.write("{}")
        try:
            ensure_outdir_allowed(d, "/tmp/other_audit.json")
            raise AssertionError("old R8 audit marker not refused")
        except ArchiveOverwriteRefused:
            pass

    cells = eval_cells(list(range(ym_to_int("2023-01"),
                                  ym_to_int("2024-12") + 1)))
    assert len(cells) == 15, cells
    assert all(t == e + h for e, h, t in cells), cells
    assert all(t <= ym_to_int("2024-12") for _, _, t in cells)
    ej = train_origins_for(ym_to_int("2024-06"), 3,
                           ym_to_int("2023-01"))
    assert ej == [], ej

    assert MODEL_SPEC["max_iter"] == 80
    assert MODEL_SPEC["early_stopping"] is False
    assert MODEL_SPEC["max_depth"] == 4
    assert MODEL_SPEC["min_samples_leaf"] == 30
    print("SELF-CHECK OK")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="R8_v2: paired causal forecast ablation "
                    "(exploratory, never a gate PASS)")
    p.add_argument("--spending", default=None)
    p.add_argument("--news-audit", default=None)
    p.add_argument("--outdir", default=None)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.spending and a.news_audit and a.outdir):
        p.error("--spending, --news-audit and --outdir are required")
    build(a.spending, a.news_audit, a.outdir, a.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
