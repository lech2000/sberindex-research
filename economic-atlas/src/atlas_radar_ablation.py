"""Frozen, supplementary Atlas/Radar ablation. Never overwrites A8/R8.

Protocol: runs/Atlas_Radar_ablation_20261006/protocol.json.
No inference of unseen holdout, historical vintage, or scientific gate PASS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import platform

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits


SEED = 20261006
ARMS = ('base2023', 'base_plus_radar', 'base_plus_raw_yoy')
ALL = 'Все категории'
EXPECTED = {
    'panel': '8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93',
    'dictionary': 'f25088539a896cdc834d77c8792d0e6ac909d8649b06d65f69215ce12a8eaf4a',
    'population': '4b69d43dd113591c12cee61df39d318200ff42b83e52a28593930e7ee0b34dbf',
    'wages': '6c350c9356f8def9d190b56e2bacaa55960ae2c2aa0eda8d25720db44bfadbe3',
    'employment': 'f643b394c11758f5d28e465380e263943c5e5e9e312a468daedca95b7e2f87d7',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n')


def cube_from_panel(panel, end='2024-09'):
    p = panel[panel.ym <= end].copy()
    assert not p.duplicated(['territory_id', 'ym', 'category']).any(), 'duplicate panel key'
    ids = np.sort(p.territory_id.unique())
    months = sorted(p.ym.unique())
    cats = sorted(p.category.unique())
    idx = pd.MultiIndex.from_product([ids, months], names=['territory_id', 'ym'])
    wide = p.pivot(index=['territory_id', 'ym'], columns='category', values='value')
    a = wide.reindex(index=idx, columns=cats).to_numpy(float).reshape(len(ids), len(months), len(cats))
    assert np.isfinite(a).all() and (a > 0).all(), 'missing/nonpositive panel'
    return ids, months, cats, a


def features(panel):
    ids, months, cats, a = cube_from_panel(panel)
    mi = {m: i for i, m in enumerate(months)}
    all_ix = cats.index(ALL)
    ci = [i for i, c in enumerate(cats) if c != ALL]
    ix2023 = [mi[f'2023-{m:02d}'] for m in range(1, 13)]
    ratios = a / a[:, :, [all_ix]]
    base = ratios[:, ix2023][:, :, ci].mean(axis=1)
    targets = np.array([mi[f'2024-{m:02d}'] for m in range(4, 10)])
    # origin=t-1, available cutoff=origin-2=t-3, own-series seasonal growth.
    forecasts = a[:, targets - 12] * a[:, targets - 3] / a[:, targets - 15]
    residuals = np.log(a[:, targets] / forecasts)
    yoy = np.log(a[:, targets] / a[:, targets - 12])
    radar = np.column_stack([residuals.mean(axis=1), residuals.std(axis=1, ddof=0)])
    raw = np.column_stack([yoy.mean(axis=1), yoy.std(axis=1, ddof=0)])
    assert base.shape[1] == 5 and radar.shape[1] == raw.shape[1] == 12
    assert np.isfinite(base).all() and np.isfinite(radar).all() and np.isfinite(raw).all()
    return ids, base, radar, raw, forecasts, cats


def seasonal_scalar_audit(panel, predictions, ids, cats):
    values = panel.set_index(['territory_id', 'ym', 'category']).value.to_dict()
    count = 0
    for i, tid in enumerate(ids):
        for j, m in enumerate(range(4, 10)):
            c = m - 3
            for k, cat in enumerate(cats):
                expected = values[(tid, f'2023-{m:02d}', cat)]
                expected *= values[(tid, f'2024-{c:02d}', cat)] / values[(tid, f'2023-{c:02d}', cat)]
                assert np.isclose(predictions[i, j, k], expected, rtol=1e-12, atol=1e-9)
                count += 1
    return count


def unique_finite(frame, keys, value):
    """Identical/NaN-only duplicates may collapse; conflicting finite values stay missing."""
    g = frame.groupby(keys, dropna=False)[value]
    finite = frame.loc[np.isfinite(frame[value]), keys + [value]]
    counts = finite.groupby(keys, dropna=False)[value].nunique()
    out = g.first()
    bad = counts[counts > 1].index
    out.loc[bad] = np.nan
    return out, {'rows': len(frame), 'keys': len(out), 'conflicting_finite_keys': len(bad),
                 'extra_rows': len(frame) - len(out)}


def external_table(path):
    d = pd.read_parquet(path, columns=['okved2', 'oktmo', 'oktmo_history', 'mun_level',
                                     'year', 'indicator_value', 'indicator_period'])
    d = d[d.okved2.str.startswith('Всего', na=False) &
          d.mun_level.str.contains('верхнего', na=False) &
          (d.indicator_period == 'Январь-декабрь') & d.year.isin([2024, 2025])].copy()
    assert d.oktmo.str.fullmatch(r'\d{8}').all(), 'invalid external OKTMO'
    values, audit = unique_finite(d, ['oktmo', 'year'], 'indicator_value')
    wide = values.unstack('year')
    # Exclude a code if any record of its 2025 history has merger/accession.
    merged = d[d.year == 2025].assign(merge=d[d.year == 2025].oktmo_history.fillna('').str.contains('Объединение|Присоединение'))
    excluded = merged.groupby('oktmo')['merge'].any()
    return wide, excluded, audit


def economic_sample(ids, dictionary, population, market, wage, employment):
    d = pd.read_parquet(dictionary).set_index('territory_id')
    assert d.index.is_unique, 'duplicate dictionary native id'
    s = d.reindex(ids)[['oktmo', 'region_code', 'lat', 'lon', 'type', 'year_to']].copy()
    s['oktmo8'] = s.oktmo.str.replace('-', '', regex=False).str[:8]
    p = pd.read_parquet(population)
    p = p[(p.year == 2024) & (p.period == 'год') & (p.age == 'Всего')].copy()
    pv, pa = unique_finite(p, ['territory_id', 'gender'], 'value')
    pp = pv.unstack('gender')
    # Exact two-sex completeness; missing one is not silently summed as zero.
    assert len(pp.columns) == 2, pp.columns.tolist()
    totals = pp.sum(axis=1, min_count=2)
    s['population'] = totals.reindex(s.index)
    ma = pd.read_parquet(market)
    mav, maa = unique_finite(ma, ['territory_id'], 'market_access')
    s['market_access'] = mav.reindex(s.index)
    stages = [{'stage': 'panel', 'n': len(s)}]
    keep = s.year_to.eq(9999) & s.oktmo8.str.fullmatch(r'\d{8}', na=False)
    stages.append({'stage': 'current_unique_dictionary_candidate', 'n': int(keep.sum())})
    duplicate_code = s.loc[keep].oktmo8.duplicated(keep=False)
    keep.loc[duplicate_code.index] &= ~duplicate_code
    ext_audit = {}
    for name, path in [('wage', wage), ('employment', employment)]:
        wide, merged, audit = external_table(path)
        ext_audit[name] = audit
        for year in [2024, 2025]:
            s[f'{name}{year}'] = s.oktmo8.map(wide[year])
            keep &= np.isfinite(s[f'{name}{year}']) & s[f'{name}{year}'].gt(0)
        keep &= ~s.oktmo8.map(merged).fillna(False).astype(bool)
        stages.append({'stage': f'plus_{name}_positive_unique_no_merger', 'n': int(keep.sum())})
    for col in ['population', 'market_access']:
        keep &= np.isfinite(s[col]) & s[col].gt(0)
    for col in ['lat', 'lon', 'region_code']:
        keep &= np.isfinite(s[col])
    keep &= s.type.notna()
    s = s.loc[keep].copy()
    assert s.oktmo8.is_unique and s.index.is_unique
    stages.append({'stage': 'complete_common_controls', 'n': len(s)})
    return s, {'population': pa, 'market_access': maa, 'external': ext_audit,
               'mask_stages': stages, 'regions': int(s.region_code.nunique())}


def fitted_clusters(base_train, base_test, temporal_train, temporal_test, k, seed):
    bs = StandardScaler().fit(base_train)
    xtr = bs.transform(base_train) / np.sqrt(base_train.shape[1])
    xte = bs.transform(base_test) / np.sqrt(base_train.shape[1])
    ts = None
    if temporal_train is not None:
        ts = StandardScaler().fit(temporal_train)
        xtr = np.column_stack([xtr, ts.transform(temporal_train) / np.sqrt(temporal_train.shape[1])])
        xte = np.column_stack([xte, ts.transform(temporal_test) / np.sqrt(temporal_train.shape[1])])
    km = KMeans(n_clusters=k, n_init=20, random_state=seed, algorithm='lloyd').fit(xtr)
    return km.labels_, km.predict(xte), km, bs, ts


def permuted(block, regions, types, seed):
    out = block.copy()
    rng = np.random.default_rng(seed)
    cells = pd.DataFrame({'region': regions, 'type': types}).groupby(['region', 'type']).indices
    for ix in cells.values():
        out[ix] = block[rng.permutation(ix)]
    return out


def controls(sample, endpoint, train, test):
    numeric = np.column_stack([np.log(sample[f'{endpoint}2024']), np.log(sample.population),
                               np.log(sample.market_access), sample.lat, sample.lon])
    scaler = StandardScaler().fit(numeric[train])
    # Vocabulary only training types; unseen type mapped to reference (documented).
    types = sorted(sample.type.iloc[train].unique())
    extra = np.column_stack([(sample.type.to_numpy() == t).astype(float) for t in types[1:]]) if len(types) > 1 else np.empty((len(sample), 0))
    return (np.column_stack([np.ones(len(train)), scaler.transform(numeric[train]), extra[train]]),
            np.column_stack([np.ones(len(test)), scaler.transform(numeric[test]), extra[test]]))


def cv_predictions(sample, base, radar, raw, k, seed, permutation=None):
    regions = sample.region_code.to_numpy()
    folds = list(GroupKFold(n_splits=5).split(base, groups=regions))
    rows, fold_audit = [], []
    arms = ARMS if permutation is None else ('base_plus_permuted_radar',)
    for fold, (train, test) in enumerate(folds):
        assert not set(regions[train]) & set(regions[test])
        fitted = {}
        for arm in arms:
            temporal = None if arm == 'base2023' else (raw if arm == 'base_plus_raw_yoy' else radar)
            tr, te = (None, None) if temporal is None else (temporal[train], temporal[test])
            if permutation is not None:
                tr = permuted(tr, regions[train], sample.type.iloc[train].to_numpy(), permutation + fold * 1000)
                te = permuted(te, regions[test], sample.type.iloc[test].to_numpy(), permutation + fold * 1000 + 500)
            labels_tr, labels_te, km, _, _ = fitted_clusters(base[train], base[test], tr, te, k, seed)
            fitted[arm] = (labels_tr, labels_te)
            assert len(np.unique(labels_tr)) == k
        for endpoint in ('wage', 'employment'):
            y = np.log(sample[f'{endpoint}2025'].to_numpy())
            xtr, xte = controls(sample, endpoint, train, test)
            predictions = {'controls': xte @ np.linalg.lstsq(xtr, y[train], rcond=None)[0]}
            for arm, (lt, le) in fitted.items():
                x1 = np.column_stack([xtr, (lt[:, None] == np.arange(1, k)).astype(float)])
                x2 = np.column_stack([xte, (le[:, None] == np.arange(1, k)).astype(float)])
                predictions[arm] = x2 @ np.linalg.lstsq(x1, y[train], rcond=None)[0]
            for arm, pred in predictions.items():
                for i, ix in enumerate(test):
                    rows.append((int(sample.index[ix]), int(regions[ix]), fold, endpoint,
                                 arm, k, seed, float(y[ix]), float(pred[i])))
        fold_audit.append({'fold': fold, 'train': len(train), 'test': len(test),
                           'train_regions': sorted(map(int, np.unique(regions[train]))),
                           'test_regions': sorted(map(int, np.unique(regions[test])))})
    f = pd.DataFrame(rows, columns=['territory_id', 'region', 'fold', 'endpoint', 'arm',
                                   'k', 'seed', 'actual_log2025', 'predicted_log2025'])
    assert not f.duplicated(['territory_id', 'endpoint', 'arm']).any()
    return f, fold_audit


def summarize(pred):
    pred = pred.copy()
    pred['sq_error'] = (pred.actual_log2025 - pred.predicted_log2025) ** 2
    pred['abs_error'] = (pred.actual_log2025 - pred.predicted_log2025).abs()
    return pred.groupby(['endpoint', 'k', 'seed', 'arm']).agg(
        n=('territory_id', 'size'), mse=('sq_error', 'mean'), mae=('abs_error', 'mean')).reset_index()


def paired_bootstrap(frame, arm, reference, seed=SEED, b=2000):
    a = frame[frame.arm == arm].set_index('territory_id')
    c = frame[frame.arm == reference].set_index('territory_id')
    assert a.index.is_unique and c.index.is_unique and set(a.index) == set(c.index), 'paired masks differ'
    c = c.reindex(a.index)
    assert not c.isna().any().any() and np.array_equal(a.actual_log2025, c.actual_log2025)
    # Positive difference means Radar is better.
    losses = (c.actual_log2025 - c.predicted_log2025) ** 2 - (a.actual_log2025 - a.predicted_log2025) ** 2
    ag = pd.DataFrame({'region': a.region, 'delta': losses}).groupby('region').agg(total=('delta', 'sum'), n=('delta', 'size'))
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(ag), (b, len(ag)))
    samples = ag.total.to_numpy()[ix].sum(axis=1) / ag.n.to_numpy()[ix].sum(axis=1)
    cmse = float(((c.actual_log2025 - c.predicted_log2025) ** 2).mean())
    return {'arm': arm, 'reference': reference, 'delta_mse_reference_minus_arm': float(losses.mean()),
            'relative_mse_reduction_percent': float(losses.mean() / cmse * 100),
            'descriptive_region_bootstrap95': list(map(float, np.quantile(samples, [.025, .975]))),
            'n': len(a), 'regions': len(ag), 'bootstrap': b, 'conditional_on_fitted_OOF': True}


def q4_space(panel, ids):
    qids, months, cats, a = cube_from_panel(panel, '2024-12')
    assert np.array_equal(qids, ids), 'Q4 and feature masks differ'
    ci = [i for i, cat in enumerate(cats) if cat != ALL]
    ratios = a / a[:, :, [cats.index(ALL)]]
    pre = ratios[:, :12][:, :, ci].mean(axis=1)
    q4 = ratios[:, [months.index(f'2024-{m}') for m in (10, 11, 12)]][:, :, ci].mean(axis=1)
    return StandardScaler().fit(pre).transform(q4)


def dispersion(x, labels):
    total = ((x - x.mean(axis=0)) ** 2).sum()
    within = sum(((x[labels == g] - x[labels == g].mean(axis=0)) ** 2).sum() for g in np.unique(labels))
    return float(within / total)


def run(args):
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    inputs = {k: Path(getattr(args, k)) for k in ['panel', 'dictionary', 'population', 'market', 'wages', 'employment']}
    hashes = {k: sha(v) for k, v in inputs.items()}
    for k, expected in EXPECTED.items():
        assert hashes[k] == expected, (k, hashes[k], 'input differs from frozen snapshot')
    protocol = json.loads(Path(args.protocol).read_text())
    assert protocol['seed'] == SEED and protocol['n_init'] == 20 and protocol['folds'] == 5
    before = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'inputs': hashes,
              'protocol_sha256': sha(args.protocol), 'code_sha256': sha(__file__),
              'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__}
    dump(out/'execution-start.json', before)
    panel = pd.read_parquet(inputs['panel'])
    ids, base, radar, raw, forecasts, cats = features(panel)
    scalar_count = seasonal_scalar_audit(panel, forecasts, ids, cats)
    future = panel.copy(); future.loc[future.ym > '2024-09', 'value'] *= 19
    mutated = features(future)
    assert all(np.array_equal(mutated[i], v) for i, v in enumerate([ids, base, radar, raw, forecasts]))
    sample, sample_audit = economic_sample(ids, inputs['dictionary'], inputs['population'], inputs['market'], inputs['wages'], inputs['employment'])
    positions = pd.Index(ids).get_indexer(sample.index); assert (positions >= 0).all()
    pred_all, summaries, comparisons, fold_audit = [], [], [], None
    for k in (2, 5):
        for seed in protocol['seeds']:
            pred, fa = cv_predictions(sample, base[positions], radar[positions], raw[positions], k, seed)
            fold_audit = fa
            pred_all.append(pred); summaries.append(summarize(pred))
            if seed == SEED:
                for endpoint in ('wage', 'employment'):
                    f = pred[pred.endpoint == endpoint]
                    for reference in ('base2023', 'base_plus_raw_yoy', 'controls'):
                        comparisons.append({'k': k, 'endpoint': endpoint, **paired_bootstrap(f, 'base_plus_radar', reference)})
            print(f'Computed regional OOF k={k} seed={seed} n={len(sample)}', flush=True)
    perms = []
    for i in range(protocol['permutations']):
        pred, _ = cv_predictions(sample, base[positions], radar[positions], raw[positions], 2, SEED, SEED+100+i)
        sm = summarize(pred); sm['permutation'] = i; perms.append(sm)
        if i % 5 == 0: print(f'Permutation diagnostic {i+1}/20', flush=True)
    predictions = pd.concat(pred_all, ignore_index=True)
    # Values are local derived outputs, not copied to public website by report compiler.
    predictions.to_parquet(out/'oof_predictions.parquet', index=False)
    metrics = pd.concat(summaries, ignore_index=True); metrics.to_csv(out/'external_metrics.csv', index=False)
    pm = pd.concat(perms, ignore_index=True); pm.to_csv(out/'permutation_metrics.csv', index=False)
    compact, labels_by_arm = [], {}
    q4 = q4_space(panel, ids)
    label_frame = pd.DataFrame({'territory_id': ids})
    for k in (2, 5):
        for arm in ARMS:
            temporal = None if arm == 'base2023' else (radar if arm == 'base_plus_radar' else raw)
            labels_list = []
            for seed in protocol['seeds']:
                labels, _, _, _, _ = fitted_clusters(base, base, temporal, temporal, k, seed)
                labels_list.append(labels); label_frame[f'{arm}_k{k}_s{seed}'] = labels
                compact.append({'arm': arm, 'k': k, 'seed': seed, 'n': len(ids),
                                'q4_silhouette_common_space': float(silhouette_score(q4, labels)),
                                'q4_within_total_dispersion': dispersion(q4, labels),
                                'group_sizes': np.bincount(labels, minlength=k).tolist(),
                                'ari_vs_first_seed': float(adjusted_rand_score(labels_list[0], labels))})
            labels_by_arm[(k, arm)] = labels_list[0]
    label_frame.to_csv(out/'labels.csv', index=False)
    seed_ranges = metrics.groupby(['k', 'endpoint', 'arm']).mse.agg(['min', 'median', 'max']).reset_index().to_dict('records')
    null_summary = []
    for endpoint in ('wage', 'employment'):
        real = float(metrics.query('k==2 and seed==@SEED and arm=="base_plus_radar" and endpoint==@endpoint').mse.iloc[0])
        vals = pm.query('arm=="base_plus_permuted_radar" and endpoint==@endpoint').mse.to_numpy()
        null_summary.append({'endpoint': endpoint, 'real_mse': real, 'permuted_mse_range': [float(vals.min()), float(vals.max())],
                             'permutations_real_beats': int((real < vals).sum()), 'permutations': len(vals), 'not_confirmatory_pvalue': True})
    result = {'status': 'COMPUTED_EXPLORATORY', 'scientific_pass': False, 'n_panel': len(ids),
              'n_external_common': len(sample), 'sample_audit': sample_audit,
              'comparisons': comparisons, 'seed_mse_ranges': seed_ranges,
              'permutation_diagnostic': null_summary, 'q4_compactness': compact,
              'full_panel_ari_radar_vs_base': {str(k): float(adjusted_rand_score(labels_by_arm[(k, 'base_plus_radar')], labels_by_arm[(k, 'base2023')])) for k in (2, 5)},
              'scalar_growth1_checks': scalar_count, 'future_mutation_invariance': True,
              'region_folds': fold_audit, 'limits': protocol['limits']}
    dump(out/'results.json', result)
    dump(out/'provenance.json', {**before, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
                               'outputs': {p.name: sha(p) for p in out.iterdir() if p.name not in ['provenance.json', 'execution-start.json'] and p.is_file()}})
    print(json.dumps({'status': result['status'], 'n': len(sample), 'regions': sample_audit['regions'],
                      'primary': [c for c in comparisons if c['k'] == 2 and c['reference'] != 'controls']}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    for name in ['panel', 'dictionary', 'population', 'market', 'wages', 'employment', 'protocol', 'out']:
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        run(args)


if __name__ == '__main__':
    main()
