"""Frozen exploratory baseline/seasonality/peer-alignment experiment; CPU only."""
from pathlib import Path
import argparse
import json
import platform
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from consumption_restructuring import (REPO, MONTHS, fixed_peers, cube_from_panel,
    deviations, predict_block, block_ci, sha, dump)
from consumer_closeout import correction, completed_origins
from r9_strong_baselines import ses_matrix

POOL = ['profile_ses', 'category_seasonal', 'growth_naive3',
        'growth_naive1', 'conditional_ses']
BASES = ['profile_ses', 'category_seasonal', 'past_pick', 'past_mix']
VARIANTS = ['one_step_zero_own', 'one_step_zero_peer',
            'direct_zero_own', 'direct_zero_peer']
SHRINKAGES = [0., .35, .7, 1.]
DIAGNOSTICS = ['profile_shrink_0', 'profile_shrink_035', 'profile_ses', 'profile_shrink_1']
KEY = ['territory_id', 'category', 'horizon', 'origin', 'target']
SEED = 20261007


def profile_at_shrinkage(values, med, oi, ti, shrinkage):
    y, m = values[:, :oi+1], med[:oi+1]
    u = np.log(y)-np.log(m)
    season = shrinkage*(u[:, :12]-u[:, :12].mean(1, keepdims=True))
    adjusted = u-season[:, np.arange(oi+1) % 12]
    k = min(3, oi-11)
    recent = np.arange(oi-k+1, oi+1)
    factor = med[ti-12]*np.exp(np.mean(np.log(med[recent])-np.log(med[recent-12])))
    return np.exp(ses_matrix(adjusted)+season[:, ti % 12])*factor


class PastBases:
    """Cache scalar-time information sets; historical choices never revised."""
    def __init__(self, values, cats, support):
        self.values, self.cats = values, cats
        self.ix = np.flatnonzero(support)
        if not len(self.ix) or not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError('Positive complete panel and support required')
        self.medians = np.median(values, axis=0)
        self.candidates, self.choices = {}, {}

    def candidate(self, cat, oi, ti):
        if not (12 <= oi < ti < self.values.shape[1]) or ti-12 > oi:
            raise ValueError('Unsupported seasonal forecast information set')
        key = (cat, oi, ti)
        if key not in self.candidates:
            c = self.cats.index(cat)
            v, med = self.values[:, :, c], self.medians[:, c]
            p = predict_block(v, med, oi, ti)
            for shrink, name in zip(SHRINKAGES, DIAGNOSTICS):
                q = profile_at_shrinkage(v, med, oi, ti, shrink)
                if name == 'profile_ses':
                    np.testing.assert_array_equal(p[name], q)
                else:
                    p[name] = q
            if not np.isfinite(np.column_stack(list(p.values()))).all():
                raise ValueError('Incomplete candidate mask')
            self.candidates[key] = p
        return self.candidates[key]

    def choice(self, cat, oi, h):
        key = (cat, oi, h)
        if key not in self.choices:
            origins = completed_origins(oi, h)
            record = {'category': cat, 'origin': MONTHS[oi], 'horizon': h,
                'training_origins': [MONTHS[u] for u in origins],
                'training_targets': [MONTHS[u+h] for u in origins],
                'monthly_blocks': len(origins), 'municipalities': len(self.ix),
                'training_rows': len(origins)*len(self.ix)}
            if len(origins) < 2:
                record.update(status='COLD_START_EXACT_PROFILE',
                              ranked_pool=POOL.copy(), past_mae=None,
                              picked='profile_ses', mixture=['profile_ses'])
            else:
                c = self.cats.index(cat)
                losses = np.zeros(len(POOL))
                for u in origins:
                    pp = self.candidate(cat, u, u+h)
                    actual = self.values[self.ix, u+h, c]
                    losses += [np.abs(actual-pp[m][self.ix]).mean() for m in POOL]
                losses /= len(origins)
                order = np.argsort(losses, kind='stable')
                ranked = [POOL[j] for j in order]
                record.update(status='PAST_SELECTION', ranked_pool=ranked,
                    past_mae={m: float(losses[j]) for j, m in enumerate(POOL)},
                    picked=ranked[0], mixture=ranked[:2])
            self.choices[key] = record
        return self.choices[key]

    def base(self, model, cat, oi, ti):
        p = self.candidate(cat, oi, ti)
        if model in POOL:
            return p[model]
        record = self.choice(cat, oi, ti-oi)
        if model == 'past_pick':
            return p[record['picked']]
        if model == 'past_mix':
            return np.mean([p[m] for m in record['mixture']], axis=0)
        raise ValueError('Unknown base: '+model)


