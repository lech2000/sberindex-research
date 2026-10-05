"""Банк детекторов D01 с ОБЩИМ бюджетом ложных тревог (ATF-M6, 02.10.2026; расширен 03.10.2026).

Банк = тревога, если сработал любой член. Члены (сигналы из d01_sensitive_signals):
  V0_last, V3_med3_cs, V4_med6_cs   правило D01 (два горячих месяца) на сигналах V0, V3, V4
  PHn@V3                            нормированный Page-Hinkley (delta = 0.5 rstd) на V3, как в d01_shock_shapes
  VOL@V3                            среднее |V3|/rstd за 3 последних месяца > k, как в d01_shock_shapes
  V1_last_cs                        правило D01 на V0 минус срез по (категория, месяц); стирает общие шоки (03.10)
Общий бюджет понимается строго: ложные тревоги считаются по ОБЪЕДИНЕНИЮ (после охлаждения по
рядам) на тестовых месяцах чистого сигнала и равны 24 или 96 в месяц, как у одиночных детекторов в
d01_sensitivity_curve. Пороги членов подбираются в заданных долях бюджета, общий масштаб t растёт,
пока объединение укладывается в бюджет (пересечения ложных тревог дают членам больше, чем F/число
членов).

Веса зафиксированы до запуска (метки событий не используются), порядок — MEMBERS:
  V0, V3, V4, PHn_V3, VOL_V3   одиночные детекторы с полным бюджетом (контроль, совпадают с d01_shock_shapes)
  B2_V0V3                      1/2 V0 + 1/2 V3                            (первая версия банка, 02.10)
  B3_equal                     1/3 V0 + 1/3 V3 + 1/3 V4                   (то же)
  B3_v3heavy                   1/4 V0 + 1/2 V3 + 1/4 V4                   (то же)
  B4_vol                       B3 + VOL@V3, по 1/4
  B4_ph                        B3 + PHn@V3, по 1/4
  B5_equal                     все пять, по 1/5
  V1, B2_V1V3, B3_V1_equal, B3_V1_v3heavy, B4_V1_vol   то же с V1 вместо V0 (03.10, задано до запуска)
  B4_V0V1                      V0, V1, V3, V4 по 1/4;  B5_V0V1_vol  V0, V1, V3, V4, VOL по 1/5

Формы шока те же и с теми же затравками, что в d01_shock_shapes: всплеск, сдвиг, рампа, рост
волатильности. Итоговые показатели: средний и минимальный recall по пяти представительным ячейкам,
заданным заранее (всплеск 30%/1 мес, сдвиг 30%/3 мес, рампа 30%/3 мес, рампа 30%/6 мес,
шум ×3/6 мес), и средний по всем 23 ячейкам.

Общие шоки (cspike, cshift): все ряды категории сдвигаются на 20% одновременно; событие = пара (категория,
месяц), recall = доля сдвинутых рядов с тревогой в окне -1..+1. Срез по категории их стирает, V0 нет.
Не входят в 23 ячейки, считаются отдельно.

Запуск: python3 d01_bank.py --clean-signal <плацебо signal.parquet> --outdir OUT [--self-check]
"""
import argparse
import hashlib
import json
import os

import numpy as np
import pandas as pd

try:
    from . import d01_sensitivity_curve as sc
    from . import d01_shock_shapes as sh
except ImportError:
    import d01_sensitivity_curve as sc
    import d01_shock_shapes as sh

SIGNALS = ("V0_last", "V3_med3_cs", "V4_med6_cs", "V1_last_cs")
MEMBER_SPECS = {  # член -> (тип детектора, сигнал)
    "V0_last": ("d01", "V0_last"),
    "V3_med3_cs": ("d01", "V3_med3_cs"),
    "V4_med6_cs": ("d01", "V4_med6_cs"),
    "PHn@V3": ("phn", "V3_med3_cs"),
    "VOL@V3": ("vol", "V3_med3_cs"),
    "V1_last_cs": ("d01", "V1_last_cs"),  # V0 минус срез по (категория, месяц); стирает общие шоки
}
MEMBERS = tuple(MEMBER_SPECS)
GRIDS = {"d01": sc.K_GRID, "vol": sc.K_GRID, "phn": sh.PHN_GRID}
def _w(**kw):
    """Доли бюджета в порядке MEMBERS по ключам V0, V3, V4, PH, VOL, V1."""
    key = {"V0": "V0_last", "V3": "V3_med3_cs", "V4": "V4_med6_cs", "PH": "PHn@V3", "VOL": "VOL@V3", "V1": "V1_last_cs"}
    w = {key[k]: v for k, v in kw.items()}
    return tuple(float(w.get(m, 0.0)) for m in MEMBERS)


