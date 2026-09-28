"""R8 TSFM paired-evaluation runner: Chronos-T5-tiny zero-shot on the 171150-point
Prophet mask, with resumable checkpoints, deterministic resume, and audit.

Key properties:
  - Same 171150-point key mask (territory_id, category, origin, horizon, target)
    as R8_prophet_full_20260927/predictions.parquet.
  - Same actuals, same 2-month release-lag training cutoff.
  - Zero-shot Chronos-T5-tiny (frozen weights, no training on target/future).
  - Atomic per-(series, origin) checkpoints; deterministic resume never re-runs.
  - Failed/missing predictions preserved as failures; never invented or dropped.
  - MAE comparison to Prophet and lastavailable on common successful mask.
  - Future-mutation negative control: mutating future inputs does not change
    past predictions (verifies no data leakage).
  - Manifest records weight revision, input/code SHA256, versions, device,
    runtime, failures, future-mutation control, exact command.

Usage:
  python r8_tsfm_paired.py --raw <raw.parquet> \\
      --paired-run <R8_prophet_full_dir> \\
      --outdir <empty_dir> \\
      --model-revision <rev> [--device cpu|mps|cuda] [--batch-size 64] \\
      [--max-series 0] [--resume]
  python r8_tsfm_paired.py --resume --outdir <existing_dir>
  python r8_tsfm_paired.py --self-check
"""

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import random as _py_random
import sys
import time

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

RUN_ID = "R8-tsfm-paired"
STATUS_PARTIAL = "PARTIAL"
STATUS_PASS = "PASS"
STATUS_NOT_PASS = "NOT_PASS"
DEFAULT_MODEL_ID = "amazon/chronos-t5-tiny"
DEFAULT_MODEL_REVISION = "main"
RELEASE_LAG = 2
HORIZONS = (1, 2, 3)
MIN_TRAIN_POINTS = 6
FULL_R8_MASK = 171150
PRED_TOL = 1e-9
MUTATION_DELTA = 1e6
DEFAULT_BATCH_SIZE = 64
DEFAULT_DEVICE = "cpu"
DEFAULT_SEED = 20260928
PROBE_SEED = 42

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


def _batch_seed(global_seed, batch_index):
    """Derive a deterministic 32-bit seed from global seed + batch index."""
    payload = ("%d:%d" % (global_seed, batch_index)).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:4], "big")


def _versions():
    v = {"python": sys.version.split()[0]}
    for mod in ("numpy", "pandas", "pyarrow", "torch", "chronos",
                "transformers"):
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
# raw handling (same contract as r8_prophet_batch)
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
# paired input (same contract as r8_prophet_batch)
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
            "pred_prophet": _finite(r.get("pred_prophet")),
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
# fingerprinting
# ---------------------------------------------------------------------------

def _paired_file_sha256(paired_run_dir):
    if paired_run_dir is None:
        return None
    for ext in ("predictions.parquet", "predictions.csv"):
        p = os.path.join(paired_run_dir, ext)
        if os.path.exists(p):
            return _sha256(p)
    return None


def compute_fingerprint(raw_path, paired_run_dir, model_id, model_revision,
                        device, release_lag, batch_size, seed):
    return {
        "raw_sha256": _sha256(raw_path),
        "paired_sha256": _paired_file_sha256(paired_run_dir),
        "code_sha256": _code_sha256(),
        "model_id": model_id,
        "model_revision": model_revision,
        "device": device,
        "release_lag": int(release_lag),
        "horizons": list(HORIZONS),
        "min_train_points": MIN_TRAIN_POINTS,
        "batch_size": int(batch_size),
        "seed": int(seed),
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
# task enumeration
# ---------------------------------------------------------------------------

def enumerate_tasks(paired_rows, obs):
    """Build sorted task list of (tid, cat, origin_ym) from paired rows."""
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
# Chronos zero-shot inference
# ---------------------------------------------------------------------------

def _require_chronos():
    try:
        import pandas  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "pandas is required for the R8 TSFM paired runner "
            "(dependency missing)")
    try:
        import torch  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "torch is required for the R8 TSFM paired runner "
            "(dependency missing)")
    try:
        from chronos import ChronosPipeline  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "chronos-forecasting is required for the R8 TSFM paired runner "
            "(dependency missing); pip install chronos-forecasting")


def load_chronos_pipeline(model_id, model_revision, device):
    """Load Chronos pipeline with pinned revision. Returns (pipeline, actual_revision)."""
    import torch
    from chronos import ChronosPipeline

    pipe = ChronosPipeline.from_pretrained(
        model_id,
        revision=model_revision,
        device_map=device,
        torch_dtype=torch.float32,
    )
    # Extract actual resolved revision from model config
    actual_rev = model_revision
    try:
        cfg = getattr(getattr(pipe, "model", None), "config", None)
        if cfg is not None:
            actual_rev = getattr(cfg, "_name_or_path", model_revision)
    except Exception:
        pass
    return pipe, actual_rev


def tsfm_predict_batch(pipe, contexts, max_horizon, device):
    """Run Chronos zero-shot prediction on a batch of context tensors.

    contexts: list of 1-D float tensors (variable-length histories)
    max_horizon: maximum horizon step to extract (typically 3)
    Returns: list of lists, each inner list has predictions for h=1..max_horizon
    """
    import torch

    if not contexts:
        return []

    with torch.no_grad():
        forecast = pipe.predict(contexts, prediction_length=max_horizon)

    # forecast shape: (batch, num_samples, prediction_length) for Chronos
    # We take the median across samples as point forecast
    fc_np = forecast.numpy()
    if fc_np.ndim == 3:
        # (batch, samples, horizon) -> median over samples -> (batch, horizon)
        import numpy as np
        med = np.median(fc_np, axis=1)
    elif fc_np.ndim == 2:
        med = fc_np
    else:
        import numpy as np
        med = fc_np.reshape(len(contexts), -1)[:, :max_horizon]

    results = []
    for row in med:
        preds = []
        for hi in range(max_horizon):
            if hi < len(row):
                preds.append(float(row[hi]))
            else:
                preds.append(None)
        results.append(preds)
    return results


# ---------------------------------------------------------------------------
# single-fit execution (one series x origin, multiple horizons)
# ---------------------------------------------------------------------------

def run_single_fit(tid, cat, origin_m, raw_series, horizons, pipe, device,
                   max_horizon, predictor=None):
    """Run zero-shot Chronos prediction for one (series, origin).

    Returns checkpoint record. predictor is injectable for self-check:
    callable(context_values, n_horizon) -> list[float] of length n_horizon.
    """
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

    context_vals = [float(v) for _, v in train]
    t0 = time.monotonic()
    try:
        if predictor is not None:
            yhat = predictor(context_vals, max_horizon)
        else:
            import torch
            ctx_tensor = torch.tensor(context_vals, dtype=torch.float32)
            results = tsfm_predict_batch(pipe, [ctx_tensor], max_horizon,
                                         device)
            yhat = results[0] if results else [None] * max_horizon
    except Exception as exc:
        return {
            "status": "failed",
            "reason": "tsfm_inference_error",
            "error": "%s: %s" % (type(exc).__name__, exc),
            "horizons": horizons,
            "predictions": {},
            "runtime_s": time.monotonic() - t0,
        }
    elapsed = time.monotonic() - t0
    preds = {}
    for h in horizons:
        # predictor returns values for horizons 1..max_horizon; index by h-1
        val = yhat[h - 1] if (h - 1) < len(yhat) else None
        if val is not None and math.isfinite(val):
            preds[h] = float(val)
        # else: missing prediction preserved as absent key
    has_missing = any(h not in preds for h in horizons)
    return {
        "status": "ok" if not has_missing else "incomplete",
        "horizons": horizons,
        "predictions": preds,
        "runtime_s": elapsed,
    }


# ---------------------------------------------------------------------------
# future-mutation negative control
# ---------------------------------------------------------------------------

