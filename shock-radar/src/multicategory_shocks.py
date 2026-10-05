"""Exploratory multivariate shock comparison; no economic ground truth claim.

Original implementation of signed/unsigned scores. Covariance shrinkage uses
sklearn's LedoitWolf. Peer inspiration and frozen protocol are in README.
"""
from pathlib import Path
import argparse
import hashlib
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

RAW_SHA = '9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
SEED = 20261004
METHODS = ['stouffer_down', 'stouffer_two_sided', 'max_absolute',
           'glr_two_sided', 'energy', 'mahalanobis']
FORMS = ['common_down', 'common_up', 'sparse_down', 'opposed', 'ramp_down']
FA = [.01, .03]


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def scores(z, precision):
    """z: municipality x time x category. No future data or zero filling."""
    z = np.asarray(z, float)
    if z.ndim != 3 or not np.isfinite(z).all():
        raise ValueError('Finite three-dimensional input required')
    d = z.shape[-1]
    net = z.sum(axis=-1) / np.sqrt(d)
    glr = np.zeros_like(net)
    for length in [1, 2, 3]:
        for t in range(length - 1, z.shape[1]):
            glr[:, t] = np.maximum(glr[:, t], net[:, t-length+1:t+1].sum(1)**2 / length)
    return {'stouffer_down': -net, 'stouffer_two_sided': np.abs(net),
            'max_absolute': np.max(np.abs(z), axis=-1), 'glr_two_sided': glr,
            'energy': np.mean(z*z, axis=-1),
            'mahalanobis': np.einsum('ntd,de,nte->nt', z, precision, z) / d}


def prepare(raw):
    raw = raw.copy()
    raw['tid'] = raw.territory_id.astype(str)
    raw['month'] = pd.PeriodIndex(raw.date, freq='M').astype(str)
    if raw.duplicated(['tid', 'category', 'month']).any() or (raw.value <= 0).any():
        raise ValueError('Duplicate or nonpositive observations')
    allcats = sorted(raw.category.unique())
    cats = [c for c in allcats if c != 'Все категории']
    months = [str(pd.Period('2023-01', freq='M') + k) for k in range(24)]
    table = raw.pivot(index='tid', columns=['month', 'category'], values='value')
    full = table.reindex(columns=pd.MultiIndex.from_product([months, allcats])).notna().all(axis=1)
    tids = table.index[full].tolist()
    values = table.loc[tids].reindex(columns=pd.MultiIndex.from_product([months, cats])).to_numpy().reshape(len(tids), 24, len(cats))
    change = np.diff(np.log(values), axis=1)
    local = change - np.median(change, axis=0, keepdims=True)
    train = local[:, :11]
    center = np.median(train, axis=1, keepdims=True)
    scale = 1.4826 * np.median(np.abs(train-center), axis=1, keepdims=True)
    keep = np.isfinite(scale).all((1, 2)) & (scale > 0).all((1, 2))
    z = (local[keep]-center[keep]) / scale[keep]
    fit = LedoitWolf().fit(z[:, :11].reshape(-1, len(cats)))
    cov = fit.covariance_
    diag = np.sqrt(np.diag(cov))
    corr = cov / np.outer(diag, diag)
    precision = np.linalg.inv(corr)
    return z, [t for t, yes in zip(tids, keep) if yes], months[1:], cats, corr, precision, {
        'complete_six_category_municipalities': len(tids), 'zero_scale_excluded': int((~keep).sum()),
        'retained_municipalities': int(keep.sum()), 'train_months': months[1:12],
        'covariance_shrinkage': float(fit.shrinkage_), 'correlation_eigenvalues': np.linalg.eigvalsh(corr).tolist()}


def noise(rng, n, t, corr, family):
    d = len(corr)
    e = rng.normal(size=(n, t, d)) @ np.linalg.cholesky(corr).T
    if family == 'student5':
        e *= np.sqrt(3 / rng.chisquare(5, size=(n, t, 1)))
    # Stationary AR(1), including the first month.
    out = e.copy()
    for k in range(1, t):
        out[:, k] = .3 * out[:, k-1] + np.sqrt(1-.3**2) * e[:, k]
    return out


