"""H5: prospectively specified scale/encoding audit on the already viewed panel."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage, cut_tree
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

import atlas_radar_ablation as external

CATS = ['Здоровье', 'Маркетплейсы', 'Общественное питание', 'Продовольствие', 'Транспорт']
TOTAL = 'Все категории'
ARMS = ['shares', 'shares_log_volume', 'volume', 'legacy_shares6', 'legacy_shares6_log_mean6', 'legacy_volume_log_mean6']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def feature_sets(panel):
    # Key columns only join observations. IDs/names/regions are never numeric predictors.
    p = panel.loc[panel.ym.astype(str).str.startswith('2023-')].copy()
    months = [f'2023-{m:02d}' for m in range(1, 13)]
    ids = np.sort(p.territory_id.unique())
    index = pd.MultiIndex.from_product([ids, months], names=['territory_id', 'ym'])
    if p.duplicated(['territory_id', 'ym', 'category']).any():
        raise ValueError('Duplicate spending key')
    if set(p.category) != {TOTAL, *CATS}:
        raise ValueError('Category coverage differs')
    wide = p.pivot(index=['territory_id', 'ym'], columns='category', values='value').reindex(index=index, columns=[TOTAL] + CATS)
    cube = wide.to_numpy(float).reshape(len(ids), 12, 6)
    if not np.isfinite(cube).all() or (cube <= 0).any():
        raise ValueError('Incomplete/nonpositive panel; no zero filling')
    canonical = (cube[:, :, 1:] / cube[:, :, [0]]).mean(axis=1)
    log_total = np.log1p(cube[:, :, 0].mean(axis=1))[:, None]
    annual = cube.mean(axis=1)
    legacy = annual / annual.sum(axis=1, keepdims=True)
    log_mean6 = np.log1p(annual.mean(axis=1))[:, None]
    features = {'shares': canonical, 'shares_log_volume': np.column_stack([canonical, log_total]),
                'volume': log_total, 'legacy_shares6': legacy,
                'legacy_shares6_log_mean6': np.column_stack([legacy, log_mean6]),
                'legacy_volume_log_mean6': log_mean6}
    return ids, features


def fit(xtr, xte, method, k, seed):
    scaler = StandardScaler().fit(xtr)
    a, b = scaler.transform(xtr), scaler.transform(xte)
    if method == 'kmeans':
        model = KMeans(n_clusters=k, random_state=seed, n_init=20, algorithm='lloyd').fit(a)
        tr, te = model.labels_, model.predict(b)
        centers = model.cluster_centers_
    else:
        tr = cut_tree(linkage(a, method='ward'), n_clusters=[k]).ravel()
        centers = np.vstack([a[tr == c].mean(axis=0) for c in range(k)])
        te = ((b[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2).argmin(axis=1)
    assert len(np.unique(tr)) == k and np.isfinite(centers).all()
    return tr, te, scaler


def oof(sample, features, method, k, seed):
    regions = sample.region_code.to_numpy(int)
    rows, folds = [], []
    for fold, (tr, te) in enumerate(GroupKFold(5).split(sample, groups=regions)):
        assert not set(regions[tr]) & set(regions[te])
        labs = {arm: fit(x[tr], x[te], method, k, seed)[:2] for arm, x in features.items()}
        for endpoint in ('wage', 'employment'):
            y = np.log(sample[f'{endpoint}2025'].to_numpy())
            a, b = external.controls(sample, endpoint, tr, te)
            predictions = {'controls': b @ np.linalg.lstsq(a, y[tr], rcond=None)[0]}
            for arm, (lt, le) in labs.items():
                a1 = np.column_stack([a, (lt[:, None] == np.arange(1, k)).astype(float)])
                b1 = np.column_stack([b, (le[:, None] == np.arange(1, k)).astype(float)])
                predictions[arm] = b1 @ np.linalg.lstsq(a1, y[tr], rcond=None)[0]
            for arm, pred in predictions.items():
                rows += [(int(sample.index[ix]), int(regions[ix]), fold, endpoint, arm, method, k, seed, float(y[ix]), float(pred[i])) for i, ix in enumerate(te)]
        folds.append({'fold': fold, 'train': len(tr), 'test': len(te), 'train_regions': sorted(set(map(int, regions[tr]))), 'test_regions': sorted(set(map(int, regions[te])))})
    return pd.DataFrame(rows, columns=['territory_id', 'region', 'fold', 'endpoint', 'arm', 'method', 'k', 'seed', 'actual_log2025', 'predicted_log2025']), folds


def contracts(panel, ids, features, seed):
    future = panel.copy()
    future.loc[future.ym.astype(str) > '2023-12', 'value'] *= 19
    changed = feature_sets(future)
    np.testing.assert_array_equal(changed[0], ids)
    assert all(np.array_equal(changed[1][a], x) for a, x in features.items())
    shuffled = panel.sample(frac=1, random_state=seed).copy()
    shuffled['unused_dictionary_name'] = 'ignored'
    rekey = {int(t): 9999999 - int(t) for t in ids}
    shuffled.territory_id = shuffled.territory_id.map(rekey)
    new_ids, new_f = feature_sets(shuffled)
    order = pd.Index(new_ids).get_indexer([rekey[int(t)] for t in ids])
    assert all(np.array_equal(new_f[a][order], x) for a, x in features.items())
    converted = panel.copy()
    converted['value'] = converted.value.astype(float) / 1000
    _, unit_f = feature_sets(converted)
    np.testing.assert_allclose(unit_f['shares'], features['shares'], atol=1e-14, rtol=1e-14)
    # log1p has a declared fixed-ruble convention, and is not claimed unit invariant.
    assert not np.array_equal(unit_f['volume'], features['volume'])
    return unit_f, {'future_2024_mutation_feature_checks': len(ids) * sum(x.shape[1] for x in features.values()),
                    'id_order_name_invariance_feature_checks': len(ids) * sum(x.shape[1] for x in features.values()),
                    'shares_currency_unit_checks': len(ids) * 5, 'unit_volume_note': 'log1p depends on unit; original ruble input and separate unit sensitivity kept'}


def run(args):
    protocol = json.loads(args.protocol.read_text())
    if args.out.exists():
        raise FileExistsError('New run only; frozen outputs cannot be overwritten')
    paths = {name: Path(getattr(args, name)) for name in ['panel', 'dictionary', 'population', 'market', 'wages', 'employment']}
    hashes = {name: sha(path) for name, path in paths.items()}
    assert hashes == protocol['input_sha256'], 'Inputs differ from protocol'
    assert protocol['arms'] == ARMS and protocol['n_init'] == 20 and protocol['folds'] == 5
    args.out.mkdir(parents=True)
    write(args.out / 'execution-start.json', {'checked_at': datetime.now(timezone.utc).isoformat(), 'input_sha256': hashes, 'protocol_sha256': sha(args.protocol), 'code_sha256': sha(__file__), 'external_helpers_sha256': sha(external.__file__)})
    panel = pd.read_parquet(paths['panel'])
    ids, fs = feature_sets(panel)
    assert len(ids) == 1896
    unit_features, checks = contracts(panel, ids, fs, protocol['primary_seed'])
    sample, mask = external.economic_sample(ids, paths['dictionary'], paths['population'], paths['market'], paths['wages'], paths['employment'])
    pos = pd.Index(ids).get_indexer(sample.index)
    assert len(sample) == 1248 and (pos >= 0).all()
    cohort_features = {a: x[pos] for a, x in fs.items()}
    # Common geometry for all silhouettes: future Q4 shares, frozen 2023 mean/std.
    q4 = external.q4_space(panel, ids)
    geometry = q4  # helper already freezes the scaler on 2023 canonical shares
    take = np.random.default_rng(protocol['primary_seed']).choice(len(ids), 400, replace=False)
    predictions, partitions, full_metrics, comparison_rows, fold_receipts = [], [], [], [], []
    for method in ('kmeans', 'ward'):
        seeds = protocol['seeds'] if method == 'kmeans' else [protocol['primary_seed']]
        for k in (5, 2):
            for seed in seeds:
                lab_map = {}
                for arm, x in fs.items():
                    lt, _, _ = fit(x, x, method, k, seed)
                    lab_map[arm] = lt
                    partitions += [(int(t), arm, method, k, seed, int(label)) for t, label in zip(ids, lt)]
                    score = silhouette_score(geometry[take], lt[take]) if len(np.unique(lt[take])) > 1 else None
                    native = silhouette_score(StandardScaler().fit_transform(x)[take], lt[take]) if len(np.unique(lt[take])) > 1 else None
                    unit_lt, _, _ = fit(unit_features[arm], unit_features[arm], method, k, seed)
                    full_metrics.append({'arm': arm, 'method': method, 'k': k, 'seed': seed, 'sizes': np.bincount(lt, minlength=k).tolist(), 'common_Q4_shares_silhouette_400': score, 'native_space_silhouette_400_not_cross_arm_comparable': native, 'ruble_to_thousand_ruble_ARI': adjusted_rand_score(lt, unit_lt)})
                for other in ARMS[1:]:
                    comparison_rows.append({'method': method, 'k': k, 'seed': seed, 'reference': 'shares', 'arm': other, 'ARI': adjusted_rand_score(lab_map['shares'], lab_map[other])})
                pred, folds = oof(sample, cohort_features, method, k, seed)
                predictions.append(pred)
                fold_receipts.append({'method': method, 'k': k, 'seed': seed, 'folds': folds})
                print(json.dumps({'method': method, 'k': k, 'seed': seed, 'complete': True}), flush=True)
    pred = pd.concat(predictions, ignore_index=True)
    pred.to_parquet(args.out / 'oof_predictions.parquet', index=False)
    pd.DataFrame(partitions, columns=['territory_id', 'arm', 'method', 'k', 'seed', 'label']).to_parquet(args.out / 'partitions.parquet', index=False)
    pd.DataFrame(full_metrics).to_json(args.out / 'full_metrics.json', orient='records', indent=2, force_ascii=False)
    pd.DataFrame(comparison_rows).to_csv(args.out / 'partition_comparisons.csv', index=False)
    primary_pairs = [('shares_log_volume', 'shares'), ('shares', 'volume'), ('shares', 'controls'), ('legacy_shares6', 'shares'), ('legacy_shares6_log_mean6', 'shares_log_volume'), ('legacy_volume_log_mean6', 'volume')]
    external_rows, comparisons = [], []
    for keys, g in pred.groupby(['method', 'k', 'seed', 'endpoint']):
        method, k, seed, endpoint = keys
        for arm, f in g.groupby('arm'):
            external_rows.append({'method': method, 'k': int(k), 'seed': int(seed), 'endpoint': endpoint, 'arm': arm, 'n': len(f), 'mse_log2025': float(((f.actual_log2025 - f.predicted_log2025) ** 2).mean())})
        if seed == protocol['primary_seed']:
            for arm, reference in primary_pairs:
                result = external.paired_bootstrap(g, arm, reference, seed=protocol['primary_seed'])
                comparisons.append({'method': method, 'k': int(k), 'seed': int(seed), 'endpoint': endpoint, **result})
    pd.DataFrame(external_rows).to_csv(args.out / 'external_metrics.csv', index=False)
    write(args.out / 'paired_comparisons.json', comparisons)
    write(args.out / 'fold_receipts.json', fold_receipts)
    result = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'EXECUTED_RETROSPECTIVE_H5_SCALE_ENCODING_AUDIT', 'scientific_pass': False, 'primary_method': 'kmeans', 'primary_k': 5, 'primary_seed': protocol['primary_seed'], 'panel_n': len(ids), 'external_n': len(sample), 'regions': int(sample.region_code.nunique()), 'full_partitions': len(full_metrics), 'oof_rows': len(pred), 'OOF_cluster_fits': len(fold_receipts) * 5 * 6, 'full_cluster_fits_including_unit_sensitivity': len(full_metrics) * 2, 'mask_audit': mask, 'contracts': checks, 'comparisons': comparisons, 'input_sha256': hashes, 'protocol_sha256': sha(args.protocol), 'code_sha256': sha(__file__), 'external_helpers_sha256': sha(external.__file__), 'versions': {'numpy': np.__version__, 'pandas': pd.__version__}, 'limits': protocol['limits']}
    write(args.out / 'results.json', result)
    print(json.dumps({k:result[k] for k in ['status','full_partitions','oof_rows','external_n','scientific_pass']}),flush=True)


def main():
    p = argparse.ArgumentParser()
    for key in ['panel', 'dictionary', 'population', 'market', 'wages', 'employment', 'protocol', 'out']:
        p.add_argument('--' + key, type=Path, required=True)
    with threadpool_limits(limits=1):
        run(p.parse_args())


if __name__ == '__main__':
    main()
