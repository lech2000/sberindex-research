"""Protect new formulas, completed horizon labels and exact decomposition."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'economic-atlas/src'))
from consumer_closeout import correction, completed_origins, at_origin, denominator, synthetic_counts
from consumption_restructuring import deviations
from test_consumption_restructuring import synthetic


def test_zero_intercept_agrees_with_independent_augmented_least_squares():
    rng = np.random.default_rng(5)
    x = rng.normal(size=(31, 4)); x[:, 3] = 2
    y = .04+.01*x[:, 0]
    q = rng.normal(size=(9, 4)); q[:, 3] = 2
    mu, scale = x.mean(0), x.std(0); scale[scale == 0] = 1
    z = (x-mu)/scale
    independent = np.linalg.lstsq(np.r_[z, np.sqrt(.1*len(x))*np.eye(4)],
                                  np.r_[y, np.zeros(4)], rcond=None)[0]
    p, fit = correction(x, y, q)
    np.testing.assert_allclose(p, np.clip((q-mu)/scale@independent, -.1, .1), atol=1e-14)
    assert fit['intercept'] == 0
    p, _ = correction(x, np.full(31, .08), x.mean(0, keepdims=True))
    np.testing.assert_array_equal(p, [0.])
    p, _ = correction(x, np.full(31, .08), x.mean(0, keepdims=True), intercept=True)
    np.testing.assert_allclose(p, [.08])


def test_completed_horizon_targets_and_h6_unavailable():
    assert [len(completed_origins(t-1, 1)) for t in range(18, 24)] == [5, 6, 7, 8, 9, 10]
    assert [len(completed_origins(t-3, 3)) for t in range(18, 24)] == [1, 2, 3, 4, 5, 6]
    assert [len(completed_origins(t-6, 6)) for t in range(18, 24)] == [0]*6
    for oi in range(12, 23):
        for h in [1, 3, 6]:
            assert all(u+h <= oi for u in completed_origins(oi, h))


def test_future_mutation_preserves_nontrivial_direct_fit_and_cold_equals_base():
    v, cats, peers, supported = synthetic()
    v[0, 12:, 0] *= np.linspace(1, 1.4, 12)
    d = deviations(v, cats, peers, supported)
    original, fits = at_origin(v, cats, d, supported, 20, 23, cats[0])
    changed = v.copy(); changed[:, 21:] = changed[:, 21:]*100+345
    dm = deviations(changed, cats, peers, supported)
    revised, fm = at_origin(changed, cats, dm, supported, 20, 23, cats[0])
    assert fits == fm
    for m in original:
        np.testing.assert_array_equal(original[m], revised[m])
    pp, ff = at_origin(v, cats, d, supported, 17, 23, cats[0])
    for fit in ff:
        if fit['model'].startswith('direct'):
            assert fit['status'] == 'COLD_START_EXACT_BASELINE'
            assert not fit['training_targets']
            np.testing.assert_array_equal(pp[fit['model']], pp['profile_ses'])


def test_denominator_only_change_is_not_nominal_confirmation():
    v, cats, peers, supported = synthetic()
    v[0, 12:, cats.index('Все категории')] *= 1.3
    d = deviations(v, cats, peers, supported)
    f = pd.DataFrame({'name_short': list('abcdefgh'), 'region_name': ['region']*8}, index=np.arange(8))
    rows, receipt = denominator(v, cats, peers, supported, f, np.array([True]+[False]*7), d)
    assert abs(rows[0]['marketplace_numerator_excess_logpoints']) < 1e-12
    assert rows[0]['aggregate_denominator_excess_logpoints'] > 0
    assert rows[0]['share_excess_logpoints_exact'] < 0
    assert rows[0]['denominator_dominates_magnitude_q4']
    assert not rows[0]['nominal_confirmation']
    assert receipt['max_additive_identity_error'] < 1e-12


def test_identical_common_shift_has_no_noise_flags():
    v, cats, _, _ = synthetic()
    v = np.concatenate([v, v], axis=0)
    peers = np.array([[j for j in range(16) if j != i] for i in range(16)])
    synthetic_counts.tids = np.arange(16)
    result = synthetic_counts(v, cats, peers, np.ones(16, bool), count=3)
    assert result['zero_noise_common_shift_persistent'] == 0
    assert result['counts'] == [0, 0, 0]
    assert result['excluded_inadmissible_base_ids'] == []
