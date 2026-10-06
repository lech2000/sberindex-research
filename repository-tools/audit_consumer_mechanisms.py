"""Independent raw, baseline, selector and augmented-lstsq verification.

No imports from any study module. Reuses only the frozen independent raw
and matching verifier, then implements candidate formulas and choices anew.
"""
from pathlib import Path
import warnings

repo = Path(__file__).resolve().parents[1]
source_path = repo/'economic-atlas/src/consumption_restructuring_independent_validation.py'
source = source_path.read_text()
prefix = source[:source.index("pred=pd.read_parquet(RUN/'predictions.parquet')")]
prefix = prefix.replace('args=parser.parse_args()',
    "parser.add_argument('--run', type=Path)\nargs=parser.parse_args()")
# Preserve frozen equations; suppress only the repetitive pandas4 signature notice.
warnings.filterwarnings('ignore', message='Starting with pandas version 4.0 all arguments of sum will be keyword-only')
exec(compile(prefix, 'frozen independent raw and matching equations', 'exec'), globals())

NEWRUN = args.run.resolve() if args.run else REPO/'economic-atlas/runs/Consumer_mechanisms_20261007'
POOL = ['profile_ses', 'category_seasonal', 'growth_naive3', 'growth_naive1', 'conditional_ses']
own = np.stack([common_gap[:, :, 1], (logs-common_log)[:, :, 2],
    (logs-common_log)[:, :, 0], common_gap[:, :, 3], (logs-common_log)[:, :, 4]], axis=2)
extra = np.stack([gap[:, :, 1], log_gap[:, :, 2], log_gap[:, :, 0],
                  gap[:, :, 3], log_gap[:, :, 4]], axis=2)
features = {'own': own, 'peer': np.concatenate([own, extra], axis=2)}
ix = np.flatnonzero(supported)
candidate_cache, selection_cache = {}, {}


def independent_ses(x):
    levels, losses = [], []
    for alpha in np.linspace(.05, .95, 19):
        level = x[:, 0].copy()
        loss = np.zeros(len(x))
        for current in x[:, 1:].T:
            loss += np.abs(current-level)
            # Keep the declared increment form: full seasonal removal creates
            # floating-point alpha ties at the first 2024 origin. Scan each
            # alpha separately (production updates an alpha matrix at once).
            level += alpha*(current-level)
        levels.append(level)
        losses.append(loss)
    levels, losses = np.array(levels).T, np.array(losses).T
    return levels[np.arange(len(x)), losses.argmin(1)]


def candidates(c, oi, ti):
    key = c, oi, ti
    if key not in candidate_cache:
        p = baseline(c, oi, ti)
        history = values[:, :oi+1, c]
        med = category_median[:oi+1, c]
        p['growth_naive1'] = values[:, ti-12, c]*history[:, oi]/history[:, oi-12]
        p['conditional_ses'] = independent_ses(history/med)*med[oi]*med[ti-12]/med[oi-12]
        u = np.log(history)-np.log(med)
        recent = np.arange(max(12, oi-2), oi+1)
        factor = med[ti-12]*np.exp(np.mean(np.log(med[recent]/med[recent-12])))
        for shrink, name in [(0., 'profile_shrink_0'), (.35, 'profile_shrink_035'), (1., 'profile_shrink_1')]:
            season = shrink*(u[:, :12]-u[:, :12].mean(1, keepdims=True))
            level = independent_ses(u-season[:, np.arange(oi+1) % 12])
            p[name] = np.exp(level+season[:, ti % 12])*factor
        candidate_cache[key] = p
    return candidate_cache[key]


def independent_choice(c, oi, h):
    key = c, oi, h
    if key not in selection_cache:
        origins = list(range(12, oi-h+1))
        if len(origins) < 2:
            selection_cache[key] = ('profile_ses', ['profile_ses'], None)
        else:
            losses = {m: 0. for m in POOL}
            for u in origins:
                p = candidates(c, u, u+h)
                for m in POOL:
                    losses[m] += np.sum(np.abs(values[ix, u+h, c]-p[m][ix]))
            losses = {m: loss/(len(ix)*len(origins)) for m, loss in losses.items()}
            order = sorted(POOL, key=losses.get)
            selection_cache[key] = order[0], order[:2], losses
    return selection_cache[key]


def independent_base(model, c, oi, ti):
    pp = candidates(c, oi, ti)
    if model in POOL:
        return pp[model]
    picked, mixture, _ = independent_choice(c, oi, ti-oi)
    if model == 'past_pick':
        return pp[picked]
    assert model == 'past_mix'
    return sum(pp[m] for m in mixture)/len(mixture)


