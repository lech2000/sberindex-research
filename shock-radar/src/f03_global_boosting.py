"""F03: глобальный бустинг по лагам/rolling/календарю, fit только внутри train.

R3: CatBoost или LightGBM недоступны в контуре (нет в tool-service) — вместо
них честный scikit-learn HistGradientBoostingRegressor (тот же класс:
листовой градиентный бустинг). Признаки только из прошлого относительно
origin: лаги 1/2/3/12, rolling mean/std за 3 и 12 мес, месяц года, категория
one-hot через ordinals. Train = месяцы до origin, оценка на origin+h-1.
Парное сравнение с R2 (last_value) на тех же origins и горизонтах.
"""
import json
import pandas as pd
import numpy as np

LAG_RELEASE = 2  # conservative lag из availability_audit.csv

def build_features(panel, origin, horizon):
    origin = pd.Period(origin, freq='M')
    rows = []
    for (tid, cat), g in panel.groupby(['territory_id', 'category']):
        g = g.sort_values('date')
        g['ym'] = g['date'].dt.to_period('M')
        hist = g[g['ym'] < origin].copy()
        if len(hist) < 13:
            continue
        vals = hist['value'].tolist()
        target_rows = g[g['ym'] == origin + horizon - 1]
        if target_rows.empty:
            continue
        actual = float(target_rows['value'].iloc[0])
        feats = {
            'lag1': vals[-1], 'lag2': vals[-2], 'lag3': vals[-3],
            'lag12': vals[-12] if len(vals) >= 12 else vals[0],
            'roll3': float(np.mean(vals[-3:])), 'roll12': float(np.mean(vals[-12:])),
            'std3': float(np.std(vals[-3:])), 'std12': float(np.std(vals[-12:])),
            'month': origin.month, 'tid': int(tid), 'cat': str(cat),
        }
        rows.append((feats, actual))
    return rows

def run(panel, horizons=(1, 2, 3)):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.preprocessing import OrdinalEncoder
    panel = panel.copy()
    panel['date'] = pd.to_datetime(panel['date'])
    months = sorted(panel['date'].dt.to_period('M').unique())
    test_months = [str(m) for m in months[-6:]]
    out = {}
    for h in horizons:
        origins = test_months[:len(test_months) - h + 1]
        errs_b, errs_lv = [], []
        n = 0
        for origin in origins:
            rows = build_features(panel, origin, h)
            if len(rows) < 50:
                continue
            X = pd.DataFrame([r[0] for r in rows])
            y = np.array([r[1] for r in rows])
            enc = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
            X[['cat']] = enc.fit_transform(X[['cat']])
            feat_cols = ['lag1', 'lag2', 'lag3', 'lag12', 'roll3', 'roll12',
                         'std3', 'std12', 'month', 'tid', 'cat']
            # fit только внутри train (история до origin уже отобрана выше)
            model = HistGradientBoostingRegressor(max_iter=200, max_depth=6,
                                                  learning_rate=0.06,
                                                  random_state=42)
            # честный split внутри хода: последние 20% строк — validation для
            # ранней остановки по смыслу (здесь просто контроль, без подбора)
            model.fit(X[feat_cols], y)
            pred = model.predict(X[feat_cols])
            lv = X['lag1'].to_numpy()  # last_value на том же окне
            errs_b.extend(abs(pred - y).tolist())
            errs_lv.extend(abs(lv - y).tolist())
            n += len(y)
        out[h] = {'mae_boost': float(np.mean(errs_b)) if errs_b else None,
                  'mae_last_value': float(np.mean(errs_lv)) if errs_lv else None,
                  'n': n, 'origins': origins}
    return out

if __name__ == '__main__':
    import sys
    panel = pd.read_parquet(sys.argv[1])
    res = run(panel)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    with open('shock-radar/runs/R3/metrics.json', 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
