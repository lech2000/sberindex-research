"""A7.S2 — проверка времени: начался ли рост расходов жителей после апреля 2024 или раньше (05.10.2026).

Если паводок апреля 2024 был причиной скачка уровня расходов в Орске/Кургане, относительный рост г/г должен быть около нуля в январе–марте и
вырасти с апреля. Если он высок уже в I квартале, паводок источником скачка быть не мог.

Статистика (заданная до расчёта): для МО i и месяца t 2024
    rel_i(t) = [ln x_i(t) − ln x_i(t−12)] − медиана по МО того же региона [ln x(t) − ln x(t−12)]
    pre_i = среднее rel за январь–март, post_i = среднее за апрель–декабрь, S_i = post_i − pre_i.
Положение S города среди МО региона (без самого города) и среди всех МО панели. Плацебо: тот же S при разрыве после месяца k = 2…10.

Дополнительно по пакету Data Sense (зарплаты, накопительные периоды январь–март/июнь/сентябрь/декабрь): рост г/г накопленной средней зарплаты на каждой
отсечке и приближённая зарплата отдельного квартала (6·W6 − 3·W3)/3 и т. д. — приближение, верное при постоянной занятости.
Занятость Tochno (накопительные периоды) — то же для числа работников организаций без малого бизнеса.

Не доказывает причину: сравнение с медианой региона не отделяет паводок от других региональных событий (трансферты, цены, структура клиентов банка).

Запуск: python timing_check.py [--employment ...] [--data-sense-dir ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ATLAS = HERE.parents[1]
sys.path.insert(0, str(ATLAS / "src"))
import a6_temporal as a6  # noqa: E402

CITIES = {1673: "Орск", 1668: "Бузулук", 1333: "Курган", 2192: "Ишим", 2190: "Тюмень", 1334: "Шадринск"}
CATS = ["Все категории", "Продовольствие", "Здоровье", "Общественное питание", "Маркетплейсы", "Транспорт"]
CUM = [("январь-март", 3), ("январь-июнь", 6), ("январь-сентябрь", 9), ("январь-декабрь", 12)]
CUM_EMP = [("Январь-март", 3), ("Январь-июнь", 6), ("Январь-сентябрь", 9), ("Январь-декабрь", 12)]


def pct(x: np.ndarray, v: float) -> float:
    x = x[np.isfinite(x)]
    return float(100.0 * (x < v).mean() + 50.0 * (x == v).mean())


def level_matrix(panel: pd.DataFrame, cat: str):
    p = panel[panel["category"] == cat].copy()
    p["tid"] = p["territory_id"].astype(int)
    p["month"] = pd.to_datetime(p["date"]).dt.strftime("%Y-%m")
    m = p.pivot_table(index="tid", columns="month", values="value", aggfunc="first")
    return m[sorted(m.columns)]


def event_study(panel: pd.DataFrame, region_of: pd.Series, cat: str):
    L = level_matrix(panel, cat)
    L = L[(L > 0).all(axis=1)]
    lg = np.log(L.to_numpy())
    yoy = lg[:, 12:] - lg[:, :12]  # (N, 12): январь…декабрь 2024
    tids = L.index.to_numpy()
    reg = region_of.reindex(tids).to_numpy()
    rel = np.empty_like(yoy)
    for r in np.unique(reg):
        sel = reg == r
        rel[sel] = yoy[sel] - np.median(yoy[sel], axis=0, keepdims=True)
    nat = yoy - np.median(yoy, axis=0, keepdims=True)
    return tids, reg, yoy, rel, nat


def stat(rel: np.ndarray, k: int):
    return rel[:, k:].mean(axis=1) - rel[:, :k].mean(axis=1)


def timing_block(panel, region_of):
    out = {}
    for cat in CATS:
        tids, reg, yoy, rel, nat = event_study(panel, region_of, cat)
        res = {}
        for t, name in CITIES.items():
            j = int(np.flatnonzero(tids == t)[0])
            peers = np.flatnonzero((reg == reg[j]) & (np.arange(len(tids)) != j))
            S3 = stat(rel, 3)
            placebo = {}
            for k in range(2, 11):
                Sk = stat(rel, k)
                placebo[str(k)] = {"S": round(float(Sk[j]), 4), "pct_region": round(pct(Sk[peers], Sk[j]), 1)}
            res[name] = {
                "pre_jan_mar_rel_yoy": round(float(rel[j, :3].mean()), 4), "post_apr_dec_rel_yoy": round(float(rel[j, 3:].mean()), 4),
                "S_post_minus_pre": round(float(S3[j]), 4), "S_pct_region": round(pct(S3[peers], S3[j]), 1), "S_pct_national": round(pct(S3, S3[j]), 1),
                "pre_pct_region": round(pct(rel[peers, :3].mean(axis=1), rel[j, :3].mean()), 1),
                "post_pct_region": round(pct(rel[peers, 3:].mean(axis=1), rel[j, 3:].mean()), 1),
                "monthly_rel_yoy_vs_region": [round(float(v), 3) for v in rel[j]],
                "monthly_yoy": [round(float(v), 3) for v in yoy[j]],
                "n_region_peers": int(len(peers)),
                "placebo_break_after_month_k": placebo,
            }
        out[cat] = res
    return out


def urban_peer_block(panel, dic):
    """Положение города среди ГОРОДСКИХ ОКРУГОВ страны (а не среди всех МО региона): рост уровня 2024/2023 и относительный рост г/г в I квартале 2024 и апр.–дек."""
    L = level_matrix(panel, "Все категории")
    L = L[(L > 0).all(axis=1)]
    lg = np.log(L.to_numpy())
    yoy = lg[:, 12:] - lg[:, :12]
    typ = dic["type"].reindex(L.index).to_numpy()
    urban = typ == "городской округ"
    lvl = L.iloc[:, 12:].mean(axis=1).to_numpy() / L.iloc[:, :12].mean(axis=1).to_numpy() - 1.0
    med_u = np.median(yoy[urban], axis=0, keepdims=True)  # медиана городских округов страны по месяцу
    rel = yoy - med_u
    pre, post = rel[:, :3].mean(axis=1), rel[:, 3:].mean(axis=1)
    out = {"n_urban_okrugs": int(urban.sum()), "median_level_yoy_urban": round(float(np.median(lvl[urban])), 4)}
    for t, name in CITIES.items():
        j = int(np.flatnonzero(L.index.to_numpy() == t)[0])
        peers = np.flatnonzero(urban & (np.arange(len(L)) != j))
        out[name] = {"level_yoy": round(float(lvl[j]), 4), "level_yoy_pct_urban": round(pct(lvl[peers], lvl[j]), 1),
                     "pre_rel_urban_median": round(float(pre[j]), 4), "pre_pct_urban": round(pct(pre[peers], pre[j]), 1),
                     "post_rel_urban_median": round(float(post[j]), 4), "post_pct_urban": round(pct(post[peers], post[j]), 1),
                     "S_post_minus_pre": round(float(post[j] - pre[j]), 4), "S_pct_urban": round(pct((post - pre)[peers], (post - pre)[j]), 1)}
    return out


def cumulative_timing(df: pd.DataFrame, key_col: str, periods, value_col: str, tids: dict):
    """df: строки с year/period/value по МО. Возвращает рост г/г накопленного показателя и приближённый квартальный рост."""
    out = {}
    for t, name in tids.items():
        row = {}
        for per, months in periods:
            a = df[(df[key_col] == t) & (df["period"] == per)].set_index("year")[value_col]
            if 2023 in a.index and 2024 in a.index and a[2023] > 0:
                row[months] = (float(a[2023]), float(a[2024]))
        res = {"cumulative_yoy": {str(m): round(v[1] / v[0] - 1, 4) for m, v in row.items()}}
        # квартальные значения как разность накоплений (среднее за первые m месяцев): Q_k = (m_k·W_k − m_{k−1}·W_{k−1}) / 3
        for yr_idx, yr in ((0, "2023"), (1, "2024")):
            q, prev_m, prev_w = {}, 0, 0.0
            for m in sorted(row):
                w = row[m][yr_idx]
                q[f"q{m // 3}"] = (m * w - prev_m * prev_w) / (m - prev_m)
                prev_m, prev_w = m, w
            res[f"quarter_value_{yr}"] = {k: round(v, 1) for k, v in q.items()}
        if all(f"q{i}" in res["quarter_value_2023"] and f"q{i}" in res["quarter_value_2024"] for i in (1, 2, 3, 4)):
            res["quarter_yoy_approx"] = {f"q{i}": round(res["quarter_value_2024"][f"q{i}"] / res["quarter_value_2023"][f"q{i}"] - 1, 4) for i in (1, 2, 3, 4)}
        out[name] = res
    return out


def annual_history(path: str, dic: pd.DataFrame, years=range(2019, 2026)):
    """Годовой рост показателя Tochno/БДМО (январь–декабрь, «Всего», МО верхнего уровня): медиана МО и шесть городов.
    Рост — явное отношение t/(t−1) там, где есть оба года (БЕЗ заполнения пропусков: pct_change по умолчанию заполняет вперёд и искажает перцентили)."""
    e = pd.read_parquet(path, columns=["okved2", "oktmo", "mun_level", "year", "indicator_value", "indicator_period"])
    d = e[e["okved2"].str.startswith("Всего", na=False) & (e["indicator_period"] == "Январь-декабрь") & e["mun_level"].str.contains("верхнего", na=False)]
    t = d.pivot_table(index="oktmo", columns="year", values="indicator_value", aggfunc="first")
    res = {"median_mo_growth": {}, "cities": {n: {} for n in CITIES.values()}, "pct_2024_among_mo": {}, "pct_2025_among_mo": {}}
    for y in years:
        if y not in t.columns or (y - 1) not in t.columns:
            continue
        a = t[[y - 1, y]].dropna()
        a = a[a[y - 1] > 0]
        g = a[y] / a[y - 1] - 1.0
        res["median_mo_growth"][str(y)] = round(float(g.median()), 4)
        for tid, name in CITIES.items():
            if tid not in dic.index:
                continue
            o8 = str(dic.loc[tid, "oktmo"]).replace("-", "")[:8]
            if o8 in g.index:
                res["cities"][name][str(y)] = round(float(g.loc[o8]), 4)
                if y in (2024, 2025):
                    res[f"pct_{y}_among_mo"][name] = round(pct(g.to_numpy(), float(g.loc[o8])), 1)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--panel", default=str(ATLAS / "data" / "panel_v1.parquet"))
    ap.add_argument("--data-sense-dir", default=os.environ.get("SBERINDEX_DATA_SENSE_DIR"))
    ap.add_argument("--employment", default=os.environ.get("SBERINDEX_TOCHNO_Y48423005"))
    ap.add_argument("--wages", default=os.environ.get("SBERINDEX_TOCHNO_Y48423007"), help="data_Y48423007_112_v20250918.parquet (зарплата организаций без малого бизнеса)")
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args(argv)
    if not a.data_sense_dir:
        raise SystemExit("нужна --data-sense-dir (справочник МО и зарплаты)")
    ds = Path(a.data_sense_dir)
    dic = pd.read_parquet(ds / "municipal_dictionary.parquet").drop_duplicates("territory_id").set_index("territory_id")
    panel = pd.read_parquet(a.panel)
    res = {"consumption_event_study": timing_block(panel, dic["region_code"])}

    res["urban_okrugs_peer_set"] = urban_peer_block(panel, dic)
    sal = pd.read_parquet(ds / "4_bdmo_salary.parquet")
    sal = sal[sal["okved_letter"] == "0"].rename(columns={"territory_id": "tid"})
    res["wages_cumulative_all_industries"] = cumulative_timing(sal, "tid", CUM, "value", CITIES)

    if a.employment and Path(a.employment).exists():
        e = pd.read_parquet(a.employment, columns=["okved2", "oktmo", "mun_level", "year", "indicator_value", "indicator_period"])
        e = e[e["okved2"].str.startswith("Всего", na=False) & e["mun_level"].str.contains("верхнего", na=False) & e["year"].isin([2023, 2024])]
        o8 = {t: str(dic.loc[t, "oktmo"]).replace("-", "")[:8] for t in CITIES}
        e = e.rename(columns={"indicator_period": "period", "indicator_value": "v"})
        rows = []
        for t, o in o8.items():
            x = e[e["oktmo"] == o].copy()
            x["tid"] = t
            rows.append(x)
        ee = pd.concat(rows)
        res["employment_cumulative_organisations_excl_small_business"] = cumulative_timing(ee, "tid", CUM_EMP, "v", CITIES)
    if a.wages and Path(a.wages).exists():
        res["annual_history_wages_Y48423007"] = annual_history(a.wages, dic)
    if a.employment and Path(a.employment).exists():
        res["annual_history_employment_Y48423005"] = annual_history(a.employment, dic)
    (Path(a.outdir) / "timing_check.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("городские округа страны (n=%d), медиана роста уровня %.3f:" % (res["urban_okrugs_peer_set"]["n_urban_okrugs"], res["urban_okrugs_peer_set"]["median_level_yoy_urban"]))
    for name in CITIES.values():
        u = res["urban_okrugs_peer_set"][name]
        print(f"  {name:<9} рост уровня {u['level_yoy']:+.3f} (перц. среди гор. округов {u['level_yoy_pct_urban']:.0f}) | до апр. {u['pre_rel_urban_median']:+.3f} (перц. {u['pre_pct_urban']:.0f}) | апр.–дек. {u['post_rel_urban_median']:+.3f} (перц. {u['post_pct_urban']:.0f}) | S {u['S_post_minus_pre']:+.3f} (перц. {u['S_pct_urban']:.0f})")
    # краткая печать для «Все категории»
    for name, r in res["consumption_event_study"]["Все категории"].items():
        print(f"{name:<9} до апр.: {r['pre_jan_mar_rel_yoy']:+.3f} (перц. региона {r['pre_pct_region']:.0f}) | апр.–дек.: {r['post_apr_dec_rel_yoy']:+.3f} (перц. {r['post_pct_region']:.0f}) | "
              f"S={r['S_post_minus_pre']:+.3f} (регион {r['S_pct_region']:.0f}, страна {r['S_pct_national']:.0f})")


if __name__ == "__main__":
    main()
