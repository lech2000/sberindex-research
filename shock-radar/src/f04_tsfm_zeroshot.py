"""F04: TSFM zero-shot (Chronos-T5-tiny) на панели расходов, тот же evaluator что R2/R3.

Лестница R4: один полноценный zero-shot опыт, фиксированная ревизия весов,
ресурсы, время, общий evaluator (expanding origins 2024-07..12, MAE micro).
Веса: amazon/chronos-t5-tiny (8.4M, ревизия фиксируется в model_card).
Без ковариат (чистый zero-shot); fit нет вовсе — веса заморожены.
Выборка: все устойчивые МО x категории (те же 1896 tid, что A2-панель),
h=1..3. Батчами по 256 рядов для скорости CPU.
"""
import json, time
import numpy as np
import pandas as pd
import torch

MODEL_ID = "amazon/chronos-t5-tiny"

def run(panel_path, out_path, batch=128, sample_tids=None, device=None):
    from chronos import ChronosPipeline
    t0 = time.time()
    device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
    pipe = ChronosPipeline.from_pretrained(MODEL_ID, device_map=device, torch_dtype=torch.float32)
    rev = getattr(getattr(pipe, 'model', None), 'config', None)
    df = pd.read_parquet(panel_path)
    df['date'] = pd.to_datetime(df['date'])
    months = sorted(df['date'].dt.to_period('M').unique().astype(str))
    test_months = months[-6:]
    series = {}
    for (tid, cat), g in df.groupby(['territory_id', 'category']):
        g = g.sort_values('date')
        vals = dict(zip(g['date'].dt.to_period('M').astype(str), g['value'].astype(float)))
        hist = [vals[m] for m in months if m in vals]
        if len(hist) >= 14:
            series[(int(tid), str(cat))] = (hist, vals)
    if sample_tids:
        series = {k: v for k, v in series.items() if k[0] in sample_tids}
    out = {}
    for h in (1, 2, 3):
        origins = test_months[:len(test_months) - h + 1]
        errs, lv_errs, n = [], [], 0
        keys = list(series.keys())
        for i in range(0, len(keys), batch):
            chunk = keys[i:i+batch]
            ctx, targets, lvs = [], [], []
            for k in chunk:
                hist, vals = series[k]
                for o in origins:
                    oi = months.index(o)
                    c = hist[max(0, oi-18):oi]
                    if len(c) < 12:
                        continue
                    t = vals.get(months[oi + h - 1])
                    if t is None:
                        continue
                    ctx.append(torch.tensor(c, dtype=torch.float32))
                    targets.append(t)
                    lvs.append(c[-h])
            if not ctx:
                continue
            with torch.no_grad():
                fc = pipe.predict(ctx, prediction_length=h)
            med = fc.numpy()[..., h-1].mean(axis=1) if fc.numpy().ndim == 3 else fc.numpy()[:, h-1] if fc.numpy().ndim == 2 else fc.numpy()
            for p, t, l in zip(med, targets, lvs):
                errs.append(abs(float(p) - t))
                lv_errs.append(abs(l - t))
                n += 1
        out[h] = {'mae_tsfm': float(np.mean(errs)) if errs else None,
                  'mae_last_value': float(np.mean(lv_errs)) if lv_errs else None,
                  'n': n, 'origins': origins}
    meta = {'model': MODEL_ID, 'params': sum(p.numel() for p in pipe.model.parameters()),
            'time_s': round(time.time() - t0, 1), 'device': device,
            'evaluator': 'expanding origins 2024-07..12, same as R2/R3'}
    res = {'metrics': out, 'meta': meta}
    json.dump(res, open(out_path, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print('meta:', json.dumps(meta))
    return res

if __name__ == '__main__':
    import sys
    run(sys.argv[1], 'shock-radar/runs/R4/metrics.json')
