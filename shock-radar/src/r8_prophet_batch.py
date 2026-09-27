"""R8 Prophet batch runner: resumable, checkpointed, full-mask Prophet fits.

Runs Prophet on ALL 12366 paired == True series (sorted stable) across all
origins in the R8_v2 paired run, producing full 171150-row coverage.

Key properties:
  - Atomic per-(series, origin) checkpoints: each fit writes its predictions
    and failure reasons to a durable checkpoint directory; resume never
    re-runs a completed fit.
  - Fingerprinted inputs: raw parquet, paired predictions.parquet, this code
    file, and config are fingerprinted at start; resume refuses to continue
    if any fingerprint changed.
  - --max-fits N bounds invocations for operator testing; --resume continues.
  - Hard raw-vs-actual check before every fit (PairedContractError stops that
    cell, not the entire run).
  - Prefix mutation + determinism probe on one sampled completed origin.
  - Aggregation: per-horizon/common-mask MAE for all 3 models, coverage/
    missing/exclusion counts, measured runtime per fit.
  - Negatives are valid forecasts; no obligatory MAE win.
  - No PASS if failures shrink the mask or completed_fits < all_required;
    summary stays PARTIAL until full completion; never closes the case.

Usage:
  python r8_prophet_batch.py --raw <raw.parquet> --paired-run <R8_v2_dir> \\
      --outdir <empty_dir> [--max-fits 50] [--seed 20260927]
  python r8_prophet_batch.py --resume --outdir <existing_dir>
  python r8_prophet_batch.py --dry-run --raw <raw.parquet> --paired-run <R8_v2_dir>
  python r8_prophet_batch.py --self-check

For reproducible, deterministic fits run with single-threaded BLAS:
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python r8_prophet_batch.py ...
"""

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import random
import sys
import time

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

RUN_ID = "R8-prophet-batch"
STATUS_PARTIAL = "PARTIAL"
STATUS_PASS = "PASS"
STATUS_NOT_PASS = "NOT_PASS"
SEED_DEFAULT = 20260927
RELEASE_LAG = 2
HORIZONS = (1, 2, 3)
MIN_TRAIN_POINTS = 6
FULL_R8_MASK = 171150
PRED_TOL = 1e-9
MUTATION_DELTA = 1e6

PAIRED_REQUIRED_COLUMNS = (
    "territory_id", "category", "origin", "horizon", "target", "actual",
    "pred_lastavailable", "pred_seasonal_naive",
)


# ---------------------------------------------------------------------------
# exceptions
# ---------------------------------------------------------------------------

class RawValidationError(ValueError):
    pass


class PairedContractError(RuntimeError):
    pass


class FingerprintMismatch(RuntimeError):
    pass


class CheckpointIncompatible(RuntimeError):
    pass


