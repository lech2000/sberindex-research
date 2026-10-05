#!/usr/bin/env python3
"""Panel coverage and descriptive official flood cases; no causal TP/FP claims."""
import argparse
from datetime import datetime, timezone
import hashlib,json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from d02_d03_detectors import d01_alarms,d02_alarms,d03_alarms,apply_cooldown,truncate_budget_monthly
from r9_category_seasonal import RAW_SHA,R9_SHA,prepare
DICT_SHA='f25088539a896cdc834d77c8792d0e6ac909d8649b06d65f69215ce12a8eaf4a'
ATLAS_SHA='8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93'
ASSIGN_SHA='7f4d3a69a2b1449f6ac793494603951b767c737475b4f2b4ccece01e54b1116b'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def coverage(dictionary,frames):
 if dictionary.territory_id.duplicated().any():raise ValueError('ambiguous dictionary territory_id')
 all_regions=set(dictionary.region_name);out={};rows=[]
 for name,df in frames.items():
  ids=set(df.territory_id.astype(int));unknown=ids-set(dictionary.territory_id.astype(int))
  if unknown:raise ValueError('unmapped territory IDs')
  sub=dictionary[dictionary.territory_id.isin(ids)]
  missing=sorted(all_regions-set(sub.region_name))
  out[name]={'n_rows':len(df),'n_municipalities':len(ids),'n_regions':sub.region_name.nunique(),
      'missing_regions_relative_to_dictionary':missing,'n_missing_regions':len(missing)}
  for reg,g in dictionary.groupby('region_name'):
   tids=set(g.territory_id.astype(int));present=ids&tids
   rows.append({'cohort':name,'region_name':str(reg),'dictionary_municipalities':len(tids),'observed_municipalities':len(present),
      'rows':int(df.territory_id.astype(int).isin(tids).sum())})
 return out,pd.DataFrame(rows)

def signal(raw):
 d=prepare(raw).sort_values(['territory_id','category','month']).copy()
 d['previous_value']=d.groupby(['territory_id','category']).value.shift()
 d['previous_month']=d.groupby(['territory_id','category']).month.shift()
 adj=pd.PeriodIndex(d.previous_month.fillna('1900-01'),freq='M').asi8+1==pd.PeriodIndex(d.month,freq='M').asi8
 d=d[adj & d.previous_value.notna()].copy()
 d['rel']=(d.value-d.previous_value)/np.maximum(d.previous_value.abs(),1e-9)
 d['tid']=d.territory_id.astype(int);d['cat']=d.category;d['ym']=d.month
 counts=d[d.ym<'2024-03'].groupby(['tid','cat']).size()
 index=pd.MultiIndex.from_frame(d[['tid','cat']]);keep=counts.reindex(index).fillna(0).to_numpy()>=6
 return d.loc[keep,['tid','cat','ym','rel']].reset_index(drop=True)

