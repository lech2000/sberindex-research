"""D01: пороговый детектор на остатках бустинга R3 + оценка на реестре R5.

Детектор: остаток = |факт − прогноз бустинга| / rolling_std(3); тревога если
z > порог. Порог подбирается на validation (события с onset до 2024-07),
тест — события с onset >= 2024-07. Метрики: precision/recall/delay/false alarms.
Прогноз бустинга считается тем же кодом что F03 (HistGradientBoosting).
"""
import json
import numpy as np
import pandas as pd

def residuals(panel, reg, model_seed=42):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.preprocessing import OrdinalEncoder
    panel = panel.copy()
    panel['date'] = pd.to_datetime(panel['date'])
    panel['ym'] = panel['date'].dt.to_period('M').astype(str)
    months = sorted(panel['ym'].unique())
    # инжектим сдвиги реестра в копию
    inj = panel.set_index(['territory_id', 'category', 'ym'])['value'].copy()
    for _, e in reg.iterrows():
        o = months.index(e['onset'])
        for k in range(e['length_m']):
            m = months[o + k]
            key = (e['tid'], e['cat'], m)
            if key in inj.index:
                inj.loc[key] *= (1 + e['rel_size'] if e['direction'] == 'up'
                                 else 1 - e['rel_size'])
    rows = []
    for (tid, cat), g in panel.groupby(['territory_id', 'category']):
        g = g.sort_values('date')
        vals = dict(zip(g['ym'], g['value'].astype(float)))
        hist = [vals[m] for m in months if m in vals]
        if len(hist) < 13:
            continue
        for o in months[12:]:
            oi = months.index(o)
            c = hist[max(0, oi-18):oi]
            feats = [c[-1], c[-2], c[-3], c[-12] if len(c) >= 12 else c[0],
                     float(np.mean(c[-3:])), float(np.mean(c[-12:])),
                     float(np.std(c[-3:])), float(np.std(c[-12:])),
                     oi % 12, float(tid)]
            rows.append((tid, cat, o, feats, inj.get((tid, cat, o), hist[oi] if oi < len(hist) else np.nan)))
    X = pd.DataFrame([r[3] for r in rows])
    X.columns = ['lag1','lag2','lag3','lag12','roll3','roll12','std3','std12','month','tid']
    X['cat'] = [r[1] for r in rows]
    enc = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
    X[['cat']] = enc.fit_transform(X[['cat']])
    cols = list(X.columns)
    model = HistGradientBoostingRegressor(max_iter=200, max_depth=6, learning_rate=0.06, random_state=model_seed)
    # fit ТОЛЬКО на чистых значениях (без инжекта): признаки содержат инжект
    # через лаги, а цель для fit — чистая, иначе модель учит сдвиги нормой
    clean = {}
    for (tid2, cat2), g in panel.groupby(['territory_id', 'category']):
        for ym_, v_ in zip(g['ym'], g['value'].astype(float)):
            clean[(tid2, cat2, ym_)] = v_
    yclean = np.array([clean.get((r[0], r[1], r[2]), np.nan) for r in rows], dtype=float)
    okc = np.isfinite(yclean) & np.isfinite(X[cols].to_numpy()).all(axis=1)
    model.fit(X[cols][okc], yclean[okc])
    y = np.array([r[4] for r in rows], dtype=float)
    ok = np.isfinite(y) & np.isfinite(X[cols].to_numpy()).all(axis=1)
    idx = [i for i, o in enumerate(ok) if o]
    pred_full = np.full(len(rows), np.nan)
    pred_full[idx] = model.predict(X[cols][ok])
    pred = pred_full
    out = pd.DataFrame({'tid': [r[0] for r in rows], 'cat': [r[1] for r in rows],
                        'ym': [r[2] for r in rows], 'actual_inj': [r[4] for r in rows],
                        'pred': pred})
    out['resid'] = (out['actual_inj'] - out['pred']).abs()
    out['roll_std'] = out.groupby(['tid','cat'])['resid'].transform(
        lambda s: s.shift(1).rolling(3, min_periods=3).mean())
    out['z'] = out['resid'] / out['roll_std'].replace(0, np.nan)
    return out.dropna(subset=['z'])

def evaluate(det, reg, threshold, test_from='2024-07', window=1, cooldown=3):
    months_cache = {}
    reg_test = reg[reg['onset'] >= test_from].copy()
    hits, delays, fa = 0, [], 0
    used_alarms = set()
    for _, e in reg_test.iterrows():
        cand = det[(det['tid'] == e['tid']) & (det['cat'] == e['cat']) & (det['z'] > threshold)].copy()
        cand = cand.sort_values('ym')
        # cooldown: не чаще одной тревоги в 3 мес на ряд
        cand = cand.groupby('tid', group_keys=False).apply(
            lambda g: g[pd.to_datetime(g['ym']).diff().dt.days.fillna(999) > cooldown*28])
        found = False
        for _, a in cand.iterrows():
            d = abs((pd.Period(a['ym'], freq='M') - pd.Period(e['onset'], freq='M')).n)
            if d <= window:
                hits += 1
                delays.append(d)
                used_alarms.add((a['tid'], a['cat'], a['ym']))
                found = True
                break
        _ = found
    fa = sum(1 for _, a in det[(det['z'] > threshold) & (det['ym'] >= test_from)].iterrows()
             if (a['tid'], a['cat'], a['ym']) not in used_alarms)
    return {'threshold': threshold, 'events': len(reg_test),
            'recall': round(hits/len(reg_test), 3) if len(reg_test) else None,
            'delay_mean': round(float(np.mean(delays)), 2) if delays else None,
            'false_alarms': fa}

if __name__ == '__main__':
    panel = pd.read_parquet('data/raw/sberindex-data-sense-2025/8_consumption.parquet')
    reg = pd.read_parquet('shock-radar/events/registry.parquet')
    det = residuals(panel, reg)
    det.to_parquet('shock-radar/runs/R5_resid.parquet', index=False)
    # подбор порога на validation (onset < 2024-07)
    res = [evaluate(det, reg[reg['onset'] < '2024-07'], t, test_from='2024-03') for t in (2.0, 2.5, 3.0, 3.5, 4.0)]
    print(json.dumps(res, ensure_ascii=False, indent=1))
    best = max(res, key=lambda r: (r['recall'] or 0, -r['false_alarms']))
    test = evaluate(det, reg, best['threshold'], test_from='2024-07')
    print('BEST thr:', best['threshold'], 'TEST:', json.dumps(test, ensure_ascii=False))
    json.dump({'validation': res, 'test': test, 'threshold': best['threshold']},
              open('shock-radar/runs/R5/alerts.json','w'), ensure_ascii=False, indent=1)
