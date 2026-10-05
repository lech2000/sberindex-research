#!/usr/bin/env python3
"""R9 retrospective paired intervals using the existing validated R8 bootstrap.
Positive benefit = last-value abs error minus Prophet abs error.
No new fits, independent holdout, as-of claim, p-value or scientific PASS.
"""
from __future__ import annotations
import argparse,hashlib,json,random,sys
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from r8_monthblock_compare import _cluster_bootstrap
KEY=['territory_id','category','origin','target','horizon']
PRED=['pred_prophet','pred_last','pred_seasonal','pred_mean']
EXPECTED={1:73728,3:73662,6:73578,12:73824}

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def validate(d):
    if not set(KEY+PRED+['actual'])<=set(d):raise ValueError('missing columns')
    if d.empty or d.duplicated(KEY).any():raise ValueError('empty or duplicate keys')
    if not np.isfinite(d[PRED+['actual']].to_numpy(dtype=float)).all():raise ValueError('nonfinite input')
    if not d.horizon.isin(EXPECTED).all():raise ValueError('unknown horizon')
    origin=pd.PeriodIndex(d.origin,freq='M').asi8
    target=pd.PeriodIndex(d.target,freq='M').asi8
    if not np.equal(origin+d.horizon.to_numpy(),target).all():raise ValueError('origin+h != target')

def evaluate(d,reps=10000,seed=20261003):
    validate(d);out=[]
    for h,g in d.groupby('horizon',sort=True):
        keys=list(g[KEY].itertuples(index=False,name=None))
        errors={c:(g.actual-g[c]).abs() for c in PRED}
        benefit=errors['pred_last']-errors['pred_prophet']
        means=g.assign(benefit=benefit).groupby('target').benefit.agg(['sum','count','mean'])
        total=means['sum'].sum();n=int(means['count'].sum())
        jk={str(m):float((total-row['sum'])/(n-row['count'])) for m,row in means.iterrows()}
        point=float(benefit.mean())
        out.append({'horizon':int(h),'n_common':n,'expected_mask_rows':EXPECTED[int(h)],
          'excluded_before_pairing':EXPECTED[int(h)]-n,'n_target_months':len(means),
          'mae':{c:float(x.mean()) for c,x in errors.items()},'benefit_prophet_vs_last':point,
          'row_win_share':float((benefit>0).mean()),'zero_diff_share':float((benefit.abs()<1e-9).mean()),
          'per_target_month':{str(k):{'n':int(v['count']),'benefit':float(v['mean'])} for k,v in means.iterrows()},
          'month_block':_cluster_bootstrap(keys,benefit.tolist(),lambda k:str(k[3]),reps,random.Random(seed+int(h))),
          'municipality_secondary':_cluster_bootstrap(keys,benefit.tolist(),lambda k:str(k[0]),2000,random.Random(seed+100+int(h))),
          'jackknife_drop_target_month':jk,'max_territory_row_weight':float(g.groupby('territory_id').size().max()/n)})
    return {'checked_at':datetime.now(timezone.utc).isoformat(),'method':'existing R8 sum/count cluster bootstrap, percentile 95% interval',
       'seed':seed,'month_reps':reps,'benefit_convention':'positive means Prophet lower MAE than last value','results':out,
       'independent_new_holdout':False,'historical_asof_verified':False,'scientific_pass':False,
       'limits':['Six target-month blocks; percentile CI describes this sample only, not unseen future performance',
                'Adjacent months may remain dependent; no inferential significance or hypothesis rejection claimed',
                'Secondary territory CI cannot replace primary temporal uncertainty',
                'MAE unit remains source-value unit, not asserted rubles; raw-MAE estimand retained',
                'No model/horizon/threshold selection by these already viewed results']}

def self_check():
    rows=[]
    for month,n in [('2024-07',1),('2024-08',3),('2024-09',2)]:
      target=pd.Period(month,freq='M');origin=str(target-1)
      for i in range(n):rows.append(dict(territory_id=str(i),category='c',origin=origin,target=month,horizon=1,actual=10.,pred_prophet=9.,pred_last=7.,pred_seasonal=6.,pred_mean=5.))
    d=pd.DataFrame(rows);r=evaluate(d,100,42);r2=evaluate(d,100,42)
    for k in ['month_block','municipality_secondary']:assert r['results'][0][k]==r2['results'][0][k]
    assert r['results'][0]['benefit_prophet_vs_last']==2
    d['pred_prophet']=5.;assert evaluate(d,100,42)['results'][0]['benefit_prophet_vs_last']==-2
    for bad in [pd.concat([d,d.iloc[:1]],ignore_index=True),d.assign(actual=np.inf),d.assign(origin='2024-01')]:
      try:validate(bad)
      except ValueError:pass
      else:raise AssertionError('invalid input accepted')
    keys=[('a',)]*1+[('b',)]*3
    b=_cluster_bootstrap(keys,[10.,0.,0.,0.],lambda k:k[0],100,random.Random(42))
    assert b['point']==2.5
    print(json.dumps({'self_check':True,'checks':['benefit sign','fixed seed','weighted unequal blocks','duplicate reject','nonfinite reject','calendar horizon reject']}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--predictions',type=Path);p.add_argument('--out',type=Path);p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check:self_check();return
    if not a.predictions or not a.out:p.error('predictions and out required')
    if a.out.exists():raise FileExistsError('new run only')
    checksum=sha(a.predictions)
    if checksum!='b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44':raise ValueError('R9 independently audited prediction SHA mismatch')
    d=pd.read_parquet(a.predictions)
    if len(d)!=294570:raise ValueError('audited mask changed')
    r=evaluate(d);r['provenance']={'predictions_sha256':checksum,'code_sha256':sha(__file__),'bootstrap_code_sha256':sha(Path(__file__).with_name('r8_monthblock_compare.py')),'python':sys.version,'pandas':pd.__version__,'command':sys.argv}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'computed_retrospective','scientific_pass':False,'rows':len(d),'out':str(a.out)}))
if __name__=='__main__':main()
