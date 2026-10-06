"""Post hoc scale sensitivity; never modifies the frozen H12 primary protocol."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def training_scales(raw, predictions):
    raw = raw.copy()
    raw['territory_id'] = raw.territory_id.astype(str)
    raw['month'] = pd.PeriodIndex(raw.date, freq='M')
    if raw.duplicated(['territory_id', 'category', 'month']).any():
        raise ValueError('Duplicate municipal input keys')
    histories = {(str(k[0]), k[1]): g.sort_values('month')
                 for k, g in raw.groupby(['territory_id', 'category'])}
    scales = []
    for row in predictions.itertuples():
        origin = pd.Period(row.origin, freq='M')
        h = histories[str(row.territory_id), row.category]
        h = h.loc[h.month <= origin]
        if len(h) != row.training_months:
            raise ValueError('Own training window differs from frozen pilot')
        value = float(h.value.mean())
        if not np.isfinite(value) or value <= 0:
            raise ValueError('Training mean must be finite and positive')
        scales.append(value)
    return np.asarray(scales)


def summarize(predictions, scales, reference, normalized, seed):
    candidate_error = np.abs(predictions.actual.to_numpy() - predictions.national_yoy_lag1.to_numpy())
    reference_error = np.abs(predictions.actual.to_numpy() - predictions[reference].to_numpy())
    if normalized:
        candidate_error = candidate_error / scales
        reference_error = reference_error / scales
    candidate_mae, reference_mae = float(candidate_error.mean()), float(reference_error.mean())
    table = predictions[['territory_id', 'category', 'target']].copy()
    table['candidate_error'], table['reference_error'] = candidate_error, reference_error
    table['benefit'] = reference_error - candidate_error
    months = table.groupby('target').benefit.mean()
    assert len(months) == 6 and table.groupby('target').size().nunique() == 1
    draws = np.random.default_rng(seed).integers(0, 6, size=(10000, 6))
    ci = np.quantile(months.to_numpy()[draws].mean(axis=1), [.025, .975])
    series = table.groupby(['territory_id', 'category'])[['candidate_error', 'reference_error']].mean()
    return {'reference': reference, 'rows': len(table), 'series': len(series),
            'loss': 'absolute_error / own_training_mean' if normalized else 'absolute_error',
            'candidate_loss': candidate_mae, 'reference_loss': reference_mae,
            'relative_improvement_percent': 100 * (reference_mae - candidate_mae) / reference_mae,
            'benefit_ci95_target_months': ci.tolist(),
            'series_wins': int((series.candidate_error < series.reference_error).sum()),
            'series_losses': int((series.candidate_error > series.reference_error).sum()),
            'series_ties': int((series.candidate_error == series.reference_error).sum())}


def main():
    parser = argparse.ArgumentParser()
    for key in ('run', 'raw', 'out'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Use a new output file for a new sensitivity run')
    digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    protocol = json.loads((args.run / 'protocol.json').read_text())
    metrics = json.loads((args.run / 'metrics.json').read_text())
    assert digest(args.raw) == protocol['input_sha256']['raw']
    assert digest(args.run / 'predictions.parquet') == metrics['sha256']['predictions']
    pred = pd.read_parquet(args.run / 'predictions.parquet')
    raw = pd.read_parquet(args.raw)
    assert len(pred) == 720 and not pred.duplicated(['territory_id', 'category', 'origin', 'target']).any()
    scales = training_scales(raw, pred)
    future = raw.copy()
    future['value'] = future.value.astype(float)
    future.loc[future.date > '2023-12', 'value'] = 1e12
    np.testing.assert_array_equal(scales, training_scales(future, pred))
    results = []
    for reference in ('conditional_prophet_linear', 'last_value'):
        for keep_total in (True, False):
            mask = np.ones(len(pred), dtype=bool) if keep_total else pred.category.to_numpy() != 'Все категории'
            for normalized in (False, True):
                result = summarize(pred.loc[mask], scales[mask], reference, normalized, protocol['seed'])
                result['includes_all_categories_aggregate'] = keep_total
                results.append(result)
    receipt = {'checked_at': datetime.now(timezone.utc).isoformat(),
               'status': 'POST_HOC_SCALE_SENSITIVITY', 'scientific_pass': False,
               'purpose': 'Quantify dependence of pooled MAE on aggregate category and series scale, after viewing primary outcomes.',
               'not_primary_replacement': True, 'historical_asof_verified': False,
               'future_training_scale_mutation_checks': len(pred), 'results': results,
               'raw_sha256': digest(args.raw), 'predictions_sha256': digest(args.run / 'predictions.parquet'),
               'code_sha256': digest(__file__),
               'limits': 'Same 720 selected forecast keys, previously viewed window. Six-month block intervals descriptive. Own training mean normalization is not MASE and not household weighting.'}
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
