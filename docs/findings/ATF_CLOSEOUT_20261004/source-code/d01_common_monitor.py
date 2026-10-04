"""Монитор общих шоков на уровне категории (ATF-M6, 03.10.2026).

Зачем. Срез по (категория, месяц) в V1, V3 и V4 стирает любой шок, общий для всей категории
(runs/D01_bank_v1_20261003: банк с V1 даёт тревогу у 0,6% рядов при общем всплеске на 20%). Монитор
смотрит на сам общий уровень: медиана по рядам категории, логарифм.

Сигналы категории (y[m] = log медианы уровня по рядам категории):
  J  скачок:         y[m] - y[m-1]
  S  устойчивый:     y[m] - медиана(y[m-3..m-1])
Ожидаемое значение сигнала (тревога = |сигнал - ожидание| > порог), все варианты причинны:
  none      среднее прошлых значений сигнала (расширяющееся окно, не меньше 8 значений)
  calendar  регрессия прошлых значений J на [1, Δlog рабочих дней, Δlog дней месяца] (только для J)
  seasonal  значение сигнала в том же месяце год назад (с 13-го месяца истории для J, с 15-го для S)
Порог каждой категории и сигнала = максимум |остатка| на валидации (2024-02 .. SPLIT, то есть ноль ложных
тревог на валидации, тест не трогается) для того же способа ожидания. Тревога монитора = любой из сигналов.

Что оценивается. События вносятся во ВСЕ ряды одной категории (как общие шоки в d01_bank): всплеск на 1
месяц, сдвиг на 3 месяца, рампа за 6 месяцев; амплитуды 2, 3, 5, 10, 20, 30%; обе стороны; начало в каждом
из тестовых месяцев, куда помещается окно. Обнаружение: тревога в течение события (всплеск: тот же месяц).
Сравнение: «доля рядов с тревогой D01@V0 по категории» с порогом = максимум на валидации. Ложные тревоги
монитора: категория-месяцы теста без вмешательства (6 категорий x 6 месяцев).

Критерии (заданы до запуска): seasonal даёт не больше 2 ложных тревог из 36 чистых категория-месяцев теста;
минимально обнаружимый общий всплеск и сдвиг (recall >= 50%) не больше 20% в каждой категории и не больше
10% минимум в трёх; seasonal не хуже none по среднему recall при тех же правилах порога.
Исправлено после первого прогона (он показал 13 ложных тревог из 36 у none и сделал recall при малых
амплитудах нечитаемым): добавлена нулевая амплитуда (база), минимально обнаружимой считается амплитуда с
recall >= 50% и превышением базы не менее 30 п.п.; сравнение методов добавлено также при равных ложных
тревогах (порог умножается на общий множитель mu так, чтобы чистых тревог теста было не больше 3 из 36). Выбор seasonal
основным опирается на T1 из runs/D01_calendar_20261003, то есть на тех же данных: это не независимая проверка.

Запуск: python3 d01_common_monitor.py --clean-signal <плацебо signal.parquet> --calendar <csv> --outdir OUT [--self-check]
"""
import argparse
import hashlib
import json
import os
import warnings

import numpy as np
import pandas as pd

try:
    from . import d01_calendar as dc
    from . import d01_sensitivity_curve as sc
except ImportError:
    import d01_calendar as dc
    import d01_sensitivity_curve as sc

METHODS = ("none", "calendar", "seasonal")
SIGNAL_NAMES = ("J", "S")
USED = {"none": ("J", "S"), "calendar": ("J",), "seasonal": ("J", "S")}  # calendar определён только для J
AMPS = (0.02, 0.03, 0.05, 0.10, 0.20, 0.30)
SHAPES = {"spike": 1, "shift": 3, "ramp": 6}  # длина события в месяцах
VAL_START = "2024-02"
MIN_HISTORY = 8


def cat_levels(X, cats):
    """log медианы уровня по рядам категории: категория -> вектор длины T."""
    out = {}
    for c in np.unique(cats):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            out[c] = np.log(np.nanmedian(X[cats == c], axis=0))
    return out


def signals(y):
    """J и S по логарифму медианы; NaN там, где истории не хватает."""
    T = len(y)
    J = np.full(T, np.nan)
    J[1:] = np.diff(y)
    S = np.full(T, np.nan)
    for m in range(3, T):
        S[m] = y[m] - np.median(y[m - 3:m])
    return {"J": J, "S": S}


def calendar_design(lw, ld):
    """Z[m] = [1, Δlog рабочих дней, Δlog дней месяца] (первый месяц без прироста)."""
    return np.column_stack([np.ones(len(lw)), np.r_[0.0, np.diff(lw)], np.r_[0.0, np.diff(ld)]])


def residuals(sig, method, Z=None):
    """Остаток сигнала относительно ожидания; ожидание использует только месяцы до m (или m-12)."""
    T = len(sig)
    r = np.full(T, np.nan)
    for m in range(T):
        if not np.isfinite(sig[m]):
            continue
        if method == "seasonal":
            if m >= 12 and np.isfinite(sig[m - 12]):
                r[m] = sig[m] - sig[m - 12]
            continue
        past = np.flatnonzero(np.isfinite(sig[:m]))
        if len(past) < MIN_HISTORY:
            continue
        if method == "none":
            r[m] = sig[m] - sig[past].mean()
        else:
            r[m] = sig[m] - Z[m] @ dc._ols(Z[past], sig[past])
    return r