def inject(base, idx, onset, direction, amplitude, form):
    z = base.copy()
    for lag in range(3):
        weight = (lag+1)/3 if form == 'ramp_down' else 1.0
        z[idx, onset+lag] += amplitude * weight * direction
    return z


def directions(rng, n, d, form):
    v = np.zeros((n, d))
    if form in ['common_down', 'common_up', 'ramp_down']:
        v[:] = (1 if form == 'common_up' else -1) / np.sqrt(d)
    else:
        for k in range(n):
            pair = rng.choice(d, 2, replace=False)
            v[k, pair[0]] = -1 if form == 'sparse_down' else -1/np.sqrt(2)
            if form == 'opposed':
                v[k, pair[1]] = 1/np.sqrt(2)
    return v


def paired_ci(rows, method, ref, family, form, amplitude, fa):
    cell = [x for x in rows if (x['family'], x['form'], x['amplitude'], x['target_fa']) == (family, form, amplitude, fa)]
    lookup = {(x['seed'], x['method']): x for x in cell}
    differences = np.array([lookup[(s, method)]['hits']-lookup[(s, ref)]['hits'] for s in sorted({x['seed'] for x in cell})], float)
    counts = np.array([lookup[(s, method)]['events'] for s in sorted({x['seed'] for x in cell})])
    rng = np.random.default_rng(SEED+99)
    ix = rng.integers(0, len(differences), (5000, len(differences)))
    values = differences[ix].sum(1) / counts[ix].sum(1)
    return {'method': method, 'reference': ref, 'family': family, 'form': form,
            'amplitude': amplitude, 'target_fa': fa, 'benefit_recall': float(differences.sum()/counts.sum()),
            'ci95_by_seed': np.quantile(values, [.025, .975]).tolist(), 'n_seed_blocks': len(differences)}


def synthetic(corr, precision, out):
    rows = []
    thresholds = {}
    for family in ['gaussian', 'student5']:
        cal = scores(noise(np.random.default_rng(SEED+1000), 2000, 12, corr, family), precision)
        thresholds[family] = {m: {str(f): float(np.quantile(s[:, 3:], 1-f)) for f in FA} for m, s in cal.items()}
    dump(out/'synthetic-thresholds.json', thresholds)  # frozen before held-out seeds
    for family in ['gaussian', 'student5']:
        for s in range(20):
            rng = np.random.default_rng(SEED+2000+s)
            base = noise(rng, 1000, 12, corr, family)
            null_scores = scores(base, precision)
            idx = rng.choice(1000, 200, replace=False)
            onset = rng.integers(3, 10, len(idx))
            for form in FORMS:
                direction = directions(rng, len(idx), len(corr), form)
                for amplitude in [2., 4., 6.]:
                    ss = scores(inject(base, idx, onset, direction, amplitude, form), precision)
                    for m in METHODS:
                        for f in FA:
                            threshold = thresholds[family][m][str(f)]
                            hit_matrix = ss[m][idx[:, None], onset[:, None]+np.arange(3)] > threshold
                            hit = hit_matrix.any(1)
                            delay = np.where(hit, hit_matrix.argmax(1), 3)
                            null = null_scores[m][:, 3:] > threshold
                            rows.append({'family': family, 'seed': s, 'form': form, 'amplitude': amplitude,
                                         'target_fa': f, 'method': m, 'events': len(idx), 'hits': int(hit.sum()),
                                         'null_alarm_cells': int(null.sum()), 'null_cells': int(null.size),
                                         'mean_delay_with_misses': float(delay.mean())})
            print(json.dumps({'phase': 'synthetic', 'family': family, 'seed_finished': s+1}), flush=True)
    pd.DataFrame(rows).to_csv(out/'synthetic-by-seed.csv', index=False)
    d = pd.DataFrame(rows)
    group = ['family', 'form', 'amplitude', 'target_fa', 'method']
    summary = d.groupby(group).agg(events=('events', 'sum'), hits=('hits', 'sum'),
                                  null_alarm_cells=('null_alarm_cells', 'sum'), null_cells=('null_cells', 'sum'),
                                  mean_delay_with_misses=('mean_delay_with_misses', 'mean')).reset_index()
    summary['recall'] = summary.hits/summary.events
    summary['observed_null_fa'] = summary.null_alarm_cells/summary.null_cells
    summary.to_csv(out/'synthetic-summary.csv', index=False)
    comparisons = [paired_ci(rows, m, ref, fam, 'opposed', 4., .03)
                   for fam in ['gaussian', 'student5'] for m in ['energy', 'mahalanobis']
                   for ref in ['stouffer_two_sided', 'max_absolute', 'glr_two_sided']]
    dump(out/'paired-comparisons.json', comparisons)
    return comparisons


