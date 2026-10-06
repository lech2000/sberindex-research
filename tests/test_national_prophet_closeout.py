from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'shock-radar/src'))
from national_prophet_closeout import national_regressor, training_frame


def test_regressor_extrapolates_from_only_available_national_yoy():
    months = pd.period_range('2021-01', '2025-12', freq='M').astype(str)
    n = pd.Series(np.exp(np.arange(len(months))*.01), index=months)
    dates = ['2023-01-01', '2023-07-01', '2024-07-01']
    x = national_regressor(n, dates, '2023-07')
    expected = [np.log(n['2022-12']), np.log(n['2023-06']),
                np.log(n['2023-06'])+np.log(n['2023-06']/n['2022-06'])]
    np.testing.assert_allclose(x, expected)
    changed = n.copy(); changed.loc[changed.index > '2023-06'] *= 1e6
    np.testing.assert_array_equal(x, national_regressor(changed, dates, '2023-07'))
    own = pd.Series(np.arange(24)+100, index=pd.period_range('2023-01', '2024-12', freq='M').astype(str))
    altered = own.copy(); altered.loc[altered.index > '2023-07'] *= 10
    pd.testing.assert_frame_equal(training_frame(own, n, '2023-07'),
                                  training_frame(altered, changed, '2023-07'))
