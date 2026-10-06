"""Bounded exploratory closeout; frozen protocol, past-only fitting, no API calls."""
from pathlib import Path
import argparse
import json
import platform
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from consumption_restructuring import (REPO, MONTHS, fixed_peers, cube_from_panel,
    deviations, persistent, peer_stats, loo_median, predict_block, block_ci, sha, dump)

MODELS = ['one_step_zero_own', 'one_step_zero_peer', 'direct_zero_own',
          'direct_zero_peer', 'direct_intercept_own', 'direct_intercept_peer',
          'direct_calibration']
SEED = 20261006


def completed_origins(origin, label_horizon):
    return list(range(12, origin-label_horizon+1))


def correction(x, y, current, intercept=False, ridge=.1):
    if not all(np.isfinite(a).all() for a in [x, y, current]):
        raise ValueError('Nonfinite supplied fit rows')
    mu, scale = x.mean(0), x.std(0)
    scale[scale == 0] = 1
    z = (x-mu)/scale
    mean = float(y.mean()) if intercept else 0.
    beta = np.linalg.solve(z.T@z/len(z)+ridge*np.eye(z.shape[1]),
                           z.T@(y-mean)/len(z))
    return np.clip(mean+(current-mu)/scale@beta, -.1, .1), {
        'mean': mu.tolist(), 'scale': scale.tolist(), 'intercept': mean,
        'beta': beta.tolist()}


def at_origin(values, cats, d, supported, oi, ti, category):
    c = cats.index(category)
    h = ti-oi
    med = np.median(values[:, :, c], axis=0)
    base = predict_block(values[:, :, c], med, oi, ti)['profile_ses']
    ix = np.flatnonzero(supported)
    pp, fits = {'profile_ses': base}, []
    cache = {}
    for model in MODELS:
        k = 1 if model.startswith('one_step') else h
        training = completed_origins(oi, k)
        cold = len(training) < 2
        fit = {'model': model, 'category': category, 'horizon': h,
               'origin': MONTHS[oi], 'target': MONTHS[ti],
               'label_horizon': k, 'training_origins': [MONTHS[u] for u in training],
               'training_targets': [MONTHS[u+k] for u in training],
               'monthly_blocks': len(training), 'training_rows': len(training)*len(ix),
               'status': 'COLD_START_EXACT_BASELINE' if cold else 'PAST_FIT'}
        if cold:
            pred = base.copy()
        else:
            if k not in cache:
                cache[k] = np.concatenate([np.log(values[ix, u+k, c]/
                    predict_block(values[:, :, c], med, u, u+k)['profile_ses'][ix])
                    for u in training])
            y = cache[k]
            if model == 'direct_calibration':
                corr = np.full(len(ix), np.clip(y.mean(), -.1, .1))
                fit['intercept'] = float(y.mean())
            else:
                key = 'peer_x' if model.endswith('peer') else 'own_x'
                x = np.concatenate([d[key][ix, u-12] for u in training])
                corr, details = correction(x, y, d[key][ix, oi-12],
                                           intercept='_intercept_' in model)
                fit.update(details)
            pred = base.copy()
            pred[ix] = base[ix]*np.exp(corr)
        pp[model] = pred
        fits.append(fit)
    return pp, fits


