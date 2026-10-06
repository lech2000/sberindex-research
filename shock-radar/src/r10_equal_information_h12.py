"""Frozen exploratory H12 comparison with causal national conditioning.

The national path for future months is extrapolated only from observations
through origin-1. Historical publication vintages remain unavailable.
"""
import argparse
import concurrent.futures as cf
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys

import numpy as np
import pandas as pd

SEED = 20261004  # Preserve the original 120-series stratified pilot.
RAW_SHA = '9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
R9_SHA = 'b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44'
NATIONAL_SHA = '940efac0b7b0411ad4317d5126bd4006cf5a78a65861f2daeebc39bd7b59c030'
KEY = ['territory_id', 'category', 'horizon', 'origin', 'target']
MODELS = ['national_yoy_lag1', 'conditional_prophet_linear',
          'conditional_prophet_yearly3', 'own_prophet_linear', 'stored_prophet', 'last_value']
CFG = dict(growth='linear', yearly_seasonality=False, weekly_seasonality=False,
           daily_seasonality=False, n_changepoints=0, uncertainty_samples=0,
           seasonality_mode='multiplicative', seasonality_prior_scale=1.0)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def offset(month, steps):
    return str(pd.Period(month, freq='M') + steps)


def positive_base(national, month):
    if month not in national.index:
        raise ValueError('Missing national month: ' + month)
    value = float(national.loc[month])
    if not np.isfinite(value) or value <= 0:
        raise ValueError('Nonpositive/nonfinite national observation: ' + month)
    return value


def historical_inputs(own, national, origin, target):
    """Return frozen fit frames and a strictly past-only future national path."""
    history = own.loc[own.month <= origin].sort_values('month').copy()
    if len(history) < 7 or history.month.duplicated().any():
        raise ValueError('Insufficient/duplicate municipal training history')
    if history.month.iloc[-1] != origin:
        raise ValueError('Missing origin; no implicit last-observation fill')
    expected = pd.period_range(history.month.iloc[0], origin, freq='M').astype(str).tolist()
    if history.month.tolist() != expected or not np.isfinite(history.value).all():
        raise ValueError('Gapped/nonfinite municipal training history')
    h = pd.Period(target, freq='M').ordinal - pd.Period(origin, freq='M').ordinal
    if h != 12:
        raise ValueError('This frozen experiment supports H12 only')
    cutoff = offset(origin, -1)
    past = national.loc[national.index <= cutoff].sort_index()
    if past.index.duplicated().any():
        raise ValueError('Duplicate national month')
    growth = positive_base(past, cutoff) / positive_base(past, offset(cutoff, -12))
    levels = np.array([positive_base(past, offset(m, -1)) for m in history.month])
    future_level = positive_base(past, offset(target, -13)) * growth
    raw = pd.DataFrame({'ds': pd.to_datetime(history.month), 'y': history.value.to_numpy(float)})
    conditional = raw.assign(y=raw.y.to_numpy() / levels)
    return raw, conditional, future_level, growth, cutoff


def load_inputs(a):
    for path, expected in [(a.raw, RAW_SHA), (a.r9, R9_SHA), (a.national, NATIONAL_SHA)]:
        if sha(path) != expected:
            raise ValueError('Frozen input SHA mismatch: ' + str(path))
    raw = pd.read_parquet(a.raw)
    raw['territory_id'] = raw.territory_id.astype(str)
    raw['month'] = pd.PeriodIndex(raw.date, freq='M').astype(str)
    if raw.duplicated(['territory_id', 'category', 'month']).any() or not np.isfinite(raw.value).all():
        raise ValueError('Invalid frozen municipal panel')
    r9 = pd.read_parquet(a.r9)
    r9['territory_id'] = r9.territory_id.astype(str)
    if r9.duplicated(KEY).any():
        raise ValueError('Duplicate frozen forecast key')
    n = pd.read_parquet(a.national)
    if set(n.unit_measure) != {'млрд. руб.'} or set(n.freq) != {'Месяц'}:
        raise ValueError('National frequency/units differ')
    n['month'] = pd.to_datetime(n.period, utc=True).dt.tz_convert('Europe/Moscow').dt.tz_localize(None).dt.to_period('M').astype(str)
    n = n.loc[n.type == 'Всего']
    if n.month.duplicated().any() or not np.isfinite(n.value).all() or (n.value <= 0).any():
        raise ValueError('Invalid national panel')
    return raw, r9, n.set_index('month').value.sort_index()


