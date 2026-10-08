"""A16 keeps hidden tax values out of municipal joins and fixes annual vintage."""

from datetime import date
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "economic-atlas/src"))
from a16_indirect_metrics import cv_association, load_five, load_seven
from a15_sector_construct_validity import region_cv
from test_atlas_a15 import sample


def test_tax_intake_preserves_hidden_values_and_excludes_ambiguous_keys(tmp_path):
    five = pd.DataFrame([
        {"object_oktmo": "12345678", "oktmo_history": "Без изменений", "deduction": deduction,
         "indicator_value": value, "null_value_reason": reason,
         "report_date": date(2025, 6, 1), "year": 2024,
         "object_level": "Муниципальное образование верхнего уровня", "indicator_code": "Y777000033"}
        for deduction, value, reason in [
            ("По коду вычета 320", 0.0, "NN"),
            ("По коду вычета 321", np.nan, "CD"),
            ("По коду вычета 330 (пп. 4 п. 1 ст. 219)", 100.0, "NN")]
    ] + [
        {"object_oktmo": "87654321", "oktmo_history": "Без изменений", "deduction": "По коду вычета 320",
         "indicator_value": value, "null_value_reason": "NN", "report_date": date(2025, 6, 1),
         "year": 2024, "object_level": "Муниципальное образование верхнего уровня", "indicator_code": "Y777000033"}
        for value in (10.0, 20.0)
    ])
    five_path = tmp_path / "five.parquet"
    five.to_parquet(five_path)
    wide, audit = load_five(five_path)
    first = wide.set_index("oktmo8").loc["12345678"]
    assert first.education_320 == 0
    assert pd.isna(first.education_321)
    assert first.npf_330 == 100
    assert "87654321" not in set(wide.oktmo8)
    assert audit["ambiguous_rows_excluded"] == 2


def test_seven_ndfl_selects_2024_annual_reported_in_2025(tmp_path):
    records = []
    for report_date, period, amount in [
        (date(2025, 1, 1), "Значение показателя за год", 200.0),
        (date(2024, 10, 1), "III квартал", 150.0),
        (date(2024, 1, 1), "Значение показателя за год", 100.0),
    ]:
        records.append({"object_oktmo": "12345678", "oktmo_history": "Без изменений",
                        "indicator_code": "Y777000006", "indicator_value": amount,
                        "null_value_reason": "NN", "report_date": report_date,
                        "indicator_period": period, "tax_rate": "Всего", "year": 2024,
                        "object_level": "Муниципальное образование верхнего уровня"})
    path = tmp_path / "seven.parquet"
    pd.DataFrame(records).to_parquet(path)
    wide, audit = load_seven(path)
    assert len(wide) == 1
    assert wide.income_rub.iloc[0] == 200
    assert audit["ambiguous_rows_excluded"] == 0


def test_new_cv_matches_frozen_a15_method():
    frame, signal, _ = sample()
    old, _ = region_cv(frame, signal)
    new = cv_association(frame, signal)
    assert new["mse_reduction"] == old["mse_reduction"]
    assert new["ci95_region_bootstrap"] == old["ci95_region_bootstrap"]
    assert new["positive_folds"] == old["positive_folds"]