def forecasts(values, cats, d, support, f):
    frames, fits = [], []
    for h in [1, 3, 6]:
        for ti in range(18, 24):
            oi = ti-h
            for cat in cats:
                pp, ff = at_origin(values, cats, d, support, oi, ti, cat)
                fits.extend(ff)
                frames.append(pd.DataFrame({'territory_id': f.index,
                    'region_code': f.region_code.to_numpy(), 'category': cat,
                    'horizon': h, 'origin': MONTHS[oi], 'target': MONTHS[ti],
                    'actual': values[:, ti, cats.index(cat)], 'supported': support,
                    **pp}))
    p = pd.concat(frames, ignore_index=True)
    results = []
    for (cat, h), g in p.loc[p.supported].groupby(['category', 'horizon']):
        if not np.isfinite(g[['profile_ses']+MODELS]).all().all():
            raise ValueError('Incomplete comparison mask')
        err = {m: np.abs(g.actual-g[m]).to_numpy() for m in ['profile_ses']+MODELS}
        compares = []
        for m in MODELS:
            gain = err['profile_ses']-err[m]
            ci, nb = block_ci(gain, g.target, SEED)
            rci, nr = block_ci(gain, g.region_code, SEED+1)
            compares.append({'model': m, 'mae_gain': float(gain.mean()),
                'gain_percent': float(100*gain.mean()/err['profile_ses'].mean()),
                'ci95_month_blocks': ci, 'month_blocks': nb,
                'ci95_region_blocks_sensitivity': rci, 'region_blocks': nr})
        results.append({'category': cat, 'horizon': int(h), 'n': len(g),
            'municipalities': g.territory_id.nunique(),
            'mae': {m: float(e.mean()) for m, e in err.items()},
            'comparisons': compares,
            'by_month': [{'target': t, 'n': len(q),
                'mae': {m: float(np.abs(q.actual-q[m]).mean()) for m in err}}
                for t, q in g.groupby('target')]})
    # Real-data whole-panel future mutation, including all possible training labels.
    checks = 0
    for oi in range(12, 23):
        changed = values.copy()
        changed[:, oi+1:] = changed[:, oi+1:]*100+12345
        dm = deviations(changed, cats, peers=forecasts.peers, supported=support)
        for h in [1, 3, 6]:
            ti = oi+h
            if ti not in range(18, 24):
                continue
            for cat in cats:
                original, fa = at_origin(values, cats, d, support, oi, ti, cat)
                revised, fb = at_origin(changed, cats, dm, support, oi, ti, cat)
                assert fa == fb
                for m in original:
                    np.testing.assert_array_equal(original[m], revised[m])
                    checks += len(values)
    return p, fits, results, checks


def robust(panel, pop, dictionary, rule, configs, values, cats, f, original):
    rows, selected = [], []
    for config in configs:
        rr = dict(rule, nearest=config['nearest'], population_ratio=config['population_ratio'])
        ff, peers, supported, _, eligible = fixed_peers(panel, pop, dictionary, rr)
        np.testing.assert_array_equal(ff.index, f.index)
        d = deviations(values, cats, peers, supported)
        k = d['non'].index('Маркетплейсы')
        gap, cg, score = (d[name][:, :, k] for name in ['gap', 'common_gap', 'score'])
        for threshold in [.75, 1., 1.25]:
            for z in [2.5, 3., 3.5]:
                flags = ((np.abs(gap) >= threshold) & (np.abs(score) >= z) &
                         (np.sign(gap) == np.sign(cg)) & supported[:, None])
                keep = persistent(flags, gap)
                key = f"{config['name']}:gap{threshold}:score{z}"
                selected.append(keep)
                intersection, union = (keep & original).sum(), (keep | original).sum()
                rows.append({'configuration': key, 'peer_config': config['name'],
                    'gap_pp': threshold, 'score': z, 'eligible': eligible,
                    'supported': int(supported.sum()), 'selected': int(keep.sum()),
                    'original25_retained': int(intersection),
                    'selected_jaccard_vs_main': float(intersection/union) if union else 1.})
    selected = np.array(selected)
    cities = []
    for i, (tid, row) in enumerate(f.iterrows()):
        if original[i] or selected[:, i].any():
            cities.append({'territory_id': int(tid), 'name': row.name_short,
                'region_name': row.region_name, 'original_signal': bool(original[i]),
                'configurations_selected': int(selected[:, i].sum()),
                'configurations_total': len(selected),
                'selection_fraction': float(selected[:, i].mean()),
                'descriptive_core80': bool(selected[:, i].mean() >= .8)})
    return rows, cities