def run_future_mutation_control(obs, fits_done, pipe, device, max_horizon,
                                predictor=None, probe_seed=None):
    """Verify that mutating future (post-cutoff) inputs does not change
    past predictions. This is the key causal integrity check.

    Uses one fitted origin; mutates all raw observations AFTER cutoff by
    +MUTATION_DELTA; re-runs inference; checks prediction equality.

    When probe_seed is set, re-seeds random, numpy (if available), and
    torch (if available) before each of the three inference calls
    (baseline, mutated, repeat) so that stochastic inference is
    controlled and the probe measures causal leakage only.
    """
    for (tid, cat, origin_m) in sorted(fits_done.keys()):
        raw_series = obs.get((tid, cat))
        if raw_series is None:
            continue
        horizons = fits_done[(tid, cat, origin_m)]
        train = causal_train_window(raw_series, origin_m)
        if len(train) < MIN_TRAIN_POINTS:
            continue

        context_vals = [float(v) for _, v in train]
        max_h = max(horizons) if horizons else max(HORIZONS)

        # --- baseline with probe re-seed ---
        if probe_seed is not None:
            _py_random.seed(probe_seed)
            try:
                import numpy as _np
                _np.random.seed(probe_seed & 0xFFFFFFFF)
            except ImportError:
                pass
        if predictor is not None:
            a1 = predictor(context_vals, max_h)
        else:
            import torch
            if probe_seed is not None:
                torch.manual_seed(probe_seed)
            ctx = torch.tensor(context_vals, dtype=torch.float32)
            r1 = tsfm_predict_batch(pipe, [ctx], max_h, device)
            a1 = r1[0] if r1 else [None] * max_h

        # Mutate future observations
        mutated = {
            k: {m: (v + MUTATION_DELTA
                    if m > last_allowed_month(origin_m) else v)
                for m, v in ser.items()}
            for k, ser in obs.items()
        }
        m_train = causal_train_window(mutated[(tid, cat)], origin_m)
        m_context = [float(v) for _, v in m_train]

        # --- mutated with probe re-seed ---
        if probe_seed is not None:
            _py_random.seed(probe_seed)
            try:
                import numpy as _np
                _np.random.seed(probe_seed & 0xFFFFFFFF)
            except ImportError:
                pass
        if predictor is not None:
            b = predictor(m_context, max_h)
        else:
            import torch
            if probe_seed is not None:
                torch.manual_seed(probe_seed)
            m_ctx = torch.tensor(m_context, dtype=torch.float32)
            r2 = tsfm_predict_batch(pipe, [m_ctx], max_h, device)
            b = r2[0] if r2 else [None] * max_h

        # Assert causal context equality: mutation must not affect
        # the allowed-history portion of context
        causal_context_equal = (context_vals == m_context)

        max_diff = 0.0
        for x, y in zip(a1, b):
            if x is not None and y is not None:
                max_diff = max(max_diff, abs(x - y))

        # --- repeat with probe re-seed ---
        if probe_seed is not None:
            _py_random.seed(probe_seed)
            try:
                import numpy as _np
                _np.random.seed(probe_seed & 0xFFFFFFFF)
            except ImportError:
                pass
        if predictor is not None:
            a2 = predictor(context_vals, max_h)
        else:
            import torch
            if probe_seed is not None:
                torch.manual_seed(probe_seed)
            ctx2 = torch.tensor(context_vals, dtype=torch.float32)
            r3 = tsfm_predict_batch(pipe, [ctx2], max_h, device)
            a2 = r3[0] if r3 else [None] * max_h

        det_diff = 0.0
        for x, y in zip(a1, a2):
            if x is not None and y is not None:
                det_diff = max(det_diff, abs(x - y))

        return {
            "series": [tid, cat],
            "origin": int_to_ym(origin_m),
            "horizons": horizons,
            "last_allowed_obs": int_to_ym(last_allowed_month(origin_m)),
            "mutated": ("all raw observations after %s by +%g"
                        % (int_to_ym(last_allowed_month(origin_m)),
                           MUTATION_DELTA)),
            "probe_seed": probe_seed,
            "causal_context_equal": causal_context_equal,
            "max_abs_forecast_diff_after_mutation": max_diff,
            "max_abs_forecast_diff_repeat_fit": det_diff,
            "passed": (causal_context_equal
                       and det_diff < PRED_TOL and max_diff < PRED_TOL),
        }
    return {"passed": None, "probe_seed": probe_seed,
            "note": "no successful fit available to probe"}


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------

