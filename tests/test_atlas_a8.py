"""A8: внешняя проверка групп на зарплатах и занятости 2025 — статистические помощники и правила выборки (economic-atlas/runs/A8_wages2025_validation_20261005/run_a8.py)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RUN = Path(__file__).resolve().parents[1] / "economic-atlas" / "runs" / "A8_wages2025_validation_20261005"
sys.path.insert(0, str(RUN.parents[1] / "src"))
_spec = importlib.util.spec_from_file_location("a8_run", RUN / "run_a8.py")
a8 = importlib.util.module_from_spec(_spec)
sys.modules["a8_run"] = a8
_spec.loader.exec_module(a8)


def synth(effect, n_regions=20, per=25, seed=0):
    rng = np.random.default_rng(seed)
    reg = np.repeat(np.arange(n_regions), per)
    region_fe = rng.normal(0, 1, n_regions)[reg]
    x = rng.normal(0, 1, len(reg))
    g = (rng.random(len(reg)) < 0.3).astype(float)
    y = region_fe + 0.4 * x + effect * g + rng.normal(0, 0.5, len(reg))
    return y, np.column_stack([np.ones(len(reg)), x]), g, reg


def test_effect_is_recovered_and_detected():
    y, Xc, g, reg = synth(0.5)
    r = a8.analyse(y, Xc, reg, g, b_boot=300, b_perm=400)
    lo, hi = r["ci95_region_bootstrap"]
    assert abs(r["coef_G"] - 0.5) < 0.12 and lo > 0 and r["p_permutation_within_region"] < 0.01
    assert r["delta_adj_r2"] > 0 and r["cv_mse_reduction"]["mean"] > 0


def test_no_effect_is_not_detected():
    y, Xc, g, reg = synth(0.0, seed=3)
    r = a8.analyse(y, Xc, reg, g, b_boot=300, b_perm=400)
    lo, hi = r["ci95_region_bootstrap"]
    assert lo < 0 < hi and r["p_permutation_within_region"] > 0.05
    assert r["cv_mse_reduction"]["mean"] < 0.01  # нет заметного выигрыша вне выборки


def test_permutation_observed_coefficient_equals_direct_ols():
    y, Xc, g, reg = synth(0.3, seed=5)
    X0 = np.column_stack([a8.onehot(reg), Xc])
    beta, p = a8.perm_pvalue(y, X0, g, reg, 50, 1)
    assert beta == pytest.approx(a8.coef_g(y, X0, g), abs=1e-8) and 0 < p <= 1


def test_s2_coefficient_equals_change_with_lag_control():
    """Уровень с контролем прошлого уровня и рост с тем же контролем дают один и тот же коэффициент при G (сдвиг на коэффициент лага)."""
    rng = np.random.default_rng(1)
    n = 400
    lag = rng.normal(0, 1, n)
    g = (rng.random(n) < 0.4).astype(float)
    cur = 0.8 * lag + 0.3 * g + rng.normal(0, 0.3, n)
    X = np.column_stack([np.ones(n), lag])
    assert a8.coef_g(cur, X, g) == pytest.approx(a8.coef_g(cur - lag, X, g), abs=1e-9)


def test_holm_adjustment_is_monotone_and_matches_hand_calculation():
    adj = a8.holm({"a": 0.01, "b": 0.02, "c": 0.03})
    assert adj["a"] == pytest.approx(0.03) and adj["b"] == pytest.approx(0.04) and adj["c"] == pytest.approx(0.04)
    assert a8.holm({"x": 0.9})["x"] == pytest.approx(0.9)


def test_singleton_regions_do_not_break_the_estimation():
    y, Xc, g, reg = synth(0.4, n_regions=10, per=20)
    reg = reg.copy()
    reg[0] = 999  # регион из одного МО
    r = a8.analyse(y, Xc, reg, g, b_boot=100, b_perm=100)
    assert np.isfinite(r["coef_G"]) and r["n_regions"] == 11


def test_sample_rules_exclude_boundary_changes_and_noncurrent_codes(tmp_path):
    """Выборка: только действующие коды (year_to = 9999), положительные значения за три года, без «Объединение/Присоединение» в истории ОКТМО."""
    ds = tmp_path / "ds"
    ds.mkdir()
    ids = [1, 2, 3, 4, 5]
    pd.DataFrame({"territory_id": ids, "region_code": [1] * 5, "lat": [1.0, 2, 3, 4, 5], "lon": [1.0, 2, 3, 4, 5], "type": ["городской округ"] * 5,
                  "oktmo": [f"1{i}-000-000-000" for i in ids], "year_to": [9999, 9999, 9999, 2023, 9999]}).to_parquet(ds / "municipal_dictionary.parquet")
    pd.DataFrame([{"territory_id": i, "year": 2024, "age": "Всего", "gender": g, "value": 1000.0} for i in ids for g in ("М", "Ж")]).to_parquet(ds / "2_bdmo_population.parquet")
    pd.DataFrame({"territory_id": ids, "market_access": [10.0] * 5}).to_parquet(ds / "1_market_access.parquet")
    a6 = tmp_path / "assign.parquet"
    pd.DataFrame({"territory_id": ids, "month": "2024-12", "label": [0, 1, 0, 1, 0]}).to_parquet(a6)
    pan = tmp_path / "panel.parquet"
    pd.DataFrame({"territory_id": ids}).to_parquet(pan)

    def tochno(path, wipe_2025_for=None):
        rows = []
        for i in ids:
            hist = "Объединение" if i == 3 else "Без изменений"
            for y, v in ((2023, 100.0), (2024, 110.0), (2025, 0.0 if i == wipe_2025_for else 121.0)):
                rows.append({"okved2": "Всего по обследуемым видам экономической деятельности", "oktmo": f"1{i}000000"[:8], "oktmo_history": hist,
                             "mun_level": "Муниципальное образование верхнего уровня", "year": y, "indicator_value": v, "indicator_period": "Январь-декабрь"})
        pd.DataFrame(rows).to_parquet(path)

    tochno(tmp_path / "w.parquet", wipe_2025_for=2)
    tochno(tmp_path / "e.parquet")
    out = a8.build_sample(ds, str(tmp_path / "w.parquet"), str(tmp_path / "e.parquet"), str(a6), str(pan))
    assert out["exclusions"]["wage"]["year_to_not_current"] == 1
    assert out["exclusions"]["wage"]["missing_or_nonpositive_values_2023_2025"] == 1   # МО 2: нулевое значение 2025
    assert out["exclusions"]["wage"]["boundary_change_merge_or_join"] == 1             # МО 3: «Объединение»
    assert sorted(out["wage"].index.tolist()) == [1, 5]
    assert sorted(out["emp"].index.tolist()) == [1, 2, 5]