def denominator(values, cats, peers, supported, f, original, d):
    logs = 100*np.log(values[:, 12:]/values[:, :12])
    # Arithmetic means, not separately taken medians, make this identity exact.
    weights = peers >= 0
    peer_mean = np.sum(logs[np.maximum(peers, 0)]*weights[:, :, None, None], axis=1)
    peer_mean /= np.maximum(weights.sum(1), 1)[:, None, None]
    ex = logs-peer_mean
    a, m, food = [cats.index(c) for c in ['Все категории', 'Маркетплейсы', 'Продовольствие']]
    ratio = 100*np.log((values[:, 12:, m]/values[:, 12:, a])/
                       (values[:, :12, m]/values[:, :12, a]))
    ratio_peer = np.sum(ratio[np.maximum(peers, 0)]*weights[:, :, None], axis=1)
    ratio_peer /= np.maximum(weights.sum(1), 1)[:, None]
    identity = np.max(np.abs((ratio-ratio_peer)[supported]-(ex[:, :, m]-ex[:, :, a])[supported]))
    np.testing.assert_allclose((ratio-ratio_peer)[supported],
                              (ex[:, :, m]-ex[:, :, a])[supported], atol=1e-12)
    rest = values[:, :, a]-values[:, :, m]
    valid = (rest > 0).all(1)
    balance = np.full((len(values), 12), np.nan)
    for i in np.flatnonzero(supported & valid):
        p = peers[i, peers[i] >= 0]
        if not valid[p].all():
            continue
        num = 100*np.log((values[i, 12:, m]/rest[i, 12:])/(values[i, :12, m]/rest[i, :12]))
        den = 100*np.log((values[p, 12:, m]/rest[p, 12:])/(values[p, :12, m]/rest[p, :12]))
        balance[i] = num-den.mean(0)
    rows = []
    k = d['non'].index('Маркетплейсы')
    for i in np.flatnonzero(original):
        sign = np.sign(np.median(d['gap'][i, 9:, k]))
        confirm = (np.abs(ex[i, 6:, m]) >= 5) & (np.sign(ex[i, 6:, m]) == sign)
        q = {name: float(x[i, 9:].mean()) for name, x in [
            ('marketplace_numerator_excess_logpoints', ex[:, :, m]),
            ('aggregate_denominator_excess_logpoints', ex[:, :, a]),
            ('share_excess_logpoints_exact', ex[:, :, m]-ex[:, :, a]),
            ('marketplace_food_excess_logpoints', ex[:, :, m]-ex[:, :, food])]}
        q.update({'territory_id': int(f.index[i]), 'name': f.iloc[i].name_short,
            'region_name': f.iloc[i].region_name,
            'original_q4_gap_pp': float(np.median(d['gap'][i, 9:, k])),
            'same_direction_nominal_months': int(confirm.sum()),
            'nominal_confirmation': bool(confirm.sum() >= 3),
            'ratio_to_food_same_direction_q4': bool(np.sign(q['marketplace_food_excess_logpoints']) == sign),
            'ratio_to_rest_excess_logpoints': float(balance[i, 9:].mean()) if np.isfinite(balance[i]).all() else None,
            'denominator_dominates_magnitude_q4': bool(abs(q['aggregate_denominator_excess_logpoints']) > abs(q['marketplace_numerator_excess_logpoints']))})
        rows.append(q)
    return rows, {'max_additive_identity_error': float(identity),
                  'positive_aggregate_minus_marketplace_histories': int(valid.sum()),
                  'supported_balance_histories': int(np.isfinite(balance).all(1).sum())}


def logit(x):
    if not ((x > 0) & (x < 1)).all():
        raise ValueError('Synthetic logit base needs strict interior shares; no clipping')
    return np.log(x/(1-x))


