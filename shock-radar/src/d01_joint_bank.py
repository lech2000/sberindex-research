"""D01-MV joint bank comparison at one total null false-alarm budget.

Separate calibration samples for channel scaling and joint threshold. A second,
explicitly retrospective ROC mode matches realized TEST null FA exactly.
"""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json
import numpy as np
import pandas as pd
from multicategory_shocks import prepare,noise,scores,inject,directions,RAW_SHA

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def combine(channel_scores,scales,channels):
 return np.maximum.reduce([channel_scores[m]/scales[m] for m in channels])

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ['raw','protocol','out']:p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();proto=json.loads(a.protocol.read_text())
 if sha(a.raw)!=RAW_SHA:raise ValueError('Frozen raw SHA differs')
 a.out.mkdir(parents=True,exist_ok=False);dump(a.out/'protocol.json',proto)
 _,_,_,_,corr,precision,training=prepare(pd.read_parquet(a.raw));dump(a.out/'training.json',training)
 banks={'base':proto['base_channels'],'extended':proto['extended_channels']};rows=[];calibration={};checks={}
 for family in proto['families']:
  scale_scores=scores(noise(np.random.default_rng(proto['channel_calibration_seed']),2000,12,corr,family),precision)
  scales={m:float(np.quantile(x[:,3:],.97)) for m,x in scale_scores.items()}
  if not all(v>0 for v in scales.values()):raise ValueError('Nonpositive channel scale')
  joint_sample=scores(noise(np.random.default_rng(proto['bank_calibration_seed']),2000,12,corr,family),precision)
  thresholds={b:float(np.quantile(combine(joint_sample,scales,ch)[:,3:],.97)) for b,ch in banks.items()}
  null_samples={b:[] for b in banks}
  for seed in range(proto['test_seeds']):
   null=scores(noise(np.random.default_rng(proto['test_seed_start']+seed),1000,12,corr,family),precision)
   for b,ch in banks.items():null_samples[b].append(combine(null,scales,ch)[:,3:].reshape(-1))
  pool={b:np.concatenate(v) for b,v in null_samples.items()}
  matched={b:float(np.quantile(v,.97)) for b,v in pool.items()}
  actual={b:float(np.mean(v>matched[b])) for b,v in pool.items()}
  for b in banks:
   if not np.isclose(actual[b],.03,rtol=0,atol=1e-12):raise ValueError('Matched total null FA differs from3%')
  calibration[family]={'channel_q97':scales,'joint_calibration_thresholds':thresholds,'matched_test_thresholds':matched,'matched_realized_total_null_fa':actual,
                       'independently_calibrated_realized_test_null_fa':{b:float(np.mean(v>thresholds[b])) for b,v in pool.items()},'null_points':len(next(iter(pool.values())))}
  # Both calibration and aggregation are frozen before scoring injected shocks.
  probe=noise(np.random.default_rng(123),2,8,corr,family);changed=probe.copy();changed[:,4:]*=100
  old=scores(probe,precision);new=scores(changed,precision)
  for b,ch in banks.items():np.testing.assert_array_equal(combine(old,scales,ch)[:,:4],combine(new,scales,ch)[:,:4])
  checks[family+'_future_mutation_joint_banks']=True
  for seed in range(proto['test_seeds']):
   rng=np.random.default_rng(proto['test_seed_start']+seed);base=noise(rng,1000,12,corr,family)
   idx=rng.choice(1000,proto['events_per_seed'],replace=False);onset=rng.integers(3,10,len(idx))
   for form in proto['forms']:
    direction=directions(rng,len(idx),len(corr),form)
    for amp in proto['amplitudes']:
     ss=scores(inject(base,idx,onset,direction,float(amp),form),precision)
     for b,ch in banks.items():
      score=combine(ss,scales,ch)
      for mode in proto['modes']:
       threshold=(thresholds if mode=='independent_calibration' else matched)[b]
       hit=(score[idx[:,None],onset[:,None]+np.arange(3)]>threshold).any(1)
       rows.append({'family':family,'seed':seed,'form':form,'amplitude':amp,'bank':b,'mode':mode,'hits':int(hit.sum()),'events':len(idx),'recall':float(hit.mean())})
 d=pd.DataFrame(rows);d.to_csv(a.out/'by-seed.csv',index=False)
 summary=d.groupby(['family','form','amplitude','bank','mode']).agg(hits=('hits','sum'),events=('events','sum')).reset_index();summary['recall']=summary.hits/summary.events;summary.to_csv(a.out/'summary.csv',index=False)
 comparisons=[]
 for key,g in d.groupby(['family','form','amplitude','mode']):
  wide=g.pivot(index='seed',columns='bank',values='hits');delta=(wide.extended-wide.base).to_numpy()
  ix=np.random.default_rng(20261005).integers(0,len(delta),(10000,len(delta)))
  boot=delta[ix].sum(1)/(len(delta)*proto['events_per_seed'])
  comparisons.append(dict(zip(['family','form','amplitude','mode'],key),extended_benefit_recall=float(delta.sum()/(len(delta)*proto['events_per_seed'])),ci95_seed_blocks=np.quantile(boot,[.025,.975]).tolist()))
 dump(a.out/'paired.json',comparisons);dump(a.out/'calibration.json',calibration)
 metrics={'status':'COMPUTED_EXPLORATORY','scientific_pass':False,'null_fa_budget_total':.03,'checks':checks,'calibration':calibration,
 'primary_comparisons':[x for x in comparisons if x['amplitude']==proto['primary_amplitude'] and x['mode']=='matched_realized_test_null'],
 'real_false_alarms':None,'legacy_univariate_bank_unchanged':True,'independent_holdout':False}
 dump(a.out/'metrics.json',metrics);dump(a.out/'manifest.json',{'checked_at':datetime.now(timezone.utc).isoformat(),'source_sha256':sha(Path(__file__)),'raw_sha256':sha(a.raw),'protocol_sha256':sha(a.protocol),'scientific_pass':False})
 print(json.dumps(metrics,ensure_ascii=False))
if __name__=='__main__':main()