def all_residuals(y, method, Z):
    sg = signals(y)
    return {n: residuals(sg[n], method, Z) for n in USED[method]}


def thresholds(panel, ylev, Z):
    """Порог по (категория, способ, сигнал) = max |остаток| на валидации; нужно не менее 3 значений."""
    val = [j for ym, j in panel.col.items() if VAL_START <= ym < sc.SPLIT]
    tau = {}
    for c, y in ylev.items():
        for method in METHODS:
            for n, r in all_residuals(y, method, Z).items():
                v = np.abs(r[val])
                v = v[np.isfinite(v)]
                if len(v) < 3:
                    raise RuntimeError("мало значений для порога: %s %s %s" % (c, method, n))
                tau[(c, method, n)] = float(v.max())
    return tau, val


def exceed_ratio(y, method, tau, cat, Z):
    """По месяцам: max по сигналам |остаток| / порог. Тревога при множителе порога mu: ratio > mu."""
    out = np.zeros(len(y))
    for n, r in all_residuals(y, method, Z).items():
        with np.errstate(invalid="ignore"):
            out = np.maximum(out, np.nan_to_num(np.abs(r) / tau[(cat, method, n)], nan=0.0))
    return out


def shocked(panel, cat, onset, amp, shape, sign):
    """X с шоком во всех рядах категории и окно (первый, последний месяц) события."""
    n = SHAPES[shape]
    X = panel.X.copy()
    rows = panel.cats == cat
    if shape == "ramp":
        k = np.arange(panel.T - onset)
        X[rows, onset:] *= 1.0 + sign * amp * np.minimum(1.0, (k + 1) / n)
    else:
        X[rows, onset:onset + n] *= 1.0 + sign * amp
    return X, (onset, onset + n - 1)


def events(panel, shape):
    """Все (категория, начало, знак), где окно помещается в тест."""
    n = SHAPES[shape]
    test = [j for ym, j in panel.col.items() if ym >= sc.SPLIT and j + n - 1 <= panel.T - 1]
    return [(c, o, s) for c in np.unique(panel.cats) for o in test for s in (1.0, -1.0)]


def share_threshold(panel, alarm_clean, val):
    """Порог доли рядов с тревогой по категориям: максимум на валидации."""
    return {c: float(alarm_clean[panel.cats == c][:, val].mean(axis=0).max()) for c in np.unique(panel.cats)}


MU_GRID = np.round(np.arange(0.5, 6.01, 0.05), 2)
FA_TARGET = 3  # ложных тревог из 36 чистых категория-месяцев теста: уровень seasonal при пороге = максимум на валидации


