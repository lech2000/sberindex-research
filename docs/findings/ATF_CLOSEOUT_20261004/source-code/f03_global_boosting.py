"""F03: глобальный бустинг по лагам/rolling/календарю — причинная версия (ATF-M6).

Что изменено 01.10.2026 относительно версии R3 (runs/R3/metrics.json теперь
НЕДЕЙСТВИТЕЛЕН, см. runs/R3/INVALIDATED.md):
  1. История признаков — только месяцы <= O - RELEASE_LAG. В R3 константа
     LAG_RELEASE=2 была объявлена и не применялась: бралась история до O-1.
  2. Цель — месяц O + h (соглашение r8_prophet_pilot), а не O + h - 1.
  3. Обучение — на строках более ранних origins O' < O, чьи цели O' + h уже
     опубликованы на O (O' + h <= O - RELEASE_LAG). Оценка — на строках O.
     В R3 fit и predict шли по одним и тем же строкам, MAE был внутривыборочным.
  4. Реальный календарь: 12 подряд идущих месяцев без пропусков (без
     «склейки» пропусков). Строки с дырой пропускаются и пересчитываются в аудите.

Признаки прежние: лаги 1/2/3/12 (по последним доступным наблюдениям), rolling
mean/std за 3 и 12 мес, месяц origin, tid, категория. Базовая линия —
lastavailable: значение за O - RELEASE_LAG. Модель: sklearn
HistGradientBoostingRegressor (CatBoost/LightGBM в контуре недоступны).

Запуск:  python3 f03_global_boosting.py panel.parquet [--out DIR] [--self-check]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

try:
    from . import leakage_guard as lg
except ImportError:  # запуск как скрипта из src/
    import leakage_guard as lg

FEATURES = ['lag1', 'lag2', 'lag3', 'lag12', 'roll3', 'roll12',
            'std3', 'std12', 'month', 'tid', 'cat']
WINDOW = 12  # подряд идущих месяцев истории


def series_from_panel(panel):
    p = panel.copy()
    p['date'] = pd.to_datetime(p['date'])
    p['m'] = p['date'].dt.year * 12 + p['date'].dt.month - 1
    out = {}
    for (tid, cat), g in p.groupby(['territory_id', 'category']):
        out[(int(tid), str(cat))] = dict(zip(g['m'].tolist(),
                                             g['value'].astype(float).tolist()))
    return out


def build_features(series, origin, horizon, lag=lg.RELEASE_LAG):
    """Строки origin: [(key, feats, target, target_month)] и счётчик пропусков."""
    o = lg.month_index(origin)
    last = lg.last_allowed_month(o, lag)
    tgt = lg.target_month(o, horizon)
    rows, skipped = [], 0
    window = range(last - WINDOW + 1, last + 1)
    for (tid, cat), s in series.items():
        if any(m not in s for m in window) or tgt not in s:
            skipped += 1
            continue
        vals = [s[m] for m in window]
        feats = {
            'lag1': vals[-1], 'lag2': vals[-2], 'lag3': vals[-3], 'lag12': vals[-12],
            'roll3': float(np.mean(vals[-3:])), 'roll12': float(np.mean(vals)),
            'std3': float(np.std(vals[-3:])), 'std12': float(np.std(vals)),
            'month': o % 12 + 1, 'tid': tid, 'cat': cat,
        }
        rows.append(((tid, cat), feats, s[tgt], tgt))
    lg.assert_history_as_of(list(window), o, lag, 'F03 features')  # tripwire на будущие правки
    return rows, skipped


def feature_frame(panel, origin, horizon, lag=lg.RELEASE_LAG):
    """Только признаки (без цели), для prefix-mutation теста."""
    rows, _ = build_features(series_from_panel(panel), origin, horizon, lag)
    df = pd.DataFrame([r[1] for r in rows])
    return df.sort_values(['tid', 'cat']).reset_index(drop=True) if len(df) else df


def _xy(rows):
    X = pd.DataFrame([r[1] for r in rows])
    y = np.array([r[2] for r in rows], dtype=float)
    return X, y


def run(panel, horizons=(1, 2, 3), n_test_origins=6, lag=lg.RELEASE_LAG, seed=42):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.preprocessing import OrdinalEncoder

    series = series_from_panel(panel)
    months = sorted({m for s in series.values() for m in s})
    last_month = months[-1]
    test_origins = months[-n_test_origins:]
    cache = {}

    def rows_for(origin, h):
        key = (origin, h)
        if key not in cache:
            cache[key] = build_features(series, origin, h, lag)
        return cache[key]

    out = {}
    for h in horizons:
        errs_b, errs_lv = [], []
        evaluated, skipped, train_origins = [], {}, {}
        for o in test_origins:
            name = lg._ym(o)
            if lg.target_month(o, h) > last_month:
                skipped[name] = 'target_after_panel'
                continue
            train_rows, tr_origins = [], []
            for op in range(months[0], o):
                if lg.target_month(op, h) > lg.last_allowed_month(o, lag):
                    continue  # цель ещё не опубликована на O
                r, _ = rows_for(op, h)
                if r:
                    train_rows.extend(r)
                    tr_origins.append(lg._ym(op))
            ev_rows, _ = rows_for(o, h)
            if len(train_rows) < 50 or not ev_rows:
                skipped[name] = 'insufficient_training_history'
                continue
            lg.assert_targets_available([r[3] for r in train_rows], o, lag)
            lg.assert_eval_target_in_future([r[3] for r in ev_rows], o, lag)
            Xtr, ytr = _xy(train_rows)
            Xev, yev = _xy(ev_rows)
            enc = OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1)
            Xtr[['cat']] = enc.fit_transform(Xtr[['cat']])
            Xev[['cat']] = enc.transform(Xev[['cat']])
            model = HistGradientBoostingRegressor(max_iter=200, max_depth=6,
                                                  learning_rate=0.06, random_state=seed)
            model.fit(Xtr[FEATURES], ytr)
            pred = model.predict(Xev[FEATURES])
            errs_b.extend(np.abs(pred - yev).tolist())
            errs_lv.extend(np.abs(Xev['lag1'].to_numpy() - yev).tolist())
            evaluated.append(name)
            train_origins[name] = tr_origins
        out[h] = {
            'mae_boost': float(np.mean(errs_b)) if errs_b else None,
            'mae_last_available': float(np.mean(errs_lv)) if errs_lv else None,
            'n': len(errs_b), 'origins': evaluated, 'skipped': skipped,
            'train_origins': train_origins, 'release_lag': lag, 'causal': True,
        }
    return out


def self_check():
    """Prefix-mutation на синтетической панели + положительный контроль guard."""
    rng = np.random.default_rng(0)
    rows = []
    for tid in range(1, 6):
        for cat in ('a', 'b'):
            base = rng.uniform(100, 200)
            for k in range(24):
                rows.append({'territory_id': tid, 'category': cat,
                             'date': pd.Timestamp(2023 + k // 12, k % 12 + 1, 1),
                             'value': base * (1 + 0.01 * k) + rng.normal(0, 3)})
    panel = pd.DataFrame(rows)
    for origin in ('2024-06', '2024-09'):
        for h in (1, 2, 3):
            lg.prefix_mutation_test(lambda p, o, h=h: feature_frame(p, o, h), panel, origin)
    return dict(lg.self_check(), f03_prefix_invariant=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('panel', nargs='?')
    ap.add_argument('--out', default='shock-radar/runs/F03_causal')
    ap.add_argument('--self-check', action='store_true')
    a = ap.parse_args()
    if a.self_check:
        print(json.dumps(self_check(), ensure_ascii=False))
        raise SystemExit(0)
    res = run(pd.read_parquet(a.panel))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'metrics.json'), 'w') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
