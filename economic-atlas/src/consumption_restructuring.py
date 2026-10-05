"""Past-bounded, exploratory consumer restructuring study; no crisis claim."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import numpy as np
import pandas as pd

from atlas_radar_joint import pre_features

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'shock-radar/src'))
from r9_strong_baselines import predict_block, predict

MODELS = ['profile_ses', 'calibration', 'own_ridge', 'peer_ridge',
          'category_seasonal', 'growth_naive3']
MONTHS = [f'{y}-{m:02d}' for y in [2023, 2024] for m in range(1, 13)]
SEED = 20261005


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def dump(p, x):
    Path(p).write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def fixed_peers(panel, population, dictionary, rule):
    """2023 covariates only; missing support is explicit; self never a peer."""
    f, cats = pre_features(panel, population)
    if dictionary.territory_id.duplicated().any():
        raise ValueError('Dictionary IDs must be unique')
    f = f.join(dictionary.set_index('territory_id'), validate='one_to_one')
    cols = ['share_'+c for c in cats] + ['log_population_2023',
            'log_mean_all_2023', 'log_all_slope_2023', 'log_all_std_2023']
    eligible = f.loc[(f.year_from <= 2023) & (f.year_to >= 2024)].dropna(subset=cols+['type'])
    x = eligible[cols].to_numpy(float)
    scale = x.std(0)
    scale[scale == 0] = 1
    z = (x-x.mean(0))/scale
    positions = {int(t): i for i, t in enumerate(f.index)}
    peers = np.full((len(f), rule['nearest']), -1, dtype=int)
    supported = np.zeros(len(f), dtype=bool)
    records = []
    for j, (tid, row) in enumerate(eligible.iterrows()):
        candidate = ((eligible.type == row.type) &
                     (eligible.population_2023/row.population_2023 >= rule['population_ratio'][0]) &
                     (eligible.population_2023/row.population_2023 <= rule['population_ratio'][1]) &
                     (eligible.index != tid)).to_numpy()
        distance = np.sqrt(((z-z[j])**2).sum(1))
        ix = np.flatnonzero(candidate & (distance <= rule['max_standardized_distance']))
        order = np.lexsort((eligible.index.to_numpy()[ix], distance[ix]))
        ix = ix[order]
        i = positions[int(tid)]
        if len(ix) < rule['minimum_peers']:
            records.append({'territory_id': int(tid), 'status': 'NO_MATCH_SUPPORT',
                            'candidate_count': len(ix)})
            continue
        supported[i] = True
        for rank, k in enumerate(ix[:rule['nearest']]):
            pt = int(eligible.index[k])
            peers[i, rank] = positions[pt]
            records.append({'territory_id': int(tid), 'peer_tid': pt, 'rank': rank+1,
                            'distance': float(distance[k]), 'candidate_count': len(ix),
                            'population_ratio': float(eligible.iloc[k].population_2023/row.population_2023),
                            'status': 'SUPPORTED'})
    seen = set(int(t) for t in eligible.index)
    records.extend({'territory_id': int(t), 'status': 'MISSING_PRE_COVARIATES',
                    'candidate_count': 0} for t in f.index if int(t) not in seen)
    return f, peers, supported, pd.DataFrame(records), len(eligible)


def cube_from_panel(panel, tids):
    cats = sorted(panel.category.unique())
    table = panel.pivot(index='territory_id', columns=['ym', 'category'], values='value')
    grid = pd.MultiIndex.from_product([MONTHS, cats])
    values = table.reindex(index=tids, columns=grid).to_numpy(float).reshape(len(tids), 24, len(cats))
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('No imputation: complete positive frozen histories required')
    return values, cats


def loo_median(x):
    """Exact leave-one-out median along first axis, including ties."""
    x = np.asarray(x, float)
    if len(x) < 2:
        raise ValueError('At least two municipalities')
    order = np.argsort(x, axis=0, kind='stable')
    rank = np.argsort(order, axis=0)
    sorted_x = np.sort(x, axis=0)
    def kth_after_removal(k):
        index = k+(rank <= k)
        return np.take_along_axis(sorted_x, index, axis=0)
    remaining = len(x)-1
    if remaining % 2:
        return kth_after_removal(remaining//2)
    return .5*(kth_after_removal(remaining//2-1)+kth_after_removal(remaining//2))


def peer_stats(x, peers, supported):
    shape = x.shape
    median = np.full(shape, np.nan)
    mad = np.full(shape, np.nan)
    ix = np.flatnonzero(supported)
    if len(ix):
        p = peers[ix]
        good = p >= 0
        v = x[np.maximum(p, 0)].copy()
        v[~good] = np.nan
        m = np.nanmedian(v, axis=1)
        median[ix] = m
        mad[ix] = np.nanmedian(np.abs(v-m[:, None]), axis=1)
    return median, mad


def deviations(values, cats, peers, supported):
    all_ix = cats.index('Все категории')
    non = [c for c in cats if c != 'Все категории']
    share = 100*values[:, :, [cats.index(c) for c in non]]/values[:, :, all_ix, None]
    dy = share[:, 12:]-share[:, :12]
    nominal = 100*(values[:, 12:]/values[:, :12]-1)
    logs = np.log(values[:, 12:]/values[:, :12])
    peer, mad = peer_stats(dy, peers, supported)
    nominal_peer, _ = peer_stats(nominal, peers, supported)
    log_peer, _ = peer_stats(logs, peers, supported)
    common_gap = dy-loo_median(dy)
    gap = dy-peer
    score = gap/np.maximum(1.4826*mad, .25)
    flag = (np.abs(gap) >= 1) & (np.abs(score) >= 3) & (gap*common_gap > 0)
    log_common_gap = logs-loo_median(logs)
    mi, fi = non.index('Маркетплейсы'), non.index('Продовольствие')
    mc, fc = cats.index('Маркетплейсы'), cats.index('Продовольствие')
    own_x = np.stack([common_gap[:, :, mi], log_common_gap[:, :, mc],
                      log_common_gap[:, :, all_ix], common_gap[:, :, fi],
                      log_common_gap[:, :, fc]], axis=2)
    peer_x = np.stack([gap[:, :, mi], (logs-log_peer)[:, :, mc],
                       (logs-log_peer)[:, :, all_ix], gap[:, :, fi],
                       (logs-log_peer)[:, :, fc]], axis=2)
    return {'share': share, 'dy': dy, 'gap': gap, 'common_gap': common_gap,
            'score': score, 'flag': flag, 'nominal': nominal,
            'nominal_gap': nominal-nominal_peer, 'own_x': own_x,
            'peer_x': np.concatenate([own_x, peer_x], axis=2), 'non': non}


def persistent(flag, gap):
    """Three consecutive flagged months of the same sign in July-December."""
    result = np.zeros(len(flag), bool)
    for j in range(6, 10):
        result |= flag[:, j:j+3].all(1) & ((gap[:, j:j+3] > 0).all(1) |
                                             (gap[:, j:j+3] < 0).all(1))
    return result


def fit_correction(x, y, current, ridge=.1):
    """Standardization and regression are learned only from supplied past rows."""
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Invalid training rows')
    mu = x.mean(0)
    scale = x.std(0)
    scale[scale == 0] = 1
    z = (x-mu)/scale
    intercept = float(y.mean())
    beta = np.linalg.solve(z.T@z/len(z)+ridge*np.eye(z.shape[1]),
                           z.T@(y-intercept)/len(z))
    predicted = intercept+((current-mu)/scale)@beta
    return np.clip(predicted, -.1, .1), {'mean': mu.tolist(), 'scale': scale.tolist(),
                                       'intercept': intercept, 'beta': beta.tolist()}


def forecast(values, cats, d, supported):
    """All target observations enter only evaluation, never fitting."""
    med = np.median(values, axis=0)
    ix = np.flatnonzero(supported)
    cache = {}
    for c in range(len(cats)):
        for oi in range(12, 23):
            for ti in sorted(set([oi+1]+[oi+h for h in [1, 3, 6] if 18 <= oi+h < 24])):
                cache[c, oi, ti] = predict_block(values[:, :, c], med[:, c], oi, ti)
    rows, fits = [], []
    for h in [1, 3, 6]:
        for ti in range(18, 24):
            oi = ti-h
            training_u = list(range(12, oi))
            for c, category in enumerate(cats):
                base = cache[c, oi, ti]
                pp = {m: base[m].copy() for m in ['profile_ses', 'category_seasonal', 'growth_naive3']}
                cold = len(training_u) < 2
                for model in ['calibration', 'own_ridge', 'peer_ridge']:
                    corr = np.full(len(values), np.nan)
                    fit = {'model': model, 'category': category, 'horizon': h,
                           'origin': MONTHS[oi], 'target': MONTHS[ti],
                           'training_origins': [MONTHS[u] for u in training_u],
                           'last_training_target': MONTHS[oi] if training_u else None,
                           'training_rows': len(training_u)*len(ix),
                           'status': 'COLD_START' if cold else 'PAST_FIT'}
                    if cold:
                        corr[ix] = 0
                    else:
                        y = np.concatenate([np.log(values[ix, u+1, c]/cache[c, u, u+1]['profile_ses'][ix])
                                            for u in training_u])
                        if model == 'calibration':
                            corr[ix] = np.clip(y.mean(), -.1, .1)
                            fit['intercept'] = float(y.mean())
                        else:
                            key = 'own_x' if model == 'own_ridge' else 'peer_x'
                            x = np.concatenate([d[key][ix, u-12] for u in training_u])
                            corr[ix], detail = fit_correction(x, y, d[key][ix, oi-12])
                            fit.update(detail)
                    pp[model] = base['profile_ses']*np.exp(corr)
                    fits.append(fit)
                rows.append({'horizon': h, 'oi': oi, 'ti': ti, 'category': category,
                             'actual': values[:, ti, c].copy(), 'predictions': pp,
                             'cold_start': cold})
    return rows, fits


def block_ci(diff, labels, seed):
    b = pd.DataFrame({'label': labels, 'diff': diff}).groupby('label')['diff'].agg(['sum', 'count'])
    rng = np.random.default_rng(seed)
    ix = rng.integers(0, len(b), (10000, len(b)))
    gain = b['sum'].to_numpy()[ix].sum(1)/b['count'].to_numpy()[ix].sum(1)
    return np.quantile(gain, [.025, .975]).tolist(), len(b)


def summarize(predictions):
    output = []
    for (cat, h), g in predictions.loc[predictions.supported].groupby(['category', 'horizon']):
        if not np.isfinite(g[MODELS]).all().all():
            raise ValueError('Primary same-key mask has unavailable forecasts')
        errors = {m: np.abs(g.actual-g[m]).to_numpy() for m in MODELS}
        comparisons = []
        for model, reference in [('peer_ridge', 'profile_ses'), ('peer_ridge', 'own_ridge'),
                                  ('own_ridge', 'profile_ses'), ('calibration', 'profile_ses')]:
            gain = errors[reference]-errors[model]
            ci, blocks = block_ci(gain, g.target, SEED)
            region_ci, regions = block_ci(gain, g.region_code, SEED+1)
            comparisons.append({'model': model, 'reference': reference,
                'mae_gain': float(gain.mean()), 'gain_percent': float(100*gain.mean()/errors[reference].mean()),
                'ci95_month_blocks': ci, 'month_blocks': blocks,
                'ci95_region_blocks_sensitivity': region_ci, 'region_blocks': regions})
        output.append({'category': cat, 'horizon': int(h), 'n': len(g),
                       'municipalities': g.territory_id.nunique(), 'cold_start_rows': int(g.cold_start.sum()),
                       'mae': {m: float(e.mean()) for m, e in errors.items()},
                       'comparisons': comparisons,
                       'by_month': [{'target': t, 'n': len(b),
                           'mae': {m: float(np.abs(b.actual-b[m]).mean()) for m in MODELS}}
                           for t, b in g.groupby('target')]})
    return output


def anomaly_table(f, d, supported):
    records = []
    for i, (tid, r) in enumerate(f.iterrows()):
        item = {'territory_id': int(tid), 'name': r.name_short, 'region_name': r.region_name,
                'type': r.type, 'region_code': int(r.region_code), 'supported': bool(supported[i]),
                'lat': float(r.lat), 'lon': float(r.lon), 'population_2023': None if pd.isna(r.population_2023) else float(r.population_2023)}
        for k, cat in enumerate(d['non']):
            if supported[i]:
                item[cat] = {'share_2023': float(d['share'][i, :12, k].mean()),
                    'share_2024': float(d['share'][i, 12:, k].mean()),
                    'annual_change_pp': float(d['dy'][i, :, k].mean()),
                    'q4_peer_gap_pp': float(np.median(d['gap'][i, 9:, k])),
                    'q4_common_gap_pp': float(np.median(d['common_gap'][i, 9:, k])),
                    'persistent': bool(persistent(d['flag'][i:i+1, :, k], d['gap'][i:i+1, :, k])[0]),
                    'flagged_h2_months': int(d['flag'][i, 6:, k].sum()),
                    'max_abs_score': float(np.abs(d['score'][i, :, k]).max()),
                    'nominal_confirmation_months': int((np.abs(d['nominal_gap'][i, 6:, cats_index(cat)]) >= 5).sum())}
            else:
                item[cat] = None
        records.append(item)
    return records


def cats_index(cat):
    return sorted(['Все категории', 'Здоровье', 'Маркетплейсы', 'Общественное питание',
                   'Продовольствие', 'Транспорт']).index(cat)


def select_stories(records):
    # Exact predeclared ordering, cities preferred; names never influence scores.
    stories = []
    for sign in [1, -1]:
        q = [r for r in records if r['supported'] and r['Маркетплейсы']['persistent'] and
             sign*r['Маркетплейсы']['q4_peer_gap_pp'] > 0]
        q.sort(key=lambda r: (r['type'].casefold() != 'городской округ',
                             -abs(r['Маркетплейсы']['q4_peer_gap_pp']), r['territory_id']))
        stories.extend(r['territory_id'] for r in q[:3])
    return stories


def run(a):
    proto = json.loads(a.protocol.read_text())
    paths = {'panel': a.repo/'economic-atlas/data/panel_v1.parquet',
             'population': a.data_dir/'2_bdmo_population.parquet',
             'dictionary': a.data_dir/'municipal_dictionary.parquet'}
    for k, h in proto['input_sha256'].items():
        if sha(paths[k]) != h:
            raise ValueError('Input hash mismatch: '+k)
    if a.out.exists():
        raise FileExistsError('New run directory required')
    panel, population, dictionary = [pd.read_parquet(paths[k]) for k in ['panel', 'population', 'dictionary']]
    f, peers, supported, matches, eligible = fixed_peers(panel, population, dictionary, proto['peer_rule'])
    values, cats = cube_from_panel(panel, f.index)
    d = deviations(values, cats, peers, supported)
    print(json.dumps({'phase': 'matches', 'panel': len(f), 'eligible': eligible,
                      'supported': int(supported.sum())}), flush=True)
    rows, fits = forecast(values, cats, d, supported)
    frames = []
    for row in rows:
        frames.append(pd.DataFrame({'territory_id': f.index, 'region_code': f.region_code.to_numpy(),
            'category': row['category'], 'horizon': row['horizon'], 'origin': MONTHS[row['oi']],
            'target': MONTHS[row['ti']], 'actual': row['actual'], 'supported': supported,
            'cold_start': row['cold_start'], **row['predictions']}))
    p = pd.concat(frames, ignore_index=True)
    records = anomaly_table(f, d, supported)
    results = summarize(p)
    # Whole-panel future mutation, including training labels, for each origin.
    checked, scalar = 0, 0
    for oi in range(12, 23):
        mutated = values.copy()
        mutated[:, oi+1:] = mutated[:, oi+1:]*100+12345
        dm = deviations(mutated, cats, peers, supported)
        np.testing.assert_array_equal(dm['own_x'][:, :oi-11], d['own_x'][:, :oi-11])
        np.testing.assert_allclose(dm['peer_x'][:, :oi-11], d['peer_x'][:, :oi-11], equal_nan=True)
        rm, fm = forecast(mutated, cats, dm, supported)
        original = [r for r in rows if r['oi'] == oi]
        revised = [r for r in rm if r['oi'] == oi]
        for r, q in zip(original, revised):
            for m in MODELS:
                np.testing.assert_allclose(r['predictions'][m], q['predictions'][m], equal_nan=True, rtol=0, atol=0)
                checked += len(values)
        assert [x for x in fits if x['origin'] == MONTHS[oi]] == [x for x in fm if x['origin'] == MONTHS[oi]]
    # Pre-period match and population invariance on real data.
    alt = panel.copy()
    alt.loc[alt.ym > '2023-12', 'value'] = alt.loc[alt.ym > '2023-12', 'value']*100+12345
    popalt = population.copy()
    popalt.loc[popalt.year > 2023, 'value'] *= 100
    ff, pp, ss, mm, ee = fixed_peers(alt, popalt, dictionary, proto['peer_rule'])
    np.testing.assert_array_equal(pp, peers)
    np.testing.assert_array_equal(ss, supported)
    pd.testing.assert_frame_equal(mm, matches)
    for row in rows:
        c, oi, ti = cats.index(row['category']), row['oi'], row['ti']
        for i in [0, len(values)//2, len(values)-1]:
            s = predict(pd.Series(values[i, :, c], index=MONTHS),
                        pd.Series(np.median(values[:, :, c], axis=0), index=MONTHS),
                        MONTHS[oi], MONTHS[ti])
            for m in ['profile_ses', 'category_seasonal', 'growth_naive3']:
                np.testing.assert_allclose(s[m], row['predictions'][m][i], rtol=1e-12)
                scalar += 1
    if p.duplicated(['territory_id', 'category', 'horizon', 'origin', 'target']).any():
        raise ValueError('Duplicate forecast keys')
    metrics = {'status': 'COMPUTED_EXPLORATORY', 'scientific_pass': False,
        'independent_holdout': False, 'historical_asof_verified': False,
        'panel': len(f), 'matching_eligible': eligible, 'supported': int(supported.sum()),
        'unsupported': int((~supported).sum()), 'forecast_rows': len(p),
        'common_forecast_rows': int(p.supported.sum()), 'results': results,
        'persistent_marketplace': sum(r['supported'] and r['Маркетплейсы']['persistent'] for r in records),
        'story_ids': select_stories(records),
        'checks': {'whole_panel_future_invariance_forecasts': checked, 'scalar_baselines': scalar,
                   'past_matching_population_invariance': True, 'same_keys': True},
        'versions': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__},
        'limits': proto['limits']}
    a.out.mkdir(parents=True)
    dump(a.out/'protocol.json', proto)
    dump(a.out/'metrics.json', metrics)
    dump(a.out/'anomalies.json', records)
    dump(a.out/'fits.json', fits)
    matches.to_csv(a.out/'peers.csv', index=False)
    f.reset_index().to_parquet(a.out/'pre-2024-features.parquet', index=False)
    p.to_parquet(a.out/'predictions.parquet', index=False)
    np.savez_compressed(a.out/'deviations.npz', territory_id=f.index.to_numpy(),
                        **{k: d[k] for k in ['share', 'dy', 'gap', 'common_gap', 'score', 'flag', 'nominal', 'nominal_gap']})
    dump(a.out/'manifest.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
         'input_sha256': {k: sha(v) for k, v in paths.items()},
         'code_sha256': {'study': sha(__file__), 'baseline': sha(REPO/'shock-radar/src/r9_strong_baselines.py'),
                         'pre_features': sha(REPO/'economic-atlas/src/atlas_radar_joint.py')},
         'protocol_sha256': sha(a.protocol), 'files': {p.name: sha(p) for p in a.out.iterdir() if p.is_file()}})
    print(json.dumps({k: v for k, v in metrics.items() if k not in ['results', 'limits']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, default=REPO)
    ap.add_argument('--data-dir', type=Path, required=True)
    ap.add_argument('--protocol', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    run(ap.parse_args())