BANKS = {  # доли бюджета в порядке MEMBERS
    "V0": _w(V0=1), "V3": _w(V3=1), "V4": _w(V4=1), "PHn_V3": _w(PH=1), "VOL_V3": _w(VOL=1),
    "B2_V0V3": _w(V0=0.5, V3=0.5),
    "B3_equal": _w(V0=1 / 3, V3=1 / 3, V4=1 / 3), "B3_v3heavy": _w(V0=0.25, V3=0.5, V4=0.25),
    "B4_vol": _w(V0=0.25, V3=0.25, V4=0.25, VOL=0.25), "B4_ph": _w(V0=0.25, V3=0.25, V4=0.25, PH=0.25),
    "B5_equal": _w(V0=0.2, V3=0.2, V4=0.2, PH=0.2, VOL=0.2),
    # 03.10.2026, задано до запуска: V1 вместо V0 и смеси V0 + V1 (V0 сохраняет видимость общих шоков)
    "V1": _w(V1=1),
    "B2_V1V3": _w(V1=0.5, V3=0.5),
    "B3_V1_equal": _w(V1=1 / 3, V3=1 / 3, V4=1 / 3), "B3_V1_v3heavy": _w(V1=0.25, V3=0.5, V4=0.25),
    "B4_V1_vol": _w(V1=0.25, V3=0.25, V4=0.25, VOL=0.25),
    "B4_V0V1": _w(V0=0.25, V1=0.25, V3=0.25, V4=0.25),
    "B5_V0V1_vol": _w(V0=0.2, V1=0.2, V3=0.2, V4=0.2, VOL=0.2),
}
FIRST_VERSION_BANKS = ("V0", "V3", "V4", "B2_V0V3", "B3_equal", "B3_v3heavy")  # их числа обязаны совпасть с 02.10
VOL_PH_BANKS = ("PHn_V3", "VOL_V3", "B4_vol", "B4_ph", "B5_equal")  # и с 03.10 (банк с монитором и ПХ)
FA_LEVELS = (24, 96)
SCALE_GRID = np.round(np.arange(1.0, 2.51, 0.02), 2)
REPRESENTATIVE = (("spike", "a0.30_L1"), ("shift", "a0.30_L3"), ("ramp", "a0.30_R3"),
                  ("ramp", "a0.30_R6"), ("vol", "m3.0_L6"))


# парные сравнения (разность recall на одних и тех же событиях): третий элемент — запланировано до запуска
PAIRS = (("B4_vol", "B3_equal", False), ("B4_ph", "B3_equal", False), ("B5_equal", "B3_equal", False),
         ("VOL_V3", "B3_equal", True),  # True = добавлено ПОСЛЕ просмотра таблицы recall
         # 03.10.2026, задано до запуска банка с V1: основные три, затем справочные
         ("B3_V1_equal", "B3_equal", False), ("B4_V1_vol", "B4_vol", False), ("B2_V1V3", "B2_V0V3", False),
         ("B4_V0V1", "B3_equal", False), ("B5_V0V1_vol", "B4_vol", False),
         ("B3_V1_equal", "V3", False), ("B4_V1_vol", "VOL_V3", False),
         # добавлены ПОСЛЕ просмотра таблицы recall банков с V1
         ("B4_V1_vol", "B3_V1_equal", True), ("B3_V1_equal", "VOL_V3", True))


# общие шоки: все ряды одной категории сдвигаются одновременно (срез по категории и месяцу такое стирает)
COMMON_SHOCKS = (("cspike", 0.20, 1), ("cshift", 0.20, 3))


def inject_common(panel, cat, onset, amp, L, sign):
    """Все полные ряды категории cat умножаются на (1 + sign*amp) в месяцах onset..onset+L-1."""
    rows = np.flatnonzero((panel.cats == cat) & np.isfinite(panel.X).all(axis=1))
    X = panel.X.copy()
    X[rows, onset:onset + L] *= 1.0 + sign * amp
    return X, rows


