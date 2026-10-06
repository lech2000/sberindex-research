import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

spec = importlib.util.spec_from_file_location('h12', Path(__file__).parents[1] / 'shock-radar/src/r10_equal_information_h12.py')
h12 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h12)


def fixture():
    months = pd.period_range('2022-01', '2025-12', freq='M').astype(str)
    national = pd.Series(np.arange(1, len(months) + 1, dtype=float) * 10 + 100, index=months)
    own_months = pd.period_range('2023-01', '2024-12', freq='M').astype(str)
    own = pd.DataFrame({'month': own_months, 'value': [h12.positive_base(national, h12.offset(m, -1)) * 3 for m in own_months]})
    return own, national


def test_future_national_and_municipal_values_cannot_change_inputs():
    own, national = fixture()
    expected = h12.historical_inputs(own, national, '2023-07', '2024-07')
    own.loc[own.month > '2023-07', 'value'] = -987654.0
    national.loc[national.index > '2023-06'] = 987654321.0
    actual = h12.historical_inputs(own, national, '2023-07', '2024-07')
    assert expected[0].equals(actual[0]) and expected[1].equals(actual[1])
    assert expected[2:] == actual[2:]


def test_conditional_last_equals_national_yoy_candidate():
    own, national = fixture()
    raw, normalized, future, growth, cutoff = h12.historical_inputs(own, national, '2023-12', '2024-12')
    assert cutoff == '2023-11'
    assert np.isclose(normalized.y.iloc[-1] * future, raw.y.iloc[-1] * growth)
    assert np.allclose(normalized.y, 3.0)


def test_national_unit_conversion_does_not_change_forecast_scale():
    own, national = fixture()
    a = h12.historical_inputs(own, national, '2023-08', '2024-08')
    b = h12.historical_inputs(own, national * 1000, '2023-08', '2024-08')
    assert np.allclose(a[1].y * a[2], b[1].y * b[2])
    assert a[3] == b[3]


def test_missing_national_annual_base_fails_instead_of_filling():
    own, national = fixture()
    with pytest.raises(ValueError, match='Missing national'):
        h12.historical_inputs(own, national.drop('2022-06'), '2023-07', '2024-07')


def test_duplicate_national_history_fails():
    own, national = fixture()
    national = pd.concat([national, national.loc[['2023-06']]])
    with pytest.raises(ValueError, match='Duplicate national'):
        h12.historical_inputs(own, national, '2023-07', '2024-07')


def test_missing_municipal_month_fails():
    own, national = fixture()
    with pytest.raises(ValueError, match='Gapped'):
        h12.historical_inputs(own.loc[own.month != '2023-03'], national, '2023-08', '2024-08')


def test_actual_future_national_level_is_not_extrapolated_level():
    own, national = fixture()
    _, _, level, growth, _ = h12.historical_inputs(own, national, '2023-07', '2024-07')
    assert level == national['2023-06'] * national['2023-06'] / national['2022-06']
    assert level != national['2024-06']


def test_unsupported_horizon_is_explicit():
    own, national = fixture()
    with pytest.raises(ValueError, match='H12 only'):
        h12.historical_inputs(own, national, '2023-07', '2024-01')