def select_series(raw, r9):
    counts = r9.loc[r9.horizon.isin([1, 3, 6])].groupby(['territory_id', 'category']).size()
    complete = raw.groupby(['territory_id', 'category']).size()
    means = raw.loc[raw.month <= '2023-12'].groupby(['territory_id', 'category']).value.mean()
    eligible = means.loc[(complete.reindex(means.index) == 24) & (counts.reindex(means.index) == 18)].reset_index(name='train_mean')
    rng = np.random.default_rng(SEED)
    selected = []
    for category, group in eligible.groupby('category', sort=True):
        group = group.sort_values(['train_mean', 'territory_id']).reset_index(drop=True)
        for stratum, part in enumerate(np.array_split(np.arange(len(group)), 4)):
            if len(part) < 5:
                raise ValueError('Frozen size stratum too small')
            for idx in sorted(rng.choice(part, size=5, replace=False)):
                selected.append({'territory_id': str(group.iloc[idx].territory_id),
                                 'category': category, 'size_stratum_2023': stratum})
    if len(selected) != 120:
        raise ValueError('Frozen cohort size differs')
    return selected


def cohort(r9, selected):
    keys = {(r['territory_id'], r['category']) for r in selected}
    base = r9.loc[(r9.horizon == 12) & r9[['territory_id', 'category']].apply(tuple, axis=1).isin(keys)].copy()
    if len(base) != 720 or not (base.groupby(['territory_id', 'category']).size() == 6).all():
        raise ValueError('Incomplete original cohort H12 keys; do not reselect by error')
    return base.sort_values(KEY).reset_index(drop=True)


def prepare(a):
    if a.out.exists():
        raise FileExistsError('Prepare requires a new run directory')
    raw, r9, national = load_inputs(a)
    selected = select_series(raw, r9)
    base = cohort(r9, selected)
    # Validate the information contract before committing a protocol or fitting.
    for (tid, category), group in base.groupby(['territory_id', 'category']):
        own = raw.loc[(raw.territory_id == tid) & (raw.category == category)]
        for row in group.itertuples():
            train, _, _, _, _ = historical_inputs(own, national, row.origin, row.target)
            if train.y.iloc[-1] != row.pred_last or float(own.set_index('month').value.loc[row.target]) != row.actual:
                raise ValueError('Cached actual/origin differs from raw')
    protocol = {
        'recorded_before_fits': datetime.now(timezone.utc).isoformat(),
        'input_sha256': {'raw': RAW_SHA, 'r9': R9_SHA, 'national': NATIONAL_SHA},
        'code_sha256': sha(__file__), 'seed': SEED, 'n_series': 120, 'expected_rows': 720,
        'selection': 'Original R9 equal-information pilot: six categories × four 2023 mean quartiles × five series. Complete frozen availability mask. No error-based selection.',
        'selection_manifest': selected, 'target_months': sorted(base.target.unique().tolist()),
        'horizon': 12, 'expected_fits': 2160, 'workers': 4,
        'primary_model': 'national_yoy_lag1', 'primary_reference': 'conditional_prophet_linear',
        'primary_prophet_config': CFG, 'sensitivity': 'Same conditional model with yearly_seasonality=3, no best-model selection',
        'formula': 'y_origin × N(origin-1)/N(origin-13)',
        'conditional_training': 'z(t)=y(t)/N(t-1), t<=origin; fit Prophet on z; forecast target then multiply by extrapolated Nhat(target-1)',
        'future_national_path': 'cutoff=origin-1; growth=N(cutoff)/N(cutoff-12); Nhat(target-1)=N(target-13)*growth. H12 target-13=cutoff. Never use actual future national observations.',
        'information_contract': 'Both primary models use own history through origin and the same national history through origin-1. The conditional-last positive control exactly equals national_yoy_lag1.',
        'ci': 'Paired absolute-error difference; 10000 target-month block bootstrap draws seed20261004; six blocks, descriptive not confirmatory',
        'no_clipping': True, 'no_tuning': True, 'scientific_pass': False,
        'historical_asof_verified': False, 'independent_holdout': False,
        'limitations': ['Windows already viewed; post-discovery bounded exploratory test',
                       'Only seven to twelve own training months; no optimal Prophet claim',
                       'National vintage downloaded2026-10-05; historical revisions/publication dates unknown',
                       'Complete 120-series cohort is not the full panel and its municipality count differs from the Atlas',
                       'National total and local spending categories have different units; only ratios/conditional rescaling are interpreted',
                       'Six shared time blocks/categories are not independent scientific replications'],
        'stop_rule': 'Every model on every720key; failures invalidate paired acceptance. Report all categories, months and negative predictions. No parameter tuning after observing results.'}
    a.out.mkdir(parents=True)
    dump(a.out / 'protocol.json', protocol)
    print(json.dumps({'prepared': True, 'protocol_sha256': sha(a.out / 'protocol.json'), 'expected_fits': 2160, 'rows': 720}), flush=True)