def event_hits(alarm, rows, onsets, lo, hi, T):
    """Булев вектор «событие обнаружено»: то же окно, что в d01_shock_shapes.score_events."""
    out = np.zeros(len(rows), dtype=bool)
    for i, (r, o) in enumerate(zip(rows, onsets)):
        a = max(0, int(o) + lo)
        b = T - 1 if hi is None else min(T - 1, int(o) + hi)
        out[i] = bool(alarm[r, a:b + 1].any())
    return out


def paired_diff(a, b):
    """Разность долей a - b на одних событиях и её дисперсия (парная схема, McNemar)."""
    n = len(a)
    p10, p01 = float(np.sum(a & ~b)) / n, float(np.sum(~a & b)) / n
    return float(a.mean() - b.mean()), (p10 + p01 - (p10 - p01) ** 2) / n


def _ci(diff, var):
    h = 1.96 * np.sqrt(var)
    return {"diff": round(diff, 4), "ci95": [round(diff - h, 4), round(diff + h, 4)]}


def paired_summary(store):
    """store[fa][(shape, key)][bank] = bool-вектор. Среднее по ячейкам: ячейки считаются независимыми."""
    out = {}
    for fa, cells in store.items():
        out[fa] = {}
        for first, second, post_hoc in PAIRS:
            dv = {cell: paired_diff(banks[first], banks[second]) for cell, banks in cells.items()}

            def mean_ci(keys):
                d = [dv[c][0] for c in keys]
                v = [dv[c][1] for c in keys]
                return _ci(float(np.mean(d)), float(np.sum(v)) / len(keys) ** 2)

            cells_ci = {"%s/%s" % c: _ci(*dv[c]) for c in dv}
            out[fa]["%s_vs_%s" % (first, second)] = {
                "post_hoc": post_hoc,
                "cells_significantly_higher": sum(1 for v in cells_ci.values() if v["ci95"][0] > 0),
                "cells_significantly_lower": sum(1 for v in cells_ci.values() if v["ci95"][1] < 0),
                "cells": cells_ci,
                "mean_representative": mean_ci([c for c in dv if c in REPRESENTATIVE]),
                "mean_all_cells": mean_ci(list(dv)),
            }
    return out


def member_alarm(panel, member, S_by_signal, p, rstd=None):
    """Тревоги члена с параметром p на матрицах сигналов S_by_signal (rstd — по умолчанию из этих же сигналов)."""
    kind, sig = MEMBER_SPECS[member]
    S = S_by_signal[sig]
    r = panel.rstd(S) if rstd is None else rstd
    if kind == "d01":
        return sc.d01_alarm_matrix(S, r, p)
    if kind == "phn":
        return sh.ph_alarm_matrix(S / r[:, None], sh.PHN_DELTA, p)
    return sh.vol_alarm_matrix(S, r, p)


class Calibrator:
    """Кэш тревог чистого сигнала по сетке порогов и подбор банка под общий бюджет."""

    def __init__(self, panel):
        self.panel = panel
        self.clean = {v: panel.signal(panel.X, v) for v in SIGNALS}
        self.rstd = {v: panel.rstd(self.clean[v]) for v in SIGNALS}
        self.test_cols = {j for ym, j in panel.col.items() if ym >= sc.SPLIT}
        self.months = len(self.test_cols)
        self.A, self.cnt = {}, {}
        for m in MEMBERS:
            kind, sig = MEMBER_SPECS[m]
            for p in GRIDS[kind]:
                a = member_alarm(panel, m, self.clean, float(p), self.rstd[sig])
                self.A[(m, float(p))] = a
                self.cnt[(m, float(p))] = sc.cooled_count(a, self.test_cols)

    def member_k(self, m, per_month):
        for p in GRIDS[MEMBER_SPECS[m][0]]:
            if self.cnt[(m, float(p))] <= per_month * self.months:
                return float(p)
        raise RuntimeError("порог не найден: %s" % m)

    def union_count(self, ks):
        acc = None
        for v, k in ks.items():
            a = self.A[(v, k)]
            acc = a.copy() if acc is None else (acc | a)
        return sc.cooled_count(acc, self.test_cols)

    def bank(self, weights, fa):
        active = [(v, w) for v, w in zip(MEMBERS, weights) if w > 0]
        if len(active) == 1:
            ks = {active[0][0]: self.member_k(active[0][0], fa)}
            scale = 1.0
        else:
            best = None
            for t in SCALE_GRID:
                ks = {v: self.member_k(v, w * fa * float(t)) for v, w in active}
                if self.union_count(ks) <= fa * self.months:
                    best = (dict(ks), float(t))
            ks, scale = best
        union_fa = self.union_count(ks) / self.months
        members_fa = {v: round(self.cnt[(v, k)] / self.months, 1) for v, k in ks.items()}
        return {"k": ks, "scale": scale, "union_false_alarms_per_test_month": round(union_fa, 1),
                "members_false_alarms_per_test_month": members_fa}


