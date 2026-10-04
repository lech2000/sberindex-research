"""Каузальные сигналы-отклонения от уровня для D01/D02/D03 (ATF-M6, 01.10.2026).

Зачем. Сигнал R7_v2 (last-value, rel[m] = x[m]/x[m-1] - 1) — первая разность. Сдвиг
уровня на несколько месяцев даёт в нём один всплеск в месяц onset, а правило D01
«два горячих месяца подряд» требует персистентности. Здесь сигнал — отклонение от
устойчивого уровня, оно держится несколько месяцев после сдвига.

Варианты зафиксированы ДО запуска детекторов, подбора под тест нет:
  V0_last      база = x[m-1] (воспроизводит runs/R7_v2 как контроль)
  V1_last_cs   V0 минус медиана rel по всем рядам той же категории в том же месяце
  V2_med3      база = медиана x[m-3..m-1] (минимум 2 наблюдения, иначе x[m-1])
  V3_med3_cs   V2 минус медиана по срезу (категория, месяц)
  V4_med6_cs   база = медиана x[m-6..m-1] (минимум 3, иначе x[m-1]) минус срез

Все сигналы в относительных единицах (доля), как rel, поэтому сетки детекторов
остаются в силе. Причинность: значение в месяце m использует только x[<=m] и срез
других рядов того же месяца m (они публикуются вместе). Реестр событий не
используется. Набор строк идентичен runs/R7_v2 (общая маска), недостающую базу
заменяет x[m-1]; доля подмен пишется в манифест.

Запуск:  python3 d01_sensitive_signals.py --signal runs/R7_v2/signal/signal.parquet \
           --outdir OUT [--self-check]
"""
import argparse
import hashlib
import json
import os
import warnings

import numpy as np
import pandas as pd

EPS = 1e-9
VARIANTS = {
    "V0_last": {"window": 1, "cs": False},
    "V1_last_cs": {"window": 1, "cs": True},
    "V2_med3": {"window": 3, "cs": False},
    "V3_med3_cs": {"window": 3, "cs": True},
    "V4_med6_cs": {"window": 6, "cs": True},
}
MIN_OBS = {1: 1, 3: 2, 6: 3}


def _mi(ym):
    y, m = str(ym).split("-")
    return int(y) * 12 + int(m) - 1


