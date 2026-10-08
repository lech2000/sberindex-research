import time
ENTRY=time.monotonic()
import os,json,hashlib,pathlib,resource,signal,csv,math,statistics,datetime
D=pathlib.Path(__file__).parent;R=pathlib.Path('/private/tmp/sberindex-official-laws-20261007');LIMIT=300;RSS=1073741824;OUTCAP=134217728
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def guard():
 if time.monotonic()-ENTRY>=LIMIT:raise InterruptedError('original300s wall exhausted')
 if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss>RSS:raise InterruptedError('own peakRSS>1GiB')
 if sum(p.stat().st_size for p in D.iterdir()if p.is_file())>OUTCAP:raise InterruptedError('own output cap')
def once(name,obj):
 p=D/name;fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w')as f:json.dump(obj,f,ensure_ascii=False,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 fd=os.open(D,os.O_RDONLY);os.fsync(fd);os.close(fd)
FILES=['docs/CONTEST_SUBMISSIONS_2026-10-08.json','economic-atlas/data/panel_v1.parquet','economic-atlas/runs/consumption_restructuring_20261005/descriptive_probe.json','economic-atlas/runs/consumption_restructuring_20261005/descriptive_probe.py','economic-atlas/runs/Consumer_closeout_20261006/robustness-municipalities.csv','economic-atlas/runs/Consumer_closeout_20261006/robustness-grid.csv','economic-atlas/runs/Consumer_closeout_20261006/protocol.json','economic-atlas/runs/H5_dimensionless_scale_20261007/full-partitions.json','economic-atlas/runs/H5_dimensionless_scale_20261007/metrics.json','economic-atlas/runs/H5_dimensionless_scale_20261007/independent-audit.json','economic-atlas/runs/H5_dimensionless_scale_20261007/reproduction-receipt.json','economic-atlas/runs/H5_dimensionless_scale_20261007/protocol.json','economic-atlas/runs/H5_dimensionless_scale_20261007/results.json']
STARTED=False
result={'state':'INCONCLUSIVE_AUDIT','scientific_pass':False,'models_fits_worlds_providers':0}
try:
 signal.signal(signal.SIGALRM,lambda s,f:(_ for _ in ()).throw(InterruptedError('own wall300s')));signal.setitimer(signal.ITIMER_REAL,max(.001,LIMIT-(time.monotonic()-ENTRY)))
 pins={}
 for name in FILES:guard();pins[name]=h(R/name)
 protocol={'kind':'ONE_EXISTING_ATLAS_SUBMISSION_ARITHMETIC_AUDIT','recorded_before_arithmetic_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'entry_monotonic':ENTRY,'wall_seconds':LIMIT,'RSS_limit_bytes':RSS,'output_limit_bytes':OUTCAP,'source_SHA':h(pathlib.Path(__file__)),'input_pins':pins,'scope':['full1896x24x6 exactkeys positivefinite shares/separateAll, meanmonthly2023vs2024 marketplace/food claims','25original/9core at>=.8/45savedconfiguration table arithmetic; no rules recalibration','14unitinvariant partition and34944forecast claim rawread ifavailable elseUNVERIFIED_CURRENT_RAW'],'no_retry':True,'no_models_fits_recluster_worlds_bootstrap':True,'no_subprocesses':True,'tolerance':'raw counts exact; descriptive scalar medians abs1e-10; no lowered thresholds','scientific_pass':False}
 once('PROTOCOL.json',protocol);once('OPERATION.json',{'state':'CONSUMED_ONE_USE','protocol_SHA':h(D/'PROTOCOL.json'),'entry_monotonic':ENTRY});STARTED=True
 guard();import pyarrow.parquet as pq
 rows=pq.read_table(R/'economic-atlas/data/panel_v1.parquet').to_pylist();guard();axes={};dates=set();cats=set()
 for row in rows:
  k=(int(row['territory_id']),row['ym'],row['category']);v=row['value']
  if k in axes or type(v)not in(int,float)or not math.isfinite(v)or v<=0:raise ValueError('duplicate/nonpositive/nonfinite panel')
  if row['date'][:7]!=row['ym']:raise ValueError('date/month conflict')
  axes[k]=v;dates.add(row['ym']);cats.add(row['category'])
 ids=sorted({k[0]for k in axes});months=[f'{y}-{m:02}'for y in [2023,2024]for m in range(1,13)];categories=['Все категории','Здоровье','Маркетплейсы','Общественное питание','Продовольствие','Транспорт']
 if len(ids)!=1896 or dates!=set(months)or cats!=set(categories)or len(axes)!=1896*24*6:raise ValueError('full exact panel mask')
 marketplace=[];foodshares=[];foodgrowth=[]
 for tid in ids:
  guard();annual={};nominal={}
  for year in [2023,2024]:
   mm=[m for m in months if m.startswith(str(year))]
   annual[year]={c:math.fsum(axes[tid,m,c]/axes[tid,m,'Все категории']*100 for m in mm)/12 for c in categories[1:]}
   nominal[year]={c:math.fsum(axes[tid,m,c]for m in mm)/12 for c in categories}
  marketplace.append(annual[2024]['Маркетплейсы']-annual[2023]['Маркетплейсы']);foodshares.append(annual[2024]['Продовольствие']-annual[2023]['Продовольствие']);foodgrowth.append((nominal[2024]['Продовольствие']/nominal[2023]['Продовольствие']-1)*100)
 saved=json.loads((R/'economic-atlas/runs/consumption_restructuring_20261005/descriptive_probe.json').read_text())['all'];median=statistics.median(marketplace)
 panelproof={'n':len(ids),'months':len(months),'category_count':len(categories),'rows':len(rows),'unique_full_keys':len(axes),'positive_finite':True,'marketplace_increase_count':sum(x>0 for x in marketplace),'marketplace_median_delta_pp':median,'marketplace_round3_pp':round(median,3),'food_share_decrease_count':sum(x<0 for x in foodshares),'food_nominal_increase_count':sum(x>0 for x in foodgrowth),'food_share_down_and_nominal_up':sum(a<0 and b>0 for a,b in zip(foodshares,foodgrowth)),'unweighted_meanmonthly_ratio_not_annualratio_or_nationalpopulationmean':True}
 if panelproof['marketplace_increase_count']!=1896 or abs(median-saved['median_ratio_change_percentage_points']['Маркетплейсы'])>1e-10 or panelproof['food_share_down_and_nominal_up']!=1803:raise ValueError('claim arithmetic mismatch')
 with (R/'economic-atlas/runs/Consumer_closeout_20261006/robustness-municipalities.csv').open()as f:mun=list(csv.DictReader(f))
 with (R/'economic-atlas/runs/Consumer_closeout_20261006/robustness-grid.csv').open()as f:grid=list(csv.DictReader(f))
 if len({r['territory_id']for r in mun})!=len(mun)or len({r['configuration']for r in grid})!=45:raise ValueError('duplicate history/configuration')
 original=[r for r in mun if r['original_signal']=='True'];core=[r for r in original if int(r['configurations_selected'])/45>=.8]
 for r in mun:
  if int(r['configurations_total'])!=45 or not 0<=int(r['configurations_selected'])<=45 or abs(float(r['selection_fraction'])-int(r['configurations_selected'])/45)>1e-12:raise ValueError('frequency arithmetic')
 for r in original:
  if (r['descriptive_core80']=='True')!=(r in core):raise ValueError('core flag mismatch')
 if len(original)!=25 or len(core)!=9:raise ValueError('25/9 rawtable mismatch')
 histories={'saved_municipality_rows':len(mun),'original_histories':len(original),'core80_histories':len(core),'configurations':len(grid),'minimum_original_retained':min(int(r['original25_retained'])for r in grid),'maximum_original_retained':max(int(r['original25_retained'])for r in grid),'core_IDs':[int(r['territory_id'])for r in core],'raw_rule_membership_matrix_verified':False,'limit':'saved frequency/grid arithmetic; rules not rerun and per-rule full membership not persisted in these tables'}
 run=R/'economic-atlas/runs/H5_dimensionless_scale_20261007';rawpaths=[run/'oof_predictions.parquet',run/'folds.json',run/'full-labels.parquet']
 parts=json.loads((run/'full-partitions.json').read_text());historical=json.loads((run/'independent-audit.json').read_text());inv={'current_raw_status':'UNVERIFIED_CURRENT_RAW','missing_paths':[str(p.relative_to(R))for p in rawpaths if not p.exists()],'saved_partition_summary_rows':len(parts),'saved_ARI1_rows':sum(r['ruble_to_thousand_ARI']==1 for r in parts),'historical_rowwise_audit_count':historical['forecast_rows_and_labels_checked'],'historical_prediction_SHA':historical['run_predictions_sha256'],'not_a_new34944_row_or14_label_numeric_verification':True}
 if all(p.exists()for p in rawpaths):inv['current_raw_status']='AVAILABLE_BUT_NO_SILENT_NEW_SCOPE';raise ValueError('unexpected newlyavailable raw requires exact prospectivelydefined schema')
 guard()
 for name,pin in pins.items():
  guard()
  if h(R/name)!=pin:raise ValueError('immutable source changed:'+name)
 result.update(state='EXISTING_CLAIMS_ARITHMETIC_VERIFIED_WITH_RAW_EVIDENCE_ABSTENTION',panel=panelproof,histories=histories,unit_invariance=inv,input_pins=pins,source_SHA=protocol['source_SHA'],quality_full225_pass=False,E05_full_actual='NOT_RUN',M4_full='STOP_NOT_FULL_1980',R11_future='UNEXECUTED',no_new_holdout_causal_or_economic_identity=True)
except BaseException as e:result.update(error=type(e).__name__+': '+str(e),one_use_preserved=STARTED)
finally:
 result.update(elapsed_before_result_fsync=time.monotonic()-ENTRY,own_peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,child_processes_created=0,last_receipt_IO_independently_timed=False)
 once('RESULT.json',result);elapsed=time.monotonic()-ENTRY;once('POST_IO.json',{'elapsed_through_RESULT_fsync_seconds':elapsed,'within_original300s':elapsed<LIMIT,'result_SHA':h(D/'RESULT.json'),'own_peak_RSS_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'output_bytes_before_post':sum(p.stat().st_size for p in D.iterdir()if p.is_file()),'last_POST_IO_write_independently_timed':False,'scientific_pass':False});signal.setitimer(signal.ITIMER_REAL,0)
print(result['state'])
