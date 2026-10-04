"""Сезонный прогноз по общему профилю категории (04.10.2026).

Идея. Месячное движение расходов во многом общее для всех МО категории и повторяется из года в год. Прогноз
ряда i категории c на месяц t с начала O (origin = t - h):

    x_hat[i, t] = x[i, O] * M_c[t - 12] / M_c[O - 12],     M_c[m] = медиана x[., m] по всем рядам категории c.

Используются только месяцы <= O (t - 12 <= O при h <= 12), параметров нет, обучения нет. Для h = 12 прошлогодней
базы нет (O - 12 < 0 на панели из 24 месяцев), поэтому горизонт 12 не поддерживается и в отчёте помечен.

Что считается. Маска как в R9: цель июль-декабрь 2024, origin = цель - h, должны существовать факт, значение в origin
и значение в цель - 12, в истории до origin не меньше двух наблюдений; заполнения и сжатия месяцев нет. Базовые
методы на той же маске: последнее значение, сезонный наив x[t - 12], среднее истории до origin. Они же служат контролем:
на сырой панели (SHA 9833ddaa...) числа должны совпасть с опубликованными в R9 (`R9_REFERENCE`).
Второе окно проверки: цели февраль-июнь 2024 (прошлогодняя база только 2023), не входит в окно R9.
Выигрыш считается и с интервалом (бутстрэп по целевым месяцам, как в R9) и «без последнего месяца».
Предсказания выгружаются в parquet, чтобы ансамбль с Prophet считать на одинаковых строках.

Запуск: python3 seasonal_common_forecast.py --panel <8_consumption.parquet> --outdir OUT [--self-check]
"""
import argparse
import hashlib
import json
import os

import numpy as np
import pandas as pd

R9_WINDOW = ("2024-07", "2024-12")
PRE_WINDOW = ("2024-02", "2024-06")
HORIZONS = (1, 3, 6)
SUPPORTED_MAX_HORIZON = 11  # для h = 12 нужна база O - 12 >= 0
MIN_HISTORY = 2
# опубликованные в R9 (audit KB76/15785, 03.10.2026) числа маски и MAE базовых методов
R9_REFERENCE = {
    1: {"n": 73728, "last_value": 625.672, "seasonal_naive": 1287.502, "train_mean": 1306.692},
    3: {"n": 73662, "last_value": 865.218, "seasonal_naive": 1287.915, "train_mean": 1408.742},
    6: {"n": 73578, "last_value": 1125.278},
}
REFERENCE_TOLERANCE = {1: 0.01, 3: 1.0, 6: 0.01}  # h = 3 в R9 считается на общей маске с Prophet (на 6 строк меньше)


def load_panel(path):
    """Длинная таблица (date, territory_id, category, value) -> X[n_series, T], ключи и месяцы."""
    d = pd.read_parquet(path, columns=["date", "territory_id", "category", "value"])
    if d.duplicated(["date", "territory_id", "category"]).any():
        raise ValueError("дубли ключа (date, territory_id, category)")
    months = sorted(d["date"].unique())
    keys = d[["territory_id", "category"]].drop_duplicates().sort_values(["territory_id", "category"]).reset_index(drop=True)
    sid = {(int(t), c): i for i, (t, c) in enumerate(zip(keys["territory_id"], keys["category"]))}
    mi = {m: j for j, m in enumerate(months)}
    X = np.full((len(keys), len(months)), np.nan)
    rows = np.fromiter((sid[(int(t), c)] for t, c in zip(d["territory_id"], d["category"])), dtype=np.int64, count=len(d))
    cols = d["date"].map(mi).to_numpy()
    X[rows, cols] = d["value"].to_numpy(dtype=float)
    return X, keys, months


def category_medians(X, cats):
    """M[c] = вектор медиан по рядам категории c в каждом месяце."""
    out = {}
    for c in np.unique(cats):
        with np.errstate(all="ignore"):
            out[c] = np.nanmedian(X[cats == c], axis=0)
    return out


def baseline_mask(X, o, t):
    """Маска R9: факт, значение в origin, значение в цель-12 и не меньше двух наблюдений до origin включительно."""
    if t - 12 < 0:
        raise ValueError("цель %d: нет значения за 12 месяцев до цели" % t)
    ok = np.isfinite(X[:, t]) & np.isfinite(X[:, o]) & np.isfinite(X[:, t - 12])
    return ok & (np.isfinite(X[:, : o + 1]).sum(axis=1) >= MIN_HISTORY)


def seasonal_common_forecast(X, cats, M, o, t):
    """Прогноз для всех рядов (NaN, если нет значения в origin или медианы). Использует месяцы не позже o."""
    if o - 12 < 0:
        raise ValueError("origin %d: нет прошлогодней базы (O - 12 < 0), горизонт не поддерживается" % o)
    if t - 12 > o:
        raise ValueError("t - 12 = %d позже origin %d: месяц ещё неизвестен" % (t - 12, o))
    g = np.full(len(X), np.nan)
    for c, m in M.items():
        sel = cats == c
        if np.isfinite(m[t - 12]) and np.isfinite(m[o - 12]) and m[o - 12] > 0:
            g[sel] = m[t - 12] / m[o - 12]
    return X[:, o] * g