def fit_task(task):
    from prophet import Prophet
    logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
    logging.getLogger('prophet').setLevel(logging.ERROR)
    key, raw, conditional, level, growth, cutoff, target = task
    values = {'national_yoy_lag1': float(raw.y.iloc[-1] * growth)}
    failures = []
    for name, frame, annual, scale in [
            ('conditional_prophet_linear', conditional, False, level),
            ('conditional_prophet_yearly3', conditional, 3, level),
            ('own_prophet_linear', raw, False, 1.0)]:
        try:
            config = dict(CFG, yearly_seasonality=annual)
            model = Prophet(**config)
            model.fit(frame, seed=SEED)
            value = float(model.predict(pd.DataFrame({'ds': [pd.Timestamp(target)]})).yhat.iloc[0] * scale)
            if not np.isfinite(value):
                raise ValueError('Nonfinite forecast')
            values[name] = value
        except Exception as exc:
            failures.append(dict(zip(KEY, key), model=name, error=str(exc)))
            values[name] = None
    return dict(zip(KEY, key), **values, national_cutoff=cutoff, training_months=len(raw)), failures


def paired(group, model, reference):
    err = np.abs(group.actual - group[model])
    ref = np.abs(group.actual - group[reference])
    blocks = pd.DataFrame({'target': group.target, 'difference': ref - err}).groupby('target').difference.agg(['sum', 'count'])
    ids = np.random.default_rng(SEED).integers(0, len(blocks), (10000, len(blocks)))
    boot = blocks['sum'].to_numpy()[ids].sum(1) / blocks['count'].to_numpy()[ids].sum(1)
    return {'model': model, 'reference': reference, 'rows': len(group), 'mae_model': float(err.mean()),
            'mae_reference': float(ref.mean()), 'benefit_mae': float((ref - err).mean()),
            'relative_improvement_percent': float(100 * (1 - err.mean() / ref.mean())),
            'benefit_ci95_target_months': np.quantile(boot, [.025, .975]).tolist(), 'month_blocks': len(blocks)}