def bank_alarm(panel, S_by_signal, ks, cache=None):
    """Объединение тревог членов; cache (dict) хранит тревоги (член, порог) для одного набора сигналов."""
    acc = None
    for m, p in ks.items():
        if cache is None:
            a = member_alarm(panel, m, S_by_signal, p)
        else:
            if (m, p) not in cache:
                cache[(m, p)] = member_alarm(panel, m, S_by_signal, p)
            a = cache[(m, p)]
        acc = a if acc is None else (acc | a)
    return acc


def run(panel, seed, n_events=sh.N_EVENTS):
    cal = Calibrator(panel)
    sigma_lvl = panel.rstd(cal.clean["V0_last"]) / np.sqrt(2.0)
    plan = {fa: {name: cal.bank(w, fa) for name, w in BANKS.items()} for fa in FA_LEVELS}
    res = {"calibration": {str(fa): plan[fa] for fa in FA_LEVELS}, "cells": {}}
    T = panel.T
    store = {str(fa): {} for fa in FA_LEVELS}

    def evaluate(shape, key, X, rows, onsets, window):
        S = {v: panel.signal(X, v) for v in SIGNALS}
        cache = {}
        for fa in FA_LEVELS:
            for name in BANKS:
                alarm = bank_alarm(panel, S, plan[fa][name]["k"], cache)
                hits, delays = sh.score_events(alarm, rows, onsets, window[0], window[1], T)
                vec = event_hits(alarm, rows, onsets, window[0], window[1], T)
                assert int(vec.sum()) == hits
                store[str(fa)].setdefault((shape, key), {})[name] = vec
                res["cells"].setdefault(shape, {}).setdefault(str(fa), {}).setdefault(name, {})[key] = \
                    sh.cell_record(hits, len(rows), delays)

    for i, (shape, amp, L) in enumerate((("spike", 0.30, 1), ("shift", 0.20, 3), ("shift", 0.30, 3))):
        rng = np.random.default_rng(seed + 10 + i)
        X, rows, onsets = sc.inject(panel, rng, amp, L, n_events)
        evaluate(shape, "a%.2f_L%d" % (amp, L), X, rows, onsets, (-1, 1))
    for i, amp in enumerate(sh.RAMP_AMPS):
        for j, R in enumerate(sh.RAMP_LENS):
            rng = np.random.default_rng(seed + 100 + 10 * i + j)
            X, rows, onsets = sh.inject_ramp(panel, rng, amp, R, n_events)
            evaluate("ramp", "a%.2f_R%d" % (amp, R), X, rows, onsets, (0, R))
    for i, m in enumerate(sh.VOL_MULTS):
        for j, L in enumerate(sh.VOL_LENS):
            rng = np.random.default_rng(seed + 200 + 10 * i + j)
            X, rows, onsets = sh.inject_vol(panel, rng, m, L, n_events, sigma_lvl)
            evaluate("vol", "m%.1f_L%d" % (m, L), X, rows, onsets, (0, L))
    # общие шоки: событие = пара (категория, месяц начала), recall = доля сдвинутых рядов с тревогой в окне -1..+1
    common = {}
    for cname, amp, L in COMMON_SHOCKS:
        pairs = [(c, o) for c in np.unique(panel.cats) for o in range(panel.col[sc.SPLIT], T - L + 1)]
        rec = {str(fa): {name: [] for name in BANKS} for fa in FA_LEVELS}
        for i, (c, o) in enumerate(pairs):
            X, rows = inject_common(panel, c, o, amp, L, 1.0 if i % 2 == 0 else -1.0)
            S = {v: panel.signal(X, v) for v in SIGNALS}
            cache = {}
            for fa in FA_LEVELS:
                for name in BANKS:
                    alarm = bank_alarm(panel, S, plan[fa][name]["k"], cache)
                    rec[str(fa)][name].append(float(event_hits(alarm, rows, np.full(len(rows), o), -1, 1, T).mean()))
        common[cname] = {"amp": amp, "length": L, "pairs": len(pairs), "recall_by_pair": rec}
    res["common"] = common_summary(common)
    # плацебо: события без инжекта, окно 5 месяцев
    rng = np.random.default_rng(seed + 300)
    complete = np.flatnonzero(np.isfinite(panel.X).all(axis=1))
    rows = rng.choice(complete, size=n_events, replace=False)
    onsets = rng.integers(panel.col[sc.SPLIT], panel.T - 3, size=n_events)
    for fa in FA_LEVELS:
        for name in BANKS:
            acc = None
            for v, k in plan[fa][name]["k"].items():
                acc = cal.A[(v, k)] if acc is None else (acc | cal.A[(v, k)])
            hits, delays = sh.score_events(acc, rows, onsets, 0, 4, T)
            res["cells"].setdefault("placebo", {}).setdefault(str(fa), {}).setdefault(name, {})["window5"] = \
                sh.cell_record(hits, len(rows), delays)
    res["summary"] = summarize(res)
    res["paired"] = paired_summary(store)
    return res


