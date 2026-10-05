"""Release checks protect measured data, candidate restrictions and negative results."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ATLAS=Path(__file__).resolve().parents[1]/"economic-atlas"
OUT=ATLAS/"runs/A14_release_20261005"
DATA=json.loads((ATLAS/"site/atlas-20261005/data.json").read_text())
ROWS={r["id"]:r for r in DATA["territories"]}


def test_payload_keys_and_monthly_values_match_frozen_input():
    panel=pd.read_parquet(ATLAS/"data/panel_v1.parquet")
    totals=panel[panel.category.eq("Все категории")].copy()
    totals["m"]=pd.to_datetime(totals.date).dt.strftime("%Y-%m")
    wide=totals.pivot(index="territory_id",columns="m",values="value")
    assert len(ROWS)==1896 and set(ROWS)==set(wide.index)
    assert len(DATA["months"])==24
    for tid,r in ROWS.items():
        np.testing.assert_allclose(r["total"],wide.loc[tid,DATA["months"]],atol=.005)
        assert np.asarray(r["shares"]).shape==(24,5)


@pytest.mark.parametrize("year",["2023","2024"])
def test_category_percentages_use_total_not_sum_of_five(year):
    panel=pd.read_parquet(ATLAS/"data/panel_v1.parquet")
    panel["m"]=pd.to_datetime(panel.date).dt.strftime("%Y-%m")
    for tid in [1673,1333,2192,1668,2190,1334]:
        wide=panel[panel.territory_id.eq(tid)].pivot(index="m",columns="category",values="value")
        for month in [year+"-01",year+"-12"]:
            i=DATA["months"].index(month)
            for c,cat in enumerate(DATA["categories"]):
                assert ROWS[tid]["shares"][i][c]==pytest.approx(wide.loc[month,cat]/wide.loc[month,"Все категории"]*100,abs=.00005)


def test_primary_cores_are_unchanged_for_both_years():
    for year,counts in [("2023",{.8:789,.9:0,.95:0}),("2024",{.8:318,.9:258,.95:0})]:
        for threshold,n in counts.items():
            assert sum(r["core"][year]["score"]>=threshold for r in ROWS.values())==n


def test_neighbor_filters_and_identity_are_applied_to_all_candidates():
    for tid,r in ROWS.items():
        for mode in ["all","matched"]:
            for year in ["2023","2024"]:
                ids=[v["id"] for v in r["neighbors"][mode][year]]
                assert len(ids)==len(set(ids))<=5 and tid not in ids
                assert all(i in ROWS for i in ids)
                if mode=="matched":
                    assert all(ROWS[i]["type"]==r["type"] for i in ids)
                    assert all(.5*r["population"]["2024"]<=ROWS[i]["population"]["2024"]<=2*r["population"]["2024"] for i in ids)
            a={v["id"] for v in r["neighbors"][mode]["2023"]}
            b={v["id"] for v in r["neighbors"][mode]["2024"]}
            assert r["neighborJaccard"][mode]==(len(a&b)/len(a|b) if a|b else None)


def test_neighbor_distances_match_independently_standardized_raw_shares():
    panel=pd.read_parquet(ATLAS/"data/panel_v1.parquet")
    panel["m"]=pd.to_datetime(panel.date).dt.strftime("%Y-%m")
    wide=panel.pivot(index=["territory_id","m"],columns="category",values="value")
    s=wide[DATA["categories"]].div(wide["Все категории"],axis=0)
    fit=s[s.index.get_level_values("m").str.startswith("2023")]
    z=(s-fit.mean())/fit.std(ddof=0)
    for year in ["2023","2024"]:
        annual=z[z.index.get_level_values("m").str.startswith(year)].groupby(level=0).mean()
        for tid in [1673,1333,2192,1668,2190]:
            for neighbor in ROWS[tid]["neighbors"]["matched"][year]:
                distance=np.linalg.norm(annual.loc[tid].to_numpy()-annual.loc[neighbor["id"]].to_numpy())
                assert neighbor["distance"]==pytest.approx(distance,abs=1e-9)


def test_duplicate_audit_proves_input_invariance_and_preserves_negative_a8():
    r=DATA["populationAudit"]
    assert r["n_population_changed"]==2
    assert all(v["year_to"]!=9999 for v in r["changed_ids"])
    assert r["secondary_label_orientation_old"]==r["secondary_label_orientation_corrected"]
    assert r["full_statistical_rerun"] is False
    assert not any(v["positive_result"] for group in DATA["a8Primary"].values() for v in group.values())


def test_reconstructed_coverage_explains_all_exclusions():
    c=DATA["coverage"]
    assert c["full_spending_territories"]==2016
    assert c["intersection_exactly_equals_panel"]
    ex=pd.read_csv(OUT/"coverage_exclusions.csv")
    assert len(ex)==294 and ex.full_spending.sum()==120
    assert not ex.reasons.str.contains("unresolved").any()


def test_without_moscow_refit_is_not_confused_with_restricted_primary():
    r=next(r for r in DATA["sensitivity"] if r["subset"]=="without_moscow" and r["month"]=="2024-12" and r["threshold"]==.9)
    assert r["n_core_refit"]==0
    assert r["n_core_primary_restricted"]==121
    assert r["n"]==1752


def test_corrected_runner_deduplicates_and_rejects_conflicting_population():
    import sys
    sys.path.insert(0,str(ATLAS/"src"))
    from atlas_a12 import population_by_year
    base=pd.DataFrame([{"territory_id":1,"year":2024,"age":"Всего","gender":g,"period":"год","value":100} for g in ["Мужчины","Женщины"]])
    repeated=pd.concat([base,base],ignore_index=True)
    assert population_by_year(repeated).loc[1,2024]==200
    bad=pd.concat([base,base.iloc[:1].assign(value=101)],ignore_index=True)
    with pytest.raises(ValueError,match="Duplicate population key"): population_by_year(bad)


def test_rendered_page_is_offline_and_contains_no_placeholder():
    html=(ATLAS/"site/atlas-20261005/index.html").read_text()
    assert "/*__ATLAS_DATA__*/" not in html
    assert "fetch(" not in html and "XMLHttpRequest" not in html
    assert '<script src=' not in html and '<link rel="stylesheet" href="http' not in html
    assert "MQ: точная спецификация не разрешена" in html
