"""Match new simple forecasts to preserved conditional Prophet pilot; no refits."""
import argparse,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
from r9_strong_baselines import KEY


def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline',type=Path,required=True);ap.add_argument('--pilot',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
 if a.out.exists():raise FileExistsError('new file required')
 p=pd.read_parquet(a.baseline);q=pd.read_parquet(a.pilot);q.territory_id=q.territory_id.astype(str)
 p=p.drop(columns=['conditional_prophet_yearly'],errors='ignore');x=p.merge(q[KEY+['conditional_prophet_yearly']],on=KEY,validate='one_to_one');rows=[]
 for (w,h),g in x.groupby(['window','horizon']):
  original=len(g);models=['category_seasonal','profile_ses','conditional_ses','growth_naive3','conditional_prophet_yearly'];g=g[g[models].notna().all(axis=1)]
  if not len(g):continue
  comp={}
  for m in models[:-1]:
   de=np.abs(g.actual-g[m])-np.abs(g.actual-g.conditional_prophet_yearly)
   b=pd.DataFrame({'target':g.target,'delta':de}).groupby('target').delta.agg(['sum','count']);rng=np.random.default_rng(20261004+h);ix=rng.integers(0,len(b),(10000,len(b)))
   samples=b['sum'].to_numpy()[ix].sum(1)/b['count'].to_numpy()[ix].sum(1)
   comp[m]={'error_delta_vs_conditional_prophet':float(de.mean()),'ci95_by_target_month':np.quantile(samples,[.025,.975]).tolist(),'n_blocks':len(b)}
  rows.append({'window':w,'horizon':int(h),'original_rows':original,'n':len(g),'series':len(g[['territory_id','category']].drop_duplicates()),'mae':{m:float(np.abs(g.actual-g[m]).mean()) for m in models},'comparisons':comp})
 sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
 o={'client_date':'2026-10-04','pilot_sha256':sha(a.pilot),'baseline_sha256':sha(a.baseline),'code_sha256':sha(Path(__file__)),
    'status':'EXPLORATORY_120_SERIES_EQUAL_AGGREGATE_INPUT','results':rows,'limits':['Same viewed sample; not independent holdout','conditional Prophet uses shared category normalization/season factor; functional forms differ','Growth naive3 uses own-series information only','No extra Prophet refits']}
 a.out.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n');print(json.dumps(rows,ensure_ascii=False))
if __name__=='__main__':main()
