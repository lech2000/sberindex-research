"""D01 финал: robust |rel|>3*rstd + персистентность 2 мес. Пишет alerts.parquet + alerts.json."""
import json
import numpy as np
import pandas as pd

K = 3.0
det = pd.read_parquet('shock-radar/runs/R5_cus.parquet').sort_values(['tid','cat','ym']).reset_index(drop=True)
reg = pd.read_parquet('shock-radar/events/registry.parquet')

def mad(s):
    return (s - s.median()).abs().median() * 1.4826
std_map = det[det['ym'] < '2024-03'].groupby(['tid','cat'])['rel'].agg(mad)
rstd = pd.to_numeric(det.set_index(['tid','cat']).index.map(std_map), errors='coerce')
det['rstd'] = np.where(pd.isna(np.asarray(rstd, dtype=float)) | (np.asarray(rstd, dtype=float) == 0), 0.05, np.asarray(rstd, dtype=float))
det['hot'] = det['rel'].abs() > K * det['rstd']
det['prev_hot'] = det.groupby(['tid','cat'])['hot'].shift(1).fillna(False).infer_objects(copy=False).astype(bool)
det['alarm'] = det['hot'] & det['prev_hot']

def score(rt, tf):
    hits, used, delays = 0, set(), []
    for _, e in rt.iterrows():
        for _, a in det[(det['tid']==e['tid']) & (det['cat']==e['cat']) & det['alarm']].sort_values('ym').iterrows():
            d = (pd.Period(a['ym'], freq='M') - pd.Period(e['onset'], freq='M')).n
            if abs(d) <= 2:
                hits += 1; delays.append(d); used.add((a['tid'],a['cat'],a['ym'])); break
    fa = sum(1 for _, a in det[det['alarm'] & (det['ym'] >= tf)].iterrows() if (a['tid'],a['cat'],a['ym']) not in used)
    return {'events': len(rt), 'recall': round(hits/max(1,len(rt)),3),
            'precision': round(hits/max(1,hits+fa),4), 'fa': fa,
            'delay_mean': round(float(np.mean(delays)),2) if delays else None,
            'calibration': 'lead 0=в месяц onset: детекция, не предупреждение (lag 2m)'}

val = score(reg[reg['onset']<'2024-07'], '2024-03')
test = score(reg[reg['onset']>='2024-07'], '2024-07')
alerts = det[det['alarm']][['tid','cat','ym','rel','rstd','cus']].copy()
alerts.to_parquet('shock-radar/runs/R5/alerts.parquet', index=False)
json.dump({'method': 'D01 threshold: |rel|>3*rstd(MAD,train) + persistence 2m',
           'validation': val, 'test': test,
           'verdict': 'технический тест на синтетике: recall держится, precision низкая — раннее предупреждение НЕ заявляется'},
          open('shock-radar/runs/R5/alerts.json','w'), ensure_ascii=False, indent=1)
print('VAL:', json.dumps(val, ensure_ascii=False))
print('TEST:', json.dumps(test, ensure_ascii=False))
print('alerts:', len(alerts))
