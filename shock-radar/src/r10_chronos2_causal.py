"""Separate Chronos-2 causal evaluator. Default preparation performs no inference.

Existing Tiny files are never read as Chronos-2 predictions or modified.
Model loading is offline, CPU-only, pinned by config and full weight SHA.
"""
from pathlib import Path
import argparse, collections, datetime, hashlib, json, math, os, platform
import resource, threading, time


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temp.replace(path)


def month(value):
    text = str(value)
    if len(text) < 7 or not 1 <= int(text[5:7]) <= 12:
        raise ValueError('invalid month')
    return int(text[:4]) * 12 + int(text[5:7]) - 1


def ym(value):
    return f'{value // 12:04d}-{value % 12 + 1:02d}'


def causal_context(series, origin, lag, start=2023 * 12):
    cutoff = month(origin) - lag
    if cutoff < start:
        raise ValueError('cutoff before input window')
    # Explicit regular calendar; NaN means source missing, never zero-filled.
    values = [float(series.get(m, float('nan'))) for m in range(start, cutoff + 1)]
    if any(math.isinf(v) for v in values):
        raise ValueError('infinite context')
    return cutoff, values


def key(row):
    return tuple(str(row[c]) for c in ('territory_id', 'category', 'origin', 'horizon', 'target'))


def context_digest(values):
    # Canonical NaN marker; direct float NaN equality would be misleading.
    payload = ['MISSING' if math.isnan(x) else float(x).hex() for x in values]
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


def load_inputs(protocol):
    import pandas as pd
    for label in ['raw', 'paired']:
        if sha(protocol['input_paths'][label]) != protocol['input_sha256'][label]:
            raise ValueError(f'{label} source SHA mismatch')
    raw = pd.read_parquet(protocol['input_paths']['raw'])
    raw['territory_id'] = raw.territory_id.astype(str)
    raw['month'] = raw.date.map(month)
    if raw.duplicated(['territory_id', 'category', 'month']).any():
        raise ValueError('duplicate raw key')
    obs = {}
    for row in raw.itertuples(index=False):
        if pd.isna(row.value):
            continue
        value = float(row.value)
        if not math.isfinite(value):
            raise ValueError('nonfinite raw value')
        obs.setdefault((str(row.territory_id), str(row.category)), {})[row.month] = value
    paired = pd.read_parquet(protocol['input_paths']['paired'])
    required = protocol['paired_key_columns'] + ['actual', 'pred_prophet']
    if any(c not in paired for c in required):
        raise ValueError('missing paired column')
    paired['territory_id'] = paired.territory_id.astype(str)
    if len(paired) != protocol['expected_rows'] or paired.duplicated(protocol['paired_key_columns']).any():
        raise ValueError('paired count/key mismatch')
    if sorted(paired.horizon.unique().tolist()) != protocol['horizons']:
        raise ValueError('unexpected horizons')
    rows = paired.sort_values(protocol['paired_key_columns']).to_dict('records')
    contexts = {}; summary = collections.defaultdict(collections.Counter); candidates = {}
    for row in rows:
        h = int(row['horizon']); oi = month(row['origin']); ti = month(row['target'])
        if ti != oi + h or ti > month('2024-12'):
            raise ValueError('target/origin mismatch')
        series = obs.get((row['territory_id'], row['category']), {})
        if series.get(ti) != float(row['actual']):
            raise ValueError('paired actual disagrees with frozen raw')
        so = (row['territory_id'], row['category'], str(row['origin']))
        if so not in contexts:
            cutoff, vals = causal_context(series, row['origin'], protocol['release_lag_months'])
            contexts[so] = (cutoff, vals)
        cutoff, vals = contexts[so]
        summary[h]['requested'] += 1
        valid = sum(math.isfinite(v) for v in vals)
        if valid < protocol['minimum_nonmissing_context_points']:
            summary[h]['insufficient_history'] += 1
            continue
        if len(vals) > protocol['context_length_limit']:
            raise ValueError('unfrozen context truncation forbidden')
        summary[h]['eligible'] += 1
        if any(math.isnan(v) for v in vals): summary[h]['eligible_with_missing_calendar_month'] += 1
        if cutoff not in series: summary[h]['missing_cutoff_anchor'] += 1
        rank = hashlib.sha256((str(protocol['seed']) + '\0' + '\0'.join(key(row))).encode()).hexdigest()
        item = {'row': row, 'cutoff': cutoff, 'context': vals, 'selection_hash': rank}
        if h not in candidates or rank < candidates[h]['selection_hash']:
            candidates[h] = item
    return obs, rows, contexts, candidates, {str(h): dict(v) for h, v in summary.items()}


