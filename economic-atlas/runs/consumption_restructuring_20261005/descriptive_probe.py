"""Descriptive feasibility probe; no crisis, causal, or forecast validation."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-dir", type=Path, required=True, help="Existing consumption and dictionary Parquet directory")
parser.add_argument("--atlas-root", type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "descriptive_probe.json")
args = parser.parse_args()
INPUTS = args.data_dir
ATLAS = args.atlas_root
OUT = args.out
FEATURES = ATLAS / "runs/A5/features.parquet"
RAW = INPUTS / "8_consumption.parquet"
DICTIONARY = INPUTS / "municipal_dictionary.parquet"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


frozen = json.loads((ATLAS / "frozen_inputs.json").read_text())
assert sha(FEATURES) == frozen["features"]["sha256"]
ids = pd.read_parquet(FEATURES).territory_id
assert len(ids) == ids.nunique() == 1896
d = pd.read_parquet(RAW)
d = d[d.territory_id.isin(ids)].copy()
d["date"] = pd.to_datetime(d.date)
assert len(d) == 273024
assert not d.duplicated(["territory_id", "date", "category"]).any()
p = d.pivot(index=["territory_id", "date"], columns="category", values="value").sort_index()
cats = ["Здоровье", "Маркетплейсы", "Общественное питание", "Продовольствие", "Транспорт"]
assert set(p.columns) == set(cats + ["Все категории"])
assert p.notna().all().all() and (p > 0).all().all()
assert p.groupby(level="territory_id").size().eq(24).all()
assert set(p.index.get_level_values("date")) == set(pd.date_range("2023-01-01", "2024-12-01", freq="MS"))
years = p.index.get_level_values("date").year
ratios = p[cats].div(p["Все категории"], axis=0) * 100
means = p.groupby([p.index.get_level_values("territory_id"), years]).mean()
annual_ratios = ratios.groupby([ratios.index.get_level_values("territory_id"), years]).mean()
a23, a24 = annual_ratios.xs(2023, level=1), annual_ratios.xs(2024, level=1)
change = a24 - a23
growth = (means.xs(2024, level=1) / means.xs(2023, level=1) - 1) * 100
assert np.isfinite(change.to_numpy()).all() and np.isfinite(growth.to_numpy()).all()

market_up = change["Маркетплейсы"] > 0
food_share_down = change["Продовольствие"] < 0
food_level_up = growth["Продовольствие"] > 0
all_up = growth["Все категории"] > 0
dictionary = pd.read_parquet(DICTIONARY).set_index("territory_id")
assert dictionary.index.is_unique
dictionary = dictionary.loc[ids]


def describe(index):
    c, g = change.loc[index], growth.loc[index]
    return {
        "n": int(len(index)),
        "median_ratio_change_percentage_points": c.median().to_dict(),
        "median_nominal_indicator_growth_pct": g.median().to_dict(),
        "count_market_ratio_up": int((c["Маркетплейсы"] > 0).sum()),
        "count_food_ratio_down": int((c["Продовольствие"] < 0).sum()),
        "count_food_nominal_level_up": int((g["Продовольствие"] > 0).sum()),
        "count_market_up_food_ratio_down_food_level_up": int(((c["Маркетплейсы"] > 0) & (c["Продовольствие"] < 0) & (g["Продовольствие"] > 0)).sum()),
    }


result = {
    "checked_at": "2026-10-05, isolated Mac local files",
    "status": "EXPLORATORY_DESCRIPTIVE_ONLY",
    "inputs_sha256": {"raw_consumption": sha(RAW), "frozen_features": sha(FEATURES), "dictionary": sha(DICTIONARY)},
    "method": {
        "panel": "Frozen Atlas mask, 1896 territories, 24 months, 6 indicators, no imputation",
        "category_ratio": "Monthly category value / All categories value; average of 12 monthly ratios per year, times 100",
        "change": "2024 annual mean ratio minus 2023 annual mean ratio, percentage points",
        "nominal_growth": "Ratio of annual means of the supplied value indicator, minus 1, times 100",
        "summary": "Unweighted municipality medians/counts; not a population-weighted national estimate",
    },
    "limits": [
        "Ratios inherit the provider's aggregation; household budget shares and per-person denominators are not verified.",
        "Five categories do not exhaust All categories; categories are not seller ownership or geographic money flows.",
        "Shared denominators can mechanically move ratios in opposite directions.",
        "Prices, quantities, coverage, household liquidity, debt and individual motives are not identified.",
        "2023/2024 are already inspected data; this probe is not an unseen forecast holdout.",
    ],
    "all": describe(change.index),
    "median_annual_ratio_pct": {"2023": a23.median().to_dict(), "2024": a24.median().to_dict()},
    "counts": {
        "market_up_food_ratio_down": int((market_up & food_share_down).sum()),
        "market_up_food_ratio_down_food_level_up_all_level_up": int((market_up & food_share_down & food_level_up & all_up).sum()),
        "market_up_food_nominal_level_down": int((market_up & ~food_level_up & (growth["Продовольствие"] < 0)).sum()),
    },
    "by_type": {str(t): describe(group.index) for t, group in dictionary.groupby("type")},
    "without_moscow": describe(dictionary[dictionary.region_code != 77].index),
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
print(json.dumps({k: result[k] for k in ["status", "all", "median_annual_ratio_pct", "counts", "without_moscow"]}, ensure_ascii=False, indent=2))
