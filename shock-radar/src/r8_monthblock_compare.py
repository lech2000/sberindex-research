"""R8 month-block comparison: Prophet vs TSFM on the 171150-row R8 mask.
Month-block bootstrap clusters by target month (Jul-Dec 2024, 6 blocks),
95% percentile CI. Positive benefit = TSFM lower abs error.
LIMITATIONS: 6 blocks too few for strong inference; no causality; 2-month
lag assumed; results can be negative. Municipality-cluster is secondary.
Usage:
  python r8_monthblock_compare.py --prophet-run <dir> --tsfm-run <dir> --outdir <dir>
  python r8_monthblock_compare.py --self-check
"""
import argparse, datetime as _dt, hashlib, json, math, os, random, sys
RUN_ID = "R8-monthblock-compare"
FULL_R8_MASK = 171150
JOIN_KEYS = ("territory_id", "category", "origin", "target", "horizon")
PROPHET_PRED_COLS = ("pred_prophet", "pred_lastavailable", "pred_seasonal_naive")
TSFM_PRED_COLS = ("pred_tsfm",)
PRED_COLS = PROPHET_PRED_COLS + TSFM_PRED_COLS
DEFAULT_N_BOOTSTRAP = 10000
DEFAULT_SEED = 20260928
MUNI_BOOTSTRAP_REPS = 2000
BENEFIT_CONVENTION = ("positive benefit = TSFM has lower absolute error than "
    "the comparator; benefit = abs_err_comparator - abs_err_tsfm")

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
def _code_sha256():
    try: return _sha256(os.path.abspath(__file__))
    except Exception: return None
def _versions():
    v = {"python": sys.version.split()[0]}
    for mod in ("numpy", "pandas", "pyarrow"):
        try: m = __import__(mod); v[mod] = getattr(m, "__version__", None)
        except Exception: v[mod] = None
    return v
def _atomic_json(path, obj, indent=None):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
def _finite(x):
    try: f = float(x)
    except (TypeError, ValueError): return None
    return f if math.isfinite(f) else None
def _ym2i(s):
    s = str(s).strip()[:7]; return int(s[0:4]) * 12 + int(s[5:7]) - 1