def model_predict(pipe, values, steps):
    import torch
    with torch.inference_mode():
        quantiles, medians = pipe.predict_quantiles(
            [torch.tensor(values, dtype=torch.float32)], prediction_length=steps,
            quantile_levels=[0.5], batch_size=1, context_length=24,
            cross_learning=False, limit_prediction_length=True)
    if len(medians) != 1 or tuple(medians[0].shape) != (1, steps):
        raise ValueError('unexpected Chronos2 median shape')
    if len(quantiles) != 1 or tuple(quantiles[0].shape) != (1, steps, 1):
        raise ValueError('unexpected Chronos2 quantile shape')
    point = float(medians[0][0, steps - 1].item())
    if not math.isfinite(point):
        raise ValueError('nonfinite median forecast')
    return point


def arm_row(item, obs, point):
    row = item['row']; cutoff = item['cutoff']; target = month(row['target'])
    series = obs[(row['territory_id'], row['category'])]
    seasonal_month = target - 12
    seasonal = series.get(seasonal_month) if seasonal_month <= cutoff else None
    return {'key': list(key(row)), 'origin': str(row['origin']), 'target': str(row['target']),
            'horizon': int(row['horizon']), 'cutoff': ym(cutoff),
            'forecast_step_from_cutoff': target - cutoff, 'context_calendar_months': len(item['context']),
            'nonmissing_context_points': sum(math.isfinite(v) for v in item['context']),
            'context_sha256': context_digest(item['context']), 'actual': float(row['actual']),
            'pred_chronos2': point, 'pred_causal_lastavailable': series.get(cutoff),
            'pred_causal_seasonal': seasonal, 'cached_prophet_lag0': float(row['pred_prophet']),
            'cached_prophet_equal_information': False}


def install_watchdog(protocol, out):
    start = time.monotonic(); limit = protocol['smoke']; stopped = threading.Event()
    def monitor():
        while not stopped.wait(0.25):
            usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            rss = usage if platform.system() == 'Darwin' else usage * 1024
            elapsed = time.monotonic() - start
            if elapsed > limit['max_wall_seconds'] or rss > limit['rss_limit_bytes']:
                atomic(out / 'budget-stop.json', {'status': 'RESOURCE_LIMIT_STOP', 'elapsed_s': elapsed,
                       'maxrss_bytes': rss, 'wall_limit': limit['max_wall_seconds'], 'rss_limit': limit['rss_limit_bytes'],
                       'scientific_pass': False})
                os._exit(124)  # Only this runner; never touches other processes.
    threading.Thread(target=monitor, daemon=True).start()
    return stopped, start