def month_range(months, window):
    return [j for j, m in enumerate(months) if window[0] <= m <= window[1]]


def evaluate_window(X, cats, months, window, horizons, with_predictions=False):
    """Помесячные суммы абсолютных ошибок по методам для каждого горизонта; (результат, список предсказаний)."""
    M = category_medians(X, cats)
    out, preds, skipped = {}, [], {}
    methods = ("last_value", "seasonal_common", "seasonal_naive", "train_mean")
    for h in horizons:
        per_month, per_cat = {}, {}
        for t in month_range(months, window):
            o = t - h
            if o < 0 or o - 12 < 0 or t - 12 < 0:
                skipped.setdefault(str(h), []).append(months[t])
                continue
            ok = baseline_mask(X, o, t)
            idx = np.flatnonzero(ok)
            act = X[idx, t]
            with np.errstate(all="ignore"):
                hist_mean = np.nanmean(X[idx, : o + 1], axis=1)
            p = {"last_value": X[idx, o], "seasonal_common": seasonal_common_forecast(X, cats, M, o, t)[idx],
                 "seasonal_naive": X[idx, t - 12], "train_mean": hist_mean}
            good = np.isfinite(p["seasonal_common"])
            idx, act = idx[good], act[good]
            p = {k: v[good] for k, v in p.items()}
            per_month[months[t]] = {"n": int(len(idx)), **{m: float(np.abs(act - p[m]).sum()) for m in methods}}
            for c in np.unique(cats[idx]):
                s = cats[idx] == c
                d = per_cat.setdefault(c, {"n": 0, **{m: 0.0 for m in methods}})
                d["n"] += int(s.sum())
                for m in methods:
                    d[m] += float(np.abs(act[s] - p[m][s]).sum())
            if with_predictions:
                preds.append(pd.DataFrame({"row": idx, "horizon": h, "origin": months[o], "target": months[t], "actual": act,
                                           "last_value": p["last_value"], "seasonal_common": p["seasonal_common"]}))
        out[str(h)] = {"per_month": per_month, "per_category": per_cat}
    out["skipped_months_no_prior_year_base"] = skipped
    return out, (pd.concat(preds, ignore_index=True) if preds else None)


def summarize(window_result, bootstrap=10000, seed=20261004):
    """MAE по методам, выигрыш сезонной модели над последним значением с интервалом по месяцам и без последнего месяца."""
    res = {}
    rng = np.random.default_rng(seed)
    methods = ("last_value", "seasonal_common", "seasonal_naive", "train_mean")
    for h, body in window_result.items():
        if h.startswith("skipped"):
            continue
        pm = body["per_month"]
        if not pm:
            res[h] = None
            continue
        months = list(pm)
        n = np.array([pm[m]["n"] for m in months], float)
        err = {m_: np.array([pm[mm][m_] for mm in months]) for m_ in methods}
        mae = {m_: float(err[m_].sum() / n.sum()) for m_ in methods}
        gain_months = {mm: pm[mm]["last_value"] / pm[mm]["n"] - pm[mm]["seasonal_common"] / pm[mm]["n"] for mm in months}
        boots = []
        for _ in range(bootstrap):
            k = rng.integers(0, len(months), len(months))
            boots.append((err["last_value"][k].sum() - err["seasonal_common"][k].sum()) / n[k].sum())
        ci = [float(np.quantile(boots, 0.025)), float(np.quantile(boots, 0.975))]
        wo_last = None
        if len(months) > 1:
            wo_last = float((err["last_value"][:-1].sum() - err["seasonal_common"][:-1].sum()) / n[:-1].sum())
        res[h] = {"n": int(n.sum()), "months": months, "mae": {k: round(v, 3) for k, v in mae.items()},
                  "gain_vs_last_value": round(mae["last_value"] - mae["seasonal_common"], 3),
                  "gain_vs_last_value_ci95_months": [round(ci[0], 3), round(ci[1], 3)],
                  "gain_vs_last_value_without_last_month": None if wo_last is None else round(wo_last, 3),
                  "months_where_seasonal_worse": [mm for mm, g in gain_months.items() if g < 0],
                  "gain_by_month": {mm: round(float(g), 2) for mm, g in gain_months.items()},
                  "mae_by_category": {c: {k: round(d[k] / d["n"], 2) for k in methods} for c, d in body["per_category"].items()}}
    return res


def blend_mae(actual, pred_a, pred_b, w=0.5):
    """MAE смеси w * pred_a + (1 - w) * pred_b (например, сезонная модель и Prophet на одинаковых строках)."""
    actual, pred_a, pred_b = map(np.asarray, (actual, pred_a, pred_b))
    return float(np.mean(np.abs(actual - (w * pred_a + (1.0 - w) * pred_b))))


