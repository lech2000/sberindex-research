"""Календарная поправка для D01: помогает ли производственный календарь (ATF-M6, 03.10.2026).

Вопрос. Расходы за месяц зависят от числа рабочих дней и длины месяца. Если этот общий для всех
муниципалитетов эффект убрать из ряда, шум сигнала уменьшится, и при тех же ложных тревогах D01
найдёт больше событий. Но срез по (категория, месяц) в V3/V4 уже убирает любой общий эффект
точно (по этому же месяцу), поэтому выигрыш возможен только у V0 без среза, а верхняя граница
выигрыша любой поправки на общую часть — V1 (V0 минус срез).

Что считается (критерии T2 и T3 заданы до запуска; T1 в предварительном виде просмотрен до
формулировки критерия, см. provenance):
  T1  Общее движение категории (медиана log-прироста по муниципалитетам) предсказывается календарём
      вне выборки? Окно расширяется, месяцы 2024-02..2024-12, регрессия на [1, log рабочих дней,
      log дней месяца], база сравнения — среднее прошлых приростов; справочно — сезонный наив
      (прирост того же месяца год назад) и модель только с рабочими днями.
  T2  Чувствительность D01 при равных ложных тревогах (24 и 96 в месяц, как в d01_bank):
        V0 / V0c (V0 на ряду, очищенном календарём) / V1 (граница) / V3 / V3c
      и ПОСЛЕ просмотра T1 (post hoc): V0s (V0 на ряду, очищенном общим приростом того же месяца
      прошлого года) и V0co (коэффициенты календаря по ВСЕМ месяцам, включая тест: подглядывание,
      верхняя граница календаря с двумя признаками, в работе недопустимо). Коэффициенты календаря подбираются по обучающим месяцам (ym < TRAIN_END)
      на чистых рядах и далее заморожены; события вносятся до поправки.
  T3  Различается ли календарная чувствительность между муниципалитетами (остаток после среза V1
      объясняется календарём каждого ряда вне выборки)?

Поправка действует на уровень ряда: x_adj = x * exp(-A), A[m] = b_work*log(work[m]) + b_days*log(days[m])
(для календаря) или накопленная сумма приростов общего движения категории год назад (для сезонной).
Календарь доступен заранее, сезонная часть использует только месяцы, прошедшие к моменту m.

Запуск: python3 d01_calendar.py --clean-signal <плацебо signal.parquet> --calendar <csv> --outdir OUT [--self-check]
"""
import argparse
import hashlib
import json
import os

import numpy as np
import pandas as pd

try:
    from . import d01_bank as bk
    from . import d01_sensitive_signals as ss
    from . import d01_sensitivity_curve as sc
    from . import d01_shock_shapes as sh
except ImportError:
    import d01_bank as bk
    import d01_sensitive_signals as ss
    import d01_sensitivity_curve as sc
    import d01_shock_shapes as sh

# вариант -> (сигнал, поправка); post hoc помечен отдельно
VARIANTS = {
    "V0": ("V0_last", None), "V0c": ("V0_last", "calendar"), "V1": ("V1_last_cs", None),
    "V3": ("V3_med3_cs", None), "V3c": ("V3_med3_cs", "calendar"), "V0s": ("V0_last", "seasonal"),
    "V0co": ("V0_last", "calendar_oracle"),
}
POST_HOC = ("V0s", "V0co")  # добавлены после просмотра T1 и T2 для V0c; V0co подглядывает (коэффициенты по всем месяцам)
PAIRS = (("V0c", "V0", False), ("V1", "V0", False), ("V3c", "V3", False), ("V0s", "V0", True), ("V0co", "V0", True))
FA_LEVELS = (24, 96)
FIRST_EXPANDING_MONTH = "2024-02"


def month_calendar(csv_path, months):
    """log числа рабочих (в т.ч. сокращённых) дней и log числа дней по месяцам 'YYYY-MM'."""
    cal = pd.read_csv(csv_path, parse_dates=["date"])
    cal["ym"] = cal["date"].dt.strftime("%Y-%m")
    g = cal.groupby("ym").agg(days=("date", "size"), work=("status_code", lambda s: int(((s == 0) | (s == 2)).sum())))
    miss = [m for m in months if m not in g.index]
    if miss:
        raise ValueError("в календаре нет месяцев %s" % miss)
    return np.log(g.loc[months, "work"].to_numpy(float)), np.log(g.loc[months, "days"].to_numpy(float))


