#!/usr/bin/env python3
"""Frozen category-seasonal hypothesis on the exact, already viewed R9 mask.

Origin means last included observation month, not an audited publication date.
No fit, clipping, tuned ensemble weight or fabricated forecast for horizon 12.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import numpy as np
import pandas as pd
from r8_monthblock_compare import _cluster_bootstrap
from r9_pair_intervals import KEY, validate

RAW_SHA = '9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
R9_SHA = 'b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44'
EXPECTED = {1: 73728, 3: 73656, 6: 73578, 12: 73608}
SEED = 20261003
REPS = 10000
MODELS = ['pred_category_seasonal', 'pred_prophet', 'pred_last',
          'pred_ensemble_half', 'pred_balanced_prior']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prepare(raw):
    d = raw.copy()
    req = ['territory_id', 'category', 'date', 'value']
    if not set(req) <= set(d) or d[req].isna().any().any():
        raise ValueError('Missing source key or value; no imputation')
    d['territory_id'] = d.territory_id.astype(str)
    d['month'] = pd.PeriodIndex(d.date, freq='M').astype(str)
    if d.duplicated(['territory_id', 'category', 'month']).any():
        raise ValueError('Duplicate source series/month')
    if not np.isfinite(d.value).all() or (d.value < 0).any():
        raise ValueError('Nonfinite or negative spending')
    return d


def predict(raw, mask):
    """Only historical category months and the series origin value are read."""
    d = prepare(raw)
    med = d.groupby(['category', 'month']).value.median()
    nobs = d.groupby(['category', 'month']).size()
    wide = d.pivot(index=['territory_id', 'category'], columns='month', values='value')
    out = mask.copy()
    out['prior_origin'] = (pd.PeriodIndex(out.origin, freq='M') - 12).astype(str)
    out['prior_target'] = (pd.PeriodIndex(out.target, freq='M') - 12).astype(str)
    for col in ['prior_origin', 'prior_target']:
        if (out[col] > out.origin).any():
            raise ValueError('Seasonal reference month after origin')
    def fetch(column, source):
        idx = pd.MultiIndex.from_arrays([out.category, out[column]])
        return source.reindex(idx).to_numpy(dtype=float)
    den, num = fetch('prior_origin', med), fetch('prior_target', med)
    out['prior_origin_median'] = den
    out['prior_target_median'] = num
    out['prior_origin_n'] = fetch('prior_origin', nobs)
    out['prior_target_n'] = fetch('prior_target', nobs)
    valid = np.isfinite(den) & np.isfinite(num) & (den > 0)
    out['exclusion'] = np.where(valid, '', 'missing_or_nonpositive_prior_base')
    ratio = np.divide(num, den, out=np.full(len(out), np.nan), where=valid)
    out['pred_category_seasonal'] = out.pred_last * ratio
    out['pred_ensemble_half'] = (out.pred_prophet + out.pred_category_seasonal) / 2
    # Declared sensitivity: same municipalities observed in both prior months.
    out['pred_balanced_prior'] = np.nan
    for (cat, po, pt), group in out.groupby(['category', 'prior_origin', 'prior_target']):
        if po not in wide.columns or pt not in wide.columns:
            continue
        pair = wide.xs(cat, level='category')[[po, pt]].dropna()
        if pair.empty:
            continue
        m0, m1 = float(pair[po].median()), float(pair[pt].median())
        if m0 > 0:
            out.loc[group.index, 'pred_balanced_prior'] = group.pred_last * (m1 / m0)
    return out


def verify_raw_match(raw, mask):
    d = prepare(raw)
    source = d.set_index(['territory_id', 'category', 'month']).value
    for column, month in [('actual', 'target'), ('pred_last', 'origin')]:
        keys = pd.MultiIndex.from_arrays([mask.territory_id, mask.category, mask[month]])
        vals = source.reindex(keys).to_numpy(dtype=float)
        if not np.array_equal(vals, mask[column].to_numpy(dtype=float)):
            raise ValueError(f'R9 {column} does not exactly match raw {month}')


def paired_summary(g, seed=SEED, reps=REPS):
    if g.empty or not np.isfinite(g[MODELS + ['actual']].to_numpy(dtype=float)).all():
        raise ValueError('Empty or nonfinite paired comparison')
    errors = {m: (g.actual - g[m]).abs() for m in MODELS}
    keys = list(g[KEY].itertuples(index=False, name=None))
    mae = {m: float(e.mean()) for m, e in errors.items()}
    comparisons = {}
    for j, (candidate, ref) in enumerate([
        ('pred_category_seasonal', 'pred_prophet'),
        ('pred_category_seasonal', 'pred_last'),
        ('pred_ensemble_half', 'pred_prophet'),
        ('pred_balanced_prior', 'pred_category_seasonal'),
    ]):
        diff = errors[ref] - errors[candidate]
        name = candidate + '_vs_' + ref
        monthly = g.assign(benefit=diff).groupby('target').benefit.agg(['sum', 'count'])
        total, n = float(diff.sum()), len(g)
        comparisons[name] = {
            'benefit': float(diff.mean()),
            'relative_mae_reduction_pct': 100 * (mae[ref] - mae[candidate]) / mae[ref] if mae[ref] else None,
            'row_win_share': float((diff > 0).mean()),
            'month_block_ci': _cluster_bootstrap(keys, diff.tolist(), lambda k: str(k[3]), reps, random.Random(seed + j)),
            'leave_one_month_out': {str(t): float((total - r['sum']) / (n - r['count'])) for t, r in monthly.iterrows()} if len(monthly) > 1 else {},
        }
    per_month = []
    for t, x in g.groupby('target'):
        per_month.append({'target': str(t), 'n': len(x), 'mae': {m: float((x.actual-x[m]).abs().mean()) for m in MODELS}})
    per_category = []
    for c, x in g.groupby('category'):
        e = {m: float((x.actual-x[m]).abs().mean()) for m in MODELS}
        per_category.append({'category': str(c), 'n': len(x), 'mae': e,
            'seasonal_gain_vs_last_pct': 100*(e['pred_last']-e['pred_category_seasonal'])/e['pred_last'],
            'seasonal_gain_vs_prophet_pct': 100*(e['pred_prophet']-e['pred_category_seasonal'])/e['pred_prophet']})
    return {'n': len(g), 'n_month_blocks': g.target.nunique(), 'mae': mae,
            'comparisons': comparisons, 'by_target': per_month, 'by_category': per_category}


def protocol():
    return {'method': 'last(series,origin) * median(category,target-12) / median(category,origin-12)',
        'median_cohort': 'all observed raw municipalities at each historical category/month; no zero fill',
        'sensitivity': 'same prior municipalities observed in both reference months',
        'origin_contract': 'origin=target-h; exactly R9 training through observation origin, no assumed release lag',
        'horizons': [1,3,6], 'unsupported_horizon': 12,
        'target_window': ['2024-07','2024-08','2024-09','2024-10','2024-11','2024-12'],
        'fixed_ensemble': '0.5 seasonal + 0.5 stored Prophet; no optimization or selection',
        'interval': 'paired absolute-error difference; target-month cluster bootstrap, 10000 resamples, percentile 95%',
        'seed': SEED, 'no_december': 'declared sensitivity, five remaining month blocks',
        'raw_sha256': RAW_SHA, 'r9_sha256': R9_SHA,
        'scientific_pass': False, 'independent_new_holdout': False, 'historical_asof_verified': False,
        'limits': ['User already inspected this target window before this protocol; this is an exploratory audit, not preregistration of unseen data',
            'One prior year (2023); no evidence of persistence across multiple annual cycles',
            'Six nearby temporal blocks; intervals describe this sample, not a confirmatory significance test',
            'Stored Prophet disables yearly seasonality; no claim against a tuned seasonal Prophet',
            'Category pooling uses shared past information; comparison with a univariate model is an information-set difference',
            'Observed category medians may change composition; balanced historical cohort is a sensitivity only',
            'All categories is an aggregate overlapping other categories; six categories are not independent replications',
            'Source MAE units retained; not asserted monetary rubles; no causal economic interpretation',
            'No vintage/publication-time evidence; observation-calendar causality is not historical as-of verification']}


def self_check():
    raw = pd.DataFrame([
        {'territory_id': t, 'category': 'c', 'date': m, 'value': v}
        for t in ['a','b'] for m,v in [('2023-01',10),('2023-02',20),('2024-01',100),('2024-02',180)]])
    mask = pd.DataFrame([dict(territory_id='a', category='c', origin='2024-01', target='2024-02', horizon=1,
        actual=180., pred_last=100., pred_prophet=170., pred_seasonal=20., pred_mean=50.)])
    verify_raw_match(raw,mask)
    p = predict(raw,mask)
    assert p.pred_category_seasonal.iloc[0] == 200 and p.pred_ensemble_half.iloc[0] == 185
    changed = raw.copy(); changed.loc[changed.date>'2024-01','value'] = 999999
    assert predict(changed,mask).pred_category_seasonal.iloc[0] == 200
    extended = pd.concat([raw,pd.DataFrame([dict(territory_id='a',category='c',date='2025-02',value=1234567)])],ignore_index=True)
    assert predict(extended,mask).pred_category_seasonal.iloc[0] == 200
    zero = raw.copy(); zero.loc[zero.date=='2023-01','value'] = 0
    assert predict(zero,mask).pred_category_seasonal.isna().all()
    missing = raw[raw.date!='2023-01']; assert predict(missing,mask).pred_category_seasonal.isna().all()
    for bad in [pd.concat([raw,raw.iloc[:1]],ignore_index=True),raw.assign(value=np.inf)]:
        try: prepare(bad)
        except ValueError: pass
        else: raise AssertionError('invalid raw accepted')
    try: verify_raw_match(raw,mask.assign(pred_last=101))
    except ValueError: pass
    else: raise AssertionError('mismatched origin accepted')
    many = pd.concat([p.assign(target=t,origin=str(pd.Period(t,freq='M')-1)) for t in ['2024-02','2024-03']],ignore_index=True)
    a,b = paired_summary(many,reps=100),paired_summary(many,reps=100)
    assert a==b and a['comparisons']['pred_category_seasonal_vs_pred_prophet']['benefit']==-10
    print(json.dumps({'self_check':True,'checks':['known seasonal ratio','fixed half ensemble','post-origin mutation invariance','future-extension invariance','zero and missing base abstention','duplicate and nonfinite reject','exact origin-value mismatch reject','paired sign and deterministic CI']}))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',type=Path);ap.add_argument('--predictions',type=Path);ap.add_argument('--outdir',type=Path)
    ap.add_argument('--self-check',action='store_true');a=ap.parse_args()
    if a.self_check:self_check();return
    if not a.raw or not a.predictions or not a.outdir:ap.error('raw, predictions, outdir required')
    if a.outdir.exists():raise FileExistsError('new run only')
    if sha(a.raw)!=RAW_SHA or sha(a.predictions)!=R9_SHA:raise ValueError('frozen input SHA mismatch')
    raw,mask=pd.read_parquet(a.raw),pd.read_parquet(a.predictions);validate(mask)
    if mask.groupby('horizon').size().to_dict()!=EXPECTED:raise ValueError('exact R9 mask changed')
    verify_raw_match(raw,mask)
    a.outdir.mkdir(parents=True)
    cfg=protocol();(a.outdir/'protocol.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n')
    result=predict(raw,mask)
    results=[]
    for h,g in result.groupby('horizon'):
        ok=g.exclusion.eq('')
        if int(h)==12:
            if ok.any():raise ValueError('unexpected prior-year base for horizon12')
            results.append({'horizon':12,'n_r9':len(g),'n_common':0,'excluded':len(g),'status':'NA: origin-12 is outside source history'})
            continue
        if not ok.all():raise ValueError('short-horizon exact mask lost rows')
        results.append({'horizon':int(h),'n_r9':len(g),'n_common':len(g),'excluded':0,
            'all_months':paired_summary(g,SEED+int(h)*10),
            'without_december':paired_summary(g[g.target!='2024-12'],SEED+int(h)*10+100)})
    result.to_parquet(a.outdir/'predictions.parquet',index=False)
    metrics={**cfg,'checked_at':datetime.now(timezone.utc).isoformat(),'results':results,
        'provenance':{'code_sha256':sha(__file__),'bootstrap_code_sha256':sha(Path(__file__).with_name('r8_monthblock_compare.py')),
        'predictions_sha256':sha(a.outdir/'predictions.parquet'),'python':sys.version,'pandas':pd.__version__,
        'command':['python','shock-radar/src/r9_category_seasonal.py','--raw','<frozen-8_consumption.parquet>',
        '--predictions','<audited-R9-predictions.parquet>','--outdir','<NEW-run-directory>']}}
    (a.outdir/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'computed_exploratory','scientific_pass':False,'rows_supported':int(result.exclusion.eq('').sum()),'results':[{'horizon':x['horizon'],'n_common':x['n_common'],'mae':x.get('all_months',{}).get('mae')} for x in results]},ensure_ascii=False))
if __name__=='__main__':main()