def synthetic_counts(values, cats, peers, supported, count=100):
    a = cats.index('Все категории')
    non = [i for i in range(len(cats)) if i != a]
    m = non.index(cats.index('Маркетплейсы'))
    share = values[:, :, non]/values[:, :, a:a+1]
    common = np.median(share[:, 12:]-share[:, :12], axis=0)
    base = share[:, :12]+common
    valid = ((base > 0) & (base < 1)).all(axis=(1, 2))
    tids = np.asarray(synthetic_counts.tids)
    excluded = tids[~valid].tolist()
    remap = np.full(len(values), -1, dtype=int)
    remap[valid] = np.arange(valid.sum())
    original_peers = peers[valid]
    peers = np.where(original_peers >= 0, remap[np.maximum(original_peers, 0)], -1)
    supported = supported[valid] & ((peers >= 0).sum(1) >= 5)
    values, share, base, tids = values[valid], share[valid], base[valid], tids[valid]
    b = logit(base)
    u = logit(share[:, :12])
    u -= np.median(u, axis=0)
    innovation = np.diff(u, axis=1)
    innovation -= innovation.mean(1, keepdims=True)
    agg_growth = np.median(values[:, 12:, a]/values[:, :12, a], axis=0)
    def make(noise):
        v = values.copy()
        v[:, 12:, a] = values[:, :12, a]*agg_growth
        # No sum-to-one assumption: observed five categories are not exhaustive.
        s = 1/(1+np.exp(-(b+noise)))
        v[:, 12:, non] = s*v[:, 12:, a:a+1]
        return v
    # The zero-noise pp shift is common exactly, including heterogeneous bases.
    zero = make(np.zeros_like(b))
    dz = deviations(zero, cats, peers, supported)
    zero_count = int(persistent(dz['flag'][:, :, m], dz['gap'][:, :, m]).sum())
    assert zero_count == 0
    rng = np.random.default_rng(SEED)
    counts, noise_rms = [], []
    first = None
    for rep in range(count):
        starts = rng.integers(0, 11, 4)
        times = ((starts[:, None]+np.arange(3)) % 11).ravel()
        noise = np.cumsum(innovation[:, times], axis=1)
        v = make(noise)
        d = deviations(v, cats, peers, supported)
        selected = persistent(d['flag'][:, :, m], d['gap'][:, :, m])
        counts.append(int(selected.sum()))
        noise_rms.append(float(np.sqrt(np.mean(noise**2))))
        if first is None:
            first = v
    # Predeclared ID-only selection, independent of outcomes or detection score.
    ids = np.flatnonzero(supported)
    ranked = sorted(ids, key=lambda i: __import__('hashlib').sha256(f'{SEED}:{tids[i]}'.encode()).hexdigest())
    targets = np.array(ranked[:10])
    injected = first.copy()
    injected[targets, 18:, cats.index('Маркетплейсы')] += .03*injected[targets, 18:, a]
    di = deviations(injected, cats, peers, supported)
    hits = persistent(di['flag'][:, :, m], di['gap'][:, :, m])
    dn = deviations(first, cats, peers, supported)
    before = persistent(dn['flag'][:, :, m], dn['gap'][:, :, m])
    real = deviations(values, cats, peers, supported)
    real_signals = persistent(real['flag'][:, :, m], real['gap'][:, :, m])
    return {'replicates': count, 'counts': counts,
        'synthetic_cohort': len(values), 'synthetic_supported': int(supported.sum()),
        'excluded_inadmissible_base_ids': [int(t) for t in excluded],
        'observed_signals_same_synthetic_mask': int(real_signals.sum()),
        'zero_noise_common_shift_persistent': zero_count,
        'null_count_quantiles_025_50_975': np.quantile(counts, [.025, .5, .975]).tolist(),
        'mean_null_count': float(np.mean(counts)), 'mean_logit_noise_rms': float(np.mean(noise_rms)),
        'injection_target_ids': [int(tids[i]) for i in targets],
        'injected_targets_detected': int(hits[targets].sum()),
        'same_targets_flagged_before_injection': int(before[targets].sum()),
        'off_target_flags_after_injection': int(hits.sum()-hits[targets].sum()),
        'interpretation': 'Conditional synthetic model only; not observed false-alarm rate or real sensitivity'}