def real(z, tids, months, precision, out, dictionary):
    ss = scores(z, precision)
    cal = [j for j, m in enumerate(months) if m in ['2024-01', '2024-02']]
    eval_idx = [j for j, m in enumerate(months) if m >= '2024-03']
    thresholds = {m: {str(f): float(np.quantile(s[:, cal], 1-f)) for f in FA} for m, s in ss.items()}
    dump(out/'real-thresholds.json', thresholds)
    names = pd.read_parquet(dictionary)
    name_col = next(c for c in ['name_short', 'name', 'municipality_name', 'territory_name'] if c in names)
    tid_col = next(c for c in ['territory_id', 'tid'] if c in names)
    selected = names[names[name_col].astype(str).str.strip().isin(['Орск', 'Оренбург', 'Новотроицк'])]
    name_map = dict(zip(selected[tid_col].astype(str), selected[name_col].astype(str)))
    if len(name_map) != 3 or not set(name_map).issubset(set(tids)):
        raise ValueError('Expected three exact dictionary names in the complete panel')
    rows, alerts = [], []
    for m in METHODS:
        for f in FA:
            for j in eval_idx:
                hot = ss[m][:, j] > thresholds[m][str(f)]
                alerts.append({'method': m, 'target_calibration_fa': f, 'month': months[j], 'selected': int(hot.sum()), 'n': len(tids)})
                for i, tid in enumerate(tids):
                    if tid in name_map:
                        rows.append({'municipality': name_map[tid], 'territory_id': tid, 'month': months[j],
                                     'method': m, 'target_calibration_fa': f, 'score': float(ss[m][i, j]),
                                     'threshold': thresholds[m][str(f)], 'alert': bool(hot[i]),
                                     'rank_descending': int(1+(ss[m][:, j] > ss[m][i, j]).sum()),
                                     'economic_truth': None, 'false_alarm_rate': None})
    pd.DataFrame(rows).to_csv(out/'real-cases.csv', index=False)
    pd.DataFrame(alerts).to_csv(out/'real-alert-volume.csv', index=False)
    np.savez_compressed(out/'private-vectors.npz', z=z, tids=np.array(tids), months=np.array(months))
    return {'real_case_municipalities': len(name_map), 'rows': len(rows), 'event_family': 'spring_flood_2024',
            'independent_real_event_test': False, 'economic_precision_recall': None}


