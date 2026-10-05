"""Формы шока вне реестра: рампа и рост волатильности (ATF-M6, 02.10.2026).

Реестр R5 содержит только временные сдвиги уровня. Здесь проверяются:
  ramp   уровень меняется линейно за R месяцев (3, 4, 6) и остаётся на новом уровне до конца окна
  vol    уровень не меняется, шум ряда растёт в m раз (1.5, 2, 3, 4) на L месяцев (3, 6)
  и два контрольных класса из прошлой кривой: spike (1 месяц) и shift (3 месяца).

Детекторы зафиксированы ДО запуска, подбора по событиям нет; порог/параметр каждого подбирается на
событие-свободном сигнале так, чтобы реальная частота ложных тревог на тестовых месяцах была
одинаковой (24 или 96 в месяц), как в d01_sensitivity_curve:
  D01@V0, D01@V3, D01@V4   правило D01 (два горячих месяца) на сигналах d01_sensitive_signals
  U(V0,V3)                 тревога V0 или V3, каждому половина бюджета
  PH@V0, PH@V3             Page-Hinkley (как d02_d03_detectors.d02_alarms), delta = 0.05,
                           порог lambda подбирается; векторная копия, сверена с модулем
  PHn@V0, PHn@V3           то же на сигнале, нормированном на rstd ряда, delta = 0.5. ДОБАВЛЕН ПОСЛЕ
                           первого прогона: ненормированный PH слеп даже на контрольных классах
                           (шумные малые муниципалитеты перебивают всех); на рампы не подбирался
  VOL@V3                   среднее |сигнал V3| / rstd за последние 3 месяца > k (без персистентности)

Окно обнаружения: spike/shift — onset-1..onset+1; ramp — onset..onset+R (пока рампа развивается),
дополнительно «к концу окна»; vol — onset..onset+L. Для рампы пишется задержка и доля итоговой
амплитуды, достигнутая к моменту тревоги. События вносятся только в полные ряды.

Запуск: python3 d01_shock_shapes.py --clean-signal <плацебо signal.parquet> --outdir OUT [--self-check]
"""
import argparse
import hashlib
import json
import os
import warnings

import numpy as np
import pandas as pd

try:
    from . import d01_sensitivity_curve as sc
except ImportError:
    import d01_sensitivity_curve as sc

PH_DELTA = 0.05
PH_GRID = np.round(np.geomspace(0.05, 8.0, 80), 4)
PHN_DELTA = 0.5  # в единицах rstd ряда (обычная настройка CUSUM: полсигмы)
PHN_GRID = np.round(np.geomspace(1.0, 100.0, 90), 3)
FA_LEVELS = (24, 96)
N_EVENTS = 500
DETECTORS = ("D01@V0", "D01@V3", "D01@V4", "U(V0,V3)", "PH@V0", "PH@V3", "VOL@V3", "PHn@V0", "PHn@V3")
RAMP_AMPS, RAMP_LENS = (0.10, 0.20, 0.30, 0.50), (3, 4, 6)
VOL_MULTS, VOL_LENS = (1.5, 2.0, 3.0, 4.0), (3, 6)


def ph_alarm_matrix(S, delta, lam):
    """Векторная копия d02_d03_detectors.d02_alarms: Page-Hinkley с обнулением после тревоги."""
    n, T = S.shape
    s_pos = np.zeros(n)
    s_neg = np.zeros(n)
    m_pos = np.zeros(n)
    m_neg = np.zeros(n)
    run_sum = np.zeros(n)
    run_n = np.zeros(n)
    alarm = np.zeros((n, T), dtype=bool)
    for t in range(T):
        v = S[:, t]
        fin = np.isfinite(v)
        vv = np.where(fin, v, 0.0)
        mu = np.where(run_n > 0, run_sum / np.maximum(run_n, 1), vv)
        s_pos = np.where(fin, s_pos + vv - mu - delta, s_pos)
        m_pos = np.where(fin, np.minimum(m_pos, s_pos), m_pos)
        s_neg = np.where(fin, s_neg + mu - vv - delta, s_neg)
        m_neg = np.where(fin, np.minimum(m_neg, s_neg), m_neg)
        ph = np.maximum(s_pos - m_pos, s_neg - m_neg)
        run_sum = np.where(fin, run_sum + vv, run_sum)
        run_n = np.where(fin, run_n + 1, run_n)
        fire = fin & (run_n > 1) & (ph > lam)
        alarm[:, t] = fire
        for arr in (s_pos, s_neg, m_pos, m_neg, run_sum, run_n):
            arr[fire] = 0.0
    return alarm


