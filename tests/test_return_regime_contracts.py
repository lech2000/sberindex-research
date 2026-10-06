"""Protect event credit and paired return controls from optimistic evaluation."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'shock-radar/src'))
from return_regime_control import match, synthetic

def test_before_onset_and_late_alarm_cannot_receive_event_credit():
    alarms = pd.DataFrame({'tid': ['before', 'late', 'onset', 'last'],
                           'ym': ['2024-06', '2024-09', '2024-07', '2024-08']})
    hits, delays = match(alarms, ['before', 'late', 'onset', 'last', 'missing'], '2024-07', 1)
    assert hits.tolist() == [False, False, True, True, False]
    assert delays == [None, None, 0, 1, None]

def test_one_transition_hit_cannot_be_credited_as_a_complete_loop():
    alarms = pd.DataFrame({'tid': ['a', 'b', 'a'], 'ym': ['2024-07', '2024-10', '2024-11']})
    enter, _ = match(alarms, ['a', 'b'], '2024-07', 1)
    returned, _ = match(alarms, ['a', 'b'], '2024-10', 1)
    assert (enter & returned).tolist() == [True, False]

def test_return_world_restores_exact_paired_noise_not_a_new_random_sample():
    for family in ['gaussian', 'student5']:
        null, shifted, ids = synthetic(202610070, family, 4)
        changed = shifted.tid.isin(ids) & shifted.ym.between('2024-07', '2024-09')
        np.testing.assert_array_equal(null.loc[~changed, 'rel'], shifted.loc[~changed, 'rel'])
        np.testing.assert_allclose(np.abs(shifted.loc[changed, 'rel'] - null.loc[changed, 'rel']), .2, atol=1e-15)
        assert len(ids) == len(set(ids)) == 10
        np.testing.assert_array_equal(null.loc[null.ym >= '2024-10', 'rel'], shifted.loc[shifted.ym >= '2024-10', 'rel'])
