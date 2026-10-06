"""Independent augmented least-squares verification of every new forecast.

Reuses the frozen independent validator's raw-input/matching equations (no
study imports), then solves the new regression with a different algorithm.
CLI: --repo --data-dir --out, as for the original independent validator.
"""
from pathlib import Path
import sys

repo = Path(__file__).resolve().parents[1]
source = (repo/'economic-atlas/src/consumption_restructuring_independent_validation.py').read_text()
prefix = source[:source.index("pred=pd.read_parquet(RUN/'predictions.parquet')")]
exec(compile(prefix, 'frozen independent raw/matching equations', 'exec'), globals())

newrun = REPO/'economic-atlas/runs/Consumer_closeout_20261006'
p = pd.read_parquet(newrun/'predictions.parquet')
assert not p.duplicated(['territory_id', 'category', 'horizon', 'origin', 'target']).any()
own_x = np.stack([common_gap[:, :, 1], (logs-common_log)[:, :, 2],
    (logs-common_log)[:, :, 0], common_gap[:, :, 3], (logs-common_log)[:, :, 4]], axis=2)
peer_x = np.concatenate([own_x, np.stack([gap[:, :, 1], log_gap[:, :, 2],
    log_gap[:, :, 0], gap[:, :, 3], log_gap[:, :, 4]], axis=2)], axis=2)
ix = np.flatnonzero(supported)
groups = {(cat, origin, target): g.set_index('territory_id').loc[tids]
          for (cat, origin, target), g in p.groupby(['category', 'origin', 'target'])}
cache = {}
def cached(c, u, t):
    key = (c, u, t)
    if key not in cache:
        cache[key] = baseline(c, u, t)['profile_ses']
    return cache[key]

fits = json.loads((newrun/'fits.json').read_text())
fit_count, predicted_count, cold_count = 0, 0, 0
for fit in fits:
    model = fit['model']
    c, oi, ti = CATS.index(fit['category']), MONTHS.index(fit['origin']), MONTHS.index(fit['target'])
    group = groups[fit['category'], fit['origin'], fit['target']]
    np.testing.assert_array_equal(group.actual, values[:, ti, c])
    base = cached(c, oi, ti)
    np.testing.assert_allclose(group.profile_ses, base, rtol=1e-10, atol=1e-7)
    h = 1 if model.startswith('one_step') else ti-oi
    u = list(range(12, oi-h+1))
    assert fit['training_origins'] == [MONTHS[i] for i in u]
    assert fit['training_targets'] == [MONTHS[i+h] for i in u]
    assert all(i+h <= oi for i in u)
    if len(u) < 2:
        assert fit['status'] == 'COLD_START_EXACT_BASELINE'
        np.testing.assert_array_equal(group[model], group.profile_ses)
        cold_count += len(tids)
        continue
    matrix = peer_x if model.endswith('peer') else own_x
    y = np.concatenate([np.log(values[ix, j+h, c]/cached(c, j, j+h)[ix]) for j in u])
    if model == 'direct_calibration':
        np.testing.assert_allclose(fit['intercept'], y.mean(), atol=1e-12)
        corr = np.full(len(ix), np.clip(y.mean(), -.1, .1))
    else:
        x = np.concatenate([matrix[ix, j-12] for j in u])
        mu, std = x.mean(0), x.std(0)
        std[std == 0] = 1
        z = (x-mu)/std
        has_intercept = '_intercept_' in model
        design = np.c_[np.ones(len(z)), z] if has_intercept else z
        penalty = np.sqrt(.1*len(x))*np.eye(x.shape[1])
        if has_intercept:
            penalty = np.c_[np.zeros(x.shape[1]), penalty]
        beta = np.linalg.lstsq(np.r_[design, penalty], np.r_[y, np.zeros(x.shape[1])], rcond=None)[0]
        expected = [fit['intercept']]+fit['beta'] if has_intercept else fit['beta']
        np.testing.assert_allclose(beta, expected, rtol=1e-8, atol=1e-10)
        np.testing.assert_allclose(mu, fit['mean'], atol=1e-11)
        np.testing.assert_allclose(std, fit['scale'], atol=1e-11)
        current = (matrix[ix, oi-12]-mu)/std
        if has_intercept:
            current = np.c_[np.ones(len(ix)), current]
        corr = np.clip(current@beta, -.1, .1)
    np.testing.assert_allclose(group.loc[tids[ix], model], base[ix]*np.exp(corr),
                              rtol=1e-9, atol=1e-6)
    predicted_count += len(ix)
    fit_count += 1

metrics = json.loads((newrun/'metrics.json').read_text())
metric_count = 0
for r in metrics['results']:
    g = p.loc[p.supported & (p.category == r['category']) & (p.horizon == r['horizon'])]
    assert len(g) == r['n']
    for m, expected in r['mae'].items():
        # Scalar list summation instead of production's NumPy mean.
        measured = sum(abs(float(a)-float(b)) for a, b in zip(g.actual, g[m]))/len(g)
        np.testing.assert_allclose(measured, expected, rtol=1e-12, atol=1e-9)
        metric_count += 1
grid = pd.read_csv(newrun/'robustness-grid.csv')
cities = pd.read_csv(newrun/'robustness-municipalities.csv')
assert len(grid) == 45 and grid.configuration.nunique() == 45
assert int((cities.original_signal & cities.descriptive_core80).sum()) == 9
assert int(cities.original_signal.sum()) == 25
decomp = pd.read_csv(newrun/'denominator-decomposition.csv')
assert set(decomp.territory_id) == set(tids[persistent[:, 1]])
assert int(decomp.nominal_confirmation.sum()) == 22
np.testing.assert_allclose(decomp.share_excess_logpoints_exact,
    decomp.marketplace_numerator_excess_logpoints-decomp.aggregate_denominator_excess_logpoints,
    atol=1e-12)
checks = {'independent_raw_and_matching': CHECKS, 'new_regression_fits': fit_count,
    'trained_predictions': predicted_count, 'cold_predictions': cold_count,
    'scalar_mae_metrics': metric_count, 'robustness_configurations': len(grid),
    'denominator_rows_exact_decomposition': len(decomp), 'source_equations_import_study': False}
save(BASE/'independent-validation.json', {'status': 'TECHNICAL_PASS',
    'created_at_utc': datetime.now(timezone.utc).isoformat(), 'checks': checks,
    'new_source_sha256': hash_file(Path(__file__)),
    'frozen_independent_source_sha256': hash_file(REPO/'economic-atlas/src/consumption_restructuring_independent_validation.py'),
    'independent_scientific_holdout': False})
print(json.dumps(checks, ensure_ascii=False), flush=True)