def run(panel, lw, ld):
    Z = calendar_design(lw, ld)
    ylev = cat_levels(panel.X, panel.cats)
    tau, val = thresholds(panel, ylev, Z)
    test = [j for ym, j in panel.col.items() if ym >= sc.SPLIT]
    cats = list(np.unique(panel.cats))
    names = METHODS + ("share_v0",)
    res = {"thresholds": {"%s|%s|%s" % k: round(v, 4) for k, v in tau.items()}, "val_months": [panel_month(panel, j) for j in val]}

    # базовый вариант: доля рядов с тревогой D01@V0 по категории
    S0 = panel.signal(panel.X, "V0_last")
    k0, _, _ = sc.calibrate_k(panel, S0, 24, on="test")
    alarm0 = sc.d01_alarm_matrix(S0, panel.rstd(S0), k0)
    tau_share = share_threshold(panel, alarm0, val)
    res["share_v0"] = {"k": k0, "thresholds": {c: round(v, 5) for c, v in tau_share.items()}}

    # чистые категория-месяцы: отношение к порогу
    clean = {m: {c: exceed_ratio(ylev[c], m, tau, c, Z) for c in cats} for m in METHODS}
    clean["share_v0"] = {c: alarm0[panel.cats == c].mean(axis=0) / tau_share[c] for c in cats}
    clean_test = {m: np.array([clean[m][c][j] for c in cats for j in test]) for m in names}

    # события (amp = 0: те же окна без шока, база ложных срабатываний); ratio окна и, для share, на месяц шире
    ev = {m: {} for m in names}
    for shape in SHAPES:
        for amp in (0.0,) + AMPS:
            for (c, o, sgn) in events(panel, shape):
                if amp == 0.0 and sgn < 0:
                    continue
                X, (lo, hi) = shocked(panel, c, o, amp, shape, sgn)
                rows = panel.cats == c
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=RuntimeWarning)
                    y = np.log(np.nanmedian(X[rows], axis=0))
                for m in METHODS:
                    ev[m].setdefault((shape, amp, c), []).append(exceed_ratio(y, m, tau, c, Z)[lo:hi + 1])
                S = panel.signal(X, "V0_last")
                al = sc.d01_alarm_matrix(S, panel.rstd(S), k0)
                ev["share_v0"].setdefault((shape, amp, c), []).append((al[rows].mean(axis=0) / tau_share[c])[lo:hi + 2])

    def fa(m, mu):
        return int((clean_test[m] > mu).sum())

    mu_eq = {}
    for m in names:
        ok = [mu for mu in MU_GRID if fa(m, float(mu)) <= FA_TARGET]
        mu_eq[m] = float(ok[0]) if ok else None
    res["mu_equal_fa"] = mu_eq
    res["clean_false_alarms_test"] = {m: {"operational": fa(m, 1.0), "equal_fa": fa(m, mu_eq[m]) if mu_eq[m] else None, "of": len(clean_test[m])}
                                      for m in names}
    res["clean_false_alarms_by_category_operational"] = {
        m: {c: int(sum(clean[m][c][j] > 1.0 for j in test)) for c in cats} for m in names}

    def detect(m, key, mu):
        return [bool((r > mu).any()) for r in ev[m][key]]

    res["recall"], res["mda"] = {}, {}
    for mode, mus in (("operational", {m: 1.0 for m in names}), ("equal_fa", mu_eq)):
        res["recall"][mode], res["mda"][mode] = {}, {}
        for m in names:
            mu = mus[m]
            res["recall"][mode][m], res["mda"][mode][m] = {}, {}
            for shape in SHAPES:
                res["recall"][mode][m][shape] = {}
                for amp in (0.0,) + AMPS:
                    v = [x for c in cats for x in detect(m, (shape, amp, c), mu)]
                    res["recall"][mode][m][shape]["%.2f" % amp] = round(float(np.mean(v)), 3)
                res["mda"][mode][m][shape] = {}
                for c in cats:
                    base = float(np.mean(detect(m, (shape, 0.0, c), mu)))
                    ok = [a for a in AMPS if np.mean(detect(m, (shape, a, c), mu)) >= 0.5 and np.mean(detect(m, (shape, a, c), mu)) - base >= 0.3]
                    res["mda"][mode][m][shape][c] = min(ok) if ok else None
            d = [int(np.flatnonzero(r > mu)[0]) for shape in SHAPES for a in AMPS for c in cats for r in ev[m][(shape, a, c)] if (r > mu).any()]
            res["recall"][mode][m]["mean_delay_months"] = round(float(np.mean(d)), 2) if d else None
    res["events"] = {shape: len(events(panel, shape)) for shape in SHAPES}
    return res


def panel_month(panel, j):
    inv = {v: k for k, v in panel.col.items()}
    return inv[j]


def self_check():
    """Монитор видит синтетический общий шок, молчит на чистых данных и не заглядывает вперёд."""
    rng = np.random.default_rng(2)
    T = 24
    lw = np.log(np.full(T, 21.0))
    ld = np.log(np.full(T, 30.0))
    Z = calendar_design(lw + rng.normal(0, 0.01, T), ld)
    season = rng.normal(0.0, 0.08, 12)
    y = np.concatenate([season, season]) + np.cumsum(np.full(T, 0.01)) + rng.normal(0.0, 0.004, T)
    sg = signals(y)
    r = residuals(sg["J"], "seasonal", Z)
    assert np.isnan(r[:13]).all() and np.isfinite(r[13:]).all()
    assert np.nanstd(r[13:]) < 0.02  # сезонность вычтена
    # причинность: порча месяцев после m не меняет остатков до m
    y2 = y.copy()
    y2[18:] += 0.5
    for method in ("none", "seasonal", "calendar"):
        a = residuals(signals(y)["J"], method, Z)[:18]
        b = residuals(signals(y2)["J"], method, Z)[:18]
        assert np.allclose(a, b, equal_nan=True), method
    y3 = y.copy()
    y3[20:] += 0.3
    big = np.abs(residuals(signals(y3)["J"], "seasonal", Z))
    assert big[20] > 0.25 and np.nanmax(np.abs(r[13:19])) < 0.05
    print(json.dumps({"seasonal_removes_cycle": True, "causal": True, "shock_visible": True}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--clean-signal")
    p.add_argument("--calendar")
    p.add_argument("--outdir")
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.clean_signal and a.calendar and a.outdir):
        p.error("--clean-signal, --calendar и --outdir обязательны")
    os.makedirs(a.outdir, exist_ok=True)
    panel = sc.Panel(pd.read_parquet(a.clean_signal))
    lw, ld = dc.month_calendar(a.calendar, dc.months_of(panel))
    res = run(panel, lw, ld)
    res["meta"] = {"methods": METHODS, "amps": AMPS, "shapes": SHAPES, "val_start": VAL_START, "min_history": MIN_HISTORY,
                   "clean_signal_sha256": hashlib.sha256(open(a.clean_signal, "rb").read()).hexdigest(),
                   "calendar_sha256": hashlib.sha256(open(a.calendar, "rb").read()).hexdigest()}
    json.dump(res, open(os.path.join(a.outdir, "common_monitor.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"clean_false_alarms_test": res["clean_false_alarms_test"], "mu_equal_fa": res["mu_equal_fa"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