def months_of(panel):
    return [ss._ym(panel.m0 + j) for j in range(panel.T)]


def common_diff(panel):
    """Прирост log медианы уровня по муниципалитетам: категория -> вектор длины T-1 (индекс i = месяц i+1)."""
    out = {}
    for c in np.unique(panel.cats):
        with np.errstate(all="ignore"):
            med = np.nanmedian(panel.X[panel.cats == c], axis=0)
        out[c] = np.diff(np.log(med))
    return out


def _ols(Z, y):
    return np.linalg.lstsq(Z, y, rcond=None)[0]


def fit_calendar(panel, lw, ld, oracle=False):
    """Коэффициенты (const, work, days) по категории на обучающих приростах (месяц и предыдущий в train).

    oracle=True: по ВСЕМ месяцам, включая тест. Это подглядывание: верхняя граница календаря с этими
    двумя признаками, в рабочем режиме недопустима."""
    dl, dd = np.diff(lw), np.diff(ld)
    tr = np.arange(len(dl)) if oracle else np.array([j - 1 for j in panel.train_cols if j >= 1])
    betas = {}
    for c, d in common_diff(panel).items():
        Z = np.column_stack([np.ones(len(tr)), dl[tr], dd[tr]])
        betas[c] = _ols(Z, d[tr])
    return betas


def calendar_adjustment(panel, betas, lw, ld):
    """A[n, T]: log-поправка уровня, по категориям (константа сноса не вычитается)."""
    A = np.zeros(panel.X.shape)
    for c, b in betas.items():
        A[panel.cats == c] = b[1] * lw[None, :] + b[2] * ld[None, :]
    return A


def seasonal_adjustment(panel, lag=12):
    """A[n, T]: накопленный общий прирост категории `lag` месяцев назад; первый год не корректируется."""
    A = np.zeros(panel.X.shape)
    for c, d in common_diff(panel).items():
        inc = np.zeros(panel.T)
        for j in range(1, panel.T):
            if j - lag >= 1:
                inc[j] = d[j - lag - 1]
        A[panel.cats == c] = np.cumsum(inc)[None, :]
    return A


def signal_of(panel, X, variant, A):
    base, kind = VARIANTS[variant]
    Xa = X if kind is None else X * np.exp(-A[kind])
    return panel.signal(Xa, base)


def expanding_diagnostic(panel, lw, ld):
    """T1: RMSE одношагового прогноза общего прироста категории; расширяющееся окно с 2024-02."""
    months = months_of(panel)
    dl, dd = np.diff(lw), np.diff(ld)
    idx = [i for i, ym in enumerate(months[1:]) if ym >= FIRST_EXPANDING_MONTH]
    Zfull = np.column_stack([np.ones(len(dl)), dl, dd])
    rmse = lambda e: float(np.sqrt(np.mean(np.square(e))))
    out = {}
    for c, d in common_diff(panel).items():
        e = {"mean": [], "calendar": [], "calendar_work_only": [], "seasonal_naive": []}
        for i in idx:
            tr = np.arange(0, i)
            e["mean"].append(d[i] - d[tr].mean())
            b = _ols(Zfull[tr], d[tr])
            e["calendar"].append(d[i] - Zfull[i] @ b)
            b1 = _ols(Zfull[tr][:, :2], d[tr])
            e["calendar_work_only"].append(d[i] - Zfull[i, :2] @ b1)
            e["seasonal_naive"].append(d[i] - d[i - 12])
        out[c] = {k: round(rmse(v), 4) for k, v in e.items()}
        out[c]["sd_diff"] = round(float(d.std()), 4)
        out[c]["calendar_beats_mean"] = out[c]["calendar"] < out[c]["mean"]
    return out