def reference_control(r9_summary):
    """Сверка базовых методов с числами R9: разность и признак совпадения в пределах допуска."""
    out = {}
    for h, ref in R9_REFERENCE.items():
        s = r9_summary.get(str(h))
        if not s:
            continue
        rec = {"n_mine": s["n"], "n_r9": ref["n"], "n_equal": s["n"] == ref["n"]}
        for k in ("last_value", "seasonal_naive", "train_mean"):
            if k in ref:
                rec[k] = {"mine": s["mae"][k], "r9": ref[k], "diff": round(s["mae"][k] - ref[k], 3),
                          "within_tolerance": abs(s["mae"][k] - ref[k]) <= REFERENCE_TOLERANCE[h]}
        out[str(h)] = rec
    return out


def self_check():
    """Формула, причинность маски и положительный/отрицательный контроль на синтетике."""
    rng = np.random.default_rng(5)
    T = 24
    months = ["%04d-%02d" % (2023 + k // 12, k % 12 + 1) for k in range(T)]
    season = rng.normal(0.0, 0.15, 12)

    def make(seasonal):
        rows = []
        for i in range(300):
            lvl = 1000.0 * np.exp(rng.normal(0, 0.5))
            for c, cat in enumerate(("a", "b")):
                f = np.exp((season if seasonal else np.zeros(12)) * (1 + 0.5 * c))
                x = lvl * np.concatenate([f, f]) * np.exp(rng.normal(0, 0.03, T))
                for k in range(T):
                    rows.append((months[k], i, cat, x[k]))
        d = pd.DataFrame(rows, columns=["date", "territory_id", "category", "value"])
        return d

    out = {}
    for name, seasonal in (("seasonal", True), ("no_season", False)):
        d = make(seasonal)
        path = "/tmp/_scf_%s.parquet" % name
        d.to_parquet(path)
        X, keys, mths = load_panel(path)
        cats = keys["category"].to_numpy()
        r, _ = evaluate_window(X, cats, mths, R9_WINDOW, (1, 3))
        s = summarize(r, bootstrap=200)
        out[name] = {h: (s[h]["mae"]["last_value"], s[h]["mae"]["seasonal_common"]) for h in ("1", "3")}
        os.remove(path)
        if seasonal:
            M = category_medians(X, cats)
            Y = X.copy()
            Y[:, 20:] *= 5.0   # порча месяцев после origin 19 не меняет прогноз
            assert np.allclose(seasonal_common_forecast(X, cats, M, 19, 20), seasonal_common_forecast(Y, cats, category_medians(Y, cats), 19, 20), equal_nan=True)
    assert out["seasonal"]["1"][1] < 0.6 * out["seasonal"]["1"][0], out
    assert out["no_season"]["1"][1] > 0.95 * out["no_season"]["1"][0], out
    print(json.dumps({"seasonal_beats_last_value_when_season_is_real": True, "no_gain_without_season": True,
                      "forecast_ignores_months_after_origin": True}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--panel")
    p.add_argument("--outdir")
    p.add_argument("--horizons", default=",".join(map(str, HORIZONS)))
    p.add_argument("--bootstrap", type=int, default=10000)
    p.add_argument("--seed", type=int, default=20261004)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.panel and a.outdir):
        p.error("--panel и --outdir обязательны")
    horizons = tuple(int(x) for x in a.horizons.split(","))
    if max(horizons) > SUPPORTED_MAX_HORIZON:
        p.error("горизонты длиннее %d не поддерживаются (нет прошлогодней базы)" % SUPPORTED_MAX_HORIZON)
    os.makedirs(a.outdir, exist_ok=True)
    X, keys, months = load_panel(a.panel)
    cats = keys["category"].to_numpy()
    res = {"panel": {"series": int(X.shape[0]), "months": months, "sha256": hashlib.sha256(open(a.panel, "rb").read()).hexdigest()}}
    for name, window in (("r9_window", R9_WINDOW), ("pre_window", PRE_WINDOW)):
        raw, preds = evaluate_window(X, cats, months, window, horizons, with_predictions=(name == "r9_window"))
        res[name] = {"window": window, "summary": summarize(raw, a.bootstrap, a.seed), "skipped": raw["skipped_months_no_prior_year_base"]}
        if preds is not None:
            k = keys.iloc[preds["row"].to_numpy()].reset_index(drop=True)
            out = pd.concat([k, preds.drop(columns="row")], axis=1)
            out.to_parquet(os.path.join(a.outdir, "predictions_r9_window.parquet"), index=False)
            res[name]["predictions_rows"] = int(len(out))
    res["control_vs_r9"] = reference_control(res["r9_window"]["summary"])
    res["meta"] = {"horizons": horizons, "bootstrap": a.bootstrap, "seed": a.seed, "unsupported_horizon": 12,
                   "code_sha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()}
    json.dump(res, open(os.path.join(a.outdir, "metrics.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"control_vs_r9": res["control_vs_r9"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