def _i2ym(m):
    return "%04d-%02d" % (m // 12, m % 12 + 1)

# data loading and validation
def _read_pred(run_dir, label):
    path = os.path.join(run_dir, "predictions.parquet")
    if not os.path.exists(path):
        raise FileNotFoundError("%s predictions.parquet not found in %r" % (label, run_dir))
    import pandas as pd
    return pd.read_parquet(path), path
def _build_key_index(df, label, required_pred_cols=None):
    if required_pred_cols is None:
        required_pred_cols = PRED_COLS
    req = list(JOIN_KEYS) + ["actual"] + list(required_pred_cols)
    miss = [c for c in req if c not in df.columns]
    if miss: raise ValueError("%s missing columns %s" % (label, miss))
    idx, dup = {}, 0
    for i, row in df.iterrows():
        key = tuple(str(row[k]).strip() if k in ("territory_id", "category",
                     "origin", "target") else int(row[k]) for k in JOIN_KEYS)
        if key in idx: dup += 1
        else: idx[key] = i
    if dup: raise ValueError("%s has %d duplicate join keys" % (label, dup))
    return idx
def validate_and_join(p_df, p_path, t_df, t_path, expected=FULL_R8_MASK):
    p_idx = _build_key_index(p_df, "Prophet", required_pred_cols=PROPHET_PRED_COLS)
    t_idx = _build_key_index(t_df, "TSFM", required_pred_cols=TSFM_PRED_COLS)
    # optional: verify TSFM's Prophet controls match originals if present
    ctrl_mismatch = 0
    for col in PROPHET_PRED_COLS:
        if col in t_df.columns:
            for key in p_idx:
                if key in t_idx:
                    pv = p_df.iloc[p_idx[key]][col]
                    tv = t_df.iloc[t_idx[key]][col]
                    if abs(float(pv) - float(tv)) > 1e-9:
                        ctrl_mismatch += 1
    if ctrl_mismatch:
        raise ValueError("TSFM has %d Prophet control mismatches (columns %s)" % (
            ctrl_mismatch, list(PROPHET_PRED_COLS)))
    p_keys, t_keys = set(p_idx), set(t_idx)
    if len(p_keys) != expected:
        raise ValueError("Prophet has %d unique keys, expected %d" % (len(p_keys), expected))
    if len(t_keys) != expected:
        raise ValueError("TSFM has %d unique keys, expected %d" % (len(t_keys), expected))
    miss_t = p_keys - t_keys
    if miss_t: raise ValueError("%d keys in Prophet but not TSFM (first: %s)" % (len(miss_t), sorted(miss_t)[:3]))
    miss_p = t_keys - p_keys
    if miss_p: raise ValueError("%d keys in TSFM but not Prophet" % len(miss_p))
    keys = sorted(p_keys)
    out = {k: [] for k in ("actual", "pred_prophet", "pred_lastavailable",
                           "pred_seasonal_naive", "pred_tsfm", "row_keys")}
    n_act_bad, n_pred_bad, n_act_mis = 0, {c: 0 for c in PRED_COLS}, 0
    for key in keys:
        pr, tr = p_df.iloc[p_idx[key]], t_df.iloc[t_idx[key]]
        ap, at = _finite(pr["actual"]), _finite(tr["actual"])
        if ap is None or at is None: n_act_bad += 1; continue
        if abs(ap - at) > 1e-9: n_act_mis += 1; continue
        vals, skip = {}, False
        for col in PRED_COLS:
            v = _finite(pr[col]) if col != "pred_tsfm" else _finite(tr[col])
            if v is None: n_pred_bad[col] += 1; skip = True; break
            vals[col] = v
        if skip: continue
        out["actual"].append(ap); out["row_keys"].append(key)
        for col in PRED_COLS: out[col].append(vals[col])
    issues = {}
    if n_act_bad: issues["n_missing_actual"] = n_act_bad
    if n_act_mis: issues["n_actual_mismatch"] = n_act_mis
    for c, n in n_pred_bad.items():
        if n: issues["n_missing_%s" % c] = n
    if issues:
        raise ValueError("Data quality issues (rejecting, not imputing): %s" % json.dumps(issues))
    nj = len(out["row_keys"])
    if nj != expected:
        raise ValueError("After validation: %d rows, expected %d" % (nj, expected))
    out["n_joined"] = nj
    return out

# metrics
def _mae(a, p):
    n = len(a)
    return sum(abs(ai - pi) for ai, pi in zip(a, p)) / n if n else float("nan")
def compute_metrics(d):
    a = d["actual"]
    return {"prophet": _mae(a, d["pred_prophet"]),
            "lastavailable": _mae(a, d["pred_lastavailable"]),
            "seasonal_naive": _mae(a, d["pred_seasonal_naive"]),
            "tsfm": _mae(a, d["pred_tsfm"]), "n_rows": len(a)}
def compute_benefits(d):
    a, tp, tl, ts, tt = (d[k] for k in ("actual", "pred_prophet",
        "pred_lastavailable", "pred_seasonal_naive", "pred_tsfm"))
    ae_t = [abs(ai - ti) for ai, ti in zip(a, tt)]
    ae_p = [abs(ai - pi) for ai, pi in zip(a, tp)]
    ae_l = [abs(ai - li) for ai, li in zip(a, tl)]
    return {"benefit_tsfm_vs_prophet": [ep - et for ep, et in zip(ae_p, ae_t)],
            "benefit_tsfm_vs_lastavailable": [el - et for el, et in zip(ae_l, ae_t)],
            "benefit_prophet_vs_lastavailable": [el - ep for el, ep in zip(ae_l, ae_p)]}
def per_group(d, ben, gfn):
    grps = {}
    for i, k in enumerate(d["row_keys"]):
        grps.setdefault(gfn(k), []).append(i)
    out = {}
    for g in sorted(grps):
        ix = grps[g]; ag = [d["actual"][i] for i in ix]; n = len(ix)
        out[g] = {"n_rows": n,
            "mae_prophet": _mae(ag, [d["pred_prophet"][i] for i in ix]),
            "mae_lastavailable": _mae(ag, [d["pred_lastavailable"][i] for i in ix]),
            "mae_seasonal_naive": _mae(ag, [d["pred_seasonal_naive"][i] for i in ix]),
            "mae_tsfm": _mae(ag, [d["pred_tsfm"][i] for i in ix]),
            "mean_benefit_tsfm_vs_prophet": sum(ben["benefit_tsfm_vs_prophet"][i] for i in ix) / n,
            "mean_benefit_tsfm_vs_lastavailable": sum(ben["benefit_tsfm_vs_lastavailable"][i] for i in ix) / n}
    return out

# bootstrap
def _cluster_bootstrap(keys, diffs, cfn, n_res, rng):
    sums, counts = {}, {}
    for i, k in enumerate(keys):
        c = cfn(k); sums[c] = sums.get(c, 0.0) + diffs[i]; counts[c] = counts.get(c, 0) + 1
    clusters = sorted(sums); nc = len(clusters); total = sum(counts.values())
    if not total:
        return {"point": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "n_resamples": n_res, "n_blocks": nc, "n_rows": 0}
    pt = sum(sums.values()) / total
    ms = [sums[c] for c in clusters]; mc = [counts[c] for c in clusters]
    draws = []
    for _ in range(n_res):
        t, n = 0.0, 0
        for _ in range(nc):
            k = rng.randrange(nc); t += ms[k]; n += mc[k]
        draws.append(t / n if n else float("nan"))
    draws.sort()
    lo = draws[max(0, int(0.025 * (n_res - 1)))]
    hi = draws[min(n_res - 1, int(0.975 * (n_res - 1)))]
    return {"point": pt, "lo": lo, "hi": hi, "n_resamples": n_res,
            "n_blocks": nc, "n_rows": total, "cluster_labels": clusters}

# full comparison
def run_comparison(prophet_dir, tsfm_dir, outdir,
                   n_bootstrap=DEFAULT_N_BOOTSTRAP, seed=DEFAULT_SEED,
                   expected_mask=FULL_R8_MASK):
    run_utc = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    p_df, p_path = _read_pred(prophet_dir, "Prophet")
    t_df, t_path = _read_pred(tsfm_dir, "TSFM")
    d = validate_and_join(p_df, p_path, t_df, t_path, expected_mask)
    panel_mae = compute_metrics(d)
    ben = compute_benefits(d)
    tmonth = lambda k: str(k[3])[:7]
    per_month = per_group(d, ben, tmonth)
    per_horizon = per_group(d, ben, lambda k: "h%d" % int(k[4]))
    per_category = per_group(d, ben, lambda k: str(k[1]))
    rng = random.Random(seed)
    boot_mp = _cluster_bootstrap(d["row_keys"], ben["benefit_tsfm_vs_prophet"], tmonth, n_bootstrap, rng)
    boot_ml = _cluster_bootstrap(d["row_keys"], ben["benefit_tsfm_vs_lastavailable"], tmonth, n_bootstrap, random.Random(seed + 1))
    boot_mup = _cluster_bootstrap(d["row_keys"], ben["benefit_tsfm_vs_prophet"], lambda k: str(k[0]), MUNI_BOOTSTRAP_REPS, random.Random(seed + 2))
    boot_mul = _cluster_bootstrap(d["row_keys"], ben["benefit_tsfm_vs_lastavailable"], lambda k: str(k[0]), MUNI_BOOTSTRAP_REPS, random.Random(seed + 3))
    months = sorted(set(tmonth(k) for k in d["row_keys"]))
    cats = sorted(set(str(k[1]) for k in d["row_keys"]))
    prov = {"run_utc": run_utc, "command": " ".join(sys.argv),
            "code_sha256": _code_sha256(), "prophet_run_sha256": _sha256(p_path),
            "tsfm_run_sha256": _sha256(t_path), "versions": _versions(),
            "seed": seed, "n_bootstrap_month_block": n_bootstrap,
            "n_bootstrap_municipality": MUNI_BOOTSTRAP_REPS}
    metrics = {"run_id": RUN_ID, "gate_pass": False,
        "gate_pass_reason": ("R8 stays open: month-block comparison completed; "
            "no external MAE win gate applied; "
            "6 blocks are too few for strong future-time inference"),
        "panel_mae": panel_mae,
        "per_target_month": per_month, "per_horizon": per_horizon,
        "per_category": per_category,
        "bootstrap": {"benefit_convention": BENEFIT_CONVENTION,
            "month_block": {"tsfm_vs_prophet": boot_mp, "tsfm_vs_lastavailable": boot_ml},
            "municipality_cluster": {"tsfm_vs_prophet": boot_mup, "tsfm_vs_lastavailable": boot_mul}},
        "n_distinct_target_months": len(months), "distinct_target_months": months,
        "n_distinct_categories": len(cats), "distinct_categories": cats,
        "limitations": ["6 target-month blocks too few for strong future-time inference; CI width reflects within-sample variability only",
            "No claim of causality: paired forecast comparison on same data",
            "2-month release lag is an assumption, not confirmed vintage date",
            "Results can be negative: TSFM may underperform baselines",
            "Municipality-cluster bootstrap is secondary; month-block is primary"]}
    manifest = {"run_id": RUN_ID,
        "input": {"prophet_run_dir": os.path.abspath(prophet_dir),
                  "tsfm_run_dir": os.path.abspath(tsfm_dir),
                  "prophet_predictions_sha256": _sha256(p_path),
                  "tsfm_predictions_sha256": _sha256(t_path),
                  "expected_mask_rows": expected_mask},
        "join": {"keys": list(JOIN_KEYS), "n_joined": d["n_joined"], "strict_exact_match": True},
        "causal": {"release_lag_months": 2, "note": "2-month lag is an assumption until confirmed"},
        "outputs": ["metrics.json", "manifest.json"], "provenance": prov}
    os.makedirs(outdir, exist_ok=True)
    _atomic_json(os.path.join(outdir, "metrics.json"), metrics, indent=1)
    _atomic_json(os.path.join(outdir, "manifest.json"), manifest, indent=1)
    print(json.dumps({"run_id": RUN_ID, "n_joined": d["n_joined"],
        "panel_mae": panel_mae, "outdir": outdir}, ensure_ascii=False, indent=1))
    return metrics, manifest

# --self-check
def self_check():
    """Synthetic self-check: exact join, duplicate/key mismatch/NaN/actual
    rejection, deterministic bootstrap, benefit sign, month-block structure,
    per-group stats, negative benefit, gate_pass, manifest.
    Uses real-schema column sets: Prophet has no pred_tsfm."""
    import tempfile, pandas as pd
    print("R8 monthblock compare self-check\n  benefit_convention: %s" % BENEFIT_CONVENTION)
    tids, cats, origins = ["t0", "t1", "t2"], ["c0", "c1"], list(range(2024*12+3, 2024*12+11))
    prophet_rows, tsfm_rows = [], []
    for tid in tids:
        for cat in cats:
            for om in origins:
                for h in (1, 2, 3):
                    tm = om + h
                    if tm < 2024*12+6 or tm > 2024*12+11: continue
                    av = 100.0 + tm * 0.1
                    base = {"territory_id": tid, "category": cat,
                        "origin": _i2ym(om), "target": _i2ym(tm), "horizon": h,
                        "actual": av}
                    prophet_rows.append({**base, "pred_prophet": av + 5.0,
                        "pred_lastavailable": av + 10.0,
                        "pred_seasonal_naive": av + 20.0})
                    tsfm_rows.append({**base, "pred_tsfm": av + 3.0})
    assert len(prophet_rows) == 108, "expected 108 rows, got %d" % len(prophet_rows)
    assert len(tsfm_rows) == 108
    with tempfile.TemporaryDirectory() as td:
        p_dir, t_dir = td + "/p", td + "/t"
        os.makedirs(p_dir); os.makedirs(t_dir)
        pdf = pd.DataFrame(prophet_rows)
        tdf = pd.DataFrame(tsfm_rows)
        pdf.to_parquet(p_dir + "/predictions.parquet", index=False)
        tdf.to_parquet(t_dir + "/predictions.parquet", index=False)
        # T1: exact join with real-schema columns
        print("  test 1: exact join (real-schema columns)...")
        m1, _ = run_comparison(p_dir, t_dir, td+"/o1", n_bootstrap=200, seed=42, expected_mask=108)
        assert m1["panel_mae"]["n_rows"] == 108 and m1["panel_mae"]["tsfm"] < m1["panel_mae"]["prophet"]
        print("    PASS: 108 rows, TSFM MAE < Prophet MAE")
        # T2: duplicate rejection
        print("  test 2: duplicate rejection...")
        try: _build_key_index(pd.DataFrame(prophet_rows + [dict(prophet_rows[0])]), "dup", required_pred_cols=PROPHET_PRED_COLS); raise AssertionError
        except ValueError as e: assert "duplicate" in str(e).lower()
        print("    PASS")
        # T3: key count mismatch
        print("  test 3: key count mismatch...")
        fd = td+"/few"; os.makedirs(fd)
        pd.DataFrame(tsfm_rows[:50]).to_parquet(fd+"/predictions.parquet", index=False)
        try: run_comparison(p_dir, fd, td+"/o3", n_bootstrap=100, seed=42, expected_mask=108); raise AssertionError
        except ValueError as e: assert "unique keys" in str(e) or "keys" in str(e).lower()
        print("    PASS")
        # T4: actual mismatch
        print("  test 4: actual mismatch...")
        bad_tsfm = [dict(r) for r in tsfm_rows]; bad_tsfm[0]["actual"] += 999.0
        bd = td+"/bad"; os.makedirs(bd)
        pd.DataFrame(bad_tsfm).to_parquet(bd+"/predictions.parquet", index=False)
        try: run_comparison(p_dir, bd, td+"/o4", n_bootstrap=100, seed=42, expected_mask=108); raise AssertionError
        except ValueError as e: assert "mismatch" in str(e).lower() or "actual" in str(e).lower()
        print("    PASS")
        # T5: NaN rejection
        print("  test 5: NaN rejection...")
        nr_tsfm = [dict(r) for r in tsfm_rows]; nr_tsfm[0]["pred_tsfm"] = float("nan")
        nd = td+"/nan"; os.makedirs(nd)
        pd.DataFrame(nr_tsfm).to_parquet(nd+"/predictions.parquet", index=False)
        try: run_comparison(p_dir, nd, td+"/o5", n_bootstrap=100, seed=42, expected_mask=108); raise AssertionError
        except ValueError as e: assert "missing" in str(e).lower() or "quality" in str(e).lower()
        print("    PASS")
        # T6: deterministic bootstrap
        print("  test 6: deterministic bootstrap...")
        m2, _ = run_comparison(p_dir, t_dir, td+"/o6a", n_bootstrap=500, seed=123, expected_mask=108)
        m3, _ = run_comparison(p_dir, t_dir, td+"/o6b", n_bootstrap=500, seed=123, expected_mask=108)
        ci_a, ci_b = m2["bootstrap"]["month_block"]["tsfm_vs_prophet"], m3["bootstrap"]["month_block"]["tsfm_vs_prophet"]
        assert abs(ci_a["lo"] - ci_b["lo"]) < 1e-12 and abs(ci_a["hi"] - ci_b["hi"]) < 1e-12
        print("    PASS: lo=%.4f hi=%.4f" % (ci_a["lo"], ci_a["hi"]))
        # T7: benefit sign
        print("  test 7: positive benefit when TSFM closer...")
        assert ci_a["point"] > 0 and ci_a["lo"] > 0
        print("    PASS: point=%.4f" % ci_a["point"])
        # T8: 6 month blocks
        print("  test 8: month-block structure...")
        assert ci_a["n_blocks"] == 6 and ci_a["n_rows"] == 108
        assert ci_a["cluster_labels"] == ["2024-07","2024-08","2024-09","2024-10","2024-11","2024-12"]
        print("    PASS: 6 blocks, Jul-Dec 2024")
        # T9: per-group stats
        print("  test 9: per-group stats...")
        assert m2["n_distinct_target_months"] == 6 and m2["n_distinct_categories"] == 2
        for ms in ("2024-07","2024-08","2024-09","2024-10","2024-11","2024-12"):
            assert ms in m2["per_target_month"] and m2["per_target_month"][ms]["n_rows"] > 0
        for hs in ("h1","h2","h3"): assert hs in m2["per_horizon"]
        print("    PASS")
        # T10: negative benefit
        print("  test 10: negative benefit when TSFM worse...")
        wr_tsfm = [dict(r) for r in tsfm_rows]
        for r in wr_tsfm: r["pred_tsfm"] = r["actual"] + 100.0
        wd = td+"/worse"; os.makedirs(wd)
        pd.DataFrame(wr_tsfm).to_parquet(wd+"/predictions.parquet", index=False)
        mw, _ = run_comparison(p_dir, wd, td+"/o10", n_bootstrap=200, seed=42, expected_mask=108)
        assert mw["bootstrap"]["month_block"]["tsfm_vs_prophet"]["point"] < 0
        print("    PASS: point=%.4f" % mw["bootstrap"]["month_block"]["tsfm_vs_prophet"]["point"])
        # T11: gate_pass
        print("  test 11: gate_pass=False...")
        assert m2["gate_pass"] is False
        print("    PASS")
        # T12: manifest
        print("  test 12: manifest...")
        with open(td+"/o6a/manifest.json") as f: man = json.load(f)
        assert man["run_id"] == RUN_ID and "prophet_predictions_sha256" in man["input"]
        assert man["join"]["strict_exact_match"] is True and man["causal"]["release_lag_months"] == 2
        print("    PASS")
    print("SELF-CHECK OK")
    return 0

# CLI
def main(argv=None):
    p = argparse.ArgumentParser(description="R8 month-block comparison: Prophet vs TSFM (R8-monthblock-compare)")
    p.add_argument("--prophet-run", default=None, help="Prophet run dir with predictions.parquet")
    p.add_argument("--tsfm-run", default=None, help="TSFM run dir with predictions.parquet")
    p.add_argument("--outdir", default=None, help="output dir for metrics.json and manifest.json")
    p.add_argument("--n-bootstrap", type=int, default=DEFAULT_N_BOOTSTRAP, help="month-block bootstrap resamples (default: %d)" % DEFAULT_N_BOOTSTRAP)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default: %d)" % DEFAULT_SEED)
    p.add_argument("--self-check", action="store_true", help="run self-checks with synthetic data")
    a = p.parse_args(argv)
    if a.self_check: return self_check()
    if not (a.prophet_run and a.tsfm_run and a.outdir):
        p.error("--prophet-run, --tsfm-run, and --outdir are required")
    run_comparison(a.prophet_run, a.tsfm_run, a.outdir, n_bootstrap=a.n_bootstrap, seed=a.seed)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())