def in_sample_r2(panel, lw, ld, n_perm=2000, seed=1):
    """R^2 календаря на общем приросте категории по ВСЕМ месяцам и перестановочная p-оценка (календарь перемешан по месяцам).

    Показывает, есть ли календарный сигнал вообще; для прогноза не годится (в выборке)."""
    dl, dd = np.diff(lw), np.diff(ld)
    Z = np.column_stack([np.ones(len(dl)), dl, dd])
    rng = np.random.default_rng(seed)
    out = {}
    for c, d in common_diff(panel).items():
        r2 = 1 - (d - Z @ _ols(Z, d)).var() / d.var()
        null = []
        for _ in range(n_perm):
            q = rng.permutation(len(dl))
            Zp = np.column_stack([np.ones(len(dl)), dl[q], dd[q]])
            null.append(1 - (d - Zp @ _ols(Zp, d)).var() / d.var())
        out[c] = {"r2": round(float(r2), 3), "perm_median": round(float(np.median(null)), 3),
                  "perm_p": round(float(np.mean(np.array(null) >= r2)), 4)}
    return out


def common_share(panel):
    """Доля общей части в разбросе V0 на обучающих месяцах: MAD^2 медиан по муниципалитетам / MAD^2 всех значений."""
    S = panel.signal(panel.X, "V0_last")[:, panel.train_cols]
    mad = lambda v: float(np.nanmedian(np.abs(v - np.nanmedian(v))) * 1.4826)
    out = {}
    for c in np.unique(panel.cats):
        s = S[panel.cats == c]
        with np.errstate(all="ignore"):
            med = np.nanmedian(s, axis=0)
        out[c] = round((mad(med) / mad(s)) ** 2, 4)
    return out


def heterogeneity(panel, lw, ld):
    """T3: R^2 вне выборки календаря по рядам на остатке V1 (после среза). Обучение: train, оценка: ym >= SPLIT."""
    S = panel.signal(panel.X, "V1_last_cs")
    C = np.column_stack([np.zeros(panel.T), np.r_[0.0, np.diff(lw)], np.r_[0.0, np.diff(ld)]])
    tr = [j for j in panel.train_cols if j >= 1]
    te = [j for ym, j in panel.col.items() if ym >= sc.SPLIT]
    Ztr = np.column_stack([np.ones(len(tr)), C[tr, 1:]])
    Zte = np.column_stack([np.ones(len(te)), C[te, 1:]])
    sse_model = sse_pooled = sse_zero = 0.0
    slopes = []
    for c in np.unique(panel.cats):
        rows = np.flatnonzero(panel.cats == c)
        per = []
        for r in rows:
            y = S[r, tr]
            ok = np.isfinite(y)
            if ok.sum() < 8:
                continue
            per.append((r, _ols(Ztr[ok], y[ok])))
        pooled = np.median(np.array([b for _, b in per]), axis=0)
        for r, b in per:
            y = S[r, te]
            ok = np.isfinite(y)
            if not ok.any():
                continue
            sse_zero += float(np.sum(y[ok] ** 2))
            sse_model += float(np.sum((y[ok] - Zte[ok] @ b) ** 2))
            sse_pooled += float(np.sum((y[ok] - Zte[ok] @ pooled) ** 2))
            slopes.append(b[1])
    return {"r2_oos_per_series": round(1 - sse_model / sse_zero, 4), "r2_oos_category_pooled": round(1 - sse_pooled / sse_zero, 4),
            "series": len(slopes), "sd_series_slope_work": round(float(np.std(slopes)), 3)}


def calibrate(panel, A, fa):
    """Порог D01 каждого варианта на чистом сигнале, ложные тревоги по тесту <= fa в месяц."""
    out = {}
    for name in VARIANTS:
        S = signal_of(panel, panel.X, name, A)
        k, n, months = sc.calibrate_k(panel, S, fa, on="test")
        out[name] = {"k": k, "false_alarms_per_test_month": round(n / months, 1)}
    return out