def common_summary(common):
    """Средний recall по парам (категория, месяц) и парные разности банков (t-интервал по парам)."""
    out = {}
    for cname, c in common.items():
        out[cname] = {"amp": c["amp"], "length": c["length"], "pairs": c["pairs"], "mean_recall": {}, "paired": {}}
        for fa, banks in c["recall_by_pair"].items():
            out[cname]["mean_recall"][fa] = {b: round(float(np.mean(v)), 3) for b, v in banks.items()}
            out[cname]["paired"][fa] = {}
            for first, second, _ in PAIRS:
                d = np.array(banks[first]) - np.array(banks[second])
                h = 1.96 * float(d.std(ddof=1)) / np.sqrt(len(d))
                out[cname]["paired"][fa]["%s_vs_%s" % (first, second)] = {
                    "diff": round(float(d.mean()), 4), "ci95": [round(float(d.mean()) - h, 4), round(float(d.mean()) + h, 4)]}
    return out


def summarize(res):
    out = {}
    for fa in res["calibration"]:
        out[fa] = {}
        for name in BANKS:
            rep = [res["cells"][s][fa][name][k]["recall"] for s, k in REPRESENTATIVE]
            allc = [rec["recall"] for shape in ("spike", "shift", "ramp", "vol")
                    for rec in res["cells"][shape][fa][name].values()]
            out[fa][name] = {"representative_mean": round(float(np.mean(rep)), 3),
                             "representative_min": round(float(np.min(rep)), 3),
                             "all_cells_mean": round(float(np.mean(allc)), 3), "n_cells": len(allc)}
    return out


def self_check():
    """Объединение укладывается в общий бюджет, а рост масштаба сверх найденного бюджет превышает."""
    rng = np.random.default_rng(4)
    rows = []
    for tid in range(300):
        x = 1000.0 * np.exp(rng.normal(0.0, 0.04, 24))
        for k in range(1, 24):
            ym = "%04d-%02d" % (2023 + k // 12, k % 12 + 1)
            rows.append({"tid": tid, "cat": "a" if tid % 2 == 0 else "b", "ym": ym,
                         "actual_inj": float(x[k]), "pred": float(x[k - 1]), "rel": float(x[k] / x[k - 1] - 1)})
    panel = sc.Panel(pd.DataFrame(rows))
    cal = Calibrator(panel)
    b = cal.bank(BANKS["B3_equal"], 6)
    assert b["union_false_alarms_per_test_month"] <= 6.0, b
    assert b["scale"] >= 1.0
    print(json.dumps({"bank_union_within_budget": True, "scale": b["scale"], "union": b["union_false_alarms_per_test_month"]}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--clean-signal")
    p.add_argument("--outdir")
    p.add_argument("--n-events", type=int, default=sh.N_EVENTS)
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
    res["meta"] = {"seed": a.seed, "n_events_per_cell": a.n_events, "fa_levels": FA_LEVELS,
                   "members": MEMBERS, "banks": {k: list(v) for k, v in BANKS.items()},
                   "paired_comparisons": [list(p) for p in PAIRS], "representative_cells": REPRESENTATIVE,
                   "common_shocks": [list(c) for c in COMMON_SHOCKS],
                   "clean_signal_sha256": hashlib.sha256(open(a.clean_signal, "rb").read()).hexdigest()}
    json.dump(res, open(os.path.join(a.outdir, "bank.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(res["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