def adjusted_at_origin(engine, d, support, oi, ti, cat, base, variant):
    ix = engine.ix
    if not np.array_equal(ix, np.flatnonzero(support)):
        raise ValueError('Support changed')
    h = ti-oi
    k = 1 if variant.startswith('one_step') else h
    origins = completed_origins(oi, k)
    p = engine.base(base, cat, oi, ti).copy()
    record = {'base': base, 'variant': variant, 'category': cat,
        'origin': MONTHS[oi], 'target': MONTHS[ti], 'horizon': h,
        'label_horizon': k, 'monthly_blocks': len(origins),
        'training_origins': [MONTHS[u] for u in origins],
        'training_targets': [MONTHS[u+k] for u in origins],
        'training_rows': len(origins)*len(ix),
        'status': 'COLD_START_EXACT_BASE' if len(origins) < 2 else 'PAST_FIT'}
    if len(origins) >= 2:
        c = engine.cats.index(cat)
        y = np.concatenate([np.log(engine.values[ix, u+k, c]/
            engine.base(base, cat, u, u+k)[ix]) for u in origins])
        key = 'peer_x' if variant.endswith('peer') else 'own_x'
        x = np.concatenate([d[key][ix, u-12] for u in origins])
        q, fit = correction(x, y, d[key][ix, oi-12])
        p[ix] *= np.exp(q)
        record.update(fit)
    return p, record


def predictions_at_origin(engine, d, support, oi, ti, cat):
    out = dict(engine.candidate(cat, oi, ti))
    fits = []
    for base in BASES:
        out[base] = engine.base(base, cat, oi, ti)
        for variant in VARIANTS:
            name = base+'__'+variant
            out[name], fit = adjusted_at_origin(engine, d, support, oi, ti, cat, base, variant)
            fits.append(fit)
    return out, fits


def feature_permutations(f, support, count=20, seed=SEED):
    ix = np.flatnonzero(support)
    population = f.population_2023.to_numpy(float)
    if not np.isfinite(population[ix]).all() or (population[ix] <= 0).any():
        raise ValueError('Invalid pre-strata population')
    bins = np.floor(np.log2(population[ix])).astype(int)
    strata = [(str(f.iloc[i]['type']), int(b)) for i, b in zip(ix, bins)]
    groups = {}
    for i, group in zip(ix, strata):
        groups.setdefault(group, []).append(i)
    rng = np.random.default_rng(seed)
    mappings, records = [], []
    for rep in range(count):
        mapping = np.arange(len(f))
        for group in sorted(groups):
            positions = np.array(sorted(groups[group], key=lambda i: int(f.index[i])))
            mapping[positions] = rng.permutation(positions)
            for i in positions:
                records.append({'replicate': rep, 'territory_id': int(f.index[i]),
                    'donor_id': int(f.index[mapping[i]]), 'municipal_type': group[0],
                    'log2_population_bin': group[1], 'stratum_size': len(positions),
                    'self_mapping': bool(mapping[i] == i)})
        mappings.append(mapping)
    return mappings, pd.DataFrame(records)


def shuffled_features(d, mapping):
    # The full12x5 trajectory is transferred together, never month by month.
    extra = d['peer_x'][:, :, 5:]
    return {'own_x': d['own_x'],
            'peer_x': np.concatenate([d['own_x'], extra[mapping]], axis=2)}


def comparison(g, reference, model):
    a = np.abs(g.actual-g[reference]).to_numpy()
    b = np.abs(g.actual-g[model]).to_numpy()
    gain = a-b
    ci, nm = block_ci(gain, g.target, SEED)
    rc, nr = block_ci(gain, g.region_code, SEED+1)
    return {'reference': reference, 'model': model, 'mae_gain': float(gain.mean()),
        'gain_percent': float(100*gain.mean()/a.mean()),
        'ci95_target_month_blocks': ci, 'target_month_blocks': nm,
        'ci95_region_blocks_sensitivity': rc, 'region_blocks': nr}


def summarize(p, names):
    results = []
    pairs = [('profile_ses', m) for m in POOL[1:]+['past_pick', 'past_mix']+DIAGNOSTICS if m != 'profile_ses']
    for base in BASES:
        pairs.extend((base, base+'__'+v) for v in VARIANTS)
        for label in ['one_step', 'direct']:
            pairs.append((base+'__'+label+'_zero_own', base+'__'+label+'_zero_peer'))
    for (cat, h), g in p.loc[p.supported].groupby(['category', 'horizon']):
        maes = {m: float(np.abs(g.actual-g[m]).mean()) for m in names}
        best_static = min(POOL, key=lambda m: maes[m])
        # Descriptive benchmark, never fed to forecasting or selections.
        extra = [(best_static, m) for m in ['past_pick', 'past_mix']+
                 [base+'__'+v for base in BASES for v in VARIANTS]]
        comparisons = [comparison(g, a, b) for a, b in dict.fromkeys(pairs+extra) if a != b]
        results.append({'category': cat, 'horizon': int(h), 'n': len(g),
            'municipalities': g.territory_id.nunique(), 'mae': maes,
            'best_static_in_viewed_test_window': best_static,
            'best_static_use': 'Descriptive hindsight comparison only; not an operational selector',
            'comparisons': comparisons,
            'by_month': [{'target': t, 'n': len(q),
                'mae': {m: float(np.abs(q.actual-q[m]).mean()) for m in names}}
                for t, q in g.groupby('target')]})
    return results