def run(panel, lw, ld, seed, n_events=sh.N_EVENTS):
    betas = fit_calendar(panel, lw, ld)
    betas_oracle = fit_calendar(panel, lw, ld, oracle=True)
    A = {"calendar": calendar_adjustment(panel, betas, lw, ld), "seasonal": seasonal_adjustment(panel),
         "calendar_oracle": calendar_adjustment(panel, betas_oracle, lw, ld)}
    res = {"t1_expanding": expanding_diagnostic(panel, lw, ld), "t1_in_sample": in_sample_r2(panel, lw, ld),
           "common_share_v0_train": common_share(panel),
           "t3_heterogeneity": heterogeneity(panel, lw, ld),
           "calendar_betas": {c: [round(float(x), 3) for x in b] for c, b in betas.items()},
           "calendar_betas_oracle": {c: [round(float(x), 3) for x in b] for c, b in betas_oracle.items()},
           "calibration": {str(fa): calibrate(panel, A, fa) for fa in FA_LEVELS}, "cells": {}}
    sigma_lvl = panel.rstd(panel.signal(panel.X, "V0_last")) / np.sqrt(2.0)
    T = panel.T
    store = {str(fa): {} for fa in FA_LEVELS}

    def evaluate(shape, key, X, rows, onsets, window):
        S = {name: signal_of(panel, X, name, A) for name in VARIANTS}
        for fa in FA_LEVELS:
            for name in VARIANTS:
                alarm = sc.d01_alarm_matrix(S[name], panel.rstd(S[name]), res["calibration"][str(fa)][name]["k"])
                hits, delays = sh.score_events(alarm, rows, onsets, window[0], window[1], T)
                vec = bk.event_hits(alarm, rows, onsets, window[0], window[1], T)
                assert int(vec.sum()) == hits
                store[str(fa)].setdefault((shape, key), {})[name] = vec
                res["cells"].setdefault(shape, {}).setdefault(str(fa), {}).setdefault(name, {})[key] = \
                    sh.cell_record(hits, len(rows), delays)

    # те же затравки и события, что в d01_bank.run
    for i, (shape, amp, L) in enumerate((("spike", 0.30, 1), ("shift", 0.20, 3), ("shift", 0.30, 3))):
        X, rows, onsets = sc.inject(panel, np.random.default_rng(seed + 10 + i), amp, L, n_events)
        evaluate(shape, "a%.2f_L%d" % (amp, L), X, rows, onsets, (-1, 1))
    for i, amp in enumerate(sh.RAMP_AMPS):
        for j, R in enumerate(sh.RAMP_LENS):
            X, rows, onsets = sh.inject_ramp(panel, np.random.default_rng(seed + 100 + 10 * i + j), amp, R, n_events)
            evaluate("ramp", "a%.2f_R%d" % (amp, R), X, rows, onsets, (0, R))
    for i, m in enumerate(sh.VOL_MULTS):
        for j, L in enumerate(sh.VOL_LENS):
            X, rows, onsets = sh.inject_vol(panel, np.random.default_rng(seed + 200 + 10 * i + j), m, L, n_events, sigma_lvl)
            evaluate("vol", "m%.1f_L%d" % (m, L), X, rows, onsets, (0, L))
    # плацебо: события без инжекта, окно 5 месяцев
    rng = np.random.default_rng(seed + 300)
    complete = np.flatnonzero(np.isfinite(panel.X).all(axis=1))
    rows = rng.choice(complete, size=n_events, replace=False)
    onsets = rng.integers(panel.col[sc.SPLIT], panel.T - 3, size=n_events)
    for fa in FA_LEVELS:
        for name in VARIANTS:
            S = signal_of(panel, panel.X, name, A)
            alarm = sc.d01_alarm_matrix(S, panel.rstd(S), res["calibration"][str(fa)][name]["k"])
            hits, delays = sh.score_events(alarm, rows, onsets, 0, 4, T)
            res["cells"].setdefault("placebo", {}).setdefault(str(fa), {}).setdefault(name, {})["window5"] = \
                sh.cell_record(hits, len(rows), delays)
    res["summary"] = summarize(res)
    res["paired"] = paired(store)
    return res


def summarize(res):
    out = {}
    for fa in res["calibration"]:
        out[fa] = {}
        for name in VARIANTS:
            rep = [res["cells"][s][fa][name][k]["recall"] for s, k in bk.REPRESENTATIVE]
            allc = [rec["recall"] for shape in ("spike", "shift", "ramp", "vol") for rec in res["cells"][shape][fa][name].values()]
            out[fa][name] = {"representative_mean": round(float(np.mean(rep)), 3), "all_cells_mean": round(float(np.mean(allc)), 3),
                             "n_cells": len(allc)}
    return out