def aggregate_metrics(paired_rows, outdir, tasks, elapsed_total,
                      run_start_utc, actual_revision, device,
                      expected_mask_rows=FULL_R8_MASK, seed=DEFAULT_SEED):
    """Collect all checkpoint results and compute aggregated metrics.

    Returns (metrics_dict, audit_dict, all_results, status).
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

    # Build results from paired rows + checkpoints
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
        tsfm_status = "ok" if pred_val is not None else (
            "failed" if ck is not None and ck["status"] != "ok" else "not_run")
        all_results.append({
            "territory_id": tid,
            "category": cat,
            "origin": int_to_ym(origin_m),
            "target": int_to_ym(r["target"]),
            "horizon": h,
            "actual": r["actual"],
            "pred_tsfm": pred_val,
            "pred_prophet": r.get("pred_prophet"),
            "pred_lastavailable": r["pred_lastavailable"],
            "pred_seasonal_naive": r["pred_seasonal_naive"],
            "paired": True,
            "tsfm_status": tsfm_status,
        })

    def _mae(vals):
        return mae_of([abs(p - a) for p, a in vals])

    def _four_way(rows):
        T = [(x["pred_tsfm"], x["actual"]) for x in rows
             if x["pred_tsfm"] is not None and x["actual"] is not None]
        P = [(x["pred_prophet"], x["actual"]) for x in rows
             if x["pred_prophet"] is not None and x["actual"] is not None]
        L = [(x["pred_lastavailable"], x["actual"]) for x in rows
             if x["pred_lastavailable"] is not None and x["actual"] is not None]
        S = [(x["pred_seasonal_naive"], x["actual"]) for x in rows
             if x["pred_seasonal_naive"] is not None and x["actual"] is not None]
        return T, P, L, S

    # Full mask (all 171150 rows) — separate partial from full
    full_tsfm_ok = [x for x in all_results if x["pred_tsfm"] is not None
                    and x["actual"] is not None]
    T_full, P_full, L_full, S_full = _four_way(full_tsfm_ok)

    # Common successful mask: TSFM AND Prophet AND lastavailable all present
    common = [x for x in all_results
              if x["pred_tsfm"] is not None
              and x["pred_prophet"] is not None
              and x["pred_lastavailable"] is not None
              and x["actual"] is not None]
    T, P, L, S = _four_way(common)
    common_mask_mae = {
        "tsfm": _mae(T),
        "prophet": _mae(P),
        "lastavailable": _mae(L),
        "seasonal_naive": _mae(S),
        "n_common": len(common),
    }

    # TSFM-only mask (may differ from common if Prophet is missing)
    tsfm_only_mae = {
        "tsfm": _mae(T_full),
        "n_tsfm_only": len(full_tsfm_ok),
    }

    per_horizon_mae = {}
    for h in HORIZONS:
        rows_h = [x for x in all_results if x["horizon"] == h]
        ch = [x for x in rows_h
              if x["pred_tsfm"] is not None
              and x["pred_prophet"] is not None
              and x["pred_lastavailable"] is not None
              and x["actual"] is not None]
        T, P, L, S = _four_way(ch)
        per_horizon_mae["h%d" % h] = {
            "tsfm": _mae(T),
            "prophet": _mae(P),
            "lastavailable": _mae(L),
            "seasonal_naive": _mae(S),
            "n_common": len(ch),
            "n_rows": len(rows_h),
            "n_tsfm": sum(1 for x in rows_h
                          if x["pred_tsfm"] is not None),
        }

    n_tsfm_ok = sum(1 for x in all_results
                    if x["pred_tsfm"] is not None)
    n_required = len(tasks)
    n_missing_ckpt = len(missing_checkpoints)

    completed_all = (fits_ok + fits_failed) >= n_required and n_missing_ckpt == 0
    failures_shrink = fits_failed > 0 or n_tsfm_ok < len(all_results)
    full_mask_ok = (len(paired_rows) == expected_mask_rows
                    and len(all_results) == expected_mask_rows
                    and n_tsfm_ok == expected_mask_rows)
    if not completed_all:
        status = STATUS_PARTIAL
    elif failures_shrink or not full_mask_ok:
        status = STATUS_NOT_PASS
    else:
        status = STATUS_PASS

    provenance = {
        "run_utc": run_start_utc,
        "command": " ".join(sys.argv),
        "code_sha256": _code_sha256(),
        "versions": _versions(),
        "device": device,
        "model_revision_actual": actual_revision,
        "seed": seed,
    }

    counts = {
        "total_input_rows": FULL_R8_MASK,
        "n_paired_rows": len(paired_rows),
        "n_joined_rows": len(all_results),
        "n_tsfm_forecasts": n_tsfm_ok,
        "n_tsfm_missing": len(all_results) - n_tsfm_ok,
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
            "R8 stays open: TSFM paired evaluation completed; "
            "status=%s; no external MAE win gate applied" % status),
        "case_action": "never_close_R8_stays_open",
        "full_r8": {
            "stays_open": True,
            "mask_rows": FULL_R8_MASK,
            "this_covers": len(all_results),
            "tsfm_covers": n_tsfm_ok,
            "confirmatory": completed_all and not failures_shrink,
        },
        "eval": {
            "horizons": list(HORIZONS),
            "n_origins": len({x["origin"] for x in all_results}),
        },
        "per_horizon_mae": per_horizon_mae,
        "common_mask_mae": common_mask_mae,
        "tsfm_only_mae": tsfm_only_mae,
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
            "model": "zero-shot Chronos-T5-tiny (frozen weights)",
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
            "actual", "pred_tsfm", "pred_prophet", "pred_lastavailable",
            "pred_seasonal_naive", "paired", "tsfm_status"]
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

def run(raw_path, paired_run_dir, outdir, model_revision, device,
        batch_size, max_series, resume=False, predictor=None,
        seed=DEFAULT_SEED, _raw_rows=None, _paired_rows=None,
        _paired_info=None, expected_mask_rows=FULL_R8_MASK):
    """Main batch run. predictor is injectable for self-check.

    max_series limits how many NEW checkpoints to save in this invocation,
    NOT batch membership or inference scope.  All tasks always enter the
    fixed batch partition; only checkpoint saving is gated.

    _raw_rows, _paired_rows, _paired_info: direct data injection for
    self-check (bypasses parquet I/O entirely).
    """
    if predictor is None:
        _require_chronos()

    run_start_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds")
    t_start = time.monotonic()

    model_id = DEFAULT_MODEL_ID

    # --- fingerprint ---
    fp = compute_fingerprint(raw_path, paired_run_dir, model_id,
                             model_revision, device, RELEASE_LAG, batch_size,
                             seed)

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
        df = read_records_parquet(raw_path, "raw spending parquet")
        raw_rows = df.to_dict(orient="records")
    norm = normalize_raw_rows(raw_rows)
    obs = norm["obs"]

    if _paired_rows is not None:
        paired_rows = _paired_rows
        paired_info = _paired_info
    else:
        paired_rows, paired_info = load_paired_rows(paired_run_dir)

    # --- hard raw-vs-actual contract ---
    validate_selected_raw_actuals(paired_rows, obs)

    # --- enumerate tasks ---
    tasks, all_series = enumerate_tasks(paired_rows, obs)

    # --- load Chronos (lazy) ---
    pipe = None
    actual_revision = model_revision
    if predictor is None:
        print("Loading Chronos %s (revision=%s, device=%s)..."
              % (model_id, model_revision, device))
        pipe, actual_revision = load_chronos_pipeline(
            model_id, model_revision, device)
        print("Chronos loaded. Actual revision: %s" % actual_revision)

    # --- check completed ---
    completed_keys = list_completed_keys(outdir)
    n_already_done = sum(
        1 for (tid, cat, origin_m) in tasks
        if _ckpt_key(tid, cat, origin_ym=int_to_ym(origin_m))
        in completed_keys)

    print("Tasks total: %d, already completed: %d, remaining: %d"
          % (len(tasks), n_already_done, len(tasks) - n_already_done))

    if max_series is not None and max_series < 0:
        raise ValueError("max-series must be non-negative, got %d" % max_series)
    if max_series is not None and max_series == 0:
        max_series = None  # 0 means unlimited

    # --- group paired rows by (series, origin) ---
    paired_by_so = {}
    for r in paired_rows:
        paired_by_so.setdefault(
            (r["territory_id"], r["category"]), {}
        ).setdefault(r["origin"], []).append(r)

    # --- run fits (deterministic batched inference) ---
    # Fixed partition: build ALL model-requiring items from full tasks list,
    # capped by max_series. Partition into stable batch_size chunks.
    # Non-model failures (missing series, no horizons, contract, history) are
    # saved immediately without affecting batch partition.
    max_horizon = max(HORIZONS)
    n_new_fits = 0
    n_new_failures = 0

    # Build ALL model-requiring items from full tasks list.
    # No skip of completed checkpoints, no max_series cap on membership.
    # Non-model failures are saved immediately and don't enter batches.
    all_batch_items = []
    for (tid, cat, origin_m) in tasks:
        origin_ym = int_to_ym(origin_m)
        raw_series = obs.get((tid, cat))
        if raw_series is None:
            result = {
                "status": "failed",
                "reason": "series_missing_in_raw",
                "horizons": [],
                "predictions": {},
            }
            save_checkpoint(outdir, tid, cat, origin_ym, result)
            n_new_fits += 1
            n_new_failures += 1
            continue
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
            save_checkpoint(outdir, tid, cat, origin_ym, result)
            n_new_fits += 1
            n_new_failures += 1
            continue
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
            save_checkpoint(outdir, tid, cat, origin_ym, result)
            n_new_fits += 1
            n_new_failures += 1
            continue
        train = causal_train_window(raw_series, origin_m)
        if len(train) < MIN_TRAIN_POINTS:
            result = {
                "status": "failed",
                "reason": "insufficient_history",
                "n_train_points": len(train),
                "min_required": MIN_TRAIN_POINTS,
                "horizons": horizons,
                "predictions": {},
            }
            save_checkpoint(outdir, tid, cat, origin_ym, result)
            n_new_fits += 1
            n_new_failures += 1
            continue
        context_vals = [float(v) for _, v in train]
        all_batch_items.append(
            (tid, cat, origin_m, context_vals, horizons))

    # Fixed partition: chunk all_batch_items into stable batch_size groups.
    # Each chunk gets a deterministic seed derived from global seed + chunk index.
    # If ALL items in a chunk already have ok checkpoints, skip the chunk.
    # If ANY item needs inference, rerun the WHOLE chunk with the same seed
    # and contexts; save only missing checkpoints; verify existing.
    # max_series limits how many NEW checkpoints to save, not batch membership.
    n_batches = 0
    new_saves_this_run = 0
    for batch_idx in range(0, len(all_batch_items), batch_size):
        chunk = all_batch_items[batch_idx:batch_idx + batch_size]
        chunk_done = True
        for tid, cat, origin_m, _, _ in chunk:
            existing = load_checkpoint(outdir, tid, cat,
                                       int_to_ym(origin_m))
            if existing is None:
                chunk_done = False
                break
        if chunk_done:
            continue

        chunk_contexts = [item[3] for item in chunk]
        batch_seed_val = _batch_seed(seed, batch_idx // batch_size)
        _py_random.seed(batch_seed_val)
        try:
            import numpy as _np
            _np.random.seed(batch_seed_val & 0xFFFFFFFF)
        except ImportError:
            pass
        t0 = time.monotonic()
        try:
            if predictor is not None:
                yhat_list = predictor(chunk_contexts, max_horizon)
            else:
                import torch
                torch.manual_seed(batch_seed_val)
                ctx_tensors = [torch.tensor(c, dtype=torch.float32)
                               for c in chunk_contexts]
                raw_results = tsfm_predict_batch(
                    pipe, ctx_tensors, max_horizon, device)
                yhat_list = raw_results
        except Exception as exc:
            for tid, cat, origin_m, _, horizons in chunk:
                result = {
                    "status": "failed",
                    "reason": "tsfm_inference_error",
                    "error": "%s: %s" % (type(exc).__name__, exc),
                    "horizons": horizons,
                    "predictions": {},
                    "runtime_s": time.monotonic() - t0,
                }
                save_checkpoint(outdir, tid, cat, int_to_ym(origin_m), result)
                n_new_fits += 1
                n_new_failures += 1
            n_batches += 1
            continue
        elapsed = time.monotonic() - t0
        for idx_in_chunk, (tid, cat, origin_m, _,
                           horizons) in enumerate(chunk):
            yhat = yhat_list[idx_in_chunk] if idx_in_chunk < len(
                yhat_list) else [None] * max_horizon
            preds = {}
            for h in horizons:
                val = yhat[h - 1] if (h - 1) < len(yhat) else None
                if val is not None and math.isfinite(val):
                    preds[h] = float(val)
            has_missing = any(h not in preds for h in horizons)
            result = {
                "status": "ok" if not has_missing else "incomplete",
                "horizons": horizons,
                "predictions": preds,
                "runtime_s": elapsed,
            }
            existing_ck = load_checkpoint(
                outdir, tid, cat, int_to_ym(origin_m))
            if existing_ck is not None and existing_ck["status"] == "ok":
                if existing_ck["predictions"] != preds:
                    raise CheckpointIncompatible(
                        "resume equivalence violated: checkpoint for "
                        "%s/%s/%s predictions %r != recomputed %r"
                        % (tid, cat, int_to_ym(origin_m),
                           existing_ck["predictions"], preds))
            else:
                at_limit = (max_series is not None
                            and new_saves_this_run >= max_series)
                if not at_limit:
                    save_checkpoint(outdir, tid, cat, int_to_ym(origin_m),
                                    result)
                    n_new_fits += 1
                    new_saves_this_run += 1
                    if result["status"] != "ok":
                        n_new_failures += 1
        n_batches += 1
        if max_series is not None and new_saves_this_run >= max_series:
            break

    if n_batches > 0:
        print("  batched inference: %d model items in %d batches "
              "(batch_size=%d, seed=%d)"
              % (len(all_batch_items), n_batches, batch_size, seed))

    # Save progress
    n_total_done = sum(
        1 for (tid, cat, origin_m) in tasks
        if load_checkpoint(outdir, tid, cat, int_to_ym(origin_m)) is not None)
    if n_new_fits > 0:
        prog = {
            "n_completed": n_total_done,
            "n_failures": n_new_failures,
            "n_total_tasks": len(tasks),
            "seed": seed,
        }
        save_progress(outdir, prog)
        print("  progress: %d/%d fits done (%d new this run)"
              % (n_total_done, len(tasks), n_new_fits))

    elapsed_total = time.monotonic() - t_start

    # --- future-mutation control ---
    fits_done = {}
    for (tid, cat, origin_m) in tasks:
        ck = load_checkpoint(outdir, tid, cat, int_to_ym(origin_m))
        if ck is not None and ck["status"] == "ok":
            fits_done[(tid, cat, origin_m)] = ck["horizons"]
    mutation_ctrl = run_future_mutation_control(
        obs, fits_done, pipe, device, max_horizon, predictor=predictor,
        probe_seed=PROBE_SEED)

    # --- aggregate ---
    metrics, audit, all_results, status = aggregate_metrics(
        paired_rows, outdir, tasks, elapsed_total, run_start_utc,
        actual_revision, device,
        expected_mask_rows=expected_mask_rows, seed=seed)

    audit["leak_controls"] = {
        "future_mutation_probe": mutation_ctrl,
    }

    # --- write outputs ---
    pred_format = _write_predictions(all_results, outdir)

    # --- probe gates: failed/absent probe blocks PASS and confirmatory ---
    probe_passed = mutation_ctrl.get("passed") is True
    if not probe_passed:
        status = STATUS_NOT_PASS
        metrics["status"] = status
        metrics["full_r8"]["confirmatory"] = False

    manifest = {
        "run_id": RUN_ID,
        "status": status,
        "seed": seed,
        "probe_seed": PROBE_SEED,
        "model": {
            "estimator": "Chronos-T5-tiny",
            "model_id": model_id,
            "model_revision_requested": model_revision,
            "model_revision_actual": actual_revision,
            "mode": "zero-shot",
            "frozen_weights": True,
            "no_training_on_target": True,
            "device": device,
        },
        "causal": {
            "release_lag_months": RELEASE_LAG,
            "train_month_max": "origin - %d" % RELEASE_LAG,
            "target": "origin + h",
            "calendar_ds": "real month timestamps, no gap compression",
            "note": "2-month lag is an assumption until confirmed by source",
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
# --self-check
# ---------------------------------------------------------------------------

def self_check():
    """Dependency-light self-check with synthetic monthly gaps and
    cutoff/merge invariants. Not merely implementation-mirroring tests.

    Tests:
    1. Causal window respects release lag: cutoff excludes post-lag months.
    2. Monthly gaps: missing months in raw data do not crash; window is
       correct subset.
    3. Key mask merge: paired rows join correctly with predictions by the
       5-tuple key.
    4. Future-mutation control: mutating future inputs doesn't change
       predictions from mock predictor (verifies causal window logic).
    5. Checkpoint resume: completed checkpoints are not re-run.
    6. Fingerprint mismatch on parameter change.
    7. Duplicate raw key rejection.
    8. Negative max-series rejection.
    9. Failed/missing predictions preserved, never invented.
    10. Deterministic resume: same fingerprint -> same results.
    11. Non-prefix horizon indexing (repro 1): h-1 indexing, not enumerate.
    12. Missing forecast → failure (repro 2): incomplete status → NOT_PASS.
    13. Batched inference batch call count (repro 3): batching reduces calls.
    14. Model revision validation (repro 4): 40-hex required for CLI.
    15. Real-mode smaller mask cannot PASS (guard 171150).
    16. (reserved — see test 15 above)
    17. Deterministic stochastic mock: full run and partial+resume produce
        identical per-key forecasts.
    18. Future-mutation with stochastic mock: probe_seed eliminates false
        failures from stochastic inference.
    19. Context-sensitive mock detects altered allowed-history input.
    20. Deliberately failed probe cannot claim PASS or confirmatory.
    21. Seed recorded in fingerprint and metrics.
    """
    import tempfile

    # --- batch-aware mock predictor with call counting ---
    _call_count = 0
    _batch_call_count = 0

    def mock_predictor(contexts_or_vals, n_horizon):
        """Batch-aware: contexts_or_vals is a list of (list of floats).
        Returns list of lists: [[h1, h2, ...], ...]"""
        nonlocal _call_count, _batch_call_count
        _call_count += 1
        if (contexts_or_vals and isinstance(contexts_or_vals[0], list)
                and not isinstance(contexts_or_vals[0], (int, float))):
            # Batch mode: list of contexts
            _batch_call_count += 1
            return [[len(ctx) * 10.0 + i * 5.0
                     for i in range(n_horizon)]
                    for ctx in contexts_or_vals]
        else:
            # Single context mode (backward compat)
            return [len(contexts_or_vals) * 10.0 + i * 5.0
                    for i in range(n_horizon)]

    # --- build synthetic raw + paired data with monthly gaps ---
    raw_records = []
    paired_records = []
    territories = ["t0", "t1", "t2"]
    categories = ["c0", "c1"]
    # Raw data covers 2022-01 through 2025-12 but with gaps
    raw_start = 2022 * 12
    raw_end_excl = 2026 * 12

    # Introduce gaps: skip month 2022-06 (ym=2022*12+5) for t0/c0
    gap_month = 2022 * 12 + 5
    for tid in territories:
        for cat in categories:
            for ym in range(raw_start, raw_end_excl):
                if tid == "t0" and cat == "c0" and ym == gap_month:
                    continue  # gap
                raw_records.append({
                    "date": int_to_ym(ym),
                    "territory_id": tid,
                    "category": cat,
                    "value": 100.0 + ym * 0.1,
                })

    # Origins chosen so targets are within raw obs window
    origins = [2023 * 12 + i for i in range(3)]
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
                        "pred_prophet": raw_val - 5,
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
        # --- Test 1: Causal window respects release lag ---
        norm = normalize_raw_rows(raw_records)
        obs = norm["obs"]
        t0_series = obs[("t0", "c0")]
        origin_m = 2023 * 12 + 1  # 2023-02
        cutoff = last_allowed_month(origin_m)  # 2023-02 - 2 = 2022-12
        train = causal_train_window(t0_series, origin_m)
        for m, _ in train:
            assert m <= cutoff, \
                "train month %s exceeds cutoff %s" % (int_to_ym(m),
                                                      int_to_ym(cutoff))
        # Verify cutoff is exactly origin - 2
        assert cutoff == 2022 * 12 + 11, \
            "expected cutoff 2022-12, got %s" % int_to_ym(cutoff)
        print("  test 1 PASS: causal window respects release lag")

        # --- Test 2: Monthly gaps handled correctly ---
        # t0/c0 is missing 2022-06; verify it's not in the train window
        train_months = [m for m, _ in train]
        assert gap_month not in train_months, \
            "gap month %s should not be in train window" % int_to_ym(gap_month)
        # Train window length should be (2022-01..2022-12) - 1 gap = 11
        assert len(train) == 11, \
            "expected 11 train points with gap, got %d" % len(train)
        print("  test 2 PASS: monthly gaps handled correctly")

        # --- Test 3: Key mask merge correctness ---
        # Verify paired rows merge by 5-tuple without duplication
        from collections import Counter
        key_counts = Counter()
        for r in paired_records:
            k = (r["territory_id"], r["category"], r["origin"],
                 r["horizon"], r["target"])
            key_counts[k] += 1
        for k, cnt in key_counts.items():
            assert cnt == 1, "duplicate key %r count=%d" % (k, cnt)
        # Verify 3 origins x 3 horizons x 6 series = 54
        assert len(paired_records) == 54, \
            "expected 54 paired records, got %d" % len(paired_records)
        print("  test 3 PASS: key mask merge correctness")

        # --- Test 4: Future-mutation control with mock predictor ---
        obs_copy = {k: dict(v) for k, v in obs.items()}
        fits_done = {
            ("t0", "c0", 2023 * 12): list(HORIZONS),
        }
        probe = run_future_mutation_control(
            obs_copy, fits_done, None, "cpu", max(HORIZONS),
            predictor=mock_predictor)
        assert probe["passed"] is True, \
            "future-mutation control failed: %r" % probe
        print("  test 4 PASS: future-mutation negative control")

        # --- Test 5: Checkpoint resume ---
        raw_csv = os.path.join(tmpdir, "raw.csv")
        import csv as _csv
        raw_fields = ["date", "territory_id", "category", "value"]
        with open(raw_csv, "w", newline="") as f:
            w = _csv.DictWriter(f, fieldnames=raw_fields)
            w.writeheader()
            w.writerows(raw_records)

        out1 = os.path.join(tmpdir, "out1")
        run(raw_csv, None, out1,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=2, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        prog1 = load_progress(out1)
        assert prog1["n_completed"] == 2, \
            "expected 2 completed, got %d" % prog1["n_completed"]

        # Resume with max_series=5 -> batch 0 re-inferred (stable partition,
        # all 16 items), 5 new checkpoints saved from missing items;
        # total checkpoints = 2 (existing) + 5 (new) = 7.
        run(raw_csv, None, out1,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=5, resume=True,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        prog2 = load_progress(out1)
        assert prog2["n_completed"] == 7, \
            "expected 7 after resume (2 existing + 5 new), got %d" \
            % prog2["n_completed"]
        print("  test 5 PASS: checkpoint resume")

        # --- Test 6: Fingerprint mismatch ---
        out2 = os.path.join(tmpdir, "out2")
        run(raw_csv, None, out2,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=1, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        try:
            run(raw_csv, None, out2,
                model_revision="different-rev", device="cpu",
                batch_size=16, max_series=1, resume=True,
                predictor=mock_predictor,
                _raw_rows=raw_records,
                _paired_rows=paired_records,
                _paired_info=paired_info_stub)
            raise AssertionError("fingerprint mismatch was not detected")
        except FingerprintMismatch:
            pass
        print("  test 6 PASS: fingerprint mismatch detection")

        # --- Test 7: Duplicate raw key rejection ---
        dup_records = raw_records + [dict(raw_records[0])]
        try:
            normalize_raw_rows(dup_records)
            raise AssertionError("duplicate raw key was not rejected")
        except RawValidationError:
            pass
        print("  test 7 PASS: duplicate raw key rejection")

        # --- Test 8: Negative max-series rejection ---
        out_neg = os.path.join(tmpdir, "out_neg")
        try:
            run(raw_csv, None, out_neg,
                model_revision="test-rev", device="cpu",
                batch_size=16, max_series=-1, resume=False,
                predictor=mock_predictor,
                _raw_rows=raw_records,
                _paired_rows=paired_records,
                _paired_info=paired_info_stub)
            raise AssertionError("negative max-series was not rejected")
        except ValueError:
            pass
        print("  test 8 PASS: negative max-series rejection")

        # --- Test 9: Failed predictions preserved, never invented ---
        short_records = []
        for ym in range(2023 * 12, 2023 * 12 + 6):  # 2023-01..2023-06
            short_records.append({
                "date": int_to_ym(ym),
                "territory_id": "short",
                "category": "thin",
                "value": 50.0 + ym * 0.01,
            })
        short_paired = list(paired_records) + [{
            "territory_id": "short",
            "category": "thin",
            "origin": 2023 * 12 + 3,  # 2023-04
            "horizon": 1,
            "target": 2023 * 12 + 4,  # 2023-05
            "actual": 50.0 + (2023 * 12 + 4) * 0.01,
            "pred_lastavailable": 54.0,
            "pred_seasonal_naive": 53.0,
            "pred_prophet": 54.5,
            "paired": True,
        }]
        short_info = dict(paired_info_stub,
                          n_rows=len(short_paired),
                          total_input_rows=len(short_paired))
        out_orphan = os.path.join(tmpdir, "out_orphan")
        run(raw_csv, None, out_orphan,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records + short_records,
            _paired_rows=short_paired,
            _paired_info=short_info)
        with open(os.path.join(out_orphan, "metrics.json")) as f:
            m = json.load(f)
        assert m["counts"]["n_fits_failed"] >= 1, \
            "expected at least 1 failure for insufficient history"
        assert m.get("gate_pass") is False, "gate_pass must be False"
        # Verify the short-history series has status=failed
        ck = load_checkpoint(out_orphan, "short", "thin", "2023-04")
        assert ck is not None, "checkpoint for short series must exist"
        assert ck["status"] == "failed", \
            "short series must have status=failed"
        print("  test 9 PASS: failed predictions preserved")

        # --- Test 10: Run to completion and verify metrics structure ---
        out_full = os.path.join(tmpdir, "out_full")
        run(raw_csv, None, out_full,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        with open(os.path.join(out_full, "metrics.json")) as f:
            m = json.load(f)
        assert m["status"] == "PASS", \
            "expected PASS status, got %s" % m["status"]
        assert m["common_mask_mae"]["tsfm"] is not None
        assert m["common_mask_mae"]["prophet"] is not None
        assert m["common_mask_mae"]["lastavailable"] is not None
        assert m["common_mask_mae"]["n_common"] == 54
        assert m["full_r8"]["this_covers"] == 54
        # Verify manifest structure
        with open(os.path.join(out_full, "manifest.json")) as f:
            man = json.load(f)
        assert man["model"]["model_id"] == "amazon/chronos-t5-tiny"
        assert man["model"]["frozen_weights"] is True
        assert man["model"]["no_training_on_target"] is True
        assert man["causal"]["release_lag_months"] == 2
        # Verify audit has mutation control
        with open(os.path.join(out_full, "audit.json")) as f:
            aud = json.load(f)
        assert "leak_controls" in aud
        assert "future_mutation_probe" in aud["leak_controls"]
        print("  test 10 PASS: full run metrics structure")

        # --- Test 11: Deterministic resume ---
        out_det = os.path.join(tmpdir, "out_det")
        run(raw_csv, None, out_det,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=3, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        # Read checkpoint predictions
        ck_before = load_checkpoint(out_det, "t0", "c0", "2023-01")
        # Resume
        run(raw_csv, None, out_det,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=5, resume=True,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        # Re-read same checkpoint - must be unchanged
        ck_after = load_checkpoint(out_det, "t0", "c0", "2023-01")
        assert ck_before["predictions"] == ck_after["predictions"], \
            "checkpoint changed after resume"
        print("  test 11 PASS: deterministic resume")

        # --- Test 12: Non-prefix horizon indexing (repro 1) ---
        # Predictions [10, 20, 30] with horizons [2, 3] should give
        # {2: 20, 3: 30}, NOT {2: 10, 3: 20}.
        def repro1_predictor(contexts_or_vals, n_horizon):
            _call_count_local = 0
            if (contexts_or_vals
                    and isinstance(contexts_or_vals[0], list)
                    and not isinstance(contexts_or_vals[0],
                                      (int, float))):
                return [[10.0, 20.0, 30.0] for _ in contexts_or_vals]
            return [10.0, 20.0, 30.0]

        # Build paired data with ONLY horizons [2, 3] (non-prefix)
        nonprefix_paired = []
        for tid in territories[:1]:
            for cat in categories[:1]:
                for origin_m in origins[:1]:
                    for h in (2, 3):
                        target_m = origin_m + h
                        raw_val = 100.0 + target_m * 0.1
                        nonprefix_paired.append({
                            "territory_id": tid,
                            "category": cat,
                            "origin": origin_m,
                            "horizon": h,
                            "target": target_m,
                            "actual": raw_val,
                            "pred_lastavailable": raw_val - 10,
                            "pred_seasonal_naive": raw_val - 20,
                            "pred_prophet": raw_val - 5,
                            "paired": True,
                        })
        np_info = {
            "total_input_rows": len(nonprefix_paired),
            "excluded_unpaired_rows": 0,
            "n_rows": len(nonprefix_paired),
            "path": "<self-check-repro1>",
            "sha256": None,
            "columns": list(nonprefix_paired[0].keys()),
            "join_keys": ["territory_id", "category", "origin",
                          "horizon", "target"],
        }
        out_np = os.path.join(tmpdir, "out_np")
        run(raw_csv, None, out_np,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=repro1_predictor,
            _raw_rows=raw_records,
            _paired_rows=nonprefix_paired,
            _paired_info=np_info,
            expected_mask_rows=len(nonprefix_paired))
        # Check the checkpoint predictions directly
        ck_np = load_checkpoint(out_np, "t0", "c0", "2023-01")
        assert ck_np is not None, "checkpoint for repro1 must exist"
        assert ck_np["predictions"][2] == 20.0, \
            "repro1: horizon 2 should be 20.0 (h-1=1), got %r" % \
            ck_np["predictions"].get(2)
        assert ck_np["predictions"][3] == 30.0, \
            "repro1: horizon 3 should be 30.0 (h-1=2), got %r" % \
            ck_np["predictions"].get(3)
        with open(os.path.join(out_np, "metrics.json")) as f:
            m_np = json.load(f)
        assert m_np["status"] == "PASS", \
            "repro1: non-prefix horizons must PASS, got %s" % m_np["status"]
        print("  test 12 PASS: non-prefix horizon indexing (repro 1)")

        # --- Test 13: Missing forecast → failure (repro 2) ---
        # Predictor that returns only [10.0] (horizon 1 only).
        # With horizons [1, 2, 3], horizon 2 and 3 will be missing
        # → status must be incomplete/NOT_PASS, never PASS.
        def incomplete_predictor(contexts_or_vals, n_horizon):
            if (contexts_or_vals
                    and isinstance(contexts_or_vals[0], list)
                    and not isinstance(contexts_or_vals[0],
                                      (int, float))):
                return [[10.0] for _ in contexts_or_vals]
            return [10.0]

        out_inc = os.path.join(tmpdir, "out_inc")
        # Use single series/origin to keep it small
        inc_paired = []
        for h in HORIZONS:
            origin_m = 2023 * 12
            target_m = origin_m + h
            raw_val = 100.0 + target_m * 0.1
            inc_paired.append({
                "territory_id": "t0",
                "category": "c0",
                "origin": origin_m,
                "horizon": h,
                "target": target_m,
                "actual": raw_val,
                "pred_lastavailable": raw_val - 10,
                "pred_seasonal_naive": raw_val - 20,
                "pred_prophet": raw_val - 5,
                "paired": True,
            })
        inc_info = {
            "total_input_rows": len(inc_paired),
            "excluded_unpaired_rows": 0,
            "n_rows": len(inc_paired),
            "path": "<self-check-repro2>",
            "sha256": None,
            "columns": list(inc_paired[0].keys()),
            "join_keys": ["territory_id", "category", "origin",
                          "horizon", "target"],
        }
        run(raw_csv, None, out_inc,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=incomplete_predictor,
            _raw_rows=raw_records,
            _paired_rows=inc_paired,
            _paired_info=inc_info)
        with open(os.path.join(out_inc, "metrics.json")) as f:
            m_inc = json.load(f)
        ck_inc = load_checkpoint(out_inc, "t0", "c0", "2023-01")
        assert ck_inc["status"] == "incomplete", \
            "repro2: checkpoint must be incomplete, got %s" % \
            ck_inc["status"]
        assert m_inc["status"] == "NOT_PASS", \
            "repro2: aggregate must be NOT_PASS when n_tsfm_missing>0, " \
            "got %s" % m_inc["status"]
        assert m_inc["counts"]["n_tsfm_missing"] > 0, \
            "repro2: n_tsfm_missing must be > 0"
        print("  test 13 PASS: missing forecast → failure (repro 2)")

        # --- Test 14: Batched inference batch call count (repro 3) ---
        # 18 tasks (6 series x 3 origins) with batch_size=100 → 1 batch.
        # Old code: 18 calls. New code: ceil(18/100)=1 call.
        _batch_call_count = 0
        out_batch = os.path.join(tmpdir, "out_batch")
        run(raw_csv, None, out_batch,
            model_revision="test-rev", device="cpu",
            batch_size=100, max_series=0, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        with open(os.path.join(out_batch, "metrics.json")) as f:
            m_batch = json.load(f)
        assert m_batch["status"] == "PASS", \
            "repro3: batched run must PASS, got %s" % m_batch["status"]
        batch_count_1 = _batch_call_count
        # With batch_size=100, 18 tasks should fit in 1 batch
        assert batch_count_1 == 1, \
            "repro3: expected 1 batch call with batch_size=100 and 18 " \
            "tasks, got %d" % batch_count_1

        # Now run with batch_size=6 → 3 batches
        _batch_call_count = 0
        out_batch2 = os.path.join(tmpdir, "out_batch2")
        run(raw_csv, None, out_batch2,
            model_revision="test-rev", device="cpu",
            batch_size=6, max_series=0, resume=False,
            predictor=mock_predictor,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        batch_count_2 = _batch_call_count
        assert batch_count_2 == 3, \
            "repro3: expected 3 batch calls with batch_size=6 and 18 " \
            "tasks, got %d" % batch_count_2
        assert batch_count_2 > batch_count_1, \
            "repro3: smaller batch_size must increase call count " \
            "(%d vs %d)" % (batch_count_2, batch_count_1)

        # Verify sparse horizon indexing still correct in batch mode
        ck_b = load_checkpoint(out_batch, "t0", "c0", "2023-01")
        assert ck_b["status"] == "ok", \
            "repro3: batched checkpoint must be ok"
        assert 1 in ck_b["predictions"], "repro3: horizon 1 must exist"
        assert 2 in ck_b["predictions"], "repro3: horizon 2 must exist"
        assert 3 in ck_b["predictions"], "repro3: horizon 3 must exist"
        print("  test 14 PASS: batched inference call count (repro 3)")

        # --- Test 15: Model revision validation (repro 4) ---
        # Verify CLI rejects non-40-hex revisions for real runs
        import re as _re
        assert not _re.fullmatch(r"[0-9a-f]{40}", "main"), \
            "revision validation regex must reject 'main'"
        assert not _re.fullmatch(r"[0-9a-f]{40}", "v1.0.0"), \
            "revision validation regex must reject tags"
        assert _re.fullmatch(r"[0-9a-f]{40}", "a" * 40), \
            "revision validation regex must accept 40-hex"
        assert not _re.fullmatch(r"[0-9a-f]{40}", "a" * 39), \
            "revision validation regex must reject 39 chars"
        # Test that main() rejects "main" at argparse level
        try:
            main(["--raw", raw_csv, "--paired-run", "/dev/null",
                  "--outdir", "/tmp/_r8_test_invalid",
                  "--model-revision", "main"])
            raise AssertionError("non-40-hex revision should be rejected")
        except SystemExit as e:
            assert e.code == 2, \
                "expected exit code 2 for invalid revision, got %s" % e.code
        # Test that a tag is rejected
        try:
            main(["--raw", raw_csv, "--paired-run", "/dev/null",
                  "--outdir", "/tmp/_r8_test_invalid",
                  "--model-revision", "v1.0.0"])
            raise AssertionError("tag revision should be rejected")
        except SystemExit as e:
            assert e.code == 2, \
                "expected exit code 2 for tag revision, got %s" % e.code
        print("  test 15 PASS: model revision validation (repro 4)")

        # --- Test 16: Real-mode smaller mask cannot PASS ---
        # Even if all predictions succeed, if len(paired_rows) < FULL_R8_MASK
        # and we use default expected_mask_rows (real mode), status must be
        # NOT_PASS. This proves a partial run can never claim PASS in prod.
        def _partial_predictor(ctx_or_vals, n_h):
            if (ctx_or_vals and isinstance(ctx_or_vals[0], list)
                    and not isinstance(ctx_or_vals[0], (int, float))):
                return [[42.0] * n_h for _ in ctx_or_vals]
            return [42.0] * n_h

        partial_paired = []
        for h in HORIZONS:
            origin_m = 2023 * 12
            target_m = origin_m + h
            raw_val = 100.0 + target_m * 0.1
            partial_paired.append({
                "territory_id": "t0",
                "category": "c0",
                "origin": origin_m,
                "horizon": h,
                "target": target_m,
                "actual": raw_val,
                "pred_lastavailable": raw_val - 10,
                "pred_seasonal_naive": raw_val - 20,
                "pred_prophet": raw_val - 5,
                "paired": True,
            })
        partial_info = {
            "total_input_rows": len(partial_paired),
            "excluded_unpaired_rows": 0,
            "n_rows": len(partial_paired),
            "path": "<self-check-real-mode-mask>",
            "sha256": None,
            "columns": list(partial_paired[0].keys()),
            "join_keys": ["territory_id", "category", "origin",
                          "horizon", "target"],
        }
        out_partial = os.path.join(tmpdir, "out_partial")
        run(raw_csv, None, out_partial,
            model_revision="a" * 40, device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=_partial_predictor,
            _raw_rows=raw_records,
            _paired_rows=partial_paired,
            _paired_info=partial_info)
            # expected_mask_rows defaults to FULL_R8_MASK=171150
        with open(os.path.join(out_partial, "metrics.json")) as f:
            m_partial = json.load(f)
        assert m_partial["status"] == "NOT_PASS", \
            "test 16: real-mode smaller mask must be NOT_PASS, got %s" \
            % m_partial["status"]
        assert m_partial["full_r8"]["this_covers"] == len(partial_paired), \
            "test 16: this_covers must equal paired rows"
        assert m_partial["full_r8"]["this_covers"] < FULL_R8_MASK, \
            "test 16: covers less than full mask (setup sanity)"
        print("  test 16 PASS: real-mode smaller mask cannot PASS")

        # --- Test 17: Deterministic stochastic mock ---
        # A mock predictor that uses Python's random module (stochastic)
        # but is controlled by torch.manual_seed (when torch available)
        # or by the deterministic batch-seed calling convention.
        # Full run and partial+resume must produce identical per-key forecasts.
        import random as _random

        def stochastic_mock(contexts_or_vals, n_horizon):
            if (contexts_or_vals
                    and isinstance(contexts_or_vals[0], list)
                    and not isinstance(contexts_or_vals[0],
                                      (int, float))):
                results = []
                for ctx in contexts_or_vals:
                    mean_v = sum(ctx) / len(ctx) if ctx else 0.0
                    preds = [mean_v + i * 10.0
                             + _random.gauss(0, 0.01)
                             for i in range(n_horizon)]
                    results.append(preds)
                return results
            mean_v = sum(contexts_or_vals) / len(contexts_or_vals) \
                if contexts_or_vals else 0.0
            return [mean_v + i * 10.0 + _random.gauss(0, 0.01)
                    for i in range(n_horizon)]

        TEST_SEED = 9999
        # Full run
        out_s_full = os.path.join(tmpdir, "s_full")
        run(raw_csv, None, out_s_full,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=stochastic_mock, seed=TEST_SEED,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        # Partial + resume
        out_s_part = os.path.join(tmpdir, "s_part")
        run(raw_csv, None, out_s_part,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=5, resume=False,
            predictor=stochastic_mock, seed=TEST_SEED,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        run(raw_csv, None, out_s_part,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=True,
            predictor=stochastic_mock, seed=TEST_SEED,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        # Compare all checkpoints
        for tid in territories:
            for cat in categories:
                for origin_m in origins:
                    ck_f = load_checkpoint(out_s_full, tid, cat,
                                           int_to_ym(origin_m))
                    ck_p = load_checkpoint(out_s_part, tid, cat,
                                           int_to_ym(origin_m))
                    assert ck_f is not None, \
                        "test 17: full checkpoint missing %s/%s/%s" \
                        % (tid, cat, int_to_ym(origin_m))
                    assert ck_p is not None, \
                        "test 17: resume checkpoint missing %s/%s/%s" \
                        % (tid, cat, int_to_ym(origin_m))
                    assert ck_f["predictions"] == ck_p["predictions"], \
                        "test 17: predictions differ for %s/%s/%s: " \
                        "full=%r resume=%r" \
                        % (tid, cat, int_to_ym(origin_m),
                           ck_f["predictions"], ck_p["predictions"])
        print("  test 17 PASS: deterministic stochastic mock "
              "(full == partial+resume)")

        # --- Test 18: Future-mutation with stochastic mock ---
        # With probe_seed, the stochastic mock produces identical outputs
        # for baseline, mutated, and repeat calls.
        obs_s = {k: dict(v) for k, v in norm["obs"].items()}
        fits_s = {
            ("t0", "c0", origins[0]): list(HORIZONS),
        }
        probe_s = run_future_mutation_control(
            obs_s, fits_s, None, "cpu", max(HORIZONS),
            predictor=stochastic_mock, probe_seed=PROBE_SEED)
        assert probe_s["passed"] is True, \
            "test 18: stochastic probe with probe_seed must PASS, got %r" \
            % probe_s
        assert probe_s["causal_context_equal"] is True, \
            "test 18: causal context must be equal"
        assert probe_s["max_abs_forecast_diff_after_mutation"] < PRED_TOL, \
            "test 18: mutation diff must be < PRED_TOL, got %r" \
            % probe_s["max_abs_forecast_diff_after_mutation"]
        assert probe_s["max_abs_forecast_diff_repeat_fit"] < PRED_TOL, \
            "test 18: repeat diff must be < PRED_TOL, got %r" \
            % probe_s["max_abs_forecast_diff_repeat_fit"]
        assert probe_s["probe_seed"] == PROBE_SEED, \
            "test 18: probe_seed must be recorded"
        print("  test 18 PASS: stochastic mock with probe_seed "
              "(mutation + repeat PASS)")

        # --- Test 19: Context-sensitive mock detects altered history ---
        # A predictor that uses the sum of context values, so changing
        # a value within the causal window changes the prediction.
        def context_sensitive_mock(contexts_or_vals, n_horizon):
            if (contexts_or_vals
                    and isinstance(contexts_or_vals[0], list)
                    and not isinstance(contexts_or_vals[0],
                                      (int, float))):
                return [[sum(ctx) + i for i in range(n_horizon)]
                        for ctx in contexts_or_vals]
            return [sum(contexts_or_vals) + i for i in range(n_horizon)]

        # Run with original data
        out_cs1 = os.path.join(tmpdir, "cs1")
        run(raw_csv, None, out_cs1,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=context_sensitive_mock, seed=TEST_SEED,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        # Alter a value within the causal window for t0/c0
        tampered_records = [dict(r) for r in raw_records]
        for r in tampered_records:
            if (r["territory_id"] == "t0" and r["category"] == "c0"
                    and r["date"] == "2022-01"):
                r["value"] = float(r["value"]) + 999.0
                break
        out_cs2 = os.path.join(tmpdir, "cs2")
        run(raw_csv, None, out_cs2,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=context_sensitive_mock, seed=TEST_SEED,
            _raw_rows=tampered_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        # At least one prediction must differ
        any_diff = False
        for origin_m in origins:
            ck1 = load_checkpoint(out_cs1, "t0", "c0",
                                  int_to_ym(origin_m))
            ck2 = load_checkpoint(out_cs2, "t0", "c0",
                                  int_to_ym(origin_m))
            if ck1["predictions"] != ck2["predictions"]:
                any_diff = True
                break
        assert any_diff, \
            "test 19: context-sensitive mock must detect altered history"
        print("  test 19 PASS: context-sensitive mock detects "
              "altered allowed-history")

        # --- Test 20: Deliberately failed probe blocks PASS ---
        # A stateful predictor that returns different values on each call.
        _probe_call_count = 0

        def alternating_mock(contexts_or_vals, n_horizon):
            nonlocal _probe_call_count
            _probe_call_count += 1
            if (contexts_or_vals
                    and isinstance(contexts_or_vals[0], list)
                    and not isinstance(contexts_or_vals[0],
                                      (int, float))):
                return [[_probe_call_count * 100.0 + i
                         for i in range(n_horizon)]
                        for _ in contexts_or_vals]
            return [_probe_call_count * 100.0 + i
                    for i in range(n_horizon)]

        out_fail = os.path.join(tmpdir, "out_fail")
        _probe_call_count = 0
        run(raw_csv, None, out_fail,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=alternating_mock, seed=TEST_SEED,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        with open(os.path.join(out_fail, "metrics.json")) as f:
            m_fail = json.load(f)
        with open(os.path.join(out_fail, "audit.json")) as f:
            a_fail = json.load(f)
        probe_fail = a_fail["leak_controls"]["future_mutation_probe"]
        assert probe_fail["passed"] is not True, \
            "test 20: alternating mock probe must NOT pass, got %r" \
            % probe_fail["passed"]
        assert m_fail["status"] == "NOT_PASS", \
            "test 20: failed probe must yield NOT_PASS, got %s" \
            % m_fail["status"]
        assert m_fail["full_r8"]["confirmatory"] is False, \
            "test 20: failed probe must block confirmatory"
        print("  test 20 PASS: failed probe blocks PASS and confirmatory")

        # --- Test 21: Seed recorded in fingerprint and metrics ---
        out_seed = os.path.join(tmpdir, "out_seed")
        run(raw_csv, None, out_seed,
            model_revision="test-rev", device="cpu",
            batch_size=16, max_series=0, resume=False,
            predictor=mock_predictor, seed=TEST_SEED,
            _raw_rows=raw_records,
            _paired_rows=paired_records,
            _paired_info=paired_info_stub,
            expected_mask_rows=len(paired_records))
        fp_seed = load_fingerprint(out_seed)
        assert fp_seed["seed"] == TEST_SEED, \
            "test 21: fingerprint seed must be %d, got %r" \
            % (TEST_SEED, fp_seed.get("seed"))
        with open(os.path.join(out_seed, "manifest.json")) as f:
            man_seed = json.load(f)
        assert man_seed["seed"] == TEST_SEED, \
            "test 21: manifest seed must be %d, got %r" \
            % (TEST_SEED, man_seed.get("seed"))
        with open(os.path.join(out_seed, "metrics.json")) as f:
            m_seed = json.load(f)
        assert m_seed["provenance"]["seed"] == TEST_SEED, \
            "test 21: metrics provenance seed must be %d, got %r" \
            % (TEST_SEED, m_seed["provenance"].get("seed"))
        # Resume with different seed must fail fingerprint check
        try:
            run(raw_csv, None, out_seed,
                model_revision="test-rev", device="cpu",
                batch_size=16, max_series=1, resume=True,
                predictor=mock_predictor, seed=TEST_SEED + 1,
                _raw_rows=raw_records,
                _paired_rows=paired_records,
                _paired_info=paired_info_stub)
            raise AssertionError(
                "test 21: seed mismatch should raise FingerprintMismatch")
        except FingerprintMismatch:
            pass
        print("  test 21 PASS: seed recorded in fingerprint and metrics")

    print("SELF-CHECK OK")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="R8 TSFM paired-evaluation runner: Chronos-T5-tiny "
                    "zero-shot on the 171150-point Prophet mask "
                    "(R8-tsfm-paired)")
    p.add_argument("--raw", default=None,
                   help="raw spending parquet (date/territory_id/category/"
                        "value)")
    p.add_argument("--paired-run", default=None,
                   help="R8_prophet_full run dir holding predictions.parquet")
    p.add_argument("--outdir", default=None,
                   help="output dir for checkpoints and final results")
    p.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION,
                   help="Chronos model revision to pin (default: main)")
    p.add_argument("--device", default=DEFAULT_DEVICE,
                   help="torch device: cpu, mps, cuda (default: cpu)")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                   help="batch size for Chronos inference (default: 64)")
    p.add_argument("--max-series", type=int, default=None,
                   help="max (series, origin) fits this invocation "
                        "(0=unlimited); for operator testing before --resume")
    p.add_argument("--resume", action="store_true",
                   help="resume from existing checkpoint in outdir")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help="global RNG seed for deterministic inference "
                        "(default: %d)" % DEFAULT_SEED)
    p.add_argument("--self-check", action="store_true",
                   help="run self-tests with mock predictor (no Chronos "
                        "required)")
    a = p.parse_args(argv)

    if a.self_check:
        return self_check()

    if a.resume:
        if not (a.raw and a.paired_run and a.outdir and a.model_revision):
            p.error("--resume requires --raw, --paired-run, --outdir, "
                    "and --model-revision (immutable 40-hex)")
    else:
        if not (a.raw and a.paired_run and a.outdir):
            p.error("--raw, --paired-run and --outdir are required")

    # Require immutable 40-hex model revision for real runs
    import re
    if not re.fullmatch(r"[0-9a-f]{40}", a.model_revision):
        p.error("--model-revision must be a 40-hex-char commit SHA "
                "(got %r); disallow 'main' or tag" % a.model_revision)

    run(a.raw, a.paired_run, a.outdir, a.model_revision, a.device,
        a.batch_size, a.max_series, resume=a.resume, seed=a.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())