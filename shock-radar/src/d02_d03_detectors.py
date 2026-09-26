"""R7: D02 (causal CUSUM / Page-Hinkley) и D03 (Bayesian online changepoint)
против D01 на том же реестре из 60 синтетических событий.

Протокол общий для всех трёх методов: тот же реестр, тот же сплит
(validation: onset < 2024-07, test: onset >= 2024-07), то же matching
(окно ±1 мес, cooldown 3 мес на ряд, одна тревога — одному событию).
Validation считает тревоги СТРОГО в [train_end, split): period_end
исключительный, тестовые месяцы в validation-метрики и в matching
не попадают никогда. Общий бюджет тревог: cooldown сначала, затем
обрезка до бюджета только на тревогах тест-периода (train-период
в бюджет не входит). Бюджет по умолчанию выводится из validation:
D01 alarm rate на выбранном пороге × число тестовых месяцев (только
досплитовые свидетельства, без числа тестовых событий и тестовых
тревог); явный --budget перекрывает вывод. Формула и ограничения
фиксируются в manifest.
Пороги подбираются ТОЛЬКО на validation. Метрики: precision, recall,
false alarms, знаковый delay и lead time.

Честная оговорка: события синтетические (инжект известного сдвига),
поэтому это технический тест детекции, а не заявление о реальном раннем
предупреждении. Тревога в месяц onset или позже — детекция с лагом.

Вход:  R5_cus.parquet (колонки tid, cat, ym, сигнал rel/cus),
        events/registry.parquet (event_id, tid, cat, onset, ...).
Выход: <outdir>/manifest.json, metrics.json, alerts.parquet.

Модуль unit-safe: импорт не трогает файлы и argv; `python
d02_d03_detectors.py --self-check` прогоняет все детекторы и скоринг на
синтетике в памяти без входных файлов.

Режимы бюджета (--budget-mode):
- legacy (default): прежнее поведение — общий бюджет на весь тест
  budget = round(D01_val_rate * n_test_months), обрезка top scores по всей
  тестовой истории. Старые runs воспроизводятся без изменений метрик.
- monthly_causal: онлайн-правило — месячный бюджет
  round(D01 validation cooled alarms / n_val_months), минимум 0, без подбора
  на тесте; cooldown, затем обработка строго хронологически, ранжирование
  только внутри текущего месяца (без отбора top scores всей истории).
  Общий бюджет и matching одинаковы для всех трёх методов.
"""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone

try:
    import numpy as np
except ImportError:
    np = None
try:
    import pandas as pd
except ImportError:
    pd = None


def _require():
    if np is None or pd is None:
        raise RuntimeError("d02_d03_detectors needs numpy+pandas to run; "
                           "import alone is dependency-free")

SEED = 20260923
SPLIT = "2024-07"
TRAIN_END = "2024-03"
MATCH_WINDOW = 1
COOLDOWN_M = 3

D01_GRID = (2.0, 2.5, 3.0, 3.5, 4.0)
D02_DELTA_GRID = (0.02, 0.05, 0.10)
D02_LAMBDA_GRID = (0.05, 0.10, 0.20, 0.40)
D03_TAU_GRID = (0.30, 0.50, 0.70, 0.90)
D03_HAZARD = 1.0 / 50.0
D03_N0 = 10.0
D03_RMAX = 24

SIGNAL_CANDIDATES = ("rel", "cus", "resid", "z")


def month_diff(a, b):
    return (pd.Period(a, freq="M") - pd.Period(b, freq="M")).n


def signal_column(det):
    for c in SIGNAL_CANDIDATES:
        if c in det.columns:
            return c
    raise KeyError("no signal column, tried %s" % (list(SIGNAL_CANDIDATES),))


def _mad(s):
    s = pd.Series(np.asarray(s, dtype=float))
    s = s[np.isfinite(s.values)]
    if len(s) == 0:
        return float("nan")
    return float((s - s.median()).abs().median() * 1.4826)


def d01_alarms(det, signal, k, train_end=TRAIN_END):
    _require()
    det = det.sort_values(["tid", "cat", "ym"]).reset_index(drop=True)
    train = det[det["ym"] < train_end]
    std_map = train.groupby(["tid", "cat"])[signal].agg(_mad)
    rstd = det.set_index(["tid", "cat"]).index.map(std_map)
    rstd = pd.to_numeric(rstd, errors="coerce")
    rstd = np.where(~np.isfinite(rstd) | (rstd == 0), 0.05, rstd)
    out = det[["tid", "cat", "ym"]].copy()
    out["score"] = det[signal].abs().to_numpy() / rstd
    out["hot"] = out["score"].to_numpy() > k
    hot = out["hot"].to_numpy()
    prev_hot = np.zeros(len(det), dtype=bool)
    for _, idx in det.groupby(["tid", "cat"]).groups.items():
        pos = det.index.get_indexer_for(idx)
        pos = np.sort(pos)
        prev_hot[pos[1:]] = hot[pos[:-1]]
    out["alarm"] = out["hot"].to_numpy() & prev_hot
    out["method"] = "D01"
    return out[out["alarm"]][["method", "tid", "cat", "ym", "score"]].reset_index(drop=True)