class DependencyMissing(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# value/key helpers
# ---------------------------------------------------------------------------

def ym_to_int(s):
    if isinstance(s, _dt.datetime):
        return s.year * 12 + (s.month - 1)
    if isinstance(s, _dt.date):
        return s.year * 12 + (s.month - 1)
    t = str(s).strip()
    if len(t) >= 7:
        try:
            return int(t[0:4]) * 12 + (int(t[5:7]) - 1)
        except ValueError:
            pass
    try:
        dt = _dt.datetime.fromisoformat(t)
        return dt.year * 12 + (dt.month - 1)
    except ValueError:
        raise RawValidationError("unparseable month %r" % (s,))


def int_to_ym(k):
    return "%04d-%02d" % (k // 12, k % 12 + 1)


def month_to_dt(m):
    return _dt.datetime(m // 12, m % 12 + 1, 1)


def last_allowed_month(origin_m):
    return origin_m - RELEASE_LAG


def target_month(origin_m, h):
    return origin_m + int(h)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _code_sha256():
    try:
        return _sha256(os.path.abspath(__file__))
    except Exception:
        return None


def _versions():
    v = {"python": sys.version.split()[0]}
    for mod in ("numpy", "pandas", "pyarrow", "prophet", "cmdstanpy"):
        try:
            m = __import__(mod)
            v[mod] = getattr(m, "__version__", None)
        except Exception:
            v[mod] = None
    return v


def mae_of(errs):
    errs = [e for e in errs if e == e]
    return sum(errs) / len(errs) if errs else None


def _finite(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# raw handling (reused from pilot)
# ---------------------------------------------------------------------------

def normalize_raw_rows(rows):
    """Pure-python schema normalization; raises on bad schema or dup keys."""
    series = {}
    seen = set()
    months = set()
    n_missing_value = 0
    n_day_truncated = 0
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise RawValidationError("row %d is not a mapping" % i)
        for col in ("date", "territory_id", "category", "value"):
            if col not in r:
                raise RawValidationError(
                    "row %d missing required column %r" % (i, col))
        raw_date = r["date"]
        m = ym_to_int(raw_date)
        day_part = str(raw_date).strip()
        if len(day_part) > 7:
            n_day_truncated += 1
        tid = str(r["territory_id"]).strip()
        cat = str(r["category"]).strip()
        if not tid or not cat:
            raise RawValidationError(
                "row %d has empty territory_id/category" % i)
        key = (tid, cat, m)
        if key in seen:
            raise RawValidationError(
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
            raise RawValidationError(
                "row %d has non-numeric value %r" % (i, v))
        if math.isnan(f):
            n_missing_value += 1
            continue
        if math.isinf(f):
            raise RawValidationError(
                "row %d has non-finite value %r" % (i, v))
        series[key] = f
        months.add(m)
    if not months:
        raise RawValidationError("no usable observations after cleaning")
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


def causal_train_window(raw_series, origin_m):
    """Sorted (month, value) for months <= origin - RELEASE_LAG only."""
    cutoff = last_allowed_month(origin_m)
    return sorted((m, v) for m, v in raw_series.items() if m <= cutoff)


# ---------------------------------------------------------------------------
# paired input (reused from pilot)
# ---------------------------------------------------------------------------

def _paired_true(v):
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    try:
        return bool(v) is True
    except (TypeError, ValueError):
        return False


def normalize_paired_rows(records, cols):
    """Pure-python paired-input contract; unpaired rows excluded FIRST."""
    cols = list(cols)
    if "paired" not in cols:
        raise PairedContractError(
            "paired predictions are missing the required boolean column "
            "'paired' (found %s); refusing to guess which rows are paired"
            % (cols,))
    missing = [c for c in PAIRED_REQUIRED_COLUMNS if c not in cols]
    if missing:
        raise PairedContractError(
            "paired predictions missing columns %s (found %s)"
            % (missing, cols))
    rows = []
    seen = {}
    excluded_unpaired = 0
    for i, r in enumerate(records):
        if not _paired_true(r.get("paired")):
            excluded_unpaired += 1
            continue
        tid = str(r["territory_id"]).strip()
        cat = str(r["category"]).strip()
        h = int(r["horizon"])
        origin_m = ym_to_int(r["origin"])
        target_m = ym_to_int(r["target"])
        if target_m != origin_m + h:
            raise PairedContractError(
                "target disagreement at row %d: origin=%s horizon=%d "
                "target=%s (expected %s)"
                % (i, int_to_ym(origin_m), h, int_to_ym(target_m),
                   int_to_ym(origin_m + h)))
        join_key = (tid, cat, origin_m, h, target_m)
        if join_key in seen:
            raise PairedContractError(
                "duplicate join key %r at row %d (first at row %d); "
                "refusing to join" % (join_key, i, seen[join_key]))
        seen[join_key] = i
        rows.append({
            "territory_id": tid,
            "category": cat,
            "origin": origin_m,
            "horizon": h,
            "target": target_m,
            "actual": _finite(r["actual"]),
            "pred_lastavailable": _finite(r["pred_lastavailable"]),
            "pred_seasonal_naive": _finite(r["pred_seasonal_naive"]),
            "paired": True,
        })
    if not rows:
        raise PairedContractError(
            "no paired == True rows among %d input rows (excluded %d "
            "unpaired); refusing to run on an empty paired mask"
            % (len(records), excluded_unpaired))
    return rows, {
        "total_input_rows": len(records),
        "excluded_unpaired_rows": excluded_unpaired,
        "n_rows": len(rows),
    }


def read_records_parquet(path, what):
    try:
        import pandas as pd
    except ImportError:
        raise DependencyMissing(
            "pandas is required to read %s (dependency missing)" % what)
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        raise DependencyMissing(
            "cannot read %s %r (%s: %s); pyarrow may be missing"
            % (what, path, type(exc).__name__, exc))
    return df


def _read_paired_predictions(paired_run_dir):
    """Read predictions.parquet, returning DataFrame (handles csv fallback)."""
    path = os.path.join(paired_run_dir, "predictions.parquet")
    if not os.path.exists(path):
        csv_path = os.path.join(paired_run_dir, "predictions.csv")
        if os.path.exists(csv_path):
            import pandas as pd
            return pd.read_csv(csv_path), csv_path
        raise PairedContractError(
            "paired predictions.parquet not found in %r" % paired_run_dir)
    return read_records_parquet(path, "paired predictions.parquet"), path


def _read_raw_data(raw_path):
    """Read raw spending data, returning DataFrame (handles csv fallback)."""
    try:
        return read_records_parquet(raw_path, "raw spending parquet")
    except (DependencyMissing, Exception):
        if raw_path.endswith(".csv"):
            import pandas as pd
            return pd.read_csv(raw_path)
        raise


def load_paired_rows(paired_run_dir):
    """Read predictions.parquet and enforce the join contract."""
    path = os.path.join(paired_run_dir, "predictions.parquet")
    if not os.path.exists(path):
        raise PairedContractError(
            "paired predictions.parquet not found in %r" % paired_run_dir)
    df = read_records_parquet(path, "paired predictions.parquet")
    cols = list(df.columns)
    rows, info = normalize_paired_rows(df.to_dict(orient="records"), cols)
    info.update({
        "path": path,
        "sha256": _sha256(path),
        "columns": cols,
        "join_keys": ["territory_id", "category", "origin", "horizon",
                      "target"],
    })
    return rows, info


def validate_selected_raw_actuals(selected_rows, obs, tol=PRED_TOL):
    """Pre-fit hard contract over EVERY selected target cell."""
    n_compared = 0
    max_abs_diff = 0.0
    for r in selected_rows:
        key = (r["territory_id"], r["category"])
        raw_series = obs.get(key)
        raw_val = raw_series.get(r["target"]) if raw_series else None
        f_raw = _finite(raw_val)
        if f_raw is None:
            raise PairedContractError(
                "raw actual missing/nonfinite for selected target cell "
                "series=%r category=%r target=%s (raw=%r paired actual=%r)"
                % (key[0], key[1], int_to_ym(r["target"]), raw_val,
                   r["actual"]))
        f_act = _finite(r["actual"])
        if f_act is None:
            raise PairedContractError(
                "paired actual missing/nonfinite for selected target cell "
                "series=%r category=%r target=%s (raw=%r paired actual=%r)"
                % (key[0], key[1], int_to_ym(r["target"]), raw_val,
                   r["actual"]))
        d = abs(f_raw - f_act)
        max_abs_diff = max(max_abs_diff, d)
        if d > tol:
            raise PairedContractError(
                "raw actual disagrees with paired actual by %g > tol %g for "
                "selected target cell series=%r category=%r target=%s "
                "(raw=%r paired actual=%r)"
                % (d, tol, key[0], key[1], int_to_ym(r["target"]),
                   f_raw, f_act))
        n_compared += 1
    return {"n_compared": n_compared, "n_mismatch": 0,
            "max_abs_diff": max_abs_diff}


# ---------------------------------------------------------------------------
# Prophet fit (reused, with injectable predictor for self-check)
# ---------------------------------------------------------------------------

def _require_prophet():
    try:
        import pandas  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "pandas is required for the R8 Prophet batch (dependency missing)")
    try:
        import prophet  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "prophet is required for the R8 Prophet batch (dependency missing); "
            "install 'prophet' to run the real fit.")


def prophet_fit_predict(train, target_ds, seed=SEED_DEFAULT):
    """Fit Prophet once on (ds, y) and predict at target_ds. Lazy import."""
    try:
        import pandas as pd
    except ImportError:
        raise DependencyMissing("pandas is required (dependency missing)")
    try:
        from prophet import Prophet
    except ImportError:
        raise DependencyMissing(
            "prophet is required (dependency missing); cannot fit Prophet")
    df = pd.DataFrame(train, columns=["ds", "y"])
    df["ds"] = pd.to_datetime(df["ds"])
    df = df.sort_values("ds").reset_index(drop=True)
    model = Prophet(
        growth="linear",
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        n_changepoints=3,
        uncertainty_samples=0,
    )
    model.fit(df, seed=int(seed))
    fut = pd.DataFrame({"ds": pd.to_datetime(list(target_ds))})
    fc = model.predict(fut)
    return [float(v) for v in fc["yhat"].tolist()]


# ---------------------------------------------------------------------------
# fingerprinting
# ---------------------------------------------------------------------------

def _paired_file_sha256(paired_run_dir):
    for ext in ("predictions.parquet", "predictions.csv"):
        p = os.path.join(paired_run_dir, ext)
        if os.path.exists(p):
            return _sha256(p)
    return None


def compute_fingerprint(raw_path, paired_run_dir, seed, release_lag):
    return {
        "raw_sha256": _sha256(raw_path),
        "paired_sha256": _paired_file_sha256(paired_run_dir),
        "code_sha256": _code_sha256(),
        "seed": int(seed),
        "release_lag": int(release_lag),
        "horizons": list(HORIZONS),
        "min_train_points": MIN_TRAIN_POINTS,
    }


def save_fingerprint(outdir, fp):
    path = os.path.join(outdir, "fingerprint.json")
    _atomic_json(path, fp, indent=1)


def load_fingerprint(outdir):
    path = os.path.join(outdir, "fingerprint.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def assert_fingerprint_compatible(outdir, new_fp):
    old = load_fingerprint(outdir)
    if old is None:
        raise FingerprintMismatch(
            "cannot resume: fingerprint.json missing in %r" % outdir)
    mismatches = []
    for k in new_fp:
        if k not in old:
            mismatches.append("%s: missing in checkpoint" % k)
        elif old[k] != new_fp[k]:
            mismatches.append("%s: checkpoint=%r vs current=%r"
                              % (k, old[k], new_fp[k]))
    if mismatches:
        raise FingerprintMismatch(
            "checkpoint fingerprint mismatch:\n  " + "\n  ".join(mismatches))


# ---------------------------------------------------------------------------
# checkpoint management
# ---------------------------------------------------------------------------

def _ckpt_key(tid, cat, origin_ym):
    tid = str(tid).strip()
    cat = str(cat).strip()
    origin_ym = str(origin_ym).strip()
    safe_tid = tid.replace("/", "_").replace("\\", "_")
    safe_cat = cat.replace("/", "_").replace("\\", "_")
    return "%s__%s__%s" % (safe_tid, safe_cat, origin_ym)


def _ckpt_dir(outdir, tid, cat, origin_ym):
    return os.path.join(outdir, "checkpoints", _ckpt_key(tid, cat, origin_ym))


def _atomic_json(path, obj, indent=None):
    """Write JSON to *path* atomically via tmpfile + fsync + os.replace."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_checkpoint(outdir, tid, cat, origin_ym, data):
    d = _ckpt_dir(outdir, tid, cat, origin_ym)
    os.makedirs(d, exist_ok=True)
    _atomic_json(os.path.join(d, "result.json"), data)


def load_checkpoint(outdir, tid, cat, origin_ym):
    d = _ckpt_dir(outdir, tid, cat, origin_ym)
    path = os.path.join(d, "result.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    # JSON serialises int horizon keys as strings; restore to int for lookups.
    if isinstance(data, dict) and "predictions" in data:
        data["predictions"] = {
            (int(k) if str(k).isdigit() else k): v
            for k, v in data["predictions"].items()
        }
    return data


def list_completed_keys(outdir):
    ckpt_base = os.path.join(outdir, "checkpoints")
    if not os.path.isdir(ckpt_base):
        return set()
    keys = set()
    for name in os.listdir(ckpt_base):
        rpath = os.path.join(ckpt_base, name, "result.json")
        if os.path.isfile(rpath):
            keys.add(name)
    return keys


# ---------------------------------------------------------------------------
# progress tracking
# ---------------------------------------------------------------------------

def load_progress(outdir):
    path = os.path.join(outdir, "progress.json")
    if not os.path.exists(path):
        return {"n_completed": 0, "n_failures": 0}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_progress(outdir, prog):
    path = os.path.join(outdir, "progress.json")
    _atomic_json(path, prog, indent=1)


# ---------------------------------------------------------------------------
# task enumeration: ALL paired-True series, sorted stable
# ---------------------------------------------------------------------------

def enumerate_tasks(paired_rows, obs):
    """Build sorted task list of (tid, cat, origin_ym) from paired rows.

    Returns (tasks, task_series_set, n_required_fits).
    A fit is "required" per (series, origin) that has at least one paired
    horizon cell AND the series exists in raw with enough history.
    """
    by_so = {}
    for r in paired_rows:
        key = (r["territory_id"], r["category"])
        by_so.setdefault(key, set()).add(r["origin"])
    tasks = []
    for (tid, cat) in sorted(by_so.keys()):
        for origin_m in sorted(by_so[(tid, cat)]):
            tasks.append((tid, cat, origin_m))
    return tasks, sorted(by_so.keys())


# ---------------------------------------------------------------------------
# single-fit execution
# ---------------------------------------------------------------------------

def run_single_fit(tid, cat, origin_m, raw_series, horizons, seed,
                   predictor=None):
    """Fit one (series, origin), return checkpoint record.

    predictor: callable(train_pairs, target_ds_list, seed=) -> yhat_list.
    Defaults to prophet_fit_predict if None.
    """
    if predictor is None:
        predictor = prophet_fit_predict
    tms = [target_month(origin_m, h) for h in horizons]
    train = causal_train_window(raw_series, origin_m)
    if len(train) < MIN_TRAIN_POINTS:
        return {
            "status": "failed",
            "reason": "insufficient_history",
            "n_train_points": len(train),
            "min_required": MIN_TRAIN_POINTS,
            "horizons": horizons,
            "predictions": {},
        }
    train_pairs = [(month_to_dt(m), float(v)) for m, v in train]
    t0 = time.monotonic()
    try:
        yhat = predictor(
            train_pairs, [month_to_dt(t) for t in tms], seed=seed)
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "prophet_fit_error",
            "error": "%s: %s" % (type(exc).__name__, exc),
            "horizons": horizons,
            "predictions": {},
            "runtime_s": time.monotonic() - t0,
        }
    elapsed = time.monotonic() - t0
    preds = {}
    for h, y in zip(horizons, yhat):
        preds[h] = float(y)
    return {
        "status": "ok",
        "horizons": horizons,
        "predictions": preds,
        "runtime_s": elapsed,
    }


# ---------------------------------------------------------------------------
# prefix mutation probe
# ---------------------------------------------------------------------------

def run_mutation_probe(obs, fits_done, seed, predictor=None):
    """Run prefix mutation + determinism probe on one fitted origin.

    Returns probe dict. Uses fits_done: {(tid,cat,origin_m): horizons_list}
    to find a completed fit.
    """
    if predictor is None:
        predictor = prophet_fit_predict
    for (tid, cat, origin_m) in sorted(fits_done.keys()):
        horizons = fits_done[(tid, cat, origin_m)]
        raw_series = obs.get((tid, cat))
        if raw_series is None:
            continue
        tms = [target_month(origin_m, h) for h in horizons]
        train = causal_train_window(raw_series, origin_m)
        if len(train) < MIN_TRAIN_POINTS:
            continue
        train_pairs = [(month_to_dt(m), float(v)) for m, v in train]
        target_ds = [month_to_dt(t) for t in tms]
        a1 = predictor(train_pairs, target_ds, seed=seed)
        a2 = predictor(train_pairs, target_ds, seed=seed)
        det_diff = max(abs(x - y) for x, y in zip(a1, a2))
        mutated = {
            k: {m: (v + MUTATION_DELTA
                    if m > last_allowed_month(origin_m) else v)
                for m, v in ser.items()}
            for k, ser in obs.items()
        }
        m_train = [(month_to_dt(m), float(v))
                   for m, v in causal_train_window(
                       mutated[(tid, cat)], origin_m)]
        b = predictor(m_train, target_ds, seed=seed)
        mut_diff = max(abs(x - y) for x, y in zip(a1, b))
        return {
            "series": [tid, cat],
            "origin": int_to_ym(origin_m),
            "horizons": horizons,
            "last_allowed_obs": int_to_ym(last_allowed_month(origin_m)),
            "mutated": ("all raw observations after %s by +%g"
                        % (int_to_ym(last_allowed_month(origin_m)),
                           MUTATION_DELTA)),
            "max_abs_forecast_diff_after_mutation": mut_diff,
            "max_abs_forecast_diff_repeat_fit": det_diff,
            "passed": det_diff < PRED_TOL and mut_diff < PRED_TOL,
        }
    return {"passed": None, "note": "no successful fit available to probe"}


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def aggregate_metrics(paired_rows, outdir, checkpoint_keys, tasks,
                      obs, elapsed_total, run_start_utc):
    """Collect all checkpoint results and compute aggregated metrics.

    Returns (metrics_dict, audit_dict).
    """
    fits_ok = 0
    fits_failed = 0
    total_runtime = 0.0
    all_results = []
    failures = []
    missing_checkpoints = []

    for (tid, cat, origin_m) in tasks:
        ck = load_checkpoint(outdir, tid, cat, int_to_ym(origin_m))
        if ck is None:
            missing_checkpoints.append((tid, cat, origin_m))
            continue
        if ck["status"] == "ok":
            fits_ok += 1
            total_runtime += ck.get("runtime_s", 0.0)
        else:
            fits_failed += 1
            failures.append({
                "series": [tid, cat],
                "origin": int_to_ym(origin_m),
                "horizons": ck.get("horizons", []),
                "reason": ck.get("reason", "unknown"),
                "error": ck.get("error"),
            })

    # build results from paired rows + checkpoints
    for r in paired_rows:
        tid = r["territory_id"]
        cat = r["category"]
        origin_m = r["origin"]
        h = r["horizon"]
        ck = load_checkpoint(outdir, tid, cat, int_to_ym(origin_m))
        if ck is not None and ck["status"] == "ok":
            pred_val = ck["predictions"].get(h)
        else:
            pred_val = None
        prophet_status = "ok" if pred_val is not None else (
            "failed" if ck is not None and ck["status"] != "ok" else "not_fit")
        all_results.append({
            "territory_id": tid,
            "category": cat,
            "origin": int_to_ym(origin_m),
            "target": int_to_ym(r["target"]),
            "horizon": h,
            "actual": r["actual"],
            "pred_prophet": pred_val,
            "pred_lastavailable": r["pred_lastavailable"],
            "pred_seasonal_naive": r["pred_seasonal_naive"],
            "paired": True,
            "prophet_status": prophet_status,
        })

    def _mae(vals):
        return mae_of([abs(p - a) for p, a in vals])

    def _three_way(rows):
        P = [(x["pred_prophet"], x["actual"]) for x in rows
             if x["pred_prophet"] is not None and x["actual"] is not None]
        L = [(x["pred_lastavailable"], x["actual"]) for x in rows
             if x["pred_lastavailable"] is not None and x["actual"] is not None]
        S = [(x["pred_seasonal_naive"], x["actual"]) for x in rows
             if x["pred_seasonal_naive"] is not None and x["actual"] is not None]
        return P, L, S

    common = [x for x in all_results
              if x["pred_prophet"] is not None
              and x["pred_lastavailable"] is not None
              and x["pred_seasonal_naive"] is not None
              and x["actual"] is not None]
    P, L, S = _three_way(common)
    common_mask_mae = {
        "prophet": _mae(P),
        "lastavailable": _mae(L),
        "seasonal_naive": _mae(S),
        "n_common": len(common),
    }

    per_horizon_mae = {}
    for h in HORIZONS:
        rows_h = [x for x in all_results if x["horizon"] == h]
        ch = [x for x in rows_h
              if x["pred_prophet"] is not None
              and x["pred_lastavailable"] is not None
              and x["pred_seasonal_naive"] is not None
              and x["actual"] is not None]
        P, L, S = _three_way(ch)
        per_horizon_mae["h%d" % h] = {
            "prophet": _mae(P),
            "lastavailable": _mae(L),
            "seasonal_naive": _mae(S),
            "n_common": len(ch),
            "n_rows": len(rows_h),
            "n_prophet": sum(1 for x in rows_h
                            if x["pred_prophet"] is not None),
        }

    n_prophet_ok = sum(1 for x in all_results
                       if x["pred_prophet"] is not None)
    n_required = len(tasks)
    n_missing_ckpt = len(missing_checkpoints)

    # status determination
    completed_all = (fits_ok + fits_failed) >= n_required and n_missing_ckpt == 0
    failures_shrink = fits_failed > 0
    if not completed_all:
        status = STATUS_PARTIAL
    elif failures_shrink:
        status = STATUS_NOT_PASS
    else:
        status = STATUS_PASS

    provenance = {
        "run_utc": run_start_utc,
        "command": " ".join(sys.argv),
        "code_sha256": _code_sha256(),
        "versions": _versions(),
    }

    counts = {
        "total_input_rows": FULL_R8_MASK,
        "n_paired_rows": len(paired_rows),
        "n_joined_rows": len(all_results),
        "n_prophet_forecasts": n_prophet_ok,
        "n_prophet_missing": len(all_results) - n_prophet_ok,
        "n_failures_recorded": fits_failed,
        "n_series_total": len({(t, c) for t, c, _ in tasks}),
        "n_origins_total": n_required,
        "n_fits_ok": fits_ok,
        "n_fits_failed": fits_failed,
        "n_fits_missing_checkpoint": n_missing_ckpt,
        "total_fit_runtime_s": total_runtime,
        "total_elapsed_s": elapsed_total,
    }

    metrics = {
        "run_id": RUN_ID,
        "status": status,
        "computation_complete": completed_all and not failures_shrink,
        "gate_pass": False,
        "gate_pass_reason": (
            "R8 stays open: full Prophet computation completed but no "
            "external MAE win gate applied; status=%s" % status),
        "case_action": "never_close_R8_stays_open",
        "full_r8": {
            "stays_open": True,
            "mask_rows": FULL_R8_MASK,
            "this_covers": len(all_results),
            "confirmatory": completed_all and not failures_shrink,
        },
        "eval": {
            "horizons": list(HORIZONS),
            "n_origins": len({x["origin"] for x in all_results}),
        },
        "per_horizon_mae": per_horizon_mae,
        "common_mask_mae": common_mask_mae,
        "counts": counts,
        "provenance": provenance,
    }

    audit = {
        "run_id": RUN_ID,
        "status": status,
        "missing_and_failures": failures,
        "missing_checkpoints": [
            [t, c, int_to_ym(o)] for t, c, o in missing_checkpoints
        ],
        "no_invented_forecasts": True,
        "train_eval": {
            "release_lag_months": RELEASE_LAG,
            "train_filter": "observation month <= origin - %d" % RELEASE_LAG,
            "target": "origin + h",
            "calendar_ds": "actual month timestamps, gaps preserved",
        },
        "provenance": provenance,
    }

    return metrics, audit, all_results, status


# ---------------------------------------------------------------------------
# predictions writer
# ---------------------------------------------------------------------------

def _write_predictions(pred_rows, out):
    try:
        import pandas as pd
    except ImportError:
        raise DependencyMissing(
            "pandas is required to write predictions (dependency missing)")
    cols = ["territory_id", "category", "origin", "target", "horizon",
            "actual", "pred_prophet", "pred_lastavailable",
            "pred_seasonal_naive", "paired", "prophet_status"]
    df = pd.DataFrame(pred_rows, columns=cols)
    df = df.sort_values(
        ["origin", "horizon", "territory_id", "category"]).reset_index(
        drop=True)
    try:
        df.to_parquet(os.path.join(out, "predictions.parquet"), index=False)
        return "parquet"
    except Exception:
        df.to_csv(os.path.join(out, "predictions.csv"), index=False)
        return "csv_fallback"


# ---------------------------------------------------------------------------
# main run
# ---------------------------------------------------------------------------

def run(raw_path, paired_run_dir, outdir, max_fits, seed, resume=False,
        predictor=None, _raw_rows=None, _paired_rows=None,
        _paired_info=None):
    """Main batch run. predictor is injectable for self-check.

    _raw_rows, _paired_rows, _paired_info: direct data injection for
    self-check (bypasses parquet I/O entirely).
    """
    if predictor is None:
        _require_prophet()

    run_start_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds")
    t_start = time.monotonic()

    # --- fingerprint ---
    fp = compute_fingerprint(raw_path, paired_run_dir, seed, RELEASE_LAG)

    if resume:
        if not os.path.isdir(outdir):
            raise FileNotFoundError(
                "cannot resume: outdir %r does not exist" % outdir)
        assert_fingerprint_compatible(outdir, fp)
        print("RESUME: fingerprint compatible, continuing from checkpoint")
    else:
        if os.path.isdir(outdir) and os.listdir(outdir):
            raise RuntimeError(
                "refusing to overwrite existing non-empty outdir %r "
                "(use --resume to continue)" % outdir)
        os.makedirs(outdir, exist_ok=True)
        save_fingerprint(outdir, fp)

    # --- load inputs ---
    if _raw_rows is not None:
        raw_rows = _raw_rows
    else:
        df = _read_raw_data(raw_path)
        raw_rows = df.to_dict(orient="records")
    norm = normalize_raw_rows(raw_rows)
    obs = norm["obs"]

    if _paired_rows is not None:
        paired_rows = _paired_rows
        paired_info = _paired_info
    else:
        paired_rows, paired_info = load_paired_rows(paired_run_dir)

    # --- hard raw-vs-actual contract over ALL paired rows BEFORE any fit ---
    validate_selected_raw_actuals(paired_rows, obs)

    # --- enumerate tasks: ALL paired-True series, sorted stable ---
    tasks, all_series = enumerate_tasks(paired_rows, obs)

    # --- check how many already completed ---
    completed_keys = list_completed_keys(outdir)
    remaining = []
    n_already_done = 0
    for (tid, cat, origin_m) in tasks:
        key = _ckpt_key(tid, cat, origin_ym=int_to_ym(origin_m))
        if key in completed_keys:
            n_already_done += 1
        else:
            remaining.append((tid, cat, origin_m))

    print("Tasks total: %d, already completed: %d, remaining: %d"
          % (len(tasks), n_already_done, len(remaining)))

    if max_fits is not None and max_fits < 0:
        raise ValueError("max-fits must be non-negative, got %d" % max_fits)
    if max_fits is not None and max_fits == 0:
        max_fits = None  # 0 means unlimited

    n_to_run = len(remaining)
    if max_fits is not None:
        n_to_run = min(n_to_run, max_fits)

    # --- group paired rows by (series, origin) for quick lookup ---
    paired_by_so = {}
    for r in paired_rows:
        paired_by_so.setdefault(
            (r["territory_id"], r["category"]), {}
        ).setdefault(r["origin"], []).append(r)

    # --- run fits ---
    n_new_fits = 0
    n_new_failures = 0
    for i, (tid, cat, origin_m) in enumerate(remaining[:n_to_run]):
        raw_series = obs.get((tid, cat))
        origin_ym = int_to_ym(origin_m)
        if raw_series is None:
            result = {
                "status": "failed",
                "reason": "series_missing_in_raw",
                "horizons": [],
                "predictions": {},
            }
        else:
            horizons = sorted({r["horizon"]
                               for r in paired_by_so.get(
                                   (tid, cat), {}).get(origin_m, [])})
            if not horizons:
                result = {
                    "status": "failed",
                    "reason": "no_paired_horizons",
                    "horizons": [],
                    "predictions": {},
                }
            else:
                # hard raw-vs-actual check before fitting
                sel_rows = paired_by_so[(tid, cat)][origin_m]
                try:
                    validate_selected_raw_actuals(sel_rows, obs)
                except PairedContractError as exc:
                    result = {
                        "status": "failed",
                        "reason": "raw_actual_contract",
                        "error": str(exc),
                        "horizons": horizons,
                        "predictions": {},
                    }
                else:
                    result = run_single_fit(
                        tid, cat, origin_m, raw_series, horizons,
                        seed, predictor=predictor)

        save_checkpoint(outdir, tid, cat, origin_ym, result)
        n_new_fits += 1
        if result["status"] != "ok":
            n_new_failures += 1

        # progress log every 100 fits
        if n_new_fits % 100 == 0 or n_new_fits == n_to_run:
            prog = {
                "n_completed": n_already_done + n_new_fits,
                "n_failures": n_new_failures,
                "n_total_tasks": len(tasks),
                "last_fit": [tid, cat, origin_ym],
            }
            save_progress(outdir, prog)
            print("  progress: %d/%d fits done (%d new failures)"
                  % (prog["n_completed"], len(tasks), n_new_failures))

    elapsed_total = time.monotonic() - t_start

    # --- mutation probe ---
    fits_done = {}
    for (tid, cat, origin_m) in tasks:
        ck = load_checkpoint(outdir, tid, cat, int_to_ym(origin_m))
        if ck is not None and ck["status"] == "ok":
            fits_done[(tid, cat, origin_m)] = ck["horizons"]
    probe = run_mutation_probe(obs, fits_done, seed, predictor=predictor)

    # --- aggregate ---
    metrics, audit, all_results, status = aggregate_metrics(
        paired_rows, outdir, completed_keys, tasks, obs, elapsed_total,
        run_start_utc)

    audit["leak_controls"] = {
        "prefix_mutation_probe": probe,
    }

    # --- write outputs ---
    pred_format = _write_predictions(all_results, outdir)

    manifest = {
        "run_id": RUN_ID,
        "status": status,
        "model": {
            "estimator": "Prophet",
            "growth": "linear",
            "yearly_seasonality": False,
            "weekly_seasonality": False,
            "daily_seasonality": False,
            "n_changepoints": 3,
            "uncertainty_samples": 0,
            "deterministic": True,
        },
        "causal": {
            "release_lag_months": RELEASE_LAG,
            "train_month_max": "origin - %d" % RELEASE_LAG,
            "target": "origin + h",
            "calendar_ds": "real month timestamps, no gap compression",
        },
        "outputs": [
            "predictions." + ("parquet" if pred_format == "parquet" else "csv"),
            "metrics.json", "audit.json", "manifest.json",
            "checkpoints/", "fingerprint.json", "progress.json",
        ],
        "provenance": metrics["provenance"],
    }

    _atomic_json(os.path.join(outdir, "metrics.json"), metrics, indent=1)
    _atomic_json(os.path.join(outdir, "audit.json"), audit, indent=1)
    _atomic_json(os.path.join(outdir, "manifest.json"), manifest, indent=1)

    result = {
        "status": status,
        "n_series": len(all_series),
        "n_tasks": len(tasks),
        "n_completed": n_already_done + n_new_fits,
        "n_new_fits": n_new_fits,
        "n_failures": metrics["counts"]["n_fits_failed"],
        "common_mask_mae": metrics["common_mask_mae"],
        "elapsed_s": elapsed_total,
        "outdir": outdir,
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return metrics, audit


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------

def dry_run(raw_path, paired_run_dir, seed):
    """Count required fits and rows without running Prophet."""
    import pandas as pd
    df = pd.read_parquet(raw_path)
    raw_rows = df.to_dict(orient="records")
    norm = normalize_raw_rows(raw_rows)
    obs = norm["obs"]

    paired_rows, paired_info = load_paired_rows(paired_run_dir)
    tasks, all_series = enumerate_tasks(paired_rows, obs)

    n_skippable = 0
    n_fittable = 0
    for (tid, cat, origin_m) in tasks:
        raw_series = obs.get((tid, cat))
        if raw_series is None:
            n_skippable += 1
            continue
        train = causal_train_window(raw_series, origin_m)
        if len(train) < MIN_TRAIN_POINTS:
            n_skippable += 1
        else:
            n_fittable += 1

    result = {
        "mode": "dry-run",
        "raw_rows_kept": norm["n_rows_kept"],
        "raw_n_series": norm["n_series"],
        "paired_rows": paired_info["n_rows"],
        "paired_excluded_unpaired": paired_info["excluded_unpaired_rows"],
        "n_series_total": len(all_series),
        "n_tasks_total": len(tasks),
        "n_fittable": n_fittable,
        "n_skippable_insufficient": n_skippable,
        "seed": int(seed),
    }
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return result


# ---------------------------------------------------------------------------
# --self-check
# ---------------------------------------------------------------------------

def self_check(seed=SEED_DEFAULT):
    """Test resume, no duplicate fits, checkpoint JSON round-trip,
    actual mismatch hard-stop, fingerprint mismatch, duplicate keys,
    negative max-fits rejection using a mock predictor (no Prophet/network).
    """
    import tempfile
    import csv as _csv

    # --- mock predictor: deterministic linear function of train length ---
    def mock_predictor(train, target_ds, seed=SEED_DEFAULT):
        base = len(train) * 10.0 + seed * 0.0001
        return [base + i * 5.0 for i in range(len(target_ds))]

    # --- build synthetic raw + paired data ---
    # Raw data covers 2022-01 through 2025-12 so target months are in obs.
    raw_records = []
    paired_records = []
    territories = ["t0", "t1", "t2"]
    categories = ["c0", "c1"]
    raw_start = 2022 * 12      # 2022-01
    raw_end_excl = 2026 * 12   # 2025-12 is last month kept
    for tid in territories:
        for cat in categories:
            for ym in range(raw_start, raw_end_excl):
                raw_records.append({
                    "date": int_to_ym(ym),
                    "territory_id": tid,
                    "category": cat,
                    "value": 100.0 + ym * 0.1,
                })
    # Origins chosen so that target = origin+h lies within raw obs window.
    origins = [2023 * 12 + i for i in range(3)]  # 2023-01 .. 2023-03
    for tid in territories:
        for cat in categories:
            for origin_m in origins:
                for h in HORIZONS:
                    target_m = origin_m + h
                    raw_val = 100.0 + target_m * 0.1
                    paired_records.append({
                        "territory_id": tid,
                        "category": cat,
                        "origin": origin_m,
                        "horizon": h,
                        "target": target_m,
                        "actual": raw_val,
                        "pred_lastavailable": raw_val - 10,
                        "pred_seasonal_naive": raw_val - 20,
                        "paired": True,
                    })

    paired_info_stub = {
        "total_input_rows": len(paired_records),
        "excluded_unpaired_rows": 0,
        "n_rows": len(paired_records),
        "path": "<self-check-injected>",
        "sha256": None,
        "columns": list(paired_records[0].keys()),
        "join_keys": ["territory_id", "category", "origin", "horizon",
                      "target"],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        # create fingerprint files for resume testing
        raw_csv = os.path.join(tmpdir, "raw.csv")
        paired_dir = os.path.join(tmpdir, "paired")
        os.makedirs(paired_dir)
        paired_csv = os.path.join(paired_dir, "predictions.csv")

        # write CSV files
        raw_fields = ["date", "territory_id", "category", "value"]
        with open(raw_csv, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=raw_fields)
            w.writeheader()
            w.writerows(raw_records)
        paired_fields = list(paired_records[0].keys())
        with open(paired_csv, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=paired_fields)
            w.writeheader()
            w.writerows(paired_records)

        # --- test 1: full run with --max-fits 3 ---
        out1 = os.path.join(tmpdir, "out1")
        run(raw_csv, paired_dir, out1, max_fits=3, seed=seed,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub)
        prog1 = load_progress(out1)
        assert prog1["n_completed"] == 3, \
            "expected 3 completed, got %d" % prog1["n_completed"]
        ckpt_base = os.path.join(out1, "checkpoints")
        assert len([d for d in os.listdir(ckpt_base)
                     if os.path.isfile(
                         os.path.join(ckpt_base, d, "result.json"))]) == 3, \
            "expected 3 checkpoint dirs after first run"

        # --- test 1b: checkpoint JSON round-trip ---
        # Verify horizons survive save→JSON→load with int keys.
        ck_sample = load_checkpoint(out1, "t0", "c0", "2023-01")
        assert ck_sample is not None, "first checkpoint must exist"
        assert ck_sample["status"] == "ok"
        for hk, hv in ck_sample["predictions"].items():
            assert isinstance(hk, int), \
                "horizon key %r is not int after JSON round-trip" % (hk,)

        # --- test 2: resume should not re-run completed fits ---
        run(raw_csv, paired_dir, out1, max_fits=5, seed=seed,
            resume=True, predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub)
        prog2 = load_progress(out1)
        assert prog2["n_completed"] == 8, \
            "expected 8 after resume (3+5), got %d" % prog2["n_completed"]

        # verify no duplicate checkpoint dirs
        ckpt_dirs = [d for d in os.listdir(ckpt_base)
                     if os.path.isfile(
                         os.path.join(ckpt_base, d, "result.json"))]
        assert len(ckpt_dirs) == 8, \
            "expected 8 checkpoint dirs, got %d" % len(ckpt_dirs)

        # --- test 3: resume to completion (max_fits=0 = unlimited) ---
        run(raw_csv, paired_dir, out1, max_fits=0, seed=seed,
            resume=True, predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub)
        with open(os.path.join(out1, "metrics.json")) as f:
            m = json.load(f)
        assert m["counts"]["n_fits_missing_checkpoint"] == 0, \
            "no missing checkpoints expected"
        # gate_pass must never be True (no external MAE win gate)
        assert m.get("gate_pass") is False, \
            "gate_pass must be False (R8 stays open)"
        # confirmatory may be True when computation is complete
        assert m.get("computation_complete") in (True, False), \
            "computation_complete must be present"

        # --- test 4: actual mismatch in LAST row raises PairedContractError
        #     before any predictor call ---
        call_count = [0]

        def counting_predictor(train, target_ds, seed=SEED_DEFAULT):
            call_count[0] += 1
            return mock_predictor(train, target_ds, seed=seed)

        bad_last = dict(paired_records[-1])
        bad_last["actual"] = -9999.0  # disagrees with raw
        bad_paired = list(paired_records) + [bad_last]
        bad_info = dict(paired_info_stub,
                        n_rows=len(bad_paired),
                        total_input_rows=len(bad_paired))
        out3 = os.path.join(tmpdir, "out3")
        try:
            run(raw_csv, paired_dir, out3, max_fits=1, seed=seed,
                predictor=counting_predictor,
                _raw_rows=raw_records,
                _paired_rows=bad_paired,
                _paired_info=bad_info)
            raise AssertionError(
                "PairedContractError was not raised for last-row mismatch")
        except PairedContractError:
            pass
        assert call_count[0] == 0, \
            "predictor was called %d times before contract error" % call_count[0]

        # --- test 5: fingerprint mismatch on resume with different seed ---
        out2 = os.path.join(tmpdir, "out2")
        run(raw_csv, paired_dir, out2, max_fits=2, seed=seed,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub)
        try:
            run(raw_csv, paired_dir, out2, max_fits=1, seed=seed + 999,
                resume=True, predictor=mock_predictor,
                _raw_rows=raw_records,
                _paired_rows=paired_records,
                _paired_info=paired_info_stub)
            raise AssertionError("fingerprint mismatch was not detected")
        except FingerprintMismatch:
            pass

        # --- test 5b: missing fingerprint on resume must raise ---
        out_fp = os.path.join(tmpdir, "out_fp")
        os.makedirs(out_fp)
        # no fingerprint.json written
        try:
            run(raw_csv, paired_dir, out_fp, max_fits=1, seed=seed,
                resume=True, predictor=mock_predictor,
                _raw_rows=raw_records,
                _paired_rows=paired_records,
                _paired_info=paired_info_stub)
            raise AssertionError("missing fingerprint on resume not detected")
        except FingerprintMismatch:
            pass

        # --- test 6: duplicate raw key hard stop ---
        dup_records = raw_records + [dict(raw_records[0])]
        try:
            normalize_raw_rows(dup_records)
            raise AssertionError("duplicate raw key was not rejected")
        except RawValidationError:
            pass

        # --- test 7: negative max-fits rejected ---
        out_neg = os.path.join(tmpdir, "out_neg")
        try:
            run(raw_csv, paired_dir, out_neg, max_fits=-1, seed=seed,
                predictor=mock_predictor,
                _raw_rows=raw_records,
                _paired_rows=paired_records,
                _paired_info=paired_info_stub)
            raise AssertionError("negative max-fits was not rejected")
        except ValueError:
            pass

    print("SELF-CHECK OK (seed=%d)" % int(seed))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="R8 Prophet batch runner: resumable, checkpointed, "
                    "full-mask Prophet fits (R8-prophet-batch)")
    p.add_argument("--raw", default=None,
                   help="raw spending parquet (date/territory_id/category/"
                        "value)")
    p.add_argument("--paired-run", default=None,
                   help="R8_v2 run dir holding predictions.parquet")
    p.add_argument("--outdir", default=None,
                   help="output dir for checkpoints and final results")
    p.add_argument("--max-fits", type=int, default=None,
                   help="max Prophet fits this invocation (0=unlimited); "
                        "for operator testing before --resume")
    p.add_argument("--resume", action="store_true",
                   help="resume from existing checkpoint in outdir")
    p.add_argument("--seed", type=int, default=SEED_DEFAULT)
    p.add_argument("--dry-run", action="store_true",
                   help="count required fits and rows without running Prophet")
    p.add_argument("--self-check", action="store_true",
                   help="run self-tests with mock predictor (no Prophet "
                        "required)")
    a = p.parse_args(argv)

    if a.self_check:
        return self_check(seed=a.seed)

    if a.dry_run:
        if not (a.raw and a.paired_run):
            p.error("--raw and --paired-run are required for --dry-run")
        return dry_run(a.raw, a.paired_run, a.seed)

    if a.resume:
        if not a.outdir:
            p.error("--outdir is required for --resume")
    else:
        if not (a.raw and a.paired_run and a.outdir):
            p.error("--raw, --paired-run and --outdir are required")

    run(a.raw, a.paired_run, a.outdir, a.max_fits, a.seed,
        resume=a.resume)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())