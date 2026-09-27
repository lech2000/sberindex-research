"""R8 Prophet pilot: causal bounded Prophet followup for shock-radar (F7b).

PILOT_PARTIAL_NOT_GATE_PASS. This is an EXPLORATORY, NOT CONFIRMATORY
followup to the R8_v2 paired causal ablation. It never gates and never closes
the case: the full R8 ablation stays open, and this pilot runs on a
deterministic SUBSET of series (default 32), NOT the full 171150-row paired
mask, so it is not confirmatory and cannot reproduce the R8 gate.

What it does (causal, bounded):
  - reads the raw spending panel (--raw) and the EXISTING paired R8_v2
    predictions.parquet (--paired-run) for observed targets and baselines;
    the boolean `paired` column is REQUIRED and only paired == True rows are
    kept: the filter is applied at load, BEFORE any selection, grouping,
    prediction or metric, and excluded rows are only counted in the audit
    (known R8_v2 shape: 171918 input rows, 171150 paired == True; the
    excluded rows never enter any comparison);
  - joins on the exact existing keys territory_id / category / origin /
    horizon / target (the actual parquet columns, validated at runtime);
  - picks a deterministic subset of series from sorted keys + seed,
    independent of any outcome (only key columns and the seed are used;
    --max-series 0 means ALL series, negative is rejected);
  - fits Prophet ONCE per (series, origin) from raw values whose observation
    month <= origin - 2 (assumed release lag 2 months), using the REAL
    calendar ds (no gap compression / no misalignment);
  - predicts the actual target origin + h (i.e. h + 2 months after the last
    allowed observation, since last allowed = origin - 2);
  - compares Prophet to the winning lastavailable and seasonal_naive
    baselines on the exact same joined rows (common mask) and reports per-h
    and common-mask MAE plus counts.

Prophet config is deliberately deterministic and causal:
  growth='linear', yearly/weekly/daily seasonality FALSE, n_changepoints=3,
  uncertainty_samples=0, and an explicit deterministic seed is passed to
  Prophet.fit(df, seed=...) (threaded from the CLI --seed). No exogenous
  regressors, no news, no leakage.

Leak controls recorded in audit.json:
  - prefix mutation test on one sampled origin: perturb ALL raw observations
    after origin - 2 and require an IDENTICAL forecast (causality) and an
    identical repeat fit on the same frame (determinism);
  - target-period exact agreement (target must equal origin + h) and a hard
    STOP on duplicate join keys;
  - raw vs paired actual agreement is HARD-ENFORCED before any fit or metric:
    for every SELECTED target cell the raw observed value must exist, be
    finite and equal the paired actual within tolerance (and the paired
    actual must be finite), else the run stops with PairedContractError and
    NO metrics are ever published from a mismatched cell; the comparison
    counts are still recorded in audit.json;
  - missing context and fit failures are recorded and NO forecast is
    ever invented for a failed/missing cell.

Legacy modules f03_global_boosting and f04_tsfm_zeroshot are deliberately NOT
imported (they are not causal). Prophet is imported LAZILY and a missing
dependency is reported clearly. The R8 module r8_forecast_ablation is not
imported either: this file is self-contained.

Outputs in --outdir (must be a fresh, empty dir; a non-empty outdir is
refused): predictions.parquet, metrics.json, audit.json, manifest.json
(raw + paired input + code + versions + seed + command + limitations).

`python r8_prophet_pilot.py --self-check` runs dependency-light tests
(determinism of subset selection, negative --max-series rejection, synthetic
target/origin/lag alignment, causal-window filtering, duplicate-key stop,
paired-column requirement + unpaired-row exclusion before any validation,
and the hard raw-actual contract incl. mismatching/missing/nonfinite values)
on a synthetic panel. A deterministic real Prophet sub-check (explicit seed
threaded from --seed through Prophet.fit(df, seed=...)) runs only when
Prophet is importable and is skipped clearly otherwise. The real run
additionally needs pandas/pyarrow and Prophet.
For reproducible, deterministic fits run with single-threaded BLAS:
  OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python r8_prophet_pilot.py ...
"""

import argparse
import datetime as _dt
import hashlib
import json
import math
import os
import random
import sys