def independent_adjusted(base, variant, matrix, c, oi, ti):
    label_horizon = 1 if variant.startswith('one_step') else ti-oi
    origins = list(range(12, oi-label_horizon+1))
    p = independent_base(base, c, oi, ti).copy()
    if len(origins) < 2:
        return p, None, origins
    y = np.concatenate([np.log(values[ix, u+label_horizon, c]/
        independent_base(base, c, u, u+label_horizon)[ix]) for u in origins])
    x = np.concatenate([matrix[ix, u-12] for u in origins])
    mu, scale = x.mean(0), x.std(0)
    scale[scale == 0] = 1
    z = (x-mu)/scale
    # Different solution method from production's normal equations.
    penalty = np.sqrt(.1*len(x))*np.eye(x.shape[1])
    beta = np.linalg.lstsq(np.vstack([z, penalty]),
                         np.concatenate([y, np.zeros(x.shape[1])]), rcond=None)[0]
    p[ix] *= np.exp(np.clip((matrix[ix, oi-12]-mu)/scale@beta, -.1, .1))
    return p, (mu, scale, beta), origins


manifest = json.loads((NEWRUN/'manifest.json').read_text())
for path, digest in manifest['files'].items():
    assert hash_file(NEWRUN/path) == digest
for path, digest in manifest['code_sha256'].items():
    assert hash_file(REPO/path) == digest
check('new_run_file_hashes', len(manifest['files']))
check('new_math_source_hashes', len(manifest['code_sha256']))
p = pd.read_parquet(NEWRUN/'predictions.parquet')
assert len(p) == 204768 and not p.duplicated(['territory_id', 'category', 'horizon', 'origin', 'target']).any()
groups = {(cat, origin, target): g.set_index('territory_id').loc[tids]
          for (cat, origin, target), g in p.groupby(['category', 'origin', 'target'])}
for (cat, origin, target), g in groups.items():
    c, oi, ti = CATS.index(cat), MONTHS.index(origin), MONTHS.index(target)
    np.testing.assert_array_equal(g.actual, values[:, ti, c])
    np.testing.assert_array_equal(g.supported, supported)
    pp = candidates(c, oi, ti)
    for name in list(pp)+['past_pick', 'past_mix']:
        q = pp[name] if name in pp else independent_base(name, c, oi, ti)
        np.testing.assert_allclose(g[name], q, rtol=1e-9, atol=1e-6,
                                   err_msg=str((cat, origin, target, name)))
        check('independent_candidate_and_adaptive_predictions', len(g))

trace = json.loads((NEWRUN/'selection-trace.json').read_text())
for r in trace:
    c, oi, h = CATS.index(r['category']), MONTHS.index(r['origin']), r['horizon']
    origins = list(range(12, oi-h+1))
    assert r['training_targets'] == [MONTHS[u+h] for u in origins]
    assert r['training_origins'] == [MONTHS[u] for u in origins]
    assert all(u+h <= oi for u in origins)
    picked, mix, losses = independent_choice(c, oi, h)
    assert r['picked'] == picked and r['mixture'] == mix
    assert r['monthly_blocks'] == len(origins)
    if losses is not None:
        for m in POOL:
            np.testing.assert_allclose(r['past_mae'][m], losses[m], rtol=1e-9, atol=1e-6)
    check('independent_selection_trace', 1)

for fit in json.loads((NEWRUN/'fits.json').read_text()):
    c, oi, ti = CATS.index(fit['category']), MONTHS.index(fit['origin']), MONTHS.index(fit['target'])
    matrix = features['peer' if fit['variant'].endswith('peer') else 'own']
    expected, solution, origins = independent_adjusted(fit['base'], fit['variant'], matrix, c, oi, ti)
    assert fit['training_origins'] == [MONTHS[u] for u in origins]
    h = fit['label_horizon']
    assert fit['training_targets'] == [MONTHS[u+h] for u in origins]
    assert all(u+h <= oi for u in origins)
    g = groups[fit['category'], fit['origin'], fit['target']]
    name = fit['base']+'__'+fit['variant']
    np.testing.assert_allclose(g[name], expected, rtol=1e-9, atol=1e-6)
    if solution is not None:
        mu, scale, beta = solution
        np.testing.assert_allclose(fit['mean'], mu, rtol=1e-9, atol=1e-9)
        np.testing.assert_allclose(fit['scale'], scale, rtol=1e-9, atol=1e-9)
        np.testing.assert_allclose(fit['beta'], beta, rtol=1e-7, atol=1e-9)
        check('independent_augmented_lstsq_fits', 1)
    else:
        assert fit['status'] == 'COLD_START_EXACT_BASE'
        np.testing.assert_array_equal(g[name], g[fit['base']])
        check('cold_fits_exact_base', 1)
    np.testing.assert_array_equal(g.loc[tids[~supported], name], g.loc[tids[~supported], fit['base']])
    check('independent_corrected_predictions', len(g))