def run(a):
    protocol = json.loads((a.out / 'protocol.json').read_text())
    if protocol['code_sha256'] != sha(__file__):
        raise ValueError('Code changed after protocol freeze')
    if (a.out / 'predictions.parquet').exists():
        raise FileExistsError('Existing predictions are immutable; new run required')
    raw, r9, national = load_inputs(a)
    base = cohort(r9, protocol['selection_manifest'])
    tasks = []
    future_checks = 0
    for row in base.itertuples(index=False):
        own = raw.loc[(raw.territory_id == row.territory_id) & (raw.category == row.category)]
        inputs = historical_inputs(own, national, row.origin, row.target)
        changed_own = own.copy()
        changed_own.loc[changed_own.month > row.origin, 'value'] = 999999999.0
        changed_national = national.copy()
        changed_national.loc[changed_national.index > inputs[4]] = 888888888.0
        mutant = historical_inputs(changed_own, changed_national, row.origin, row.target)
        assert inputs[0].equals(mutant[0]) and inputs[1].equals(mutant[1]) and inputs[2:] == mutant[2:]
        assert np.isclose(inputs[1].y.iloc[-1] * inputs[2], inputs[0].y.iloc[-1] * inputs[3], rtol=1e-12)
        future_checks += 1
        tasks.append((tuple(getattr(row, k) for k in KEY), *inputs[:4], inputs[4], row.target))
    rows, failures = [], []
    with cf.ProcessPoolExecutor(max_workers=a.workers) as executor:
        for i, (record, errors) in enumerate(executor.map(fit_task, tasks), 1):
            rows.append(record)
            failures.extend(errors)
            if i % 40 == 0:
                print(json.dumps({'tasks': i, 'total': len(tasks), 'fits_attempted': i * 3, 'failures': len(failures)}), flush=True)
    dump(a.out / 'failures.json', failures)
    pred = base[KEY + ['actual', 'pred_last', 'pred_prophet']].merge(pd.DataFrame(rows), on=KEY, validate='one_to_one')
    pred = pred.rename(columns={'pred_last': 'last_value', 'pred_prophet': 'stored_prophet'})
    pred.to_parquet(a.out / 'predictions.parquet', index=False)
    if failures or not np.isfinite(pred[MODELS + ['actual']]).all().all():
        raise ValueError('Failed/nonfinite fits; full paired run not accepted')
    result = [paired(pred, 'national_yoy_lag1', ref) for ref in MODELS if ref != 'national_yoy_lag1']
    cats = [dict(category=c, **paired(g, 'national_yoy_lag1', ref)) for c, g in pred.groupby('category') for ref in MODELS if ref != 'national_yoy_lag1']
    months = [{'target': t, 'model': m, 'rows': len(g), 'mae': float(np.abs(g.actual - g[m]).mean())} for t, g in pred.groupby('target') for m in MODELS]
    pd.DataFrame(cats).to_csv(a.out / 'by-category.csv', index=False)
    pd.DataFrame(months).to_csv(a.out / 'by-month.csv', index=False)
    import prophet
    metrics = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'COMPUTED_EXPLORATORY_EQUAL_INFORMATION',
               'scientific_pass': False, 'historical_asof_verified': False, 'independent_holdout': False,
               'rows': len(pred), 'n_series': 120, 'municipalities': int(pred.territory_id.nunique()),
               'fits_success': 2160, 'fits_expected': 2160, 'failures': 0,
               'training_months': [int(pred.training_months.min()), int(pred.training_months.max())],
               'future_mutation_and_conditional_last_checks': future_checks,
               'results': result, 'negative_predictions': {m: int((pred[m] < 0).sum()) for m in MODELS},
               'sha256': {'protocol': sha(a.out / 'protocol.json'), 'code': sha(__file__), 'predictions': sha(a.out / 'predictions.parquet')},
               'versions': {'python': sys.version, 'prophet': prophet.__version__, 'pandas': pd.__version__}}
    dump(a.out / 'metrics.json', metrics)
    print(json.dumps(metrics, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ['raw', 'r9', 'national', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if args.workers != 4:
        raise ValueError('Frozen worker budget is four')
    (prepare if args.prepare else run)(args)


if __name__ == '__main__':
    main()