RUN_ID = "R8-prophet-pilot"
STATUS = "PILOT_PARTIAL_NOT_GATE_PASS"
SEED = 20260927
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


class RawValidationError(ValueError):
    pass


class PairedContractError(RuntimeError):
    pass


class OutdirNotFresh(RuntimeError):
    pass


class DependencyMissing(RuntimeError):
    pass


# ---------------------------------------------------------------- value/key

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


def target_gap_after_last_allowed(h):
    return int(h) + RELEASE_LAG


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
        return _sha256(os.path.abspath(__file__))
    except Exception:
        return None


def _git_commit():
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
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


# ------------------------------------------------------------ raw handling

def normalize_raw_rows(rows):
    """Pure-python schema normalization; raises on bad schema or dup keys.

    Raw spending columns (validated): date, territory_id, category, value.
    Gaps are preserved as missing months (never compressed). Non-finite or
    missing values are dropped and counted, never imputed.
    """
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
    """Sorted (month, value) for months <= origin - RELEASE_LAG only.

    This is the causal boundary: no observation after origin - 2 is ever
    visible to the fit. Gaps are preserved (actual calendar months), never
    compressed.
    """
    cutoff = last_allowed_month(origin_m)
    return sorted((m, v) for m, v in raw_series.items() if m <= cutoff)


def select_series(series_keys, seed, max_series):
    """Deterministic, outcome-independent subset from sorted keys + seed.

    Only key columns and the seed are used; never any value/outcome. The
    input order is irrelevant (keys are sorted first). max_series == 0 means
    ALL series; negative max_series is rejected.
    """
    keys = sorted({(str(t), str(c)) for t, c in series_keys})
    n_candidates = len(keys)
    max_series = int(max_series)
    if max_series < 0:
        raise ValueError(
            "max_series must be >= 0 (0 means ALL series), got %d"
            % max_series)
    if max_series == 0 or max_series >= n_candidates:
        return keys, {
            "n_candidates": n_candidates,
            "n_selected": n_candidates,
            "max_series": max_series,
            "all_series": True,
        }
    rng = random.Random(int(seed))
    picked = sorted(rng.sample(keys, max_series))
    return picked, {
        "n_candidates": n_candidates,
        "n_selected": len(picked),
        "max_series": max_series,
        "all_series": False,
    }


# --------------------------------------------------------------- Prophet

def _require_prophet():
    try:
        import pandas  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "pandas is required for the R8 Prophet pilot (dependency "
            "missing); install pandas and pyarrow to read the parquet inputs")
    try:
        import prophet  # noqa: F401
    except ImportError:
        raise DependencyMissing(
            "prophet is required for the R8 Prophet pilot (dependency "
            "missing); install 'prophet' to run the real fit. "
            "This pilot does NOT substitute any other model.")


def prophet_fit_predict(train, target_ds, seed=SEED):
    """Fit Prophet once on (ds, y) and predict at target_ds. Lazy import.

    train: list of (datetime ds, float y), already restricted to months
    <= origin - 2. target_ds: list of datetime, one per requested target.
    seed: explicit deterministic fit seed, threaded from the CLI --seed all
    the way into Prophet.fit(df, seed=...). Returns a list of yhat aligned to
    target_ds. Deterministic and causal.
    """
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


# ------------------------------------------------------------ paired input

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


def _paired_true(v):
    """True only for an explicit boolean True.

    None, NaN and ambiguous missing markers (e.g. pandas NA, whose truth
    value is undefined and raises) never count as paired.
    """
    if v is None:
        return False
    if isinstance(v, float) and math.isnan(v):
        return False
    try:
        return bool(v) is True
    except (TypeError, ValueError):
        return False


def normalize_paired_rows(records, cols):
    """Pure-python paired-input contract; unpaired rows are excluded FIRST.

    The boolean `paired` column is REQUIRED and never guessed. Rows with
    paired != True are dropped BEFORE any selection, grouping, prediction or
    metric: they are only counted as excluded_unpaired_rows and never enter
    any comparison (their key/target validity is irrelevant). On the kept
    rows: hard STOP on duplicate join keys and on any target that is not
    exactly origin + horizon.
    """
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
        # exact target agreement: target must be exactly origin + h.
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


