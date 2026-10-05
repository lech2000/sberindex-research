"""R7_v2: причинный last-value relative residual (baseline, НЕ бустинг R3).

Сигнал для D01/D02/D03 на существующем реестре синтетических событий:
  - инжект реестра в КОПИЮ value панели raw8_consumption, строго по точным
    ключам tid/cat/ym; отсутствующие ключи не импутируются нулями, а уходят
    в отчёт о покрытии;
  - прогноз pred[m] = actual_inj[m-1]: предыдущий наблюдённый/инжектированный
    месяц того же ряда, только смежный календарный месяц, без будущего;
  - rel[m] = (actual_inj[m] - pred[m]) / max(abs(pred[m]), eps).
Диапазон сигнала 2023-02..2024-12. Это baseline residual, НЕ остатки
бустинга R3 из d01_threshold.residuals — названо явно, путать запрещено.

Сплит: train ym < 2024-03, validation 2024-03..2024-06, test ym >= 2024-07.
Аудит pretrain пишется по каждому ряду; ряды с <6 pretrain-месяцами
исключаются с явным отчётом. Выходной файл сигнала — общая единая маска
для D01/D02/D03. registry_eligible считается по факту покрытия; 60 не
утверждается, если покрытие меньше.

Встроенные проверки: causal prefix invariance к будущим инжектам, disjoint
сплитов, синтетические метки реестра. Детекторы на подготовленном сигнале
запускает ОТДЕЛЬНО оператор через d02_d03_detectors.run
(см. R7_v2_README.md).

Модуль unit-safe: импорт не трогает файлы и argv; `python
r7_causal_signal.py --self-check` гоняет маленькую синтетическую панель
в памяти без входных файлов.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
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
        raise RuntimeError("r7_causal_signal needs numpy+pandas to run; "
                           "import alone is dependency-free")


SEED = 20260923
SIGNAL_START = "2023-02"
SIGNAL_END = "2024-12"
TRAIN_END = "2024-03"
SPLIT = "2024-07"
MIN_PRETRAIN = 6
EPS = 1e-9

PANEL_DEFAULT = ("deliverables/sberindex-2026/data/raw/"
                 "sberindex-data-sense-2025/8_consumption.parquet")
REGISTRY_DEFAULT = ("deliverables/sberindex-2026/shock-radar/"
                    "events/registry.parquet")


def _ym_parts(ym):
    y, m = str(ym).split("-")
    return int(y), int(m)


def _add_months(ym, k):
    y, m = _ym_parts(ym)
    m = m + k
    y = y + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return "%04d-%02d" % (y, m)


def _month_range(a, b):
    out, cur = [], str(a)
    b = str(b)
    while cur <= b:
        out.append(cur)
        cur = _add_months(cur, 1)
    return out


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


def _normalize_panel(panel):
    _require()
    df = panel.copy()
    for col in ("territory_id", "category", "value"):
        if col not in df.columns:
            raise KeyError("panel misses column %r" % col)
    if "ym" in df.columns:
        df["ym"] = df["ym"].astype(str)
    elif "date" in df.columns:
        df["ym"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    else:
        raise KeyError("panel has neither 'ym' nor 'date' column")
    df["tid"] = df["territory_id"].astype(int)
    df["cat"] = df["category"].astype(str)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df[np.isfinite(df["value"].to_numpy())].copy()
    if df.empty:
        raise ValueError("panel has no finite values")
    key = list(zip(df["tid"], df["cat"], df["ym"]))
    if len(set(key)) != len(df):
        raise ValueError("panel keys (tid, cat, ym) are not unique")
    return df[["tid", "cat", "ym", "value"]].reset_index(drop=True)


def _lookup(inj, key):
    try:
        if key in inj.index:
            return float(inj.loc[key])
    except (KeyError, TypeError):
        pass
    return float("nan")


def _inject(panel_df, reg, months):
    _require()
    for col in ("event_id", "tid", "cat", "onset", "length_m", "rel_size",
                "direction"):
        if col not in reg.columns:
            raise KeyError("registry misses column %r" % col)
    base = panel_df.set_index(["tid", "cat", "ym"])["value"].astype(float)
    inj = base.copy()
    injected_cells = 0
    for _, e in reg.iterrows():
        onset = str(e["onset"])
        if onset not in months:
            continue
        o = months.index(onset)
        size = float(e["rel_size"])
        up = str(e["direction"]) == "up"
        for k in range(int(e["length_m"])):
            if o + k >= len(months):
                break
            key = (int(e["tid"]), str(e["cat"]), months[o + k])
            if key in inj.index:
                inj.loc[key] = float(inj.loc[key]) * (1.0 + size if up
                                                      else 1.0 - size)
                injected_cells += 1
    return inj, int(injected_cells)


def build_signal(panel_df, reg, signal_months, train_end=TRAIN_END,
                 eps=EPS):
    _require()
    inj, injected_cells = _inject(panel_df, reg, signal_months)
    obs = {}
    for (tid, cat), g in panel_df.groupby(["tid", "cat"]):
        g = g.sort_values("ym")
        obs[(int(tid), str(cat))] = dict(
            zip(g["ym"].astype(str), g["value"].astype(float)))
    rows = []
    pretrain = {}
    for (tid, cat), series in sorted(obs.items()):
        n_pre = 0
        for ym in sorted(series):
            if ym < SIGNAL_START or ym > SIGNAL_END:
                continue
            prev = _add_months(ym, -1)
            if prev not in series:
                continue
            a = _lookup(inj, (tid, cat, ym))
            p = _lookup(inj, (tid, cat, prev))
            if not (np.isfinite(a) and np.isfinite(p)):
                continue
            rel = (a - p) / max(abs(p), float(eps))
            rows.append({"tid": tid, "cat": cat, "ym": ym,
                         "rel": float(rel), "actual_inj": float(a),
                         "pred": float(p)})
            if ym < train_end:
                n_pre += 1
        pretrain[(tid, cat)] = int(n_pre)
    cols = ["tid", "cat", "ym", "rel", "actual_inj", "pred"]
    if rows:
        sig = pd.DataFrame(rows, columns=cols).sort_values(
            ["tid", "cat", "ym"]).reset_index(drop=True)
    else:
        sig = pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
        sig["tid"] = pd.Series(dtype="int64")
        sig["cat"] = pd.Series(dtype="object")
        sig["ym"] = pd.Series(dtype="object")
        sig = sig[cols]
    return sig, pretrain, injected_cells


def check_synthetic_marks(reg):
    if "source" in reg.columns:
        vals = reg["source"].astype(str)
        ok = bool(vals.str.contains("synthetic", case=False).all())
        return ok, "source"
    if "confidence" in reg.columns:
        vals = reg["confidence"].astype(str)
        ok = bool(vals.str.contains("inject", case=False).all())
        return ok, "confidence"
    return False, "absent"


def check_prefix_invariance(panel_df, reg, signal_months, split=SPLIT,
                            train_end=TRAIN_END, eps=EPS):
    _require()
    full, _, _ = build_signal(panel_df, reg, signal_months, train_end, eps)
    past_reg = reg[reg["onset"].astype(str) < str(split)].reset_index(
        drop=True)
    past, _, _ = build_signal(panel_df, past_reg, signal_months, train_end,
                              eps)
    cols = ["tid", "cat", "ym", "rel", "actual_inj", "pred"]
    f = full[full["ym"] < str(split)].sort_values(
        ["tid", "cat", "ym"])[cols].reset_index(drop=True)
    p = past[past["ym"] < str(split)].sort_values(
        ["tid", "cat", "ym"])[cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(f, p, check_dtype=False)
    return True


def check_split_disjoint(signal_months, train_end=TRAIN_END, split=SPLIT):
    tr = {m for m in signal_months if m < str(train_end)}
    va = {m for m in signal_months if str(train_end) <= m < str(split)}
    te = {m for m in signal_months if m >= str(split)}
    assert tr.isdisjoint(va) and tr.isdisjoint(te) and va.isdisjoint(te)
    assert tr | va | te == set(signal_months)
    return {"train_months": sorted(tr), "val_months": sorted(va),
            "test_months": sorted(te)}


def _write_frame(df, path_parquet):
    try:
        df.to_parquet(path_parquet, index=False)
        return path_parquet
    except Exception:
        csv_path = path_parquet.replace(".parquet", ".csv")
        df.to_csv(csv_path, index=False)
        return csv_path


def build(panel_path, reg_path, outdir, seed=SEED, split=SPLIT,
          train_end=TRAIN_END, signal_start=SIGNAL_START,
          signal_end=SIGNAL_END, min_pretrain=MIN_PRETRAIN, eps=EPS):
    _require()
    import os
    panel = pd.read_parquet(panel_path)
    reg = pd.read_parquet(reg_path)
    for col in ("event_id", "tid", "cat", "onset"):
        if col not in reg.columns:
            raise KeyError("registry misses column %r" % col)
    reg = reg.sort_values("onset").reset_index(drop=True)
    panel_df = _normalize_panel(panel)

    signal_months = [m for m in _month_range(signal_start, signal_end)]
    panel_months = sorted(panel_df["ym"].unique())
    signal_months = [m for m in signal_months if m in set(panel_months)]
    if not signal_months:
        raise ValueError("no signal months overlap the panel")

    marks_ok, marks_col = check_synthetic_marks(reg)
    if not marks_ok:
        raise RuntimeError(
            "registry lacks synthetic provenance marks (need 'source' "
            "containing 'synthetic' or 'confidence' containing 'inject'); "
            "refusing to build an honesty-critical signal")
    split_info = check_split_disjoint(signal_months, train_end, split)
    check_prefix_invariance(panel_df, reg, signal_months, split, train_end,
                            eps)

    sig, pretrain, injected_cells = build_signal(panel_df, reg,
                                                 signal_months, train_end,
                                                 eps)
    audit_rows = [{"tid": tid, "cat": cat, "n_pretrain": n,
                   "included": bool(n >= min_pretrain)}
                  for (tid, cat), n in sorted(pretrain.items())]
    audit = pd.DataFrame(audit_rows,
                         columns=["tid", "cat", "n_pretrain", "included"])
    included_keys = {(r["tid"], r["cat"]) for r in audit_rows
                     if r["included"]}
    kept = sig[sig[["tid", "cat"]].apply(
        lambda r: (r["tid"], r["cat"]) in included_keys,
        axis=1)].reset_index(drop=True) if len(sig) else sig
    kept_keys = set(zip(kept["tid"], kept["cat"], kept["ym"])) if len(
        kept) else set()

    eligible, ineligible = [], []
    for _, e in reg.iterrows():
        tid, cat, onset = int(e["tid"]), str(e["cat"]), str(e["onset"])
        n_pre = pretrain.get((tid, cat), 0)
        if (tid, cat) not in included_keys:
            ineligible.append({"event_id": str(e["event_id"]), "tid": tid,
                               "cat": cat, "onset": onset,
                               "reason": "series_excluded_n_pretrain_%d"
                               % n_pre})
        elif (tid, cat, onset) not in kept_keys:
            ineligible.append({"event_id": str(e["event_id"]), "tid": tid,
                               "cat": cat, "onset": onset,
                               "reason": "onset_key_missing_in_signal"})
        else:
            eligible.append(str(e["event_id"]))

    os.makedirs(outdir, exist_ok=True)
    sig_path = _write_frame(
        kept, os.path.join(outdir, "signal.parquet"))
    audit_path = _write_frame(
        audit, os.path.join(outdir, "pretrain_audit.parquet"))
    manifest = {
        "experiment_id": "R7-v2-causal-lastvalue-baseline",
        "method": ("causal last-value relative residual — baseline, "
                   "NOT R3 boosting"),
        "signal_formula": ("pred[m] = actual_inj[m-1] (adjacent calendar "
                           "month only, observed/injected, no future); "
                           "rel[m] = (actual_inj[m] - pred[m]) / "
                           "max(abs(pred[m]), eps); no zero-imputation, "
                           "missing month pairs yield no row"),
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "seed": int(seed),
        "eps": float(eps),
        "inputs": {"panel": str(panel_path),
                   "panel_sha256": _sha256(panel_path),
                   "registry": str(reg_path),
                   "registry_sha256": _sha256(reg_path),
                   "n_panel_rows": int(len(panel_df))},
        "signal_months": [signal_months[0], signal_months[-1]],
        "n_signal_months": int(len(signal_months)),
        "n_signal_rows": int(len(kept)),
        "n_signal_rows_before_mask": int(len(sig)),
        "injected_cells": int(injected_cells),
        "split": {"train": "ym < %s" % train_end,
                  "validation": "%s <= ym < %s" % (train_end, split),
                  "test": "ym >= %s" % split,
                  "disjoint": True,
                  "train_months": split_info["train_months"],
                  "val_months": split_info["val_months"],
                  "test_months": split_info["test_months"]},
        "series": {"total": int(len(audit_rows)),
                   "included": int(len(included_keys)),
                   "excluded": int(len(audit_rows) - len(included_keys)),
                   "min_pretrain_months": int(min_pretrain),
                   "audit_file": audit_path,
                   "audit_sha256": _sha256(audit_path)},
        "registry": {"total": int(len(reg)),
                     "eligible": int(len(eligible)),
                     "eligible_ids": eligible,
                     "ineligible": ineligible,
                     "synthetic_marks": {"column": marks_col,
                                         "ok": True}},
        "checks": {"causal_prefix_invariance": True,
                   "split_disjoint": True,
                   "synthetic_marks": True},
        "same_mask_for_detectors": ("D01/D02/D03 consume this identical "
                                    "signal file; input hash is recorded "
                                    "in the detector manifest"),
        "test_status": ("test already opened (R7 primary runs/R7, "
                        "2026-09-25 counts as exploratory); R7_v2 is "
                        "exploratory-v2; runs/R7 is not rewritten"),
        "limitations": [
            "synthetic injected shifts only — technical detection test, "
            "no real early-warning claim",
            "last-value baseline residual, not a tuned forecaster; "
            "negative result is a valid experiment",
            "registry coverage below total is reported, not rounded up",
        ],
        "note": ("технический тест детекции на синтетических инжектах; "
                 "раннее предупреждение о реальных шоках НЕ заявляется"),
        "next_step": ("оператор запускает d02_d03_detectors.run на "
                      "signal.parquet с --budget-mode monthly_causal"),
    }
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    print(json.dumps(
        {"signal_rows": int(len(kept)),
         "series_included": int(len(included_keys)),
         "series_excluded": int(len(audit_rows) - len(included_keys)),
         "registry_total": int(len(reg)),
         "registry_eligible": int(len(eligible))}, ensure_ascii=False,
        indent=1))
    return manifest, kept, audit


def self_check():
    _require()
    months = _month_range("2023-01", "2023-06")
    panel_rows = []
    for ym, v in zip(months, (100.0, 101.0, 99.0, 102.0, 100.0, 101.0)):
        panel_rows.append({"territory_id": 1, "category": "A",
                           "date": ym + "-15", "value": v})
    for ym, v in zip(months[4:], (50.0, 51.0)):
        panel_rows.append({"territory_id": 2, "category": "B",
                           "date": ym + "-15", "value": v})
    panel = pd.DataFrame(panel_rows)
    reg = pd.DataFrame([
        {"event_id": "EV001", "tid": 1, "cat": "A", "onset": "2023-04",
         "length_m": 2, "rel_size": 0.5, "direction": "up",
         "source": "synthetic_assumption"},
        {"event_id": "EV002", "tid": 1, "cat": "A", "onset": "2023-06",
         "length_m": 1, "rel_size": 0.2, "direction": "down",
         "source": "synthetic_assumption"},
    ])
    panel_df = _normalize_panel(panel)
    assert (panel_df["ym"].min(), panel_df["ym"].max()) == ("2023-01",
                                                            "2023-06")
    sig_months = [m for m in _month_range(SIGNAL_START, "2023-06")]
    sig, pretrain, cells = build_signal(panel_df, reg, sig_months)
    assert cells == 3, cells
    r_apr = sig[(sig["tid"] == 1) & (sig["ym"] == "2023-04")].iloc[0]
    assert abs(r_apr["actual_inj"] - 102.0 * 1.5) < 1e-9, r_apr
    assert abs(r_apr["pred"] - 99.0) < 1e-9, r_apr
    assert abs(r_apr["rel"] - (153.0 - 99.0) / 99.0) < 1e-9, r_apr
    r_may = sig[(sig["tid"] == 1) & (sig["ym"] == "2023-05")].iloc[0]
    assert abs(r_may["actual_inj"] - 100.0 * 1.5) < 1e-9, r_may
    assert abs(r_may["pred"] - 102.0 * 1.5) < 1e-9, r_may
    assert abs(r_may["rel"] - (150.0 - 153.0) / 153.0) < 1e-9, r_may
    assert pretrain[(1, "A")] == 5, pretrain
    assert pretrain[(2, "B")] == 1, pretrain
    ok, col = check_synthetic_marks(reg)
    assert ok and col == "source"
    bad = reg.drop(columns=["source"])
    ok2, _ = check_synthetic_marks(bad)
    assert not ok2
    assert check_prefix_invariance(panel_df, reg, sig_months,
                                   split="2023-05")
    info = check_split_disjoint(sig_months, train_end="2023-03",
                                split="2023-05")
    assert info["train_months"] == ["2023-02"], info
    assert info["val_months"] == ["2023-03", "2023-04"], info
    assert info["test_months"] == ["2023-05", "2023-06"], info
    with tempfile.TemporaryDirectory() as tmp:
        mf, kept, audit = build_from_frames(panel, reg, tmp)
        assert mf["series"]["excluded"] == 2, mf["series"]
        assert mf["registry"]["total"] == 2
        assert mf["registry"]["eligible"] == 0, mf["registry"]
        assert mf["checks"]["causal_prefix_invariance"] is True
        assert mf["method"].startswith("causal last-value")
        assert "NOT R3 boosting" in mf["method"]
    with tempfile.TemporaryDirectory() as tmp:
        mf2, kept2, _ = build_from_frames(panel, reg, tmp, min_pretrain=5)
        assert mf2["series"]["included"] == 1, mf2["series"]
        assert mf2["series"]["excluded"] == 1, mf2["series"]
        assert mf2["registry"]["eligible"] == 2, mf2["registry"]
        assert len(kept2) == 5, len(kept2)
    print("SELF-CHECK OK")


def build_from_frames(panel, reg, outdir, **kw):
    _require()
    import os
    os.makedirs(outdir, exist_ok=True)
    panel_path = os.path.join(outdir, "_selfcheck_panel.parquet")
    reg_path = os.path.join(outdir, "_selfcheck_registry.parquet")
    panel.to_parquet(panel_path, index=False)
    reg.to_parquet(reg_path, index=False)
    try:
        return build(panel_path, reg_path, outdir, **kw)
    finally:
        for p in (panel_path, reg_path):
            try:
                os.remove(p)
            except OSError:
                pass


def main(argv=None):
    p = argparse.ArgumentParser(
        description="R7_v2: causal last-value relative residual "
                    "(baseline, NOT R3 boosting)")
    p.add_argument("--panel", default=PANEL_DEFAULT)
    p.add_argument("--registry", default=REGISTRY_DEFAULT)
    p.add_argument("--outdir", default=None)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--split", default=SPLIT)
    p.add_argument("--train-end", default=TRAIN_END)
    p.add_argument("--signal-start", default=SIGNAL_START)
    p.add_argument("--signal-end", default=SIGNAL_END)
    p.add_argument("--min-pretrain", type=int, default=MIN_PRETRAIN)
    p.add_argument("--eps", type=float, default=EPS)
    p.add_argument("--self-check", action="store_true")
    a = p.parse_args(argv)
    if a.self_check:
        self_check()
        return 0
    if not a.outdir:
        p.error("--outdir is required")
    build(a.panel, a.registry, a.outdir, seed=a.seed, split=a.split,
          train_end=a.train_end, signal_start=a.signal_start,
          signal_end=a.signal_end, min_pretrain=a.min_pretrain, eps=a.eps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