def d02_alarms(det, signal, delta, lam):
    _require()
    rows = []
    det = det.sort_values(["tid", "cat", "ym"]).reset_index(drop=True)
    for (_, _), g in det.groupby(["tid", "cat"]):
        g = g.sort_values("ym").reset_index(drop=True)
        x = g[signal].to_numpy(dtype=float)
        run_sum = 0.0
        run_n = 0
        s_pos = 0.0
        s_neg = 0.0
        m_pos = 0.0
        m_neg = 0.0
        for t, v in enumerate(x):
            if not np.isfinite(v):
                continue
            mu = run_sum / run_n if run_n else v
            s_pos += v - mu - delta
            m_pos = min(m_pos, s_pos)
            s_neg += mu - v - delta
            m_neg = min(m_neg, s_neg)
            ph = max(s_pos - m_pos, s_neg - m_neg)
            run_sum += v
            run_n += 1
            if run_n > 1 and ph > lam:
                rows.append({"method": "D02", "tid": g["tid"].iloc[t],
                             "cat": g["cat"].iloc[t], "ym": g["ym"].iloc[t],
                             "score": float(ph)})
                s_pos = 0.0
                s_neg = 0.0
                m_pos = 0.0
                m_neg = 0.0
                run_sum = 0.0
                run_n = 0
    cols = ["method", "tid", "cat", "ym", "score"]
    if not rows:
        return _empty_alarms()
    return pd.DataFrame(rows, columns=cols)


def _logsumexp(a):
    m = np.max(a)
    if not np.isfinite(m):
        return float("-inf")
    return float(m + np.log(np.sum(np.exp(a - m))))


def _empty_alarms():
    return pd.DataFrame({
        "method": pd.Series(dtype="object"),
        "tid": pd.Series(dtype="object"),
        "cat": pd.Series(dtype="object"),
        "ym": pd.Series(dtype="object"),
        "score": pd.Series(dtype="float64"),
    })


def _logr_is_bad(new_logr, strict_log_support=False):
    if strict_log_support:
        if np.any(np.isnan(new_logr)):
            return True
        if np.any(new_logr == np.inf):
            return True
        return not np.any(np.isfinite(new_logr))
    return not np.all(np.isfinite(new_logr))


def _bocd_cp_prob(x, mu0, var, hazard, n0, rmax, strict_log_support=False):
    x = np.asarray(x, dtype=float)
    if not np.isfinite(mu0):
        mu0 = 0.0
    if not np.isfinite(var) or var <= 0:
        var = 1e-6
    var = float(max(var, 1e-9))
    hazard = float(hazard)
    if not np.isfinite(hazard) or hazard <= 0.0 or hazard >= 1.0:
        hazard = min(max(hazard if np.isfinite(hazard) else 1.0 / 50.0,
                         1e-6), 1.0 - 1e-6)
    logh = float(np.log(hazard))
    log1mh = float(np.log1p(-hazard))
    logr = np.full(rmax + 1, -np.inf)
    logr[0] = 0.0
    sums = np.full(rmax + 1, mu0 * n0)
    cnts = np.full(rmax + 1, n0)
    out = np.zeros(len(x))
    for t in range(len(x)):
        v = x[t]
        if not np.isfinite(v):
            v = mu0
        mu = sums / cnts
        s2 = var * (1.0 + 1.0 / cnts)
        ll = -0.5 * (np.log(2.0 * np.pi * s2) + (v - mu) ** 2 / s2)
        s2_prior = var * (1.0 + 1.0 / n0)
        ll_prior = float(-0.5 * (np.log(2.0 * np.pi * s2_prior)
                                 + (v - mu0) ** 2 / s2_prior))
        if not np.all(np.isfinite(ll)) or not np.isfinite(ll_prior):
            p_prev = float(np.exp(logr[0]))
            out[t] = p_prev if np.isfinite(p_prev) else 0.0
            continue
        new_logr = np.full(rmax + 1, -np.inf)
        new_logr[1:] = logr[:-1] + ll[:-1] + log1mh
        extra = logr[rmax] + ll[rmax] + log1mh
        new_logr[rmax] = np.logaddexp(new_logr[rmax], extra)
        new_logr[0] = _logsumexp(logr) + ll_prior + logh
        norm = _logsumexp(new_logr)
        if not np.isfinite(norm):
            new_logr = np.full(rmax + 1, -np.inf)
            new_logr[0] = 0.0
        else:
            new_logr = new_logr - norm
        if _logr_is_bad(new_logr, strict_log_support):
            new_logr = np.full(rmax + 1, -np.inf)
            new_logr[0] = 0.0
        new_sums = np.empty(rmax + 1)
        new_cnts = np.empty(rmax + 1)
        new_sums[1:] = sums[:-1] + v
        new_cnts[1:] = cnts[:-1] + 1.0
        new_sums[0] = mu0 * n0 + v
        new_cnts[0] = n0 + 1.0
        logr, sums, cnts = new_logr, new_sums, new_cnts
        p = float(np.exp(logr[0]))
        out[t] = p if np.isfinite(p) else 0.0
    return np.clip(out, 0.0, 1.0)