def load_paired_rows(paired_run_dir):
    """Read predictions.parquet and enforce the join contract.

    Uses the ACTUAL parquet columns (validated in normalize_paired_rows):
    territory_id, category, origin, horizon, target, actual,
    pred_lastavailable, pred_seasonal_naive and the REQUIRED boolean paired.
    Only paired == True rows are returned (the filter happens at load, before
    any selection, grouping, prediction or metric). info audits the
    total_input_rows and excluded_unpaired_rows counts.
    """
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
    """Pre-fit hard contract over EVERY selected target cell.

    The raw panel must hold a finite observed value at each selected target
    month, it must equal the paired `actual` within tol, and the paired
    actual itself must be finite. Any violation is a broken input contract:
    PairedContractError is raised BEFORE any fit, metric or output, so no
    metric is ever published from a missing/nonfinite/mismatched cell.
    Returns the comparison audit (necessarily all-agreeing) for the selected
    cells.
    """
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


# ------------------------------------------------------------------ output

def ensure_outdir_fresh(outdir, paired_run_dir):
    out = os.path.abspath(outdir)
    paired = os.path.abspath(paired_run_dir)
    if out == paired or out.startswith(paired + os.sep):
        raise OutdirNotFresh(
            "refusing to write into the paired-run dir %r" % paired)
    if os.path.isdir(out) and os.listdir(out):
        raise OutdirNotFresh(
            "refusing to write into existing non-empty outdir %r; use a "
            "fresh empty dir" % out)
    os.makedirs(out, exist_ok=True)
    return out


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


# -------------------------------------------------------------------- run