def paired(store):
    out = {}
    for fa, cells in store.items():
        out[fa] = {}
        for first, second, post_hoc in PAIRS:
            dv = {cell: bk.paired_diff(v[first], v[second]) for cell, v in cells.items()}

            def mean_ci(keys):
                return bk._ci(float(np.mean([dv[c][0] for c in keys])), float(np.sum([dv[c][1] for c in keys])) / len(keys) ** 2)

            sig_hi = sum(1 for d, v in dv.values() if d - 1.96 * np.sqrt(v) > 0)
            sig_lo = sum(1 for d, v in dv.values() if d + 1.96 * np.sqrt(v) < 0)
            out[fa]["%s_vs_%s" % (first, second)] = {
                "post_hoc": post_hoc, "cells": {"%s/%s" % c: bk._ci(*dv[c]) for c in dv},
                "mean_representative": mean_ci([c for c in dv if c in bk.REPRESENTATIVE]), "mean_all_cells": mean_ci(list(dv)),
                "cells_significantly_higher": sig_hi, "cells_significantly_lower": sig_lo}
    return out


def self_check():
    """Календарь известен заранее; поправка очищает синтетический эффект; сезонная не заглядывает вперёд."""
    rng = np.random.default_rng(3)
    months = ["%04d-%02d" % (2023 + k // 12, k % 12 + 1) for k in range(24)]
    work = np.array([20 + (k * 7) % 4 for k in range(24)], float)
    days = np.array([30 + (k % 2) for k in range(24)], float)
    lw, ld = np.log(work), np.log(days)
    rows = []
    for tid in range(200):
        x = 1000.0 * np.exp(0.8 * lw + 0.3 * ld + rng.normal(0.0, 0.03, 24))
        for k in range(1, 24):
            rows.append({"tid": tid, "cat": "a", "ym": months[k], "actual_inj": float(x[k]),
                         "pred": float(x[k - 1]), "rel": float(x[k] / x[k - 1] - 1)})
    panel = sc.Panel(pd.DataFrame(rows))
    betas = fit_calendar(panel, lw, ld)
    b = betas["a"]
    assert abs(b[1] - 0.8) < 0.15 and abs(b[2] - 0.3) < 0.8, b
    A = calendar_adjustment(panel, betas, lw, ld)
    S0 = panel.signal(panel.X, "V0_last")
    S1 = panel.signal(panel.X * np.exp(-A), "V0_last")
    sd = lambda S: float(np.nanstd(S[:, panel.train_cols]))
    assert sd(S1) < 0.7 * sd(S0), (sd(S0), sd(S1))
    # причинность сезонной поправки: порча месяцев после m не меняет A[:, :m+1]
    As = seasonal_adjustment(panel)
    X2 = panel.X.copy()
    X2[:, 15:] *= 2.0
    p2 = sc.Panel(pd.DataFrame(rows))
    p2.X = X2
    As2 = seasonal_adjustment(p2)
    assert np.allclose(As[:, :15], As2[:, :15]) and np.allclose(As[:, :13], 0.0)
    print(json.dumps({"calendar_effect_removed": True, "seasonal_causal": True, "sd_before": round(sd(S0), 4), "sd_after": round(sd(S1), 4)}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--clean-signal")
    p.add_argument("--calendar")
    p.add_argument("--outdir")
    p.add_argument("--n-events", type=int, default=sh.N_EVENTS)
    p.add_argument("--seed", type=int, default=20261002)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.clean_signal and a.calendar and a.outdir):
        p.error("--clean-signal, --calendar и --outdir обязательны")
    os.makedirs(a.outdir, exist_ok=True)
    panel = sc.Panel(pd.read_parquet(a.clean_signal))
    lw, ld = month_calendar(a.calendar, months_of(panel))
    res = run(panel, lw, ld, a.seed, a.n_events)
    res["meta"] = {"seed": a.seed, "n_events_per_cell": a.n_events, "fa_levels": FA_LEVELS,
                   "variants": {k: list(v) for k, v in VARIANTS.items()}, "post_hoc": POST_HOC,
                   "paired_comparisons": [list(p_) for p_ in PAIRS], "representative_cells": bk.REPRESENTATIVE,
                   "clean_signal_sha256": hashlib.sha256(open(a.clean_signal, "rb").read()).hexdigest(),
                   "calendar_sha256": hashlib.sha256(open(a.calendar, "rb").read()).hexdigest()}
    json.dump(res, open(os.path.join(a.outdir, "calendar.json"), "w"), ensure_ascii=False, indent=1, default=lambda o: bool(o) if isinstance(o, np.bool_) else str(o))
    print(json.dumps(res["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