def run(a):
    proto = json.loads(a.protocol.read_text())
    old = json.loads((REPO/proto['input_protocol']).read_text())
    paths = {'panel': REPO/'economic-atlas/data/panel_v1.parquet',
        'population': a.data_dir/'2_bdmo_population.parquet',
        'dictionary': a.data_dir/'municipal_dictionary.parquet'}
    for k, path in paths.items():
        if sha(path) != old['input_sha256'][k]:
            raise ValueError('Frozen input mismatch: '+k)
    if a.out.exists():
        raise FileExistsError('New run directory required')
    panel, pop, dictionary = [pd.read_parquet(paths[k]) for k in ['panel', 'population', 'dictionary']]
    f, peers, support, _, eligible = fixed_peers(panel, pop, dictionary, old['peer_rule'])
    values, cats = cube_from_panel(panel, f.index)
    d = deviations(values, cats, peers, support)
    k = d['non'].index('Маркетплейсы')
    original = persistent(d['flag'][:, :, k], d['gap'][:, :, k])
    assert original.sum() == 25
    forecasts.peers = peers
    p, fits, results, checks = forecasts(values, cats, d, support, f)
    oldp = pd.read_parquet(REPO/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2/predictions.parquet')
    key = ['territory_id', 'category', 'horizon', 'origin', 'target']
    joined = p.merge(oldp[key+['profile_ses', 'actual']], on=key, validate='one_to_one', suffixes=('', '_old'))
    assert len(joined) == len(p)
    np.testing.assert_array_equal(joined.actual, joined.actual_old)
    np.testing.assert_array_equal(joined.profile_ses, joined.profile_ses_old)
    print(json.dumps({'phase': 'forecasts_checked', 'rows': len(p), 'future_mutation_predictions': checks}), flush=True)
    grid, cities = robust(panel, pop, dictionary, old['peer_rule'], proto['robustness']['peer_configs'], values, cats, f, original)
    print(json.dumps({'phase': 'robustness', 'configurations': len(grid)}), flush=True)
    decomposed, identity = denominator(values, cats, peers, support, f, original, d)
    synthetic_counts.tids = f.index.to_numpy()
    null = synthetic_counts(values, cats, peers, support, proto['synthetic']['replicates'])
    a.out.mkdir(parents=True)
    pd.DataFrame(grid).to_csv(a.out/'robustness-grid.csv', index=False)
    pd.DataFrame(cities).to_csv(a.out/'robustness-municipalities.csv', index=False)
    pd.DataFrame(decomposed).to_csv(a.out/'denominator-decomposition.csv', index=False)
    p.to_parquet(a.out/'predictions.parquet', index=False)
    dump(a.out/'fits.json', fits)
    dump(a.out/'synthetic-null.json', null)
    dump(a.out/'protocol.json', proto)
    metrics = {'status': 'COMPUTED_EXPLORATORY', 'independent_holdout': False,
        'historical_asof_verified': False, 'scientific_pass': False,
        'panel': len(values), 'supported': int(support.sum()), 'eligible': eligible,
        'same_key_forecasts': len(p), 'results': results,
        'robustness': {'configurations': len(grid),
            'original_signals': int(original.sum()),
            'original_core80': sum(r['original_signal'] and r['descriptive_core80'] for r in cities),
            'core80_all': sum(r['descriptive_core80'] for r in cities),
            'original_min_max_retained': [min(r['original25_retained'] for r in grid), max(r['original25_retained'] for r in grid)]},
        'denominator': {'signals': len(decomposed),
            'nominal_confirmed': sum(r['nominal_confirmation'] for r in decomposed),
            'ratio_to_food_same_direction': sum(r['ratio_to_food_same_direction_q4'] for r in decomposed),
            'denominator_dominates_magnitude': sum(r['denominator_dominates_magnitude_q4'] for r in decomposed), **identity},
        'checks': {'real_future_mutation_predictions': checks,
            'old_baseline_actual_exact_match_rows': len(p), 'unique_keys': not p.duplicated(key).any()},
        'direct_h6': 'UNSUPPORTED_TRAINING_ALL36_CATEGORY_TARGET_BLOCKS_COLD_START',
        'versions': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__},
        'limits': proto['limits']}
    dump(a.out/'metrics.json', metrics)
    dump(a.out/'manifest.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_sha256': {k: sha(v) for k, v in paths.items()},
        'code_sha256': sha(__file__), 'protocol_sha256': sha(a.protocol),
        'dependency_code_sha256': {str(p.relative_to(REPO)): sha(p) for p in [
            REPO/'economic-atlas/src/consumption_restructuring.py',
            REPO/'economic-atlas/src/atlas_radar_joint.py', REPO/'shock-radar/src/r9_strong_baselines.py']},
        'files': {p.name: sha(p) for p in a.out.iterdir() if p.is_file()}})
    print(json.dumps({k: v for k, v in metrics.items() if k not in ['results', 'limits']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-dir', type=Path, required=True)
    ap.add_argument('--protocol', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    run(ap.parse_args())