def run(raw_path, paired_run_dir, outdir, max_series, seed):
    _require_prophet()
    out = ensure_outdir_fresh(outdir, paired_run_dir)

    df = read_records_parquet(raw_path, "raw spending parquet")
    raw_rows = df.to_dict(orient="records")
    norm = normalize_raw_rows(raw_rows)
    obs = norm["obs"]

    paired_rows, paired_info = load_paired_rows(paired_run_dir)

    candidates = sorted({(r["territory_id"], r["category"])
                         for r in paired_rows})
    subset, sel_meta = select_series(candidates, seed, max_series)
    subset_set = set(subset)

    # paired == True is already enforced at load; only those rows reach here.
    selected_rows = [r for r in paired_rows
                     if (r["territory_id"], r["category"]) in subset_set]
    # pre-fit hard contract: every selected target cell must carry a finite
    # raw actual equal to the paired actual within tolerance, else STOP
    # before any fit or metric is produced.
    raw_contract = validate_selected_raw_actuals(selected_rows, obs)

    # group paired rows by (series, origin)
    by_series = {}
    for r in paired_rows:
        key = (r["territory_id"], r["category"])
        if key not in subset_set:
            continue
        by_series.setdefault(key, {}).setdefault(
            (r["origin"], r["horizon"]), r)

    pred_by_key = {}   # (tid,cat,origin,h) -> prophet yhat or None
    failures = []      # recorded, never invented
    fits = {}          # (tid,cat,origin) -> {"targets":[...], "yhat":[...]}

    for key in subset:
        tid, cat = key
        raw_series = obs.get(key)
        cells = by_series.get(key, {})
        origins = sorted({o for (o, _h) in cells})
        for origin_m in origins:
            horizons_here = sorted({h for (o, h) in cells if o == origin_m})
            tms = [target_month(origin_m, h) for h in horizons_here]
            if raw_series is None:
                failures.append({
                    "series": [tid, cat], "origin": int_to_ym(origin_m),
                    "horizons": horizons_here,
                    "reason": "series_missing_in_raw",
                })
                for h in horizons_here:
                    pred_by_key[(tid, cat, origin_m, h)] = None
                continue
            train = causal_train_window(raw_series, origin_m)
            if len(train) < MIN_TRAIN_POINTS:
                failures.append({
                    "series": [tid, cat], "origin": int_to_ym(origin_m),
                    "horizons": horizons_here,
                    "reason": "insufficient_history",
                    "n_train_points": len(train),
                    "min_required": MIN_TRAIN_POINTS,
                })
                for h in horizons_here:
                    pred_by_key[(tid, cat, origin_m, h)] = None
                continue
            train_pairs = [(month_to_dt(m), float(v)) for m, v in train]
            try:
                yhat = prophet_fit_predict(
                    train_pairs, [month_to_dt(t) for t in tms], seed=seed)
            except Exception as exc:
                failures.append({
                    "series": [tid, cat], "origin": int_to_ym(origin_m),
                    "horizons": horizons_here,
                    "reason": "prophet_fit_error",
                    "error": "%s: %s" % (type(exc).__name__, exc),
                })
                for h in horizons_here:
                    pred_by_key[(tid, cat, origin_m, h)] = None
                continue
            fits[(tid, cat, origin_m)] = {"targets": tms, "yhat": yhat,
                                          "horizons": horizons_here}
            for h, y in zip(horizons_here, yhat):
                pred_by_key[(tid, cat, origin_m, h)] = float(y)

    # ---- prefix mutation probe: one sampled origin, identical forecast ----
    probe = None
    for key in subset:
        for origin_m in sorted({o for (o, _h) in by_series.get(key, {})}):
            if (key[0], key[1], origin_m) in fits:
                probe = (key, origin_m)
                break
        if probe:
            break
    leak_controls = {}
    if probe is not None:
        (ptid, pcat), porigin = probe
        cached = fits[(ptid, pcat, porigin)]
        raw_series = obs[(ptid, pcat)]
        target_ds = [month_to_dt(t) for t in cached["targets"]]
        train_pairs = [(month_to_dt(m), float(v))
                       for m, v in causal_train_window(raw_series, porigin)]
        # determinism: refit on the identical frame with the same CLI seed
        a1 = prophet_fit_predict(train_pairs, target_ds, seed=seed)
        a2 = prophet_fit_predict(train_pairs, target_ds, seed=seed)
        det_diff = max(abs(x - y) for x, y in zip(a1, a2))
        # causality: perturb ALL raw obs after origin-2, forecast must match
        mutated = {
            k: {m: (v + MUTATION_DELTA
                    if m > last_allowed_month(porigin) else v)
                for m, v in ser.items()}
            for k, ser in obs.items()
        }
        m_train = [(month_to_dt(m), float(v))
                   for m, v in causal_train_window(mutated[(ptid, pcat)],
                                                   porigin)]
        b = prophet_fit_predict(m_train, target_ds, seed=seed)
        mut_diff = max(abs(x - y) for x, y in zip(a1, b))
        if not (det_diff < PRED_TOL):
            raise AssertionError(
                "Prophet determinism violated: %r" % det_diff)
        if not (mut_diff < PRED_TOL):
            raise AssertionError(
                "prefix mutation causality violated: %r" % mut_diff)
        leak_controls["prefix_mutation_probe"] = {
            "series": [ptid, pcat],
            "origin": int_to_ym(porigin),
            "horizons": cached["horizons"],
            "last_allowed_obs": int_to_ym(last_allowed_month(porigin)),
            "mutated": ("all raw observations after %s by +%g"
                        % (int_to_ym(last_allowed_month(porigin)),
                           MUTATION_DELTA)),
            "max_abs_forecast_diff_after_mutation": mut_diff,
            "max_abs_forecast_diff_repeat_fit": det_diff,
            "passed": True,
        }
    else:
        leak_controls["prefix_mutation_probe"] = {
            "passed": None,
            "note": "no successful fit available to probe",
        }

    # ---------------------------- join + metrics ----------------------------
    # only selected, paired == True rows reach these metrics; the raw vs
    # paired actual agreement was already hard-validated pre-fit.
    results = []
    for r in selected_rows:
        key = (r["territory_id"], r["category"])
        pp = pred_by_key.get((key[0], key[1], r["origin"], r["horizon"]),
                             "ABSENT")
        prophet_pred = None if pp in (None, "ABSENT") else float(pp)
        status = ("ok" if prophet_pred is not None else
                  ("failed" if pp is None else "not_fit"))
        results.append({
            "territory_id": key[0], "category": key[1],
            "origin": int_to_ym(r["origin"]), "target": int_to_ym(r["target"]),
            "horizon": r["horizon"],
            "actual": r["actual"],
            "pred_prophet": prophet_pred,
            "pred_lastavailable": r["pred_lastavailable"],
            "pred_seasonal_naive": r["pred_seasonal_naive"],
            "paired": r["paired"],
            "prophet_status": status,
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

    common = [x for x in results
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
        rows_h = [x for x in results if x["horizon"] == h]
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
            "n_prophet": sum(1 for x in rows_h if x["pred_prophet"] is not None),
        }

    n_prophet_ok = sum(1 for x in results if x["pred_prophet"] is not None)
    counts = {
        "total_input_rows": paired_info["total_input_rows"],
        "excluded_unpaired_rows": paired_info["excluded_unpaired_rows"],
        "selected_paired_rows": len(selected_rows),
        "common_mask_rows": len(common),
        "n_joined_rows": len(results),
        "n_prophet_forecasts": n_prophet_ok,
        "n_prophet_missing": len(results) - n_prophet_ok,
        "n_failures_recorded": len(failures),
        "n_series_selected": len(subset),
        "n_series_candidates": sel_meta["n_candidates"],
        "n_series_fit_ok": len({k[:2] for k in fits}),
        "n_origins_fit_ok": len(fits),
    }

    # ------------------------------- outputs --------------------------------
    pred_format = _write_predictions(results, out)

    provenance = {
        "run_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(
            timespec="seconds"),
        "command": " ".join(sys.argv),
        "inputs": {
            "raw": raw_path,
            "raw_sha256": _sha256(raw_path),
            "raw_rows_kept": norm["n_rows_kept"],
            "raw_n_series": norm["n_series"],
            "raw_panel_range": [int_to_ym(norm["months"][0]),
                                int_to_ym(norm["months"][-1])],
            "paired_run": paired_run_dir,
            "paired_predictions": paired_info["path"],
            "paired_predictions_sha256": paired_info["sha256"],
            "paired_total_input_rows": paired_info["total_input_rows"],
            "paired_excluded_unpaired_rows":
                paired_info["excluded_unpaired_rows"],
            "paired_n_rows": paired_info["n_rows"],
            "paired_columns": paired_info["columns"],
            "join_keys": paired_info["join_keys"],
        },
        "code_sha256": _code_sha256(),
        "git_commit": _git_commit(),
        "versions": _versions(),
        "seed": int(seed),
    }

    limitations = [
        "PILOT_PARTIAL_NOT_GATE_PASS: exploratory Prophet followup, NOT "
        "confirmatory; the full R8 ablation stays open",
        "subset is NOT the full %d-row paired mask (deterministic subset of "
        "%d series, max_series=%s); no full-mask or gate claim is made"
        % (FULL_R8_MASK, len(subset), max_series),
        "assumed release lag of %d months is a synthetic assumption, not a "
        "measured release timestamp" % RELEASE_LAG,
        "yearly/weekly/daily seasonality are OFF and n_changepoints=3: this "
        "is a bounded linear-trend Prophet, not a seasonal model; it is a "
        "causal comparator to lastavailable/seasonal_naive",
        "Prophet fit is bounded and causal (month <= origin-2), but the "
        "24-ish monthly points per series give high trend uncertainty",
        "observed target values come from the paired R8_v2 parquet; raw "
        "target value agreement is hard-enforced before any fit or metric "
        "(PairedContractError on missing/nonfinite raw actual, "
        "missing/nonfinite paired actual, or a mismatch beyond tolerance)",
        "no forecast is ever invented for a failed or missing cell",
    ]

    metrics = {
        "run_id": RUN_ID,
        "status": STATUS,
        "gate_pass": False,
        "gate_pass_reason": (
            "exploratory Prophet pilot on a subset, not the full %d-row R8 "
            "mask, and not confirmatory; PASS is forbidden and the full R8 "
            "stays open" % FULL_R8_MASK),
        "case_action": "do_not_close_full_R8_stays_open",
        "full_r8": {
            "stays_open": True,
            "mask_rows": FULL_R8_MASK,
            "this_subset_covers": len(results),
            "confirmatory": False,
        },
        "subset": dict(sel_meta, seed=int(seed),
                       selection="sorted_keys_seeded_sample",
                       outcome_independent=True),
        "eval": {
            "horizons": list(HORIZONS),
            "n_origins": len({x["origin"] for x in results}),
        },
        "per_horizon_mae": per_horizon_mae,
        "common_mask_mae": common_mask_mae,
        "counts": counts,
        "limitations": limitations,
        "predictions_file": os.path.join(
            out, "predictions." + ("parquet" if pred_format == "parquet"
                                   else "csv")),
        "predictions_format": pred_format,
        "provenance": provenance,
    }
    with open(os.path.join(out, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)

    audit = {
        "run_id": RUN_ID,
        "status": STATUS,
        "leak_controls": leak_controls,
        "join_contract": {
            "join_keys": paired_info["join_keys"],
            "target_exact_agreement": "target == origin + horizon enforced",
            "duplicate_keys": "hard stop",
            "paired_filter": {
                "required_column": "paired (boolean), never guessed",
                "filter": "paired == True applied at load, before selection/"
                          "grouping/prediction/metrics",
                "total_input_rows": paired_info["total_input_rows"],
                "excluded_unpaired_rows":
                    paired_info["excluded_unpaired_rows"],
                "selected_paired_rows": len(selected_rows),
                "common_mask_rows": len(common),
            },
            "raw_vs_paired_actual": {
                "enforcement": "hard pre-fit contract: PairedContractError "
                               "on missing/nonfinite raw actual, "
                               "missing/nonfinite paired actual, or "
                               "|raw - paired actual| > tolerance on any "
                               "selected target cell, before any metric is "
                               "published",
                "tolerance": PRED_TOL,
                "n_compared": raw_contract["n_compared"],
                "n_mismatch": raw_contract["n_mismatch"],
                "max_abs_diff": raw_contract["max_abs_diff"],
            },
        },
        "missing_and_failures": failures,
        "no_invented_forecasts": True,
        "train_eval": {
            "release_lag_months": RELEASE_LAG,
            "train_filter": "observation month <= origin - %d"
                            % RELEASE_LAG,
            "target": "origin + h (h + %d after last allowed obs)"
                      % RELEASE_LAG,
            "calendar_ds": "actual month timestamps, gaps preserved",
        },
        "provenance": provenance,
    }
    with open(os.path.join(out, "audit.json"), "w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=1)

    manifest = {
        "run_id": RUN_ID,
        "status": STATUS,
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
            "target_gap_after_last_allowed": "h + %d" % RELEASE_LAG,
            "calendar_ds": "real month timestamps, no gap compression",
        },
        "subset": dict(sel_meta, seed=int(seed),
                       selection="sorted_keys_seeded_sample",
                       outcome_independent=True),
        "outputs": ["predictions." + ("parquet" if pred_format == "parquet"
                                      else "csv"),
                    "metrics.json", "audit.json", "manifest.json"],
        "limitations": limitations,
        "provenance": provenance,
    }
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)

    print(json.dumps({
        "status": STATUS,
        "subset_series": len(subset),
        "joined_rows": len(results),
        "common_mask_mae": common_mask_mae,
        "outdir": out,
    }, ensure_ascii=False, indent=1))
    return metrics, audit


# -------------------------------------------------------------- self-check

def self_check(seed=SEED):
    # --- target / origin / lag alignment (synthetic) ---
    for h in HORIZONS:
        assert target_gap_after_last_allowed(h) == h + 2
        for origin_m in (2024 * 12 + 5, 2023 * 12 + 0):
            assert last_allowed_month(origin_m) == origin_m - 2
            assert target_month(origin_m, h) == origin_m + h
            assert (target_month(origin_m, h)
                    == last_allowed_month(origin_m) + (h + 2))

    # --- causal train window: excludes everything after origin-2 ---
    raw_series = {m: float(m) for m in range(2023 * 12, 2023 * 12 + 24)}
    origin_m = 2023 * 12 + 15
    win = causal_train_window(raw_series, origin_m)
    cutoff = last_allowed_month(origin_m)
    assert win and all(m <= cutoff for m, _ in win), win
    assert win[-1][0] == cutoff, win[-1]
    # no gap compression: months are the actual calendar months present
    assert [m for m, _ in win] == sorted(m for m in raw_series if m <= cutoff)

    # mutate all obs after origin-2; the causal window is unchanged
    mutated = {m: v + MUTATION_DELTA if m > cutoff else v
               for m, v in raw_series.items()}
    assert causal_train_window(mutated, origin_m) == win

    # gap preservation: a missing month is not filled or compressed
    gapped = {m: v for m, v in raw_series.items() if m != cutoff - 1}
    gwin = causal_train_window(gapped, origin_m)
    assert len(gwin) == len(win) - 1
    assert all(m != cutoff - 1 for m, _ in gwin)

    # --- subset selection determinism / outcome independence ---
    keys = [("t%02d" % i, "c%d" % (i % 3)) for i in range(40)]
    s1, meta1 = select_series(keys, SEED, 12)
    s2, _ = select_series(list(reversed(keys)), SEED, 12)  # order irrelevant
    assert s1 == s2, (s1, s2)
    assert len(s1) == 12 and len(set(s1)) == 12
    assert s1 == sorted(s1)
    assert meta1["n_selected"] == 12 and meta1["all_series"] is False
    s3, _ = select_series(keys, SEED + 1, 12)  # different seed -> (likely) new
    assert len(s3) == 12
    alls, meta_all = select_series(keys, SEED, 0)  # 0 == ALL
    assert alls == sorted({(str(t), str(c)) for t, c in keys})
    assert meta_all["all_series"] is True
    big, meta_big = select_series(keys, SEED, 10 ** 6)
    assert big == alls and meta_big["all_series"] is True
    # selecting is a pure function of (sorted keys, seed, k): no outcomes used
    assert select_series(keys, SEED, 12)[0] == select_series(
        list(keys), SEED, 12)[0]
    # negative --max-series is rejected, never silently treated as "ALL"
    try:
        select_series(keys, SEED, -1)
        raise AssertionError("negative max_series was not rejected")
    except ValueError:
        pass

    # --- normalize_raw_rows: dup keys and non-finite rejected ---
    rows = [{"date": "2023-01", "territory_id": "t0", "category": "c0",
             "value": 1.0},
            {"date": "2023-02", "territory_id": "t0", "category": "c0",
             "value": 2.0}]
    norm = normalize_raw_rows(rows)
    assert norm["n_series"] == 1 and norm["n_rows_kept"] == 2
    dup = rows + [dict(rows[0])]
    try:
        normalize_raw_rows(dup)
        raise AssertionError("duplicate key was not rejected")
    except RawValidationError:
        pass
    bad = [dict(rows[0])]
    bad[0]["value"] = float("nan")
    # NaN-only input leaves no usable month -> must raise, never invent
    try:
        normalize_raw_rows(bad)
        raise AssertionError("all-NaN input was not rejected")
    except RawValidationError:
        pass

    # --- paired contract: paired column required, unpaired excluded FIRST ---
    pcols = ["territory_id", "category", "origin", "horizon", "target",
             "actual", "pred_lastavailable", "pred_seasonal_naive", "paired"]

    def _prec(tid, cat, origin, h, target, paired, actual=10.0):
        return {"territory_id": tid, "category": cat, "origin": origin,
                "horizon": h, "target": target, "actual": actual,
                "pred_lastavailable": 9.0, "pred_seasonal_naive": 8.0,
                "paired": paired}

    prec = [
        _prec("t0", "c0", "2024-01", 1, "2024-02", True),
        # unpaired rows are excluded BEFORE validation: this one has a wrong
        # target (origin + h != target) and this one duplicates a kept key;
        # neither may abort or enter any comparison
        _prec("t0", "c0", "2024-01", 3, "2024-09", False),
        _prec("t0", "c0", "2024-01", 1, "2024-02", False),
        _prec("t1", "c1", "2024-01", 1, "2024-02", None),
        _prec("t1", "c1", "2024-01", 2, "2024-03", True),
    ]
    prows, pinfo = normalize_paired_rows(prec, pcols)
    assert pinfo["total_input_rows"] == 5, pinfo
    assert pinfo["excluded_unpaired_rows"] == 3, pinfo
    assert pinfo["n_rows"] == 2, pinfo
    assert [(r["territory_id"], r["horizon"]) for r in prows] == \
        [("t0", 1), ("t1", 2)], prows
    assert all(r["paired"] is True for r in prows)
    # the required boolean `paired` column is never guessed
    try:
        normalize_paired_rows(prec, [c for c in pcols if c != "paired"])
        raise AssertionError("missing paired column was not rejected")
    except PairedContractError:
        pass
    # an all-unpaired input keeps nothing and hard stops
    try:
        normalize_paired_rows(
            [_prec("t9", "c9", "2024-01", 1, "2024-02", False)], pcols)
        raise AssertionError("all-unpaired input was not rejected")
    except PairedContractError:
        pass

    # --- raw actual contract: hard fail before metrics on bad raw actual ---
    obs_sel = {("t0", "c0"): {2024 * 12 + 1: 10.0}}
    sel = [{"territory_id": "t0", "category": "c0",
            "target": 2024 * 12 + 1, "actual": 10.0}]
    ok = validate_selected_raw_actuals(sel, obs_sel)
    assert ok["n_compared"] == 1 and ok["n_mismatch"] == 0, ok
    assert ok["max_abs_diff"] == 0.0, ok
    bad_cases = [
        ("mismatched raw actual",
         [{"territory_id": "t0", "category": "c0",
           "target": 2024 * 12 + 1, "actual": 10.5}]),
        ("missing raw actual",
         [{"territory_id": "t0", "category": "c0",
           "target": 2024 * 12 + 2, "actual": 10.0}]),
        ("missing paired actual",
         [{"territory_id": "t0", "category": "c0",
           "target": 2024 * 12 + 1, "actual": None}]),
    ]
    for label, bad_sel in bad_cases:
        try:
            validate_selected_raw_actuals(bad_sel, obs_sel)
            raise AssertionError("%s was not rejected" % label)
        except PairedContractError:
            pass
    try:
        validate_selected_raw_actuals(
            [{"territory_id": "t0", "category": "c0",
              "target": 2024 * 12 + 3, "actual": 1.0}],
            {("t0", "c0"): {2024 * 12 + 3: float("inf")}})
        raise AssertionError("nonfinite raw actual was not rejected")
    except PairedContractError:
        pass

    # --- month parsing / target agreement helper ---
    assert ym_to_int("2024-06") == 2024 * 12 + 5
    assert int_to_ym(2024 * 12 + 5) == "2024-06"
    assert month_to_dt(2024 * 12 + 5) == _dt.datetime(2024, 6, 1)

    # --- real Prophet determinism sub-check (only if Prophet available):
    # the CLI seed is threaded through the real fit via Prophet.fit seed ---
    try:
        import pandas  # noqa: F401
        import prophet  # noqa: F401
    except Exception:
        print("SELF-CHECK OK (real Prophet sub-check skipped: "
              "dependency missing)")
        return 0
    train = [(month_to_dt(2023 * 12 + i), 100.0 + 2.0 * i + (i % 3))
             for i in range(16)]
    tgt = [month_to_dt(2023 * 12 + 16 + j) for j in range(3)]
    y1 = prophet_fit_predict(train, tgt, seed=int(seed))
    y2 = prophet_fit_predict(train, tgt, seed=int(seed))
    assert max(abs(a - b) for a, b in zip(y1, y2)) < PRED_TOL, (y1, y2)
    assert len(y1) == 3 and all(isinstance(v, float) for v in y1)
    print("SELF-CHECK OK (real Prophet fit seed=%d)" % int(seed))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(
        description="R8 Prophet pilot: causal bounded Prophet followup "
                    "(PILOT_PARTIAL_NOT_GATE_PASS, never a gate PASS)")
    p.add_argument("--raw", default=None,
                   help="raw spending parquet (date/territory_id/category/"
                        "value)")
    p.add_argument("--paired-run", default=None,
                   help="R8_v2 run dir holding predictions.parquet")
    p.add_argument("--outdir", default=None,
                   help="fresh empty output dir (non-empty refused)")
    p.add_argument("--max-series", type=int, default=32,
                   help="deterministic series subset size; 0 means ALL, "
                        "negative is rejected")
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        return self_check(seed=a.seed)
    if a.max_series < 0:
        p.error("--max-series must be >= 0 (0 means ALL series)")
    if not (a.raw and a.paired_run and a.outdir):
        p.error("--raw, --paired-run and --outdir are required")
    run(a.raw, a.paired_run, a.outdir, a.max_series, a.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