def vol_alarm_matrix(S, rstd, k):
    """Среднее нормированной величины отклонения за 3 последних месяца (все три известны) > k."""
    A = np.abs(S) / rstd[:, None]
    out = np.zeros(S.shape, dtype=bool)
    for j in range(2, S.shape[1]):
        w = A[:, j - 2:j + 1]
        ok = np.isfinite(w).all(axis=1)
        out[:, j] = ok & (np.where(ok[:, None], w, 0.0).sum(axis=1) / 3.0 > k)
    return out


def inject_ramp(panel, rng, amp, R, n):
    complete = np.flatnonzero(np.isfinite(panel.X).all(axis=1))
    rows = rng.choice(complete, size=min(n, len(complete)), replace=False)
    onsets = rng.integers(panel.col[sc.SPLIT], panel.T - R + 1, size=len(rows))
    sign = np.where(np.arange(len(rows)) % 2 == 0, 1.0, -1.0)
    X = panel.X.copy()
    for r, o, s in zip(rows, onsets, sign):
        k = np.arange(panel.T - o)
        X[r, o:] *= 1.0 + s * amp * np.minimum(1.0, (k + 1) / R)
    return X, rows, onsets


def inject_vol(panel, rng, mult, L, n, sigma_lvl):
    """Шум уровня ряда растёт в mult раз: к lognormal-множителю с sd = sigma_lvl*sqrt(mult^2-1)."""
    complete = np.flatnonzero(np.isfinite(panel.X).all(axis=1))
    rows = rng.choice(complete, size=min(n, len(complete)), replace=False)
    onsets = rng.integers(panel.col[sc.SPLIT], panel.T - L + 1, size=len(rows))
    X = panel.X.copy()
    for r, o in zip(rows, onsets):
        sd = sigma_lvl[r] * np.sqrt(mult ** 2 - 1.0)
        X[r, o:o + L] *= np.exp(rng.normal(0.0, sd, size=L))
    return X, rows, onsets