def d03_alarms(det, signal, tau, hazard=D03_HAZARD, n0=D03_N0,
               rmax=D03_RMAX, train_end=TRAIN_END, strict_log_support=False):
    _require()
    rows = []
    det = det.sort_values(["tid", "cat", "ym"]).reset_index(drop=True)
    for (_, _), g in det.groupby(["tid", "cat"]):
        g = g.sort_values("ym").reset_index(drop=True)
        x = g[signal].to_numpy(dtype=float)
        mask = np.isfinite(x)
        tr = x[(g["ym"] < train_end).to_numpy() & mask]
        if len(tr) >= 3:
            mu0 = float(np.mean(tr))
            var = float(max(np.var(tr), 1e-6))
        elif np.any(mask):
            mu0 = float(x[mask][0])
            var = float(max((0.05 * abs(mu0)) ** 2, 1e-6))
        else:
            continue
        cp = _bocd_cp_prob(np.where(mask, x, mu0), mu0, var, hazard, n0,
                           rmax, strict_log_support=strict_log_support)
        for t in range(len(g)):
            if not mask[t]:
                continue
            if cp[t] > tau:
                rows.append({"method": "D03", "tid": g["tid"].iloc[t],
                             "cat": g["cat"].iloc[t], "ym": g["ym"].iloc[t],
                             "score": float(cp[t])})
                mu0 = float(x[t])
                if t + 1 < len(g):
                    cp[t + 1:] = _bocd_cp_prob(
                        np.where(mask[t + 1:], x[t + 1:], mu0), mu0, var,
                        hazard, n0, rmax,
                        strict_log_support=strict_log_support)
    cols = ["method", "tid", "cat", "ym", "score"]
    if not rows:
        return _empty_alarms()
    return pd.DataFrame(rows, columns=cols)


def apply_cooldown(alarms, cooldown_m=COOLDOWN_M):
    if len(alarms) == 0:
        return alarms
    keep = []
    a = alarms.sort_values(["method", "tid", "cat", "ym"]).reset_index(drop=True)
    for (_, _, _), g in a.groupby(["method", "tid", "cat"]):
        g = g.sort_values("ym")
        last = None
        for _, r in g.iterrows():
            if last is None or month_diff(r["ym"], last) >= cooldown_m:
                keep.append(r)
                last = r["ym"]
    if not keep:
        return a.iloc[0:0]
    return pd.DataFrame(keep).sort_values(
        ["method", "tid", "cat", "ym"]).reset_index(drop=True)


def truncate_budget(alarms, budget):
    if budget is None or len(alarms) <= budget:
        return alarms
    a = alarms.sort_values(["score", "ym", "tid", "cat"],
                           ascending=[False, True, True, True])
    return a.head(budget).sort_values(
        ["tid", "cat", "ym"]).reset_index(drop=True)


def truncate_budget_monthly(alarms, monthly_budget):
    """Онлайн-бюджет: обработка строго хронологически, ранжирование только
    внутри текущего месяца. Тревоги будущих месяцев никогда не вытесняют
    тревоги текущего (future-prefix invariance). monthly_budget <= 0 —
    пустой результат. Возвращает охлаждённые-в-маске тревоги метки split
    без изменений состава внутри месяца, кроме top-k по score."""
    if monthly_budget is None or monthly_budget <= 0 or len(alarms) == 0:
        return alarms.iloc[0:0] if len(alarms) == 0 else alarms.iloc[0:0].copy()
    a = alarms.sort_values(["ym", "score", "tid", "cat"],
                           ascending=[True, False, True, True])
    kept = []
    for _, g in a.groupby("ym", sort=True):
        kept.append(g.head(int(monthly_budget)))
    if not kept:
        return alarms.iloc[0:0]
    return pd.concat(kept, ignore_index=True).sort_values(
        ["tid", "cat", "ym"]).reset_index(drop=True)


