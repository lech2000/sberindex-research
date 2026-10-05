"""A7.S2: истории МО — помощники расчёта и правило отбора (economic-atlas/runs/A7_stories_20261004/build_stories.py)."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

RUN = Path(__file__).resolve().parents[1] / "economic-atlas" / "runs" / "A7_stories_20261004"
sys.path.insert(0, str(RUN.parents[1] / "src"))
_spec = importlib.util.spec_from_file_location("a7_build_stories", RUN / "build_stories.py")
bs = importlib.util.module_from_spec(_spec)
sys.modules["a7_build_stories"] = bs
_spec.loader.exec_module(bs)


def test_selection_rule_is_declared_and_excludes_the_control():
    """Истории — города с ≥ 1 парой бюджетных наблюдений; Шадринск без бюджетов остаётся контрольным."""
    names = {bs.CITIES[t] for t in bs.STORY_IDS}
    assert names == {"Орск", "Курган", "Ишим", "Бузулук", "Тюмень"}
    assert 1334 in bs.CITIES and 1334 not in bs.STORY_IDS


def test_margin_is_zero_on_the_boundary_and_grows_away_from_it():
    c = np.array([[0.0, 0.0], [10.0, 0.0]])
    X = np.array([[5.0, 0.0], [1.0, 0.0], [0.0, 0.0]])
    m = bs.margins(X, c)
    assert m[0] == pytest.approx(0.0, abs=1e-9) and 0 < m[1] < m[2] <= 1.0


def test_alignment_undoes_a_permutation_of_raw_ids():
    rng = np.random.default_rng(0)
    centres = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0]])
    truth = rng.integers(0, 3, 90)
    raw_l, raw_c = [], []
    for m in range(4):
        perm = rng.permutation(3)  # «сырые» id каждый месяц перепутаны
        inv = np.argsort(perm)
        raw_l.append(inv[truth])
        raw_c.append(centres[perm] + 0.01 * m)
    aligned, _ = bs.align_sequence(raw_l, raw_c)
    for m in range(1, 4):
        assert (aligned[m] == aligned[0]).all()


def test_modal_group_and_tie_flag():
    lab = np.array([[0, 0, 1], [0, 1, 1], [1, 1, 0], [1, 0, 0]])  # 4 «месяца», 3 МО
    mode, tie = bs.modal(lab, 2)
    assert tie.tolist() == [True, True, True]  # у каждого МО 2 против 2
    lab2 = np.array([[0, 1], [0, 1], [0, 1], [1, 0]])
    mode2, tie2 = bs.modal(lab2, 2)
    assert mode2.tolist() == [0, 1] and not tie2.any()


def test_changed_flag_requires_a_clear_mode_in_both_years():
    months = [f"2023-{m:02d}" for m in range(1, 13)] + [f"2024-{m:02d}" for m in range(1, 13)]
    stay = np.zeros((24, 1), int)
    flip = np.vstack([np.zeros((12, 1), int), np.ones((12, 1), int)])
    tied = np.vstack([np.zeros((12, 1), int), np.array([[0]] * 6 + [[1]] * 6)])
    mar = np.full((24, 1), 0.5)
    assert bs.summarise_config(stay, mar, 2, months, 0.1)["changed"].tolist() == [False]
    assert bs.summarise_config(flip, mar, 2, months, 0.1)["changed"].tolist() == [True]
    assert bs.summarise_config(tied, mar, 2, months, 0.1)["changed"].tolist() == [False]  # ничья — не смена


def test_population_total_uses_the_total_row_not_the_sum_of_all_age_rows(tmp_path):
    """В таблице населения рядом лежат одиночные возрасты, агрегаты 65+/70+/80+ и «Всего»: сумма всех строк даёт двойной счёт
    (Орск вышел 410 тыс. вместо ~191 тыс.). Берётся только age = «Всего»."""
    import pandas as pd

    rows = []
    for year, scale in ((2023, 1.0), (2024, 1.1)):
        for g in ("Мужчины", "Женщины"):
            rows += [(1, year, "год", "20", g, 100.0 * scale), (1, year, "год", "21", g, 100.0 * scale),
                     (1, year, "год", "65+", g, 50.0 * scale), (1, year, "год", "Всего", g, 250.0 * scale)]
    pd.DataFrame(rows, columns=["territory_id", "year", "period", "age", "gender", "value"]).to_parquet(tmp_path / "2_bdmo_population.parquet")
    pd.DataFrame({"territory_id": [1], "year": [2023], "period": ["год"], "age": ["Всего"], "gender": ["Мужчины"], "value": [5.0]}).to_parquet(tmp_path / "3_bdmo_migration.parquet")
    pd.DataFrame({"territory_id": [1], "year": [2023], "period": ["январь-декабрь"], "okved_name": ["Все отрасли"], "okved_letter": ["0"], "value": [1.0]}).to_parquet(tmp_path / "4_bdmo_salary.parquet")
    pop, _, _ = bs.context(tmp_path, np.array([1]))
    assert pop.loc[1, 2023] == pytest.approx(500.0) and pop.loc[1, 2024] == pytest.approx(550.0)


def test_archive_identity_stats_counts_switches_and_ignores_ambiguous_gaps():
    """Смена считается между соседними НЕПУСТЫМИ сквозными id; пустой id (неоднозначный месяц) не разрывает и не создаёт смену."""
    import pandas as pd

    months = [f"2023-{m:02d}" for m in range(1, 13)] + [f"2024-{m:02d}" for m in range(1, 13)]
    seq_a = ["ID0001"] * 8 + ["", ""] + ["ID0001"] * 14          # без смен, два неоднозначных месяца
    seq_b = ["ID0002"] * 10 + ["ID0001"] * 13 + [""]              # одна устойчивая смена в 2023-11, декабрь 2024 неоднозначен
    seq_c = ["ID0001", "ID0002"] * 12                             # граничный: смена каждый месяц
    rows = []
    for tid, seq in ((1, seq_a), (2, seq_b), (3, seq_c)):
        for m, i in zip(months, seq):
            rows.append((tid, m, 2, 0, i, "continuing"))
    a = pd.DataFrame(rows, columns=["territory_id", "month", "k", "label", "identity_id", "status"])
    st = bs._identity_stats(a)
    assert st[1]["switches"] == 0 and st[1]["ambiguous_months"] == 2 and not st[1]["changed"]
    assert st[2]["switches"] == 1 and st[2]["changed"] and st[2]["dec_2024_ambiguous"]
    assert st[3]["switches"] == 23 and st[2]["sequence"].endswith("-")


def test_employment_block_uses_annual_total_and_8_digit_oktmo(tmp_path):
    import pandas as pd

    def row(oktmo, okved, year, v, period="Январь-декабрь", lvl="Муниципальное образование верхнего уровня"):
        return {"okved2": okved, "oktmo": oktmo, "mun_level": lvl, "year": year, "indicator_value": v, "indicator_period": period}

    rows = []
    for o, a, b in (("11111111", 1000.0, 1100.0), ("22222222", 1000.0, 900.0), ("33333333", 1000.0, 1000.0)):
        rows += [row(o, "Всего по обследуемым видам экономической деятельности", 2023, a), row(o, "Всего по обследуемым видам экономической деятельности", 2024, b),
                 row(o, "Раздел C Обрабатывающие производства", 2023, a), row(o, "Раздел C Обрабатывающие производства", 2024, b)]
    rows.append(row("11111111", "Всего по обследуемым видам экономической деятельности", 2024, 5.0, period="Январь-март"))  # квартальную строку не брать
    p = tmp_path / "emp.parquet"
    pd.DataFrame(rows).to_parquet(p)
    dic = pd.DataFrame({"oktmo": ["11-111-111-000"]}, index=pd.Index([7], name="territory_id"))  # 11-111-111-000 → «11111111», как 53-723-000-000 → «53723000»
    out = bs.employment_block(str(p), dic, [7])[7]
    assert out["oktmo8"] == "11111111" and out["growth"] == pytest.approx(0.10)
    assert out["growth_pct_national"] > 60 and out["n_national"] == 3
    assert out["largest_section_changes"][0]["d_workers"] == pytest.approx(100.0)


def test_budget_block_recomputes_shares_and_changes(tmp_path):
    import pandas as pd

    def r(tid, y, m, v):
        return {"territory_id": tid, "year": y, "metric": m, "executed_kopecks": v}

    rows = []
    for y, tot, ж in ((2023, 10000000, 1000000), (2024, 15000000, 3000000)):
        rows += [r(1, y, "expense", tot), r(1, y, "function_05", ж), r(1, y, "grants", tot // 2)]
    rows += [r(2, 2023, "expense", 500), r(2, 2024, "expense", None)]
    pilot = tmp_path / "p.parquet"
    pd.DataFrame(rows).to_parquet(pilot)
    sup = []
    for y, tot in ((2023, 1000000), (2024, 1300000)):
        for m, v in (("expense", tot), ("function_07", tot // 2)):
            sup.append({"territory_id": 1668, "year": y, "metric": m, "measure": "executed", "value_kopecks": v})
    supp = tmp_path / "s.parquet"
    pd.DataFrame(sup).to_parquet(supp)
    out = bs.budget_block(str(pilot), str(supp))
    assert out[1]["expense_change"] == pytest.approx(0.5) and out[1]["function_share"]["function_05"]["2023"] == pytest.approx(0.1)
    assert out[1]["function_share"]["function_05"]["2024"] == pytest.approx(0.2) and out[1]["grants_change"] == pytest.approx(0.5)
    assert out[2]["note"] == "2024 отсутствует"
    assert out[1668]["expense_change"] == pytest.approx(0.3) and "H1" in out[1668]["period"]


def test_percentile_rank_conventions():
    x = np.arange(100.0)
    assert bs.pct_rank(x, 99.0) == pytest.approx(99.5, abs=0.6) and bs.pct_rank(x, 0.0) < 1.0
    assert bs.pct_rank(np.array([1.0, 1.0, 1.0, np.nan]), 1.0) == pytest.approx(50.0)


@pytest.mark.skipif(not os.environ.get("SBERINDEX_DATA_SENSE_DIR"), reason="нет SBERINDEX_DATA_SENSE_DIR")
def test_real_panel_contains_all_six_cities_and_grid_is_complete():
    import pandas as pd
    import a6_temporal as a6

    panel = pd.read_parquet(RUN.parents[1] / "data" / "panel_v1.parquet")
    tids, months, S, _ = a6.build_monthly_shares(panel)
    assert set(bs.CITIES) <= set(int(t) for t in tids)
    assert len(bs.NORMS) * len(bs.KS) * (len(bs.SEEDS) + 1) == 36


# ───────────── проверка времени (timing_check.py) ─────────────
_tspec = importlib.util.spec_from_file_location("a7_timing_check", RUN / "timing_check.py")
tc = importlib.util.module_from_spec(_tspec)
sys.modules["a7_timing_check"] = tc
_tspec.loader.exec_module(tc)


def _toy_panel(jump_from=None, early_advantage=False, n=12):
    """24 месяца, регион из n МО; МО 0 — «город»: либо скачок роста после месяца jump_from (индекс 0…23), либо преимущество с января 2024."""
    import pandas as pd

    rng = np.random.default_rng(3)
    months = [f"{2023 + t // 12}-{t % 12 + 1:02d}-01" for t in range(24)]
    rows = []
    for i in range(n):
        base = 1000.0 * (1 + 0.02 * i)
        for t, m in enumerate(months):
            v = base * (1.0 + 0.002 * t) * np.exp(rng.normal(0, 0.003))
            if i == 0 and early_advantage and t >= 12:
                v *= 1.15
            if i == 0 and jump_from is not None and t >= jump_from:
                v *= 1.15
            rows.append((m, 100 + i, "Все категории", v))
    return pd.DataFrame(rows, columns=["date", "territory_id", "category", "value"])


def test_event_study_detects_a_jump_after_april_and_not_an_early_advantage():
    import pandas as pd

    region = pd.Series(1, index=[100 + i for i in range(12)])
    jump = _toy_panel(jump_from=15)  # скачок с апреля 2024 (индекс 15)
    tids, reg, yoy, rel, nat = tc.event_study(jump, region, "Все категории")
    j = int(np.flatnonzero(tids == 100)[0])
    S = tc.stat(rel, 3)
    assert S[j] > 0.10 and tc.pct(np.delete(S, j), S[j]) > 90
    early = _toy_panel(early_advantage=True)  # преимущество с января 2024: до апреля уже высоко, излома нет
    tids, reg, yoy, rel, nat = tc.event_study(early, region, "Все категории")
    j = int(np.flatnonzero(tids == 100)[0])
    S = tc.stat(rel, 3)
    assert abs(S[j]) < 0.03 and rel[j, :3].mean() > 0.10


def test_quarter_values_from_cumulative_periods_recover_constant_quarters():
    import pandas as pd

    rows = []
    for yr, w in ((2023, 100.0), (2024, 130.0)):  # зарплата постоянна внутри года → накопленные средние равны
        for per in ("январь-март", "январь-июнь", "январь-сентябрь", "январь-декабрь"):
            rows.append({"tid": 1, "year": yr, "period": per, "value": w})
    out = tc.cumulative_timing(pd.DataFrame(rows), "tid", tc.CUM, "value", {1: "город"})["город"]
    assert out["cumulative_yoy"]["12"] == pytest.approx(0.30)
    assert all(v == pytest.approx(0.30) for v in out["quarter_yoy_approx"].values())


def test_quarter_values_expose_a_second_half_acceleration():
    import pandas as pd

    # 2024: квартальные зарплаты 100, 100, 200, 200 → накопленные средние 100, 100, 133,33, 150
    cum24 = {"январь-март": 100.0, "январь-июнь": 100.0, "январь-сентябрь": 400 / 3, "январь-декабрь": 150.0}
    rows = [{"tid": 1, "year": 2023, "period": p, "value": 100.0} for p in cum24]
    rows += [{"tid": 1, "year": 2024, "period": p, "value": v} for p, v in cum24.items()]
    q = tc.cumulative_timing(pd.DataFrame(rows), "tid", tc.CUM, "value", {1: "город"})["город"]["quarter_yoy_approx"]
    assert q["q1"] == pytest.approx(0.0) and q["q2"] == pytest.approx(0.0) and q["q3"] == pytest.approx(1.0) and q["q4"] == pytest.approx(1.0)


def test_annual_history_uses_explicit_ratios_not_forward_filled_growth(tmp_path):
    """pct_change по умолчанию заполняет пропуски вперёд: рост 2024 к 2022 при отсутствии 2023 попадает в 2024 и сдвигает перцентили.
    Здесь у МО B нет значения за 2023 — в 2024 оно не должно получить рост."""
    import pandas as pd

    def row(o, y, v):
        return {"okved2": "Всего по обследуемым видам экономической деятельности", "oktmo": o, "mun_level": "Муниципальное образование верхнего уровня",
                "year": y, "indicator_value": v, "indicator_period": "Январь-декабрь"}

    rows = [row("11111111", 2023, 100.0), row("11111111", 2024, 120.0), row("22222222", 2022, 100.0), row("22222222", 2024, 500.0),
            row("33333333", 2023, 100.0), row("33333333", 2024, 110.0), row("44444444", 2023, 100.0), row("44444444", 2024, 130.0)]
    p = tmp_path / "h.parquet"
    pd.DataFrame(rows).to_parquet(p)
    dic = pd.DataFrame({"oktmo": ["11-111-111-000"]}, index=pd.Index([1673], name="territory_id"))
    out = tc.annual_history(str(p), dic, years=range(2023, 2026))
    assert out["median_mo_growth"]["2024"] == pytest.approx(0.20)  # МО 22222222 в 2024 не участвует: нет 2023
    assert out["cities"]["Орск"]["2024"] == pytest.approx(0.20) and 0 < out["pct_2024_among_mo"]["Орск"] < 100
