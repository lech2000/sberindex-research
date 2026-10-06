"""Information boundaries, causal selection traces and whole-history controls."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'economic-atlas/src'))
from consumer_mechanisms import (PastBases, POOL, BASES, VARIANTS,
    profile_at_shrinkage, predictions_at_origin, feature_permutations, shuffled_features)
from consumption_restructuring import deviations, MONTHS
from r9_strong_baselines import predict
from test_consumption_restructuring import synthetic


def changing_panel():
    v, cats, peers, support = synthetic()
    rng = np.random.default_rng(41)
    v *= np.exp(rng.normal(0, .15, v.shape))
    v[0, 12:, cats.index('Маркетплейсы')] *= np.linspace(1, 2, 12)
    return v, cats, peers, support


def test_past_choice_agrees_with_independent_scalar_completed_forecasts():
    v, cats, _, support = changing_panel()
    e = PastBases(v, cats, support)
    cat, oi, h = cats[0], 20, 3
    c = cats.index(cat)
    med = pd.Series(np.median(v[:, :, c], axis=0), index=MONTHS)
    losses = dict.fromkeys(POOL, 0.)
    for u in range(12, oi-h+1):
        for i in range(len(v)):
            p = predict(pd.Series(v[i, :, c], index=MONTHS), med, MONTHS[u], MONTHS[u+h])
            for m in POOL:
                losses[m] += abs(v[i, u+h, c]-p[m])
    losses = {m: s/(len(v)*(oi-h-11)) for m, s in losses.items()}
    choice = e.choice(cat, oi, h)
    np.testing.assert_allclose(list(choice['past_mae'].values()), list(losses.values()), rtol=1e-12)
    order = sorted(POOL, key=losses.get)
    assert choice['picked'] == order[0] and choice['mixture'] == order[:2]
    assert choice['training_targets'][-1] == MONTHS[oi]
    np.testing.assert_array_equal(e.base('past_pick', cat, oi, oi+h),
                                  e.candidate(cat, oi, oi+h)[order[0]])


def test_future_mutation_does_not_change_choices_fits_or_predictions():
    v, cats, peers, support = changing_panel()
    d = deviations(v, cats, peers, support)
    e = PastBases(v, cats, support)
    original, fits = predictions_at_origin(e, d, support, 20, 23, cats[0])
    changed = v.copy()
    changed[:, 21:] = 123456+changed[:, 21:]*100
    m = PastBases(changed, cats, support)
    dm = deviations(changed, cats, peers, support)
    mutant, fm = predictions_at_origin(m, dm, support, 20, 23, cats[0])
    assert fits == fm and e.choices == m.choices
    for name in original:
        np.testing.assert_array_equal(original[name], mutant[name])
    assert any(np.any(original[b+'__one_step_zero_own'] != original[b]) for b in BASES)


def test_cold_start_direct_h6_and_unsupported_are_exact_base():
    v, cats, peers, support = changing_panel()
    support[-2:] = False
    d = deviations(v, cats, peers, support)
    e = PastBases(v, cats, support)
    pp, fits = predictions_at_origin(e, d, support, 17, 23, cats[0])
    assert e.choice(cats[0], 17, 6)['status'] == 'COLD_START_EXACT_PROFILE'
    assert e.choice(cats[0], 15, 3)['status'] == 'COLD_START_EXACT_PROFILE'
    for b in BASES:
        for variant in VARIANTS:
            np.testing.assert_array_equal(pp[b][-2:], pp[b+'__'+variant][-2:])
        for variant in ['direct_zero_own', 'direct_zero_peer']:
            np.testing.assert_array_equal(pp[b], pp[b+'__'+variant])
    for fit in fits:
        if fit['variant'].startswith('direct'):
            assert fit['monthly_blocks'] == 0 and fit['status'] == 'COLD_START_EXACT_BASE'
        assert all(t <= fit['origin'] for t in fit['training_targets'])


def test_historical_adaptive_label_uses_historical_choice_not_current_winner():
    v, cats, peers, support = changing_panel()
    e = PastBases(v, cats, support)
    d = deviations(v, cats, peers, support)
    predictions_at_origin(e, d, support, 20, 23, cats[0])
    # January had no completed forecast, even when the current winner differs.
    early = e.choice(cats[0], 12, 1)
    assert early['picked'] == 'profile_ses' and early['monthly_blocks'] == 0
    np.testing.assert_array_equal(e.base('past_pick', cats[0], 12, 13),
                                  e.candidate(cats[0], 12, 13)['profile_ses'])
    assert (cats[0], 12, 1) in e.choices and (cats[0], 20, 3) in e.choices


def test_profile_shrink_07_matches_scalar_reference_and_zero_removes_season():
    v, cats, _, support = changing_panel()
    e = PastBases(v, cats, support)
    c, oi, ti = 0, 19, 22
    med = e.medians[:, c]
    q = profile_at_shrinkage(v[:, :, c], med, oi, ti, .7)
    for i in range(len(v)):
        scalar = predict(pd.Series(v[i, :, c], index=MONTHS),
                         pd.Series(med, index=MONTHS), MONTHS[oi], MONTHS[ti])
        np.testing.assert_allclose(q[i], scalar['profile_ses'], rtol=1e-12)
    for shrink in [0., .35, .7, 1.]:
        p = profile_at_shrinkage(v[:, :, c], med, oi, ti, shrink)
        assert np.isfinite(p).all() and (p > 0).all()


def test_shuffle_preserves_pre_strata_and_full_temporal_feature_histories():
    v, cats, peers, support = changing_panel()
    f = pd.DataFrame({'type': ['town']*6+['village']*2,
        'population_2023': [1000]*6+[1000, 4000]}, index=np.arange(8))
    mappings, records = feature_permutations(f, support, count=3, seed=31)
    again, _ = feature_permutations(f, support, count=3, seed=31)
    d = deviations(v, cats, peers, support)
    for mapping, repeat in zip(mappings, again):
        np.testing.assert_array_equal(mapping, repeat)
        assert set(mapping[:6]) == set(range(6)) and list(mapping[6:]) == [6, 7]
        shuffled = shuffled_features(d, mapping)
        np.testing.assert_array_equal(shuffled['peer_x'][:, :, :5], d['own_x'])
        np.testing.assert_array_equal(shuffled['peer_x'][:, :, 5:], d['peer_x'][mapping, :, 5:])
    assert records.loc[records.territory_id.isin([6, 7]), 'self_mapping'].all()
    assert not records.loc[records.territory_id < 6, 'self_mapping'].all()