def self_check():
 a=pd.DataFrame({'territory_id':[1]*3,'category':['c']*3,'date':['2023-01','2023-02','2023-04'],'value':[10,20,100]})
 # Build sufficient history but preserve a gap: never compare April with February.
 hist=pd.DataFrame({'territory_id':[1]*12,'category':['c']*12,'date':pd.period_range('2022-01','2022-12',freq='M').astype(str),'value':[10]*12})
 d=signal(pd.concat([hist,a],ignore_index=True));assert '2023-04' not in set(d.ym)
 # Budget is selected alerts, not false alarms; no future month can displace April.
 alerts=pd.DataFrame([dict(method='D01',tid=i,cat='c',ym=m,score=float(i)) for m in ['2024-04','2024-05'] for i in range(4)])
 full=truncate_budget_monthly(alerts,2);prefix=truncate_budget_monthly(alerts[alerts.ym=='2024-04'],2)
 pd.testing.assert_frame_equal(full[full.ym=='2024-04'].reset_index(drop=True),prefix.reset_index(drop=True))
 print(json.dumps({'self_check':True,'checks':['calendar gaps not compressed','monthly budget future-prefix invariance']}))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['raw','dictionary','atlas','assignments','predictions','events','threshold_manifest','outdir']:p.add_argument('--'+name.replace('_','-'),type=Path)
 p.add_argument('--self-check',action='store_true');a=p.parse_args()
 if a.self_check:self_check();return
 if any(getattr(a,x) is None for x in ['raw','dictionary','atlas','assignments','predictions','events','threshold_manifest','outdir']):p.error('all paths required')
 if a.outdir.exists():raise FileExistsError('new run only')
 for name,expected in [('raw',RAW_SHA),('dictionary',DICT_SHA),('atlas',ATLAS_SHA),('assignments',ASSIGN_SHA),('predictions',R9_SHA)]:
  if sha(getattr(a,name))!=expected:raise ValueError(name+' frozen SHA mismatch')
 raw,dictionary,atlas,assign,preds=[pd.read_parquet(getattr(a,n)) for n in ['raw','dictionary','atlas','assignments','predictions']]
 prepare(raw);events=json.loads(a.events.read_text());thresholds=json.loads(a.threshold_manifest.read_text())
 cfg=thresholds['fitted_on_validation_only'];expected={'D01':{'k':2.5},'D02':{'delta':0.1,'lambda':0.4},'D03':{'tau':0.3}}
 if cfg!=expected or thresholds['monthly_budget']!=24:raise ValueError('original frozen R7 parameters changed')
 a.outdir.mkdir(parents=True)
 cov,regions=coverage(dictionary,{'raw':raw,'atlas':atlas,'r9':preds})
 regions.to_csv(a.outdir/'coverage_by_region.csv',index=False)
 (a.outdir/'coverage.json').write_text(json.dumps(cov,ensure_ascii=False,indent=2)+'\n')
 # Freeze before bank evaluation; never tune against the selected real examples.
 protocol={'event_registry_sha256':sha(a.events),'threshold_manifest_sha256':sha(a.threshold_manifest),
   'parameters':cfg,'monthly_selected_alert_budgets':[24,96],'primary_budget':24,
   'sensitivity_budget':96,'cooldown_months':3,'training_calibration_end_exclusive':'2024-03',
   'match_window':'2024-03..2024-05 (monthly coincidence, not economic-change truth)',
   'story_selection':'three municipalities documented in the fixed official intake, not ranked by spending or detector hits',
   'no_injected_data':True,'is_independent_test':False,'scientific_pass':False}
 (a.outdir/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2)+'\n')
 cases=[];tid_map={}
 wide=prepare(raw).pivot(index=['territory_id','category'],columns='month',values='value')
 for event in events['events']:
  if event['scope']!='municipality':continue
  mo=dictionary[dictionary.name_short==event['entity_name']]
  if len(mo)!=1:raise ValueError('ambiguous municipal event identity')
  meta=mo.iloc[0];tid=int(meta.territory_id);tid_map[event['entity_name']]=tid;story=[]
  for cat in sorted(raw.category.unique()):
   s=wide.loc[(str(tid),cat)];entry={'category':str(cat)}
   for yr in ['2023','2024']:
    v={m:float(s[yr+'-'+m]) for m in ['03','04','05']}
    entry[yr]={'values_mar_apr_may':v,'april_mom_pct':100*(v['04']/v['03']-1),'may_mom_pct':100*(v['05']/v['04']-1)}
   story.append(entry)
  labels=assign[(assign.territory_id==tid)&assign.month.isin(['2024-03','2024-04','2024-05'])].to_dict('records')
  cases.append({'event_id':event['event_id'],'municipality':event['entity_name'],'territory_id':tid,'oktmo':str(meta.oktmo),
    'region':str(meta.region_name),'source_url':event['source_url'],'published_date':event['source_claimed_published_date'],
    'event_month':'2024-04','is_economic_effect_proof':False,'spending':story,'atlas_identity_assignments':labels})
 det=signal(raw);det.to_parquet(a.outdir/'signal.parquet',index=False)
 print(json.dumps({'stage':'signal_ready','rows':len(det),'series':det.groupby(['tid','cat']).ngroups}),flush=True)
 builders=[('D01',lambda:d01_alarms(det,'rel',cfg['D01']['k'])),
  ('D02',lambda:d02_alarms(det,'rel',cfg['D02']['delta'],cfg['D02']['lambda'])),
  ('D03',lambda:d03_alarms(det,'rel',cfg['D03']['tau'],strict_log_support=True))]
 counts=[];frames=[]
 for name,build in builders:
  cooled=apply_cooldown(build(),3);period=cooled[cooled.ym>='2024-03']
  for budget in [24,96]:
   kept=truncate_budget_monthly(period,budget);kept['budget']=budget;frames.append(kept)
   counts.append({'method':name,'monthly_selected_alert_budget':budget,'n_selected':len(kept),
    'counts_by_month':{str(k):int(v) for k,v in kept.groupby('ym').size().items()},
    'false_alarm_count':None,'precision':None,'recall':None})
   for case in cases:
    sub=kept[(kept.tid==case['territory_id']) & kept.ym.between('2024-03','2024-05')]
    case.setdefault('detector_coincidences',[]).append({'method':name,'budget':budget,'alerts':sub.to_dict('records'),
       'has_any_category_alert_in_window':bool(len(sub)),'interpretation':'post-selected documented-event coincidence; not verified true positive'})
  print(json.dumps({'stage':'detector_complete','method':name}),flush=True)
 pd.concat(frames,ignore_index=True).to_parquet(a.outdir/'alerts.parquet',index=False)
 metrics={'checked_at':datetime.now(timezone.utc).isoformat(),'coverage':cov,'n_official_events':len(events['events']),
   'n_sources':len(events['sources']),'n_local_case_stories':len(cases),'protocol':protocol,'cases':cases,
   'bank':counts,'scientific_pass':False,'historical_asof_verified':False,
   'limits':['Cases are descriptive and share a flood family; selection was already suggested/viewed, not independent evaluation',
    'A documented disaster is not a labeled causal economic shift in every category; no recall/precision/false-alarm estimand assigned',
    '24/96 are caps on selected alerts per month, not verified false-alarm counts',
    'Existing R7 thresholds selected on a previously seen synthetic validation period; no new threshold tuning',
    'Partial regional raw data may fail R9 prior-year mask or Atlas complete coverage; three universes reported separately',
    'First-seen time is today; historical available_at/vintage remains unverified',
    'Atlas identity changes are exploratory algorithm assignments, not proven structural economic changes'],
   'provenance':{'code_sha256':sha(__file__),'detector_code_sha256':sha(Path(__file__).with_name('d02_d03_detectors.py')),
      'input_sha256':{n:sha(getattr(a,n)) for n in ['raw','dictionary','atlas','assignments','predictions','events','threshold_manifest']},
      'python':sys.version,'pandas':pd.__version__}}
 (a.outdir/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'status':'computed_descriptive','scientific_pass':False,'n_cases':len(cases),'missing_regions':{k:v['n_missing_regions'] for k,v in cov.items()}}),flush=True)
if __name__=='__main__':main()