def run(a):
    proto = json.loads(a.protocol.read_text())
    if (proto['baseline_pool_order'] != POOL or proto['correction']['bases'] != BASES or
        proto['correction']['variants'] != VARIANTS or
        proto['peer_alignment_control']['replicates'] != 20 or
        proto['seasonal_profile_diagnostic']['shrinkage'] != SHRINKAGES):
        raise ValueError('Code/protocol mismatch')
    old = json.loads((REPO/proto['input_protocol']).read_text())
    paths = {'panel': REPO/'economic-atlas/data/panel_v1.parquet',
        'population': a.data_dir/'2_bdmo_population.parquet',
        'dictionary': a.data_dir/'municipal_dictionary.parquet'}
    for k, path in paths.items():
        if sha(path) != old['input_sha256'][k]:
            raise ValueError('Frozen input mismatch: '+k)
    if a.out.exists():
        raise FileExistsError('New run directory required')
    panel, pop, dictionary = [pd.read_parquet(paths[k]) for k in paths]
    f, peers, support, _, eligible = fixed_peers(panel, pop, dictionary, old['peer_rule'])
    values, cats = cube_from_panel(panel, f.index)
    d = deviations(values, cats, peers, support)
    engine = PastBases(values, cats, support)
    frames, fits, names = [], [], None
    for h in proto['horizons']:
        for ti in [MONTHS.index(t) for t in proto['targets']]:
            oi = ti-h
            for cat in cats:
                pp, records = predictions_at_origin(engine, d, support, oi, ti, cat)
                names = list(pp)
                fits.extend(records)
                frames.append(pd.DataFrame({'territory_id': f.index,
                    'region_code': f.region_code.to_numpy(), 'category': cat,
                    'horizon': h, 'origin': MONTHS[oi], 'target': MONTHS[ti],
                    'actual': values[:, ti, cats.index(cat)], 'supported': support, **pp}))
    p = pd.concat(frames, ignore_index=True)
    if p.duplicated(KEY).any() or not np.isfinite(p[names]).all().all():
        raise ValueError('Incomplete or repeated predictions')
    oldp = pd.read_parquet(REPO/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2/predictions.parquet')
    joined = p.merge(oldp[KEY+['profile_ses', 'category_seasonal', 'growth_naive3', 'actual']],
                     on=KEY, validate='one_to_one', suffixes=('', '_old'))
    assert len(joined) == len(p)
    for col in ['profile_ses', 'category_seasonal', 'growth_naive3', 'actual']:
        np.testing.assert_array_equal(joined[col], joined[col+'_old'])
    print(json.dumps({'phase': 'main_predictions', 'rows': len(p), 'models': len(names)}), flush=True)
    # Check complete implementation, including historical adaptive choices.
    future_checks = 0
    for oi in range(12, 23):
        changed = values.copy()
        changed[:, oi+1:] = changed[:, oi+1:]*100+12345
        dm = deviations(changed, cats, peers, support)
        mutant = PastBases(changed, cats, support)
        for h in proto['horizons']:
            ti = oi+h
            if ti >= 24 or MONTHS[ti] not in proto['targets']:
                continue
            for cat in cats:
                pp, ff = predictions_at_origin(engine, d, support, oi, ti, cat)
                pm, fm = predictions_at_origin(mutant, dm, support, oi, ti, cat)
                assert ff == fm
                assert engine.choice(cat, oi, h) == mutant.choice(cat, oi, h)
                for m in pp:
                    np.testing.assert_array_equal(pp[m], pm[m])
                    future_checks += len(values)
    print(json.dumps({'phase': 'future_mutation', 'prediction_comparisons': future_checks}), flush=True)
    mappings, mapping_records = feature_permutations(f, support)
    control_frames = []
    for rep, mapping in enumerate(mappings):
        dp = shuffled_features(d, mapping)
        for h in proto['peer_alignment_control']['horizons']:
            for ti in [MONTHS.index(t) for t in proto['targets']]:
                for cat in proto['primary_categories']:
                    out = {}
                    for v in proto['peer_alignment_control']['variants']:
                        out[v], _ = adjusted_at_origin(engine, dp, support, ti-h, ti, cat, 'past_pick', v)
                    ix = engine.ix
                    control_frames.append(pd.DataFrame({'replicate': rep,
                        'territory_id': f.index[ix], 'category': cat, 'horizon': h,
                        'origin': MONTHS[ti-h], 'target': MONTHS[ti],
                        'actual': values[ix, ti, cats.index(cat)], **{m: x[ix] for m, x in out.items()}}))
        print(json.dumps({'phase': 'peer_alignment_control', 'replicate': rep+1, 'total': 20}), flush=True)
    controls = pd.concat(control_frames, ignore_index=True)
    controls_results = []
    for (cat, h), g in controls.groupby(['category', 'horizon']):
        original = p.loc[p.supported & (p.category == cat) & (p.horizon == h)]
        rows = []
        for v in proto['peer_alignment_control']['variants']:
            matched_mae = float(np.abs(original.actual-original['past_pick__'+v]).mean())
            each = [{'replicate': int(rep), 'mae': float(np.abs(q.actual-q[v]).mean())}
                    for rep, q in g.groupby('replicate')]
            e = np.array([r['mae'] for r in each])
            rows.append({'variant': v, 'matched_peer_mae': matched_mae,
                'own_only_mae': float(np.abs(original.actual-original['past_pick__'+v.replace('_peer', '_own')]).mean()),
                'controls': each, 'control_mae_mean': float(e.mean()),
                'control_mae_quantiles_025_50_975': np.quantile(e, [.025, .5, .975]).tolist(),
                'matched_strictly_better_than_controls': int((matched_mae < e).sum()),
                'interpretation': 'Descriptive feature-alignment rank only; not a permutation p-value'})
        controls_results.append({'category': cat, 'horizon': int(h), 'n_per_replicate': len(original), 'results': rows})
    results = summarize(p, names)
    # Every computed choice is kept, including bases of historical residual labels.
    choices = sorted(engine.choices.values(), key=lambda r: (r['category'], r['origin'], r['horizon']))
    assert all(t <= r['origin'] for r in choices for t in r['training_targets'])
    assert all(t <= r['origin'] for r in fits for t in r['training_targets'])
    for base in BASES:
        q = p.loc[~p.supported]
        for v in VARIANTS:
            np.testing.assert_array_equal(q[base], q[base+'__'+v])
        for v in ['direct_zero_own', 'direct_zero_peer']:
            q = p.loc[p.horizon == 6]
            np.testing.assert_array_equal(q[base], q[base+'__'+v])
    a.out.mkdir(parents=True)
    p.to_parquet(a.out/'predictions.parquet', index=False)
    controls.to_parquet(a.out/'peer-alignment-predictions.parquet', index=False)
    mapping_records.to_csv(a.out/'peer-alignment-mappings.csv', index=False)
    dump(a.out/'fits.json', fits)
    dump(a.out/'selection-trace.json', choices)
    dump(a.out/'protocol.json', proto)
    metrics = {'status': 'COMPUTED_EXPLORATORY', 'independent_holdout': False,
        'historical_asof_verified': False, 'scientific_pass': False,
        'panel': len(values), 'eligible': eligible, 'supported': int(support.sum()),
        'rows': len(p), 'models': names, 'results': results,
        'peer_alignment_controls': controls_results,
        'control_rows': len(controls), 'control_replicates': len(mappings),
        'control_strata': mapping_records[['municipal_type', 'log2_population_bin']].drop_duplicates().shape[0],
        'singleton_municipalities': int((mapping_records.loc[mapping_records.replicate == 0].stratum_size == 1).sum()),
        'self_mappings_by_replicate': mapping_records.groupby('replicate').self_mapping.sum().astype(int).to_dict(),
        'checks': {'exact_old_rows': len(joined), 'future_mutation_predictions': future_checks,
                   'selector_training_targets_before_origin': True,
                   'correction_training_targets_before_origin': True,
                   'unsupported_corrections_exact_base': True,
                   'direct_h6_exact_cold_base': True},
        'versions': {'python': platform.python_version(), 'numpy': np.__version__, 'pandas': pd.__version__},
        'limits': proto['limits']}
    dump(a.out/'metrics.json', metrics)
    source = [Path(__file__), REPO/'economic-atlas/src/consumer_closeout.py',
              REPO/'economic-atlas/src/consumption_restructuring.py',
              REPO/'economic-atlas/src/atlas_radar_joint.py', REPO/'shock-radar/src/r9_strong_baselines.py']
    dump(a.out/'manifest.json', {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'input_sha256': {k: sha(v) for k, v in paths.items()}, 'protocol_sha256': sha(a.protocol),
        'code_sha256': {str(p.relative_to(REPO)): sha(p) for p in source},
        'files': {p.name: sha(p) for p in sorted(a.out.iterdir()) if p.is_file()}})
    print(json.dumps({'complete': True, 'rows': len(p), 'models': len(names),
                      'scientific_pass': False}), flush=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-dir', type=Path, required=True)
    ap.add_argument('--protocol', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    run(ap.parse_args())
