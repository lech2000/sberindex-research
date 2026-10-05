"""Checks protect time boundaries, denominator interpretation and match support."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'economic-atlas/src'))
from consumption_restructuring import (loo_median, deviations, persistent,
    fit_correction, fixed_peers, forecast, select_stories, MONTHS)
from test_atlas_radar_joint import sample


def test_leave_one_out_median_odd_even_ties():
    for n in [2, 3, 6, 7]:
        x = np.random.default_rng(n).integers(0, 3, (n, 12, 5)).astype(float)
        expected = np.stack([np.median(np.delete(x, i, axis=0), axis=0) for i in range(n)])
        np.testing.assert_array_equal(loo_median(x), expected)


def synthetic():
    cats = sorted(['Все категории', 'Здоровье', 'Маркетплейсы',
                   'Общественное питание', 'Продовольствие', 'Транспорт'])
    v = np.ones((8, 24, 6))*10
    v[:, :, cats.index('Все категории')] = 100
    v[:, 12:] *= 1.2  # Common nominal growth leaves ratios unchanged.
    peers = np.array([[j for j in range(8) if j != i] for i in range(8)])
    return v, cats, peers, np.ones(8, bool)


def test_common_growth_unflagged_exception_persistent_and_prefix_invariant():
    v, cats, peers, support = synthetic()
    d = deviations(v, cats, peers, support)
    assert not d['flag'].any()
    v[0, 12:, cats.index('Маркетплейсы')] += 6
    d = deviations(v, cats, peers, support)
    k = d['non'].index('Маркетплейсы')
    assert persistent(d['flag'][:, :, k], d['gap'][:, :, k]).tolist() == [True]+[False]*7
    changed = v.copy()
    changed[:, 20:] *= 1000
    dm = deviations(changed, cats, peers, support)
    np.testing.assert_array_equal(dm['peer_x'][:, :8], d['peer_x'][:, :8])
    # Two isolated flags cannot satisfy persistence; opposing signs cannot either.
    flag = np.zeros((1, 12), bool); flag[0, [6, 8]] = True
    assert not persistent(flag, np.ones((1, 12)))[0]
    flag[0, 7] = True; gap = np.ones((1, 12)); gap[0, 7] = -1
    assert not persistent(flag, gap)[0]


def test_nominal_and_ratio_confirmation_differ_when_denominator_grows():
    v, cats, peers, support = synthetic()
    v[0, 12:, cats.index('Все категории')] *= 1.2
    d = deviations(v, cats, peers, support)
    food = d['non'].index('Продовольствие')
    assert (d['gap'][0, :, food] < 0).all()
    assert (d['nominal_gap'][0, :, cats.index('Продовольствие')] == 0).all()


def test_ridge_matches_independent_augmented_least_squares_and_clips():
    rng = np.random.default_rng(123)
    x = rng.normal(size=(40, 5)); x[:, 4] = 2
    y = rng.normal(size=40)/100
    current = rng.normal(size=(7, 5)); current[:, 4] = 2
    predicted, fit = fit_correction(x, y, current)
    mu, scale = x.mean(0), x.std(0); scale[scale == 0] = 1
    z = np.c_[np.ones(len(x)), (x-mu)/scale]
    penalty = np.zeros((5, 6)); penalty[:, 1:] = np.sqrt(.1*len(x))*np.eye(5)
    beta = np.linalg.lstsq(np.r_[z, penalty], np.r_[y, np.zeros(5)], rcond=None)[0]
    expected = np.clip(np.c_[np.ones(len(current)), (current-mu)/scale]@beta, -.1, .1)
    np.testing.assert_allclose(predicted, expected, rtol=1e-11, atol=1e-13)
    clipped, _ = fit_correction(x, np.ones(40), current)
    np.testing.assert_array_equal(clipped, np.full(7, .1))


def test_matching_no_self_future_population_or_outcome_and_missing_support():
    panel, pop = sample()
    dictionary = pd.DataFrame([{'territory_id': i, 'type': 'city', 'year_from': 2010,
                                 'year_to': 9999} for i in range(1, 8)])
    rule = {'nearest': 10, 'minimum_peers': 5, 'population_ratio': [.5, 2],
            'max_standardized_distance': 3}
    f, p, s, records, _ = fixed_peers(panel, pop, dictionary, rule)
    assert s.all()
    for i, row in enumerate(p):
        assert i not in row
    altered = panel.copy(); altered.loc[altered.ym > '2023-12', 'value'] *= 100000
    pop.loc[pop.year == 2024, 'value'] *= 99999
    _, pp, ss, rr, _ = fixed_peers(altered, pop, dictionary, rule)
    np.testing.assert_array_equal(p, pp); np.testing.assert_array_equal(s, ss)
    pd.testing.assert_frame_equal(records, rr)
    dictionary.loc[dictionary.territory_id >= 4, 'type'] = 'district'
    _, _, ss, rr, _ = fixed_peers(panel, pop, dictionary, rule)
    assert not ss.any() and (rr.status == 'NO_MATCH_SUPPORT').all()


def test_forecast_training_targets_never_future_and_exact_cold_start():
    v, cats, peers, support = synthetic()
    # Different past dynamics create nontrivial training labels.
    v[0, 12:, 0] *= np.linspace(1, 1.4, 12)
    d = deviations(v, cats, peers, support)
    rows, fits = forecast(v, cats, d, support)
    for fit in fits:
        assert fit['last_training_target'] is None or fit['last_training_target'] <= fit['origin']
        assert all(t < fit['origin'] for t in fit['training_origins'])
    assert sum(r['cold_start'] for r in rows) == 12  # 2 earliest h6 blocks x 6 categories.
    for r in rows:
        if r['cold_start']:
            np.testing.assert_array_equal(r['predictions']['peer_ridge'], r['predictions']['profile_ses'])
    oi = 17
    changed = v.copy(); changed[:, oi+1:] = changed[:, oi+1:]*1000+123
    dm = deviations(changed, cats, peers, support)
    rr, ff = forecast(changed, cats, dm, support)
    a, b = [r for r in rows if r['oi'] == oi], [r for r in rr if r['oi'] == oi]
    for r, q in zip(a, b):
        for m in r['predictions']:
            np.testing.assert_array_equal(r['predictions'][m], q['predictions'][m])
    assert [f for f in fits if f['origin'] == MONTHS[oi]] == [f for f in ff if f['origin'] == MONTHS[oi]]


def test_story_selection_honors_case_insensitive_dictionary_city_type():
    rows = [{'territory_id': i, 'type': kind, 'supported': True,
             'Маркетплейсы': {'persistent': True, 'q4_peer_gap_pp': gap}}
            for i, kind, gap in [(1, 'муниципальный район', 20),
                                 (2, 'городской округ', 2),
                                 (3, 'Городской округ', 3),
                                 (4, 'городской округ', 4),
                                 (5, 'городской округ', -2),
                                 (6, 'муниципальный район', -5)]]
    assert select_stories(rows) == [4, 3, 2, 5, 6]