def evaluate(alarms, reg, period_start, period_end=None, window=1,
              cooldown_m=COOLDOWN_M, already_cooled=False):
    if not already_cooled:
        alarms = apply_cooldown(alarms, cooldown_m)
    if len(alarms) == 0:
        pin = alarms
    elif period_end is None:
        pin = alarms[alarms["ym"] >= period_start].copy()
    else:
        pin = alarms[(alarms["ym"] >= period_start)
                     & (alarms["ym"] < period_end)].copy()
    hits = 0
    delays = []
    used = set()
    match_rows = []
    for _, e in reg.iterrows():
        cand = pin[(pin["tid"] == e["tid"]) & (pin["cat"] == e["cat"])]
        best = None
        for _, a in cand.iterrows():
            akey = (a["tid"], a["cat"], a["ym"])
            if akey in used:
                continue
            d = month_diff(a["ym"], e["onset"])
            if abs(d) <= window:
                srt = (abs(d), d, str(a["ym"]))
                if best is None or srt < best[0]:
                    best = (srt, a, d, akey)
        if best is not None:
            _, a, d, akey = best
            hits += 1
            delays.append(d)
            used.add(akey)
            match_rows.append({"event_id": e["event_id"], "tid": e["tid"],
                               "cat": e["cat"], "alarm_ym": a["ym"],
                               "delay_m": d})
    n_period = len(pin)
    fa = n_period - len(used)
    delays = [int(d) for d in delays]
    early = [-d for d in delays if d < 0]
    return {"events": int(len(reg)),
            "alarms": int(n_period),
            "hits": int(hits),
            "recall": round(hits / len(reg), 3) if len(reg) else None,
            "precision": round(hits / n_period, 4) if n_period else 0.0,
            "false_alarms": int(fa),
            "delay_signed_mean": round(float(np.mean(delays)), 2) if delays else None,
            "delay_abs_mean": round(float(np.mean([abs(d) for d in delays])), 2) if delays else None,
            "lead_mean_m": round(float(np.mean(early)), 2) if early else 0.0,
            "frac_early": round(len(early) / hits, 3) if hits else 0.0,
            "matches": match_rows}


def _threshold_sort_key(th):
    if isinstance(th, (tuple, list)):
        vals = tuple(float(v) for v in th)
    else:
        vals = (float(th),)
    return tuple(-v for v in vals)


def _fit_grid(make_alarms, det, signal, reg_val, val_from, grid,
               period_end=None):
    scored = []
    for th in grid:
        al = make_alarms(det, signal, th)
        m = evaluate(al, reg_val, val_from, period_end)
        f1 = 0.0
        if (m["precision"] or 0) + (m["recall"] or 0) > 0:
            f1 = 2 * m["precision"] * m["recall"] / (m["precision"] + m["recall"])
        scored.append((round(f1, 4), -m["false_alarms"], th, m))
    scored.sort(key=lambda r: (r[0], r[1], _threshold_sort_key(r[2])),
                reverse=True)
    return scored[0][2], scored[0][3], [
        {"threshold": th, "f1": f1, "metrics": m} for f1, _, th, m in scored]