def self_check():
    z = np.array([[[3., -3., 0.], [1., 1., 1.], [2., -2., 1.], [3., 1., -1.]]])
    p = np.eye(3)
    a = scores(z, p)
    assert a['stouffer_two_sided'][0, 0] == 0 and a['energy'][0, 0] == 6
    assert np.array_equal(a['energy'], a['mahalanobis'])
    b = z.copy(); b[:, 2:] = 999
    for m in METHODS:
        assert np.allclose(a[m][:, :2], scores(b, p)[m][:, :2])
    for m in METHODS:
        assert np.allclose(a[m], scores(z[:, :, ::-1], p)[m])
    try:
        scores(np.full((1, 1, 3), np.nan), p)
    except ValueError:
        pass
    else:
        raise AssertionError('Missing input accepted')
    print(json.dumps({'self_check': True, 'checks': ['opposite cancellation', 'identity covariance', 'future invariance all methods', 'category permutation', 'missing rejected']}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', type=Path); ap.add_argument('--dictionary', type=Path)
    ap.add_argument('--out', type=Path); ap.add_argument('--self-check', action='store_true')
    a = ap.parse_args()
    if a.self_check:
        self_check(); return
    if a.out.exists():
        raise FileExistsError('New run directory required')
    if sha(a.raw) != RAW_SHA:
        raise ValueError('Frozen raw mismatch')
    a.out.mkdir(parents=True)
    protocol = {'recorded_before_results': datetime.now(timezone.utc).isoformat(), 'run_id': 'D04_multicategory_20261004',
                'client_date': '2026-10-04', 'raw_sha256': RAW_SHA, 'code_sha256': sha(__file__),
                'methods': METHODS, 'primary_categories': 'five nonaggregate; exclude overlapping All categories',
                'real_signal': 'adjacent monthly log change minus contemporaneous category median; per-MO median/MAD fitted Feb-Dec2023',
                'covariance': 'LedoitWolf on 2023 standardized residuals, diagonal-normalized correlation; no future fit',
                'real_threshold_calibration': 'Jan-Feb2024 only; evaluation Mar-Dec2024',
                'target_false_alarm_rates': FA, 'real_false_alarm_rate': None,
                'synthetic': {'families': ['Gaussian', 'Student-t5'], 'correlation': 'empirical training correlation', 'AR1': .3,
                              'calibration': 'independent null seed+1000; discard first three months for GLR warmup',
                              'test_seeds': 20, 'municipalities_per_seed': 1000, 'events_per_seed': 200,
                              'forms': FORMS, 'effect': 'L2-normalized directions; vector amplitudes 2/4/6 standardized units; 3 months',
                              'matching': 'any alert in onset..onset+2, no early warning claim',
                              'primary_cell': 'opposed amplitude4 targetFA3%; paired CI by seed vs unsigned Stouffer, maxabs, unsigned GLR'},
                'known_real_examples': ['Орск', 'Оренбург', 'Новотроицк'], 'independent_holdout': False,
                'scientific_pass': False, 'limits': ['Exploratory post-discovery specification; real flood examples already viewed',
                 'Simulated event truth only; empirical-correlation noise does not prove real-event power',
                 'Equal calibration FA targets, not forced equal realized held-out FA; publish achieved null FA',
                 'Real targetFA labels are calibration quantiles, not known economic false alarms',
                 'Contemporaneous cross-sectional centering removes national common shocks',
                 'Monthly changes are post-observation detection, not historical as-of forecasting']}
    dump(a.out/'protocol.json', protocol)
    z, tids, months, cats, corr, precision, prep = prepare(pd.read_parquet(a.raw))
    dump(a.out/'training.json', dict(prep, categories=cats, correlation=corr.tolist()))
    real_result = real(z, tids, months, precision, a.out, a.dictionary)
    comparisons = synthetic(corr, precision, a.out)
    import sklearn
    metrics = {'status': 'EXPLORATORY_SYNTHETIC_AND_DESCRIPTIVE_REAL', 'training': prep, 'real': real_result,
               'primary_paired_comparisons': comparisons, 'scientific_pass': False,
               'versions': {'numpy': np.__version__, 'pandas': pd.__version__, 'sklearn': sklearn.__version__}}
    dump(a.out/'metrics.json', metrics)
    dump(a.out/'manifest.json', {p.name: sha(p) for p in sorted(a.out.iterdir()) if p.is_file() and p.name != 'manifest.json'})
    print(json.dumps({'complete': True, 'municipalities': len(tids), 'scientific_pass': False}), flush=True)


if __name__ == '__main__':
    main()