print(json.dumps({'phase': 'independent main forecasts passed', 'checks': CHECKS}), flush=True)

maps = pd.read_csv(NEWRUN/'peer-alignment-mappings.csv')
controls = pd.read_parquet(NEWRUN/'peer-alignment-predictions.parquet')
assert len(maps) == 20*len(ix) and len(controls) == 20*len(ix)*2*2*6
assert not controls.duplicated(['replicate', 'territory_id', 'category', 'horizon', 'origin', 'target']).any()
for rep, rows in maps.groupby('replicate'):
    mapping = np.arange(len(tids))
    assert sorted(rows.territory_id) == sorted(tids[ix])
    for row in rows.itertuples():
        i, j = positions[row.territory_id], positions[row.donor_id]
        assert supported[i] and supported[j]
        assert str(f.iloc[i]['type']) == str(f.iloc[j]['type']) == row.municipal_type
        assert int(np.floor(np.log2(f.iloc[i].population_2023))) == row.log2_population_bin
        assert int(np.floor(np.log2(f.iloc[j].population_2023))) == row.log2_population_bin
        assert row.self_mapping == (i == j)
        mapping[i] = j
    assert set(mapping[ix]) == set(ix)
    matrix = np.concatenate([own, extra[mapping]], axis=2)
    for (cat, origin, target), g in controls.loc[controls.replicate == rep].groupby(['category', 'origin', 'target']):
        g = g.set_index('territory_id').loc[tids[ix]]
        c, oi, ti = CATS.index(cat), MONTHS.index(origin), MONTHS.index(target)
        np.testing.assert_array_equal(g.actual, values[ix, ti, c])
        for variant in ['one_step_zero_peer', 'direct_zero_peer']:
            expected, _, _ = independent_adjusted('past_pick', variant, matrix, c, oi, ti)
            np.testing.assert_allclose(g[variant], expected[ix], rtol=1e-9, atol=1e-6)
            check('independent_control_predictions', len(g))
    check('pre_strata_history_permutations', len(ix))
    print(json.dumps({'phase': 'independent controls passed', 'replicate': int(rep)+1}), flush=True)

metrics = json.loads((NEWRUN/'metrics.json').read_text())
for r in metrics['results']:
    g = p.loc[p.supported & (p.category == r['category']) & (p.horizon == r['horizon'])]
    for name, expected in r['mae'].items():
        measured = sum(abs(float(y)-float(q)) for y, q in zip(g.actual, g[name]))/len(g)
        np.testing.assert_allclose(measured, expected, rtol=1e-12, atol=1e-8)
        check('scalar_mae_values', 1)
    for comparison in r['comparisons']:
        gain = np.abs(g.actual-g[comparison['reference']])-np.abs(g.actual-g[comparison['model']])
        for field, blocks, seed in [('ci95_target_month_blocks', g.target, 20261007),
                                    ('ci95_region_blocks_sensitivity', g.region_code, 20261008)]:
            unique = sorted(blocks.unique())
            sums = np.array([sum(gain.loc[blocks == b]) for b in unique])
            counts = np.array([(blocks == b).sum() for b in unique])
            samples = np.random.default_rng(seed).integers(0, len(unique), (10000, len(unique)))
            boot = sums[samples].sum(1)/counts[samples].sum(1)
            np.testing.assert_allclose(comparison[field], np.quantile(boot, [.025, .975]), rtol=1e-10, atol=1e-7)
            check('independent_paired_intervals', 1)
for r in metrics['peer_alignment_controls']:
    g = controls.loc[(controls.category == r['category']) & (controls.horizon == r['horizon'])]
    for result in r['results']:
        maes = [float(np.abs(q.actual-q[result['variant']]).mean()) for _, q in g.groupby('replicate')]
        np.testing.assert_allclose(maes, [row['mae'] for row in result['controls']], rtol=1e-12)
        assert result['matched_strictly_better_than_controls'] == sum(result['matched_peer_mae'] < x for x in maes)
        check('control_metrics', len(maes))
save(BASE/'independent-validation.json', {'status': 'TECHNICAL_PASS',
    'created_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': CHECKS,
    'code_sha256': hash_file(Path(__file__)),
    'frozen_independent_source_sha256': hash_file(source_path),
    'independent_scientific_holdout': False, 'scientific_pass': False})
print(json.dumps({'complete': True, 'checks': CHECKS}), flush=True)