def _sha256(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip() or None
    except Exception:
        return None


def run(cus_path, reg_path, outdir, seed=SEED, split=SPLIT,
        train_end=TRAIN_END, window=MATCH_WINDOW, cooldown_m=COOLDOWN_M,
        budget=None, budget_mode="legacy"):
    _require()
    import os
    if budget_mode not in ("legacy", "monthly_causal"):
        raise ValueError("budget_mode must be 'legacy' or 'monthly_causal'")
    rng = np.random.default_rng(seed)
    _ = rng
    det = pd.read_parquet(cus_path)
    reg = pd.read_parquet(reg_path)
    for col in ("tid", "cat", "ym"):
        if col not in det.columns:
            raise KeyError("R5_cus misses column %r" % col)
    for col in ("event_id", "tid", "cat", "onset"):
        if col not in reg.columns:
            raise KeyError("registry misses column %r" % col)
    det = det.sort_values(["tid", "cat", "ym"]).reset_index(drop=True)
    reg = reg.sort_values("onset").reset_index(drop=True)
    signal = signal_column(det)
    reg_val = reg[reg["onset"] < split].reset_index(drop=True)
    reg_test = reg[reg["onset"] >= split].reset_index(drop=True)

    det_months = sorted(det["ym"].unique())
    val_months = [m for m in det_months if train_end <= m < split]
    test_months = [m for m in det_months if m >= split]
    has_pretrain = bool((det["ym"] < train_end).any())

    k_best, _, d01_val_trials = _fit_grid(
        lambda d, s, th: d01_alarms(d, s, th, train_end),
        det, signal, reg_val, train_end, D01_GRID, split)
    dl_best, _, d02_val_trials = _fit_grid(
        lambda d, s, th: d02_alarms(d, s, th[0], th[1]),
        det, signal, reg_val, train_end,
        [(dl, l) for dl in D02_DELTA_GRID for l in D02_LAMBDA_GRID], split)
    d03_strict = (budget_mode == "monthly_causal")
    tau_best, _, d03_val_trials = _fit_grid(
        lambda d, s, th: d03_alarms(
            d, s, th, train_end=train_end, strict_log_support=d03_strict),
        det, signal, reg_val, train_end, D03_TAU_GRID, split)

    fitted = {"D01": {"k": k_best},
              "D02": {"delta": dl_best[0], "lambda": dl_best[1]},
              "D03": {"tau": tau_best}}
    d01_val_cooled = apply_cooldown(d01_alarms(det, signal, k_best, train_end),
                                    cooldown_m)
    if len(d01_val_cooled):
        d01_val_n = int(len(d01_val_cooled[
            (d01_val_cooled["ym"] >= train_end)
            & (d01_val_cooled["ym"] < split)]))
    else:
        d01_val_n = 0
    d01_val_rate = (d01_val_n / len(val_months)) if val_months else 0.0
    budget_derived = int(round(d01_val_rate * len(test_months)))
    monthly_derived = int(round(d01_val_rate)) if val_months else 0
    monthly_derived = max(monthly_derived, 0)
    if budget_mode == "legacy":
        if budget is None:
            budget = budget_derived
            budget_source = "derived"
        else:
            budget = int(budget)
            budget_source = "explicit --budget override"
        monthly_budget = None
    else:
        if budget is None:
            monthly_budget = monthly_derived
            budget_source = ("derived monthly_causal: round(D01_val_cooled "
                             "alarms / n_val_months)")
        else:
            monthly_budget = max(int(budget), 0)
            budget_source = "explicit --budget override (monthly budget)"
        budget = int(monthly_budget) * len(test_months)
    raw_test = {
        "D01": d01_alarms(det, signal, k_best, train_end),
        "D02": d02_alarms(det, signal, dl_best[0], dl_best[1]),
        "D03": d03_alarms(det, signal, tau_best, train_end=train_end,
                         strict_log_support=d03_strict),
    }
    test_alarms = {}
    for m, a in raw_test.items():
        cooled = apply_cooldown(a, cooldown_m)
        period = cooled[cooled["ym"] >= split].copy() if len(cooled) else cooled
        if budget_mode == "legacy":
            test_alarms[m] = truncate_budget(period, budget)
        else:
            test_alarms[m] = truncate_budget_monthly(period, monthly_budget)
    val_metrics = {
        "D01": evaluate(d01_alarms(det, signal, k_best, train_end),
                        reg_val, train_end, split, window, cooldown_m),
        "D02": evaluate(d02_alarms(det, signal, dl_best[0], dl_best[1]),
                        reg_val, train_end, split, window, cooldown_m),
        "D03": evaluate(d03_alarms(det, signal, tau_best,
                                   train_end=train_end,
                                   strict_log_support=d03_strict),
                        reg_val, train_end, split, window, cooldown_m),
    }
    test_metrics = {m: evaluate(a, reg_test, split, window=window,
                                cooldown_m=cooldown_m, already_cooled=True)
                    for m, a in test_alarms.items()}
    for m in test_metrics:
        test_metrics[m]["budget"] = int(budget)

    os.makedirs(outdir, exist_ok=True)
    frames = []
    for m, a in test_alarms.items():
        mm = test_metrics[m]
        ev_by_alarm = {}
        for row in mm["matches"]:
            ev_by_alarm[(row["tid"], row["cat"],
                         row["alarm_ym"])] = (row["event_id"], row["delay_m"])
        b = a.copy()
        keys = list(zip(b["tid"], b["cat"], b["ym"])) if len(b) else []
        b["event_id"] = [ev_by_alarm.get(k, (None, None))[0] for k in keys]
        b["delay_m"] = [ev_by_alarm.get(k, (None, None))[1] for k in keys]
        frames.append(b)
    alerts = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["method", "tid", "cat", "ym", "score", "event_id", "delay_m"])
    alerts_path = os.path.join(outdir, "alerts.parquet")
    try:
        alerts.to_parquet(alerts_path, index=False)
    except Exception:
        alerts.to_csv(os.path.join(outdir, "alerts.csv"), index=False)

    det_n_rows = int(len(det))
    if not has_pretrain:
        limitation = ("data limitation: input panel starts at/after train_end "
                      "%s — train stats use in-period fallback, pre-split "
                      "calibration has only %d validation months" %
                      (train_end, len(val_months)))
    elif len(val_months) < 3:
        limitation = ("data limitation: only %d validation months in "
                      "[%s, %s) — D01 alarm-rate estimate is noisy" %
                      (len(val_months), train_end, split))
    else:
        limitation = None
    manifest = {
        "experiment_id": "R7-d02-d03-vs-d01",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "seed": int(seed),
        "inputs": {"R5_cus": cus_path, "R5_cus_sha256": _sha256(cus_path),
                   "registry": reg_path, "registry_sha256": _sha256(reg_path),
                   "n_rows": det_n_rows},
        "signal_column": signal,
        "registry_events": int(len(reg)),
        "registry_is_60": bool(len(reg) == 60),
        "split": {"validation": "onset < %s" % split,
                  "test": "onset >= %s" % split,
                  "train_stats_end": train_end,
                  "validation_alarm_window": "[%s, %s) exclusive end" %
                  (train_end, split),
                  "no_test_leakage": True},
        "matching": {"window_m": window, "cooldown_m": cooldown_m},
        "budget": int(budget),
        "budget_source": budget_source,
        "budget_formula": ("budget = round(D01_val_alarm_rate "
                           "* n_test_months), D01_val_alarm_rate = "
                           "D01_val_alarms_in_[train_end, split) "
                           "/ n_validation_months; "
                           "D01_val_alarms=%d, n_validation_months=%d, "
                           "n_test_months=%d; explicit --budget overrides; "
                           "uses only pre-split validation evidence, never "
                           "test event/alarms counts" %
                           (d01_val_n, len(val_months), len(test_months))),
        "budget_inputs": {"d01_val_alarms": int(d01_val_n),
                          "n_validation_months": int(len(val_months)),
                          "n_test_months": int(len(test_months)),
                          "validation_months": val_months,
                          "test_months": test_months,
                          "has_pretrain_data": bool(has_pretrain)},
        "data_limitation": limitation,
        "fitted_on_validation_only": fitted,
        "d03_config": {"hazard": D03_HAZARD, "n0": D03_N0, "rmax": D03_RMAX,
                       "reset_on_alarm": True,
                       "strict_log_support": bool(d03_strict)},
        "note": ("технический тест детекции на %d синтетических инжектах; "
                 "раннее предупреждение о реальных шоках НЕ заявляется; "
                 "тревога в месяц onset или позже — детекция с лагом" %
                 len(reg)),
    }
    if budget_mode == "monthly_causal":
        manifest["budget_mode"] = "monthly_causal"
        manifest["monthly_budget"] = int(monthly_budget)
        manifest["d03_strict_log_support"] = True
        manifest["d03_legacy_note"] = (
            "old D03 legacy numerical bug (reset on any -inf in "
            "normalized log-posterior) retained only for repro; "
            "monthly_causal runs use strict_log_support=True")
        manifest["budget_formula"] = (
            "monthly_budget = round(D01_val_cooled_alarms_in_[train_end, "
            "split) / n_validation_months), минимум 0, без подбора на "
            "тесте; общий бюджет = monthly_budget * n_test_months; "
            "D01_val_alarms=%d, n_validation_months=%d, n_test_months=%d; "
            "explicit --budget overrides как месячный бюджет; uses only "
            "pre-split validation evidence, never test event/alarms counts"
            % (d01_val_n, len(val_months), len(test_months)))
        manifest["online_budget_rule"] = (
            "cooldown сначала, затем обработка строго хронологически, "
            "ранжирование (top score) только внутри текущего месяца; "
            "тревоги будущих месяцев не вытесняют тревоги текущего; "
            "общий бюджет и matching одинаковы для D01/D02/D03")
        manifest["calibration"] = (
            "per-series: D01 — MAD-масштаб на train (ym < train_end); "
            "D03 — mu0/var ряда на train; D02 — последовательный, "
            "без калибровки")
        manifest["test_status"] = (
            "test already opened (R7 primary runs/R7, 2026-09-25 counts "
            "as exploratory); этот прогон — exploratory, первичный "
            "результат runs/R7 не переписывается")
        manifest["limitations"] = [
            "синтетические инжекты известного сдвига — технический тест "
            "детекции, раннее предупреждение о реальных шоках НЕ "
            "заявляется",
            "отрицательный результат — валидный исход эксперимента, "
            "не провал протокола",
        ]
        manifest["budget_inputs"]["monthly_budget"] = int(monthly_budget)
    metrics = {
        "validation": val_metrics,
        "test": test_metrics,
        "fitted_thresholds": fitted,
        "budget": int(budget),
        "validation_trials": {"D01": d01_val_trials, "D02": d02_val_trials,
                              "D03": d03_val_trials},
        "verdict": ("сравнение детекторов на синтетике; выводы только о "
                    "технической детекции, не о раннем предупреждении"),
    }
    if budget_mode == "monthly_causal":
        metrics["budget_mode"] = "monthly_causal"
        metrics["monthly_budget"] = int(monthly_budget)
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(outdir, "metrics.json"), "w") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    print(json.dumps({m: test_metrics[m] for m in ("D01", "D02", "D03")
                      if m in test_metrics}, ensure_ascii=False, indent=1))
    return manifest, metrics, alerts