def _ym(i):
    return "%04d-%02d" % (i // 12, i % 12 + 1)


def wide_series(sig):
    """Восстанавливает ряды x[series, month]: actual_inj строки m и pred = x[m-1]."""
    sig = sig.sort_values(["tid", "cat", "ym"]).reset_index(drop=True)
    mi = sig["ym"].map(_mi).to_numpy()
    sid = sig.groupby(["tid", "cat"], sort=True).ngroup().to_numpy()
    m0 = int(mi.min()) - 1
    X = np.full((int(sid.max()) + 1, int(mi.max()) - m0 + 1), np.nan)
    prev = X.copy()
    X[sid, mi - m0] = sig["actual_inj"].to_numpy(dtype=float)
    prev[sid, mi - 1 - m0] = sig["pred"].to_numpy(dtype=float)
    both = np.isfinite(X) & np.isfinite(prev)
    if not np.allclose(X[both], prev[both], rtol=0, atol=1e-6):
        raise ValueError("pred не равен x[m-1]: сигнал не last-value, восстановление рядов невозможно")
    X = np.where(np.isfinite(X), X, prev)
    return sig, sid, mi, m0, X


def level_deviation(X, window):
    """S[:, j] = (x[j] - base[j]) / |base[j]|; base по x[<j] (причинно). Возвращает S, base, fallback."""
    n, T = X.shape
    S = np.full((n, T), np.nan)
    B = np.full((n, T), np.nan)
    FB = np.zeros((n, T), dtype=bool)
    need = MIN_OBS[window]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        for j in range(1, T):
            last = X[:, j - 1]
            if window == 1:
                base = last
            else:
                win = X[:, max(0, j - window):j]
                cnt = np.isfinite(win).sum(axis=1)
                med = np.nanmedian(win, axis=1)
                use = cnt >= need
                base = np.where(use, med, last)
                FB[:, j] = ~use & np.isfinite(last)
            B[:, j] = base
            S[:, j] = (X[:, j] - base) / np.maximum(np.abs(base), EPS)
    return S, B, FB


def build_variant(sig, name):
    cfg = VARIANTS[name]
    sig, sid, mi, m0, X = wide_series(sig)
    S, B, FB = level_deviation(X, cfg["window"])
    col = mi - m0
    out = sig[["tid", "cat", "ym"]].copy()
    out["rel"] = S[sid, col]
    out["actual_inj"] = sig["actual_inj"].to_numpy()
    out["pred"] = B[sid, col]
    if cfg["cs"]:
        out["rel"] = out["rel"] - out.groupby(["cat", "ym"])["rel"].transform("median")
    fallback = float(FB[sid, col].mean())
    return out, fallback


def self_check():
    """Причинность и контроль воспроизведения на синтетике, без файлов."""
    rng = np.random.default_rng(7)
    n, T = 40, 18
    X = rng.normal(1000, 80, size=(n, T))
    for window in (1, 3, 6):
        base_S, _, _ = level_deviation(X, window)
        for cut in (6, 9, 12):
            Xm = X.copy()
            Xm[:, cut + 1:] = Xm[:, cut + 1:] * 50 + 999
            S2, _, _ = level_deviation(Xm, window)
            if not np.allclose(base_S[:, :cut + 1], S2[:, :cut + 1], equal_nan=True):
                raise AssertionError("сигнал window=%d читает будущее после месяца %d" % (window, cut))
    # сдвиг уровня на 3 месяца: у med3 отклонение держится минимум 2 месяца, у last-value — 1
    flat = np.full((1, 12), 1000.0)
    shifted = flat.copy()
    shifted[0, 6:9] = 1300.0
    s1, _, _ = level_deviation(shifted, 1)
    s3, _, _ = level_deviation(shifted, 3)
    hot = lambda s: int((np.abs(s[0, 6:9]) > 0.15).sum())
    if not (hot(s1) == 1 and hot(s3) >= 2):
        raise AssertionError("персистентность сдвига: last=%d med3=%d" % (hot(s1), hot(s3)))
    print(json.dumps({"causal": True, "persistence_last": hot(s1), "persistence_med3": hot(s3)}))


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--signal")
    p.add_argument("--outdir")
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not (a.signal and a.outdir):
        p.error("--signal и --outdir обязательны")
    sig = pd.read_parquet(a.signal)
    os.makedirs(a.outdir, exist_ok=True)
    base_sorted = sig.sort_values(["tid", "cat", "ym"]).reset_index(drop=True)
    report = {"input": a.signal, "input_sha256": hashlib.sha256(open(a.signal, "rb").read()).hexdigest(),
              "rows": int(len(sig)), "variants": {}}
    for name in VARIANTS:
        out, fb = build_variant(sig, name)
        if name == "V0_last":  # контроль: воспроизводит исходный сигнал
            if not np.allclose(out["rel"].to_numpy(), base_sorted["rel"].to_numpy(), rtol=0, atol=1e-9, equal_nan=True):
                raise AssertionError("V0_last не воспроизводит исходный rel")
        vdir = os.path.join(a.outdir, name)
        os.makedirs(vdir, exist_ok=True)
        path = os.path.join(vdir, "signal.parquet")
        out.to_parquet(path, index=False)
        r = out["rel"].abs()
        report["variants"][name] = {
            **VARIANTS[name], "rows": int(len(out)), "base_fallback_share": round(fb, 4),
            "nan_rel": int(out["rel"].isna().sum()),
            "abs_rel_quantiles": {q: round(float(r.quantile(float(q))), 4) for q in ("0.5", "0.9", "0.99", "0.998")},
            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()}
    json.dump(report, open(os.path.join(a.outdir, "variants_manifest.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps(report["variants"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
