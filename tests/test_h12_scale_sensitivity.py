import importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location('h12_scale', Path(__file__).parents[1] / 'shock-radar/src/h12_scale_sensitivity.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_future_levels_do_not_change_training_scale():
    raw = pd.DataFrame({'territory_id': [1, 1, 1], 'category': ['x'] * 3,
                        'date': ['2023-01', '2023-02', '2023-03'], 'value': [2., 4., 1e12]})
    pred = pd.DataFrame({'territory_id': ['1'], 'category': ['x'], 'origin': ['2023-02'], 'training_months': [2]})
    assert module.training_scales(raw, pred).tolist() == [3.]
    raw.loc[2, 'value'] = -1e12
    assert module.training_scales(raw, pred).tolist() == [3.]


def test_normalized_loss_is_invariant_to_individual_series_units():
    p = pd.DataFrame({'territory_id': ['1'] * 6 + ['2'] * 6, 'category': ['x'] * 12,
                      'target': ['2024-' + f'{m:02}' for m in range(7, 13)] * 2,
                      'actual': [2.] * 6 + [30.] * 6,
                      'national_yoy_lag1': [1.] * 6 + [32.] * 6,
                      'ref': [4.] * 6 + [20.] * 6})
    scales = np.array([2.] * 6 + [20.] * 6)
    a = module.summarize(p, scales, 'ref', True, 42)
    p.loc[p.territory_id == '1', ['actual', 'national_yoy_lag1', 'ref']] *= 1000
    scales[:6] *= 1000
    b = module.summarize(p, scales, 'ref', True, 42)
    assert a == b


def test_bad_or_incomplete_scale_is_rejected():
    raw = pd.DataFrame({'territory_id': [1], 'category': ['x'], 'date': ['2023-01'], 'value': [0.]})
    pred = pd.DataFrame({'territory_id': ['1'], 'category': ['x'], 'origin': ['2023-01'], 'training_months': [1]})
    with pytest.raises(ValueError, match='positive'):
        module.training_scales(raw, pred)
    pred['training_months'] = 2
    with pytest.raises(ValueError, match='window'):
        module.training_scales(raw, pred)