def self_check():
    _require()
    rng = np.random.default_rng(SEED)
    months = pd.period_range("2024-01", "2024-10", freq="M").astype(str).tolist()
    det_rows, reg_rows = [], []
    for tid in (1, 2, 3):
        base = 100.0 + tid
        vals = base + rng.normal(0, 1.0, len(months))
        onset = "2024-06" if tid < 3 else "2024-08"
        oi = months.index(onset)
        vals[oi:] *= 1.40
        for m, v in zip(months, vals):
            det_rows.append({"tid": tid, "cat": "food", "ym": m,
                             "rel": float(v / base - 1.0),
                             "cus": float(v / base - 1.0)})
        reg_rows.append({"event_id": "EV%03d" % tid, "tid": tid, "cat": "food",
                         "onset": onset, "length_m": 3, "rel_size": 0.40,
                         "direction": "up"})
    det = pd.DataFrame(det_rows)
    reg = pd.DataFrame(reg_rows)
    reg_val = reg[reg["onset"] < "2024-07"].reset_index(drop=True)
    a1 = apply_cooldown(d01_alarms(det, "rel", 2.0))
    a2 = apply_cooldown(d02_alarms(det, "rel", 0.02, 0.05))
    a3 = apply_cooldown(d03_alarms(det, "rel", 0.30))
    for name, a in (("D01", a1), ("D02", a2), ("D03", a3)):
        m = evaluate(a, reg, "2024-07", already_cooled=True)
        assert set(("events", "hits", "recall", "precision", "false_alarms",
                    "delay_signed_mean", "lead_mean_m")) <= set(m), name
        print(name, json.dumps({k: m[k] for k in
              ("events", "hits", "recall", "precision", "false_alarms",
               "delay_signed_mean", "lead_mean_m")}, ensure_ascii=False))
    assert len(truncate_budget(a1, 1)) <= 1
    future_only = pd.DataFrame([{"method": "D01", "tid": 1, "cat": "food",
                                 "ym": "2024-09", "score": 99.0}])
    mv_clean = evaluate(a1, reg_val, TRAIN_END, "2024-07",
                        already_cooled=True)
    mv_leaky = evaluate(pd.concat([a1, future_only], ignore_index=True),
                        reg_val, TRAIN_END, "2024-07", already_cooled=True)
    assert mv_clean["alarms"] == mv_leaky["alarms"], (mv_clean, mv_leaky)
    assert mv_clean["false_alarms"] == mv_leaky["false_alarms"]
    assert not any(r["alarm_ym"] >= "2024-07"
                   for r in mv_leaky["matches"]), mv_leaky["matches"]
    print("LEAK-PROBE", json.dumps({"val_alarms": mv_leaky["alarms"]},
                                   ensure_ascii=False))
    k1, _, _ = _fit_grid(lambda d, s, th: d01_alarms(d, s, th, TRAIN_END),
                         det, "rel", reg_val, TRAIN_END, D01_GRID, "2024-07")
    k2, _, _ = _fit_grid(lambda d, s, th: d01_alarms(d, s, th, TRAIN_END),
                         det, "rel", reg_val, TRAIN_END, D01_GRID, "2024-07")
    assert k1 == k2
    grid2 = [(dl, l) for dl in D02_DELTA_GRID for l in D02_LAMBDA_GRID]
    dl1, _, trials1 = _fit_grid(
        lambda d, s, th: d02_alarms(d, s, th[0], th[1]),
        det, "rel", reg_val, TRAIN_END, grid2, "2024-07")
    dl2, _, trials2 = _fit_grid(
        lambda d, s, th: d02_alarms(d, s, th[0], th[1]),
        det, "rel", reg_val, TRAIN_END, grid2, "2024-07")
    assert isinstance(dl1, tuple) and len(dl1) == 2
    assert dl1 == dl2
    assert [t["threshold"] for t in trials1] == [t["threshold"] for t in trials2]
    assert {t["threshold"] for t in trials1} == set(grid2)
    print("D02-GRID", json.dumps({"best": list(dl1)}, ensure_ascii=False))
    mm = pd.DataFrame([
        {"method": "D01", "tid": 1, "cat": "food", "ym": "2024-07",
         "score": 1.0},
        {"method": "D01", "tid": 2, "cat": "food", "ym": "2024-07",
         "score": 2.0},
        {"method": "D01", "tid": 3, "cat": "food", "ym": "2024-08",
         "score": 99.0},
        {"method": "D01", "tid": 4, "cat": "food", "ym": "2024-08",
         "score": 98.0},
    ])
    got = truncate_budget_monthly(mm, 1)
    assert sorted(zip(got["ym"], got["tid"])) == [("2024-07", 2),
                                                  ("2024-08", 3)], got
    assert len(truncate_budget_monthly(mm, 0)) == 0
    assert len(truncate_budget_monthly(mm, -1)) == 0
    prefix = mm[mm["ym"] <= "2024-07"].copy()
    full_kept = truncate_budget_monthly(mm, 1)
    prefix_kept = truncate_budget_monthly(prefix, 1)
    in_prefix = full_kept[full_kept["ym"] <= "2024-07"].sort_values(
        ["tid", "cat", "ym"]).reset_index(drop=True)
    assert in_prefix.equals(prefix_kept.sort_values(
        ["tid", "cat", "ym"]).reset_index(drop=True)), (in_prefix,
                                                        prefix_kept)
    print("MONTHLY-BUDGET",
          json.dumps({"per_month": 1, "kept": int(len(got)),
                      "future_prefix_invariant": True}, ensure_ascii=False))
    toy = np.zeros(12)
    cp_strict = _bocd_cp_prob(toy, 0.0, 1.0, D03_HAZARD, D03_N0, D03_RMAX,
                              strict_log_support=True)
    assert np.all(np.isfinite(cp_strict))
    assert np.all((cp_strict >= 0.0) & (cp_strict <= 1.0))
    assert not np.all(cp_strict == 1.0), cp_strict
    cp_legacy = _bocd_cp_prob(toy, 0.0, 1.0, D03_HAZARD, D03_N0, D03_RMAX)
    assert np.all(cp_legacy == 1.0), cp_legacy
    mixed = np.array([0.0, -np.inf, -np.inf])
    assert _logr_is_bad(mixed)
    assert not _logr_is_bad(mixed, True)
    assert _logr_is_bad(np.full(3, -np.inf), True)
    assert _logr_is_bad(np.array([0.0, np.nan, -np.inf]), True)
    assert _logr_is_bad(np.array([0.0, np.inf, -np.inf]), True)
    xs = np.concatenate([np.zeros(8), np.full(8, 5.0)])
    full = _bocd_cp_prob(xs, 0.0, 1.0, D03_HAZARD, D03_N0, D03_RMAX,
                         strict_log_support=True)
    part = _bocd_cp_prob(xs[:8], 0.0, 1.0, D03_HAZARD, D03_N0, D03_RMAX,
                         strict_log_support=True)
    assert np.array_equal(full[:8], part), (full[:8], part)
    print("D03-STRICT",
          json.dumps({"stable_toy_max": float(np.max(cp_strict)),
                      "legacy_all_one": bool(np.all(cp_legacy == 1.0)),
                      "prefix_invariant": True}, ensure_ascii=False))
    print("SELF-CHECK OK")


def main(argv=None):
    p = argparse.ArgumentParser(description="R7: D02/D03 vs D01")
    p.add_argument("--cus", default=None)
    p.add_argument("--registry", default=None)
    p.add_argument("--outdir", default=None)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--split", default=SPLIT)
    p.add_argument("--train-end", default=TRAIN_END)
    p.add_argument("--window", type=int, default=MATCH_WINDOW)
    p.add_argument("--cooldown", type=int, default=COOLDOWN_M)
    p.add_argument("--budget", type=int, default=None)
    p.add_argument("--budget-mode", default="legacy",
                   choices=("legacy", "monthly_causal"))
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.cus and a.registry and a.outdir):
        p.error("--cus, --registry and --outdir are required")
    run(a.cus, a.registry, a.outdir, seed=a.seed, split=a.split,
        train_end=a.train_end, window=a.window, cooldown_m=a.cooldown,
        budget=a.budget, budget_mode=a.budget_mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