class Detectors:
    """Калибровка и вычисление тревог всех детекторов на заданной матрице рядов."""

    def __init__(self, panel):
        self.panel = panel
        S = {v: panel.signal(panel.X, v) for v in ("V0_last", "V3_med3_cs", "V4_med6_cs")}
        self.clean = S
        self.test_cols = {j for ym, j in panel.col.items() if ym >= sc.SPLIT}
        self.params = {}
        for fa in FA_LEVELS:
            for name in DETECTORS:
                if name == "U(V0,V3)":
                    continue
                self.params[(name, fa)] = self._calibrate(name, fa)
            for name in ("D01@V0", "D01@V3"):
                self.params[(name + "/half", fa)] = self._calibrate(name, fa // 2)

    def _alarm(self, name, S_by_variant, param):
        base = name.split("/")[0]
        if base.startswith("D01@"):
            v = {"V0": "V0_last", "V3": "V3_med3_cs", "V4": "V4_med6_cs"}[base[4:]]
            S = S_by_variant[v]
            return sc.d01_alarm_matrix(S, self.panel.rstd(S), param)
        if base.startswith("PHn@"):
            v = {"V0": "V0_last", "V3": "V3_med3_cs"}[base[4:]]
            S = S_by_variant[v]
            return ph_alarm_matrix(S / self.panel.rstd(S)[:, None], PHN_DELTA, param)
        if base.startswith("PH@"):
            v = {"V0": "V0_last", "V3": "V3_med3_cs"}[base[3:]]
            return ph_alarm_matrix(S_by_variant[v], PH_DELTA, param)
        S = S_by_variant["V3_med3_cs"]
        return vol_alarm_matrix(S, self.panel.rstd(S), param)

    def _calibrate(self, name, fa):
        grid = PHN_GRID if name.startswith("PHn@") else PH_GRID if name.startswith("PH@") else sc.K_GRID
        target = fa * len(self.test_cols)
        for p in grid:
            a = self._alarm(name, self.clean, float(p))
            n = sc.cooled_count(a, self.test_cols)
            if n <= target:
                return {"param": float(p), "false_alarms_per_test_month": round(n / len(self.test_cols), 1)}
        raise RuntimeError("параметр не найден: %s" % name)

    def alarms(self, S_by_variant, fa):
        out = {}
        for name in DETECTORS:
            if name == "U(V0,V3)":
                a = self._alarm("D01@V0", S_by_variant, self.params[("D01@V0/half", fa)]["param"])
                b = self._alarm("D01@V3", S_by_variant, self.params[("D01@V3/half", fa)]["param"])
                out[name] = a | b
            else:
                out[name] = self._alarm(name, S_by_variant, self.params[(name, fa)]["param"])
        return out


def score_events(alarm, rows, onsets, lo, hi, T):
    """hits, список задержек; окно [onset+lo, min(onset+hi, T-1)]; hi=None -> до конца окна."""
    hits, delays = 0, []
    for r, o in zip(rows, onsets):
        a = max(0, int(o) + lo)
        b = T - 1 if hi is None else min(T - 1, int(o) + hi)
        idx = np.flatnonzero(alarm[r, a:b + 1])
        if len(idx):
            hits += 1
            delays.append(int(a + idx[0] - o))
    return hits, delays


def cell_record(hits, n, delays, extra=None):
    lo, hi = sc.wilson(hits, n)
    rec = {"n": n, "hits": hits, "recall": round(hits / n, 3), "ci95": [lo, hi],
           "mean_delay_m": round(float(np.mean(delays)), 2) if delays else None}
    if extra:
        rec.update(extra)
    return rec


def run(panel, seed, n_events=N_EVENTS):
    det = Detectors(panel)
    S0 = det.clean["V0_last"]
    sigma_lvl = panel.rstd(S0) / np.sqrt(2.0)
    res = {"calibration": {str(fa): {name: det.params[(name, fa)] for name in DETECTORS if name != "U(V0,V3)"}
                           for fa in FA_LEVELS}, "cells": {}}
    T = panel.T

    def evaluate(shape, key, X, rows, onsets, windows):
        S = {v: panel.signal(X, v) for v in ("V0_last", "V3_med3_cs", "V4_med6_cs")}
        for fa in FA_LEVELS:
            alarms = det.alarms(S, fa)
            for name, alarm in alarms.items():
                rec = {}
                for wname, (lo, hi) in windows.items():
                    hits, delays = score_events(alarm, rows, onsets, lo, hi, T)
                    rec[wname] = cell_record(hits, len(rows), delays)
                res["cells"].setdefault(shape, {}).setdefault(str(fa), {}).setdefault(name, {})[key] = rec

    # контрольные классы
    for i, (shape, amp, L) in enumerate((("spike", 0.30, 1), ("shift", 0.20, 3), ("shift", 0.30, 3))):
        rng = np.random.default_rng(seed + 10 + i)
        X, rows, onsets = sc.inject(panel, rng, amp, L, n_events)
        evaluate(shape, "a%.2f_L%d" % (amp, L), X, rows, onsets, {"match": (-1, 1)})
    # рампа
    for i, amp in enumerate(RAMP_AMPS):
        for j, R in enumerate(RAMP_LENS):
            rng = np.random.default_rng(seed + 100 + 10 * i + j)
            X, rows, onsets = inject_ramp(panel, rng, amp, R, n_events)
            evaluate("ramp", "a%.2f_R%d" % (amp, R), X, rows, onsets,
                     {"during_ramp": (0, R), "by_window_end": (0, None)})
    # рост волатильности
    for i, m in enumerate(VOL_MULTS):
        for j, L in enumerate(VOL_LENS):
            rng = np.random.default_rng(seed + 200 + 10 * i + j)
            X, rows, onsets = inject_vol(panel, rng, m, L, n_events, sigma_lvl)
            evaluate("vol", "m%.1f_L%d" % (m, L), X, rows, onsets, {"during_episode": (0, L)})
    # плацебо для волатильности и рампы: те же детекторы на чистом сигнале должны давать только шум
    for shape, key in (("ramp", "a0.00_R4"), ("vol", "m1.0_L3")):
        rng = np.random.default_rng(seed + 300)
        complete = np.flatnonzero(np.isfinite(panel.X).all(axis=1))
        rows = rng.choice(complete, size=n_events, replace=False)
        onsets = rng.integers(panel.col[sc.SPLIT], panel.T - 3, size=n_events)
        for fa in FA_LEVELS:
            alarms = det.alarms(det.clean, fa)
            for name, alarm in alarms.items():
                hits, delays = score_events(alarm, rows, onsets, 0, 4, T)
                res["cells"].setdefault("placebo_" + shape, {}).setdefault(str(fa), {}).setdefault(name, {})[key] = \
                    {"during": cell_record(hits, len(rows), delays)}
    return res


def self_check():
    import d02_d03_detectors as dmod
    rng = np.random.default_rng(9)
    rows = []
    for tid in range(1, 41):
        x = rng.normal(1000, 80, size=24)
        x[14:] *= np.linspace(1.0, 1.5, 10)  # рампа
        for k in range(1, 24):
            ym = "%04d-%02d" % (2023 + k // 12, k % 12 + 1)
            rows.append({"tid": tid, "cat": "a", "ym": ym, "actual_inj": float(x[k]),
                         "pred": float(x[k - 1]), "rel": float(x[k] / x[k - 1] - 1)})
    sig = pd.DataFrame(rows)
    panel = sc.Panel(sig)
    S = panel.signal(panel.X, "V0_last")
    for delta, lam in ((0.05, 0.3), (0.02, 0.1), (0.10, 0.4)):
        ref = dmod.d02_alarms(sig, "rel", delta, lam)
        mine = ph_alarm_matrix(S, delta, lam)
        got = {(int(panel.tids[r]), sc.ss._ym(panel.m0 + j)) for r, j in zip(*np.nonzero(mine))}
        want = {(int(t), ym) for t, ym in zip(ref["tid"], ref["ym"])}
        assert got == want, (delta, lam, len(got), len(want))
    # профиль рампы: полный уровень достигается к R-му месяцу и удерживается
    X, rows_, onsets = inject_ramp(panel, np.random.default_rng(1), 0.3, 4, 10)
    r, o = rows_[0], onsets[0]
    ratio = X[r, o:] / panel.X[r, o:]
    assert np.allclose(ratio[:4], [1 + 0.3 * f for f in (0.25, 0.5, 0.75, 1.0)], atol=1e-9) or \
        np.allclose(ratio[:4], [1 - 0.3 * f for f in (0.25, 0.5, 0.75, 1.0)], atol=1e-9)
    assert np.allclose(ratio[3:], ratio[3])
    print(json.dumps({"ph_vectorized_equals_module": True, "ramp_profile_ok": True}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--clean-signal")
    p.add_argument("--outdir")
    p.add_argument("--n-events", type=int, default=N_EVENTS)
    p.add_argument("--seed", type=int, default=20261002)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.clean_signal and a.outdir):
        p.error("--clean-signal и --outdir обязательны")
    os.makedirs(a.outdir, exist_ok=True)
    panel = sc.Panel(pd.read_parquet(a.clean_signal))
    res = run(panel, a.seed, a.n_events)
    res["meta"] = {"seed": a.seed, "n_events_per_cell": a.n_events, "ph_delta": PH_DELTA, "phn_delta": PHN_DELTA, "fa_levels": FA_LEVELS,
                   "detectors": DETECTORS, "ramp_amps": RAMP_AMPS, "ramp_lens": RAMP_LENS,
                   "vol_mults": VOL_MULTS, "vol_lens": VOL_LENS,
                   "clean_signal_sha256": hashlib.sha256(open(a.clean_signal, "rb").read()).hexdigest(),
                   "series": int(panel.X.shape[0])}
    json.dump(res, open(os.path.join(a.outdir, "shapes.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res["calibration"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