def execute_smoke(protocol, weights, out, candidates, obs):
    # Never implicitly fetch weights or use the user's active GPU/MPS service.
    for name, expected in [('model.safetensors', protocol['model']['weight_sha256']),
                           ('config.json', protocol['model']['config_sha256'])]:
        if not (weights / name).is_file() or sha(weights / name) != expected:
            raise ValueError('missing or unpinned local weights/config; model loading refused')
    os.environ['HF_HUB_OFFLINE'] = '1'; os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['OMP_NUM_THREADS'] = '1'; os.environ['OPENBLAS_NUM_THREADS'] = '1'
    os.environ['MKL_NUM_THREADS'] = '1'; os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
    stop, started = install_watchdog(protocol, out)
    import torch
    from chronos import Chronos2Pipeline
    torch.set_num_threads(1); torch.set_num_interop_threads(1); torch.manual_seed(protocol['seed'])
    pipe = Chronos2Pipeline.from_pretrained(str(weights), device_map='cpu', torch_dtype=torch.float32,
                                          local_files_only=True)
    pipe.model.eval()
    if pipe.model.__class__.__name__ != 'Chronos2Model' or pipe.model.device.type != 'cpu':
        raise ValueError('wrong model class/device')
    records = []; calls = 0
    for h in protocol['horizons']:
        if h not in candidates: raise ValueError(f'no eligible smoke task for h{h}')
        item = candidates[h]; series = obs[(item['row']['territory_id'], item['row']['category'])]
        steps = month(item['row']['target']) - item['cutoff']
        # Three actual API calls per horizon: primary, deterministic repeat, future mutation.
        point = model_predict(pipe, item['context'], steps); calls += 1
        repeated = model_predict(pipe, item['context'], steps); calls += 1
        mutated = {m: v if m <= item['cutoff'] else v + 1e6 for m, v in series.items()}
        cutoff2, vals2 = causal_context(mutated, item['row']['origin'], protocol['release_lag_months'])
        if cutoff2 != item['cutoff'] or context_digest(vals2) != context_digest(item['context']):
            raise ValueError('future mutation changed causal input')
        changed = model_predict(pipe, vals2, steps); calls += 1
        if not (point == repeated == changed): raise ValueError('repeat/future invariant failed')
        record = arm_row(item, obs, point); record['deterministic_repeat_and_future_mutation_pass'] = True
        records.append(record); atomic(out / f'h{h}-checkpoint.json', record)
    stop.set(); usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {'status': 'BOUNDED_SMOKE_COMPLETED_NOT_FULL_ACTION05', 'model': protocol['model'],
              'model_verified_by_local_weight_config_sha': True, 'model_calls': calls, 'predictions': records,
              'elapsed_s': time.monotonic() - started, 'peak_rss_bytes': usage if platform.system() == 'Darwin' else usage * 1024,
              'scientific_pass': False, 'historical_asof_verified': False, 'independent_holdout': False,
              'cached_prophet_not_equal_information': True}
    atomic(out / 'smoke-results.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--mode', choices=['prepare', 'smoke'], default='prepare')
    p.add_argument('--weights-dir', type=Path)
    p.add_argument('--raw', type=Path, help='relocate byte-identical frozen raw input')
    p.add_argument('--paired', type=Path, help='relocate byte-identical frozen paired input')
    args = p.parse_args()
    if args.out.exists(): raise ValueError('new output directory required; never overwrite scientific run')
    protocol = json.loads(args.protocol.read_text()); args.out.mkdir(parents=True)
    for label in ('raw', 'paired'):
        if getattr(args, label) is not None:
            protocol['input_paths'][label] = str(getattr(args, label))
    obs, rows, contexts, candidates, summary = load_inputs(protocol)
    receipt = {'status': 'PREPARED_NO_MODEL_LOADED', 'protocol_sha256': sha(args.protocol),
               'runner_sha256': sha(Path(__file__)), 'input_sha256': protocol['input_sha256'],
               'requested_rows': len(rows), 'distinct_series_origins': len(contexts), 'eligibility_by_horizon': summary,
               'smoke_selection': {str(h): {'key': list(key(x['row'])), 'selection_hash': x['selection_hash'],
                                      'cutoff': ym(x['cutoff']), 'context_sha256': context_digest(x['context']),
                                      'forecast_step': month(x['row']['target']) - x['cutoff']} for h,x in candidates.items()},
               'scientific_pass': False, 'historical_asof_verified': False, 'independent_holdout': False}
    atomic(args.out / 'preparation.json', receipt)
    # Release full mask/context objects before loading 120M model in the 8GB host.
    del rows, contexts
    if args.mode == 'smoke':
        if args.weights_dir is None: raise ValueError('explicit pinned local weight directory required')
        result = execute_smoke(protocol, args.weights_dir, args.out, candidates, obs)
        receipt['status'] = result['status']
    print(json.dumps({'status': receipt['status'], 'requested_rows': receipt['requested_rows']}, indent=2))


if __name__ == '__main__':
    main()
