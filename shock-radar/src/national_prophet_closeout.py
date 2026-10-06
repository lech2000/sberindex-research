"""Fresh, bounded Prophet/national comparison on predeclared historical keys."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
import numpy as np
import pandas as pd
from radar_external_checks import load_raw, paired, sha, dump, national_factor

SEED = 20261006
KEY = ['territory_id', 'category', 'horizon', 'origin', 'target']


def national_regressor(national, dates, origin, lag=1):
    cutoff = str(pd.Period(origin, freq='M')-lag)
    history = national.loc[national.index <= cutoff]
    growth = np.log(history[cutoff]/history[str(pd.Period(cutoff, freq='M')-12)])
    out = []
    for date in dates:
        month = pd.Period(date, freq='M')
        if str(month) <= origin:
            out.append(float(np.log(history[str(month-lag)])))
        else:
            delta = month.ordinal-pd.Period(origin, freq='M').ordinal
            out.append(float(np.log(history[cutoff])+delta*growth/12))
    return np.array(out)


def training_frame(own, national, origin):
    own = own.loc[own.index <= origin].sort_index()
    if len(own) < 6 or not np.isfinite(own).all() or (own <= 0).any():
        raise ValueError('Incomplete/nonpositive own history')
    dates = pd.to_datetime(own.index+'-01')
    return pd.DataFrame({'ds': dates, 'y': own.to_numpy(float),
                         'national_log': national_regressor(national, dates, origin)})


def fresh_prediction(own, national, origin, target, exogenous):
    from prophet import Prophet
    train = training_frame(own, national, origin)
    model = Prophet(growth='linear', yearly_seasonality=False,
        weekly_seasonality=False, daily_seasonality=False,
        n_changepoints=3, uncertainty_samples=0)
    future = pd.DataFrame({'ds': pd.to_datetime([target+'-01'])})
    if exogenous:
        model.add_regressor('national_log', standardize=True, mode='additive')
        future['national_log'] = national_regressor(national, future.ds, origin)
    else:
        train = train.drop(columns=['national_log'])
    model.fit(train, seed=SEED)
    pred = float(model.predict(future).yhat.iloc[0])
    if not np.isfinite(pred):
        raise ValueError('Nonfinite fit result')
    return pred


def run(a):
    import prophet
    proto = json.loads(a.protocol.read_text())
    for k in ['raw', 'r9', 'national']:
        if sha(getattr(a, k)) != proto['input_sha256'][k]:
            raise ValueError('Frozen input mismatch: '+k)
    if a.out.exists():
        raise FileExistsError('New run directory required')
    raw = load_raw(a.raw)
    n = pd.read_parquet(a.national)
    n['month'] = pd.to_datetime(n.period, utc=True).dt.tz_convert('Europe/Moscow').dt.to_period('M').astype(str)
    n = n.loc[n.type == 'Всего'].set_index('month').value.sort_index().astype(float)
    if n.index.duplicated().any() or not np.isfinite(n).all() or (n <= 0).any():
        raise ValueError('Invalid national input')
    r9 = pd.read_parquet(a.r9)
    r9.territory_id = r9.territory_id.astype(str)
    r9 = r9.loc[(r9.horizon == 12) & r9.target.isin(proto['targets'])].copy()
    assert not r9.duplicated(KEY).any()
    cats = sorted(raw.category.unique())
    counts = r9.groupby(['territory_id', 'category']).size().unstack('category')
    eligible = counts.loc[(counts[cats] == 6).all(axis=1)].index.tolist()
    selected = sorted(eligible, key=lambda t: hashlib.sha256(f'{SEED}:{t}'.encode()).hexdigest())[:20]
    if len(selected) != 20:
        raise ValueError('Insufficient predeclared complete IDs')
    q = r9.loc[r9.territory_id.isin(selected)].sort_values(KEY).copy()
    assert len(q) == 720
    wide = raw.pivot(index=['territory_id', 'category'], columns='month', values='value')
    logging.getLogger('cmdstanpy').setLevel(logging.ERROR)
    logging.getLogger('prophet').setLevel(logging.ERROR)
    a.out.mkdir(parents=True)
    dump(a.out/'protocol.json', proto)
    dump(a.out/'selection.json', {'municipality_ids': selected,
        'eligible_municipality_ids': len(eligible), 'categories': cats,
        'series': 120, 'rows': len(q), 'rule': proto['series_selection']})
    rows, mutation_checks = [], 0
    started = time.monotonic()
    for j, ((tid, cat), group) in enumerate(q.groupby(['territory_id', 'category'])):
        own = wide.loc[(tid, cat)].dropna().astype(float)
        for row in group.itertuples():
            assert own[row.target] == row.actual and own[row.origin] == row.pred_last
            plain = fresh_prediction(own, n, row.origin, row.target, False)
            national = fresh_prediction(own, n, row.origin, row.target, True)
            record = {k: getattr(row, k) for k in KEY}
            record.update({'actual': float(row.actual), 'stored_prophet': float(row.pred_prophet),
                'fresh_plain_prophet': plain, 'national_prophet': national,
                'national_yoy_lag1': float(own[row.origin]*national_factor(n, row.origin, 1)),
                'training_observations': int((own.index <= row.origin).sum())})
            rows.append(record)
            if j == 0:
                modified = own.copy(); modified.loc[modified.index > row.origin] *= 100
                altered = n.copy()
                cutoff = str(pd.Period(row.origin, freq='M')-1)
                altered.loc[altered.index > cutoff] = altered.loc[altered.index > cutoff]*100+12345
                pd.testing.assert_frame_equal(training_frame(own, n, row.origin),
                                               training_frame(modified, altered, row.origin))
                np.testing.assert_array_equal(
                    national_regressor(n, [row.target+'-01'], row.origin),
                    national_regressor(altered, [row.target+'-01'], row.origin))
                for exogenous, expected in [(False, plain), (True, national)]:
                    np.testing.assert_allclose(fresh_prediction(modified, altered, row.origin, row.target, exogenous),
                                               expected, rtol=0, atol=1e-8)
                    mutation_checks += 1
        if (j+1) % 20 == 0:
            dump(a.out/'progress.json', {'series_completed': j+1, 'series_total': 120,
                'forecasts_completed': len(rows), 'status': 'RUNNING'})
            print(json.dumps({'series_completed': j+1, 'rows': len(rows)}), flush=True)
    p = pd.DataFrame(rows)
    assert len(p) == 720 and not p.duplicated(KEY).any()
    models = ['fresh_plain_prophet', 'national_prophet', 'national_yoy_lag1', 'stored_prophet']
    if not np.isfinite(p[models+['actual']]).all().all():
        raise ValueError('Incomplete comparison mask; no silent exclusions')
    comparisons = [paired(p, m, ref) for m, ref in [
        ('national_prophet', 'fresh_plain_prophet'),
        ('national_yoy_lag1', 'national_prophet'),
        ('national_yoy_lag1', 'fresh_plain_prophet')]]
    bycat = [{'category': cat, 'n': len(g),
        'mae': {m: float(np.abs(g.actual-g[m]).mean()) for m in models},
        'comparisons': [paired(g, 'national_yoy_lag1', 'national_prophet'),
                         paired(g, 'national_prophet', 'fresh_plain_prophet')]}
        for cat, g in p.groupby('category')]
    metrics = {'status': 'COMPUTED_EXPLORATORY', 'rows': len(p), 'series': 120,
        'municipalities': 20, 'models': models,
        'mae': {m: float(np.abs(p.actual-p[m]).mean()) for m in models},
        'comparisons': comparisons, 'by_category': bycat,
        'fresh_plain_vs_stored_max_abs_difference': float(np.abs(p.fresh_plain_prophet-p.stored_prophet).max()),
        'checks': {'raw_actual_and_last_keys': len(p),
            'future_mutation_fresh_refits': mutation_checks, 'fit_failures': 0, 'same_keys': True},
        'new_fits': len(p)*2+mutation_checks,
        'elapsed_seconds': float(time.monotonic()-started),
        'versions': {'prophet': prophet.__version__, 'numpy': np.__version__, 'pandas': pd.__version__},
        'scientific_pass': False, 'independent_holdout': False, 'historical_asof_verified': False,
        'limits': proto['limits']}
    p.to_parquet(a.out/'predictions.parquet', index=False)
    dump(a.out/'metrics.json', metrics)
    dump(a.out/'progress.json', {'series_completed': 120, 'forecasts_completed': len(p),
                                'status': 'COMPUTED_EXPLORATORY'})
    dump(a.out/'manifest.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_sha256': {k: sha(getattr(a, k)) for k in ['raw', 'r9', 'national']},
        'code_sha256': sha(__file__), 'protocol_sha256': sha(a.protocol),
        'dependency_code_sha256': sha(Path(__file__).with_name('radar_external_checks.py')),
        'files': {p.name: sha(p) for p in a.out.iterdir() if p.is_file()}})
    print(json.dumps({k: v for k, v in metrics.items() if k not in ['by_category', 'limits']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ['raw', 'r9', 'national', 'protocol', 'out']:
        ap.add_argument('--'+name, type=Path, required=True)
    run(ap.parse_args())
