"""Strict descriptive mixed-authority publication validator; never scientific PASS."""
from pathlib import Path
import hashlib,json,math
STATUSES={'COMPUTED','DEGENERATE_BULK','INCONCLUSIVE_GRAPH_ISOLATE','INCONCLUSIVE_NO_BULK'}
VERDICTS={'INCONCLUSIVE_GRAPH_ISOLATE','ABSTAIN_M1','INCONCLUSIVE_CALIBRATION','INCONCLUSIVE_DEGENERATE_BULK','INCONCLUSIVE_SHUFFLE','ABSTAIN_LOW_SIG','ABSTAIN_NULL_GAP','REAL_GAP','INCONCLUSIVE_CONTROL_QUALITY'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def number(x,name,nullable=False):
 if x is None and nullable:return
 if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x):raise ValueError('finite numeric '+name)
def flags(result,required):
 for key in required:
  if result.get(key) is not False:raise ValueError('literal false '+key)
def statistics(row):
 if not {'m','sig','raw_gap','status','n','edges','density','isolates','components'}<=set(row):raise ValueError('complete spectral fields')
 if row.get('status') not in STATUSES or type(row.get('n')) is not int or row['n']!=1896:raise ValueError('literal spectral status/n')
 if type(row.get('edges')) is not int or row['edges']<0 or type(row.get('isolates')) is not int or not 0<=row['isolates']<=1896 or type(row.get('components')) is not int or not 1<=row['components']<=1896:raise ValueError('graph metadata')
 number(row.get('density'),'density')
 if not 0<=row['density']<=1:raise ValueError('density range')
 m=row.get('m')
 if m is not None and (type(m) is not int or not 0<=m<=1896):raise ValueError('literal spectral m')
 for key in ('sig','raw_gap'):number(row.get(key),key,True)
 if row['status']=='COMPUTED' and (m is None or row.get('sig') is None or row.get('raw_gap') is None):raise ValueError('computed statistics incomplete')
 if row['status']=='INCONCLUSIVE_GRAPH_ISOLATE' and any(row.get(k) is not None for k in ('m','sig','raw_gap')):raise ValueError('isolated graph cannot have fitted stats')
 if row['status']=='DEGENERATE_BULK' and row.get('sig') is not None:raise ValueError('degenerate bulk sig')
 if row.get('raw_gap') is not None and not 0<=row['raw_gap']<=2:raise ValueError('raw gap range')
 if row.get('sig') is not None and row['sig']<0:raise ValueError('sig range')
 for key in ('bulk_spread','shuffle_p95','shuffle_p'):
  if key in row:number(row[key],key,True)
 for x in row.get('lambda2_through_mplus2',[]):number(x,'eigen diagnostic')
def graph_metadata(row,k):
 if row['edges']!=1896*k//2 or not math.isclose(row['density'],(2*row['edges'])/(1896*1895),rel_tol=0,abs_tol=1e-15):raise ValueError('unchanged graph edge/density contract')
def nulls(row,base):
 gaps=row['shuffle_raw_gaps'];bad=row['shuffle_invalid_seeds']
 if not isinstance(gaps,list) or not isinstance(bad,list) or len(gaps)+len(bad)!=99 or len(bad)!=len(set(bad)) or any(type(s) is not int for s in bad) or not set(bad)<=set(range(base,base+99)):raise ValueError('exact99nulls')
 for x in gaps:
  number(x,'nullgap')
  if not 0<=x<=2:raise ValueError('nullgap range')
 if row.get('verdict') not in VERDICTS:raise ValueError('unknown verdict')
def negative_fit_verdict(row):
 return 'INCONCLUSIVE_GRAPH_ISOLATE' if row['m'] is None else ('ABSTAIN_M1' if row['m']==1 else 'INCONCLUSIVE_CALIBRATION')
def authority_check(manifest,authority):
 if manifest.get('authority')!=authority or manifest.get('code_sha256')!=authority['engine'] or manifest.get('protocol_sha256')!=authority['amendment']:raise ValueError('actual numerical authority; no oldsource-only manifest')
def full_manifest(out,manifest,expected,admission):
 present={p.name for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}
 if present!=expected or set(manifest.get('files_sha256',{}))!=expected or any(p.is_dir() for p in out.iterdir()):raise ValueError('exact full phase file universe')
 for name,digest in manifest['files_sha256'].items():
  admission()
  if Path(name).name!=name or sha(out/name)!=digest:raise ValueError('phase artifact SHA')
def freeze_check(out,authority,phase):
 f=json.loads((out/'protocol-freeze.json').read_text())
 if f.get('authority')!=authority or f.get('phase')!=phase or f.get('scientific_pass') is not False:raise ValueError('source-produced exact phase freeze')
def calibration(out,authority,protocol,frozen,ancestral,admission):
 out=Path(out);admission();manifest=json.loads((out/'manifest.json').read_text());r=json.loads((out/'result.json').read_text())
 authority_check(manifest,authority);freeze_check(out,authority,'recovery_calibration')
 full_manifest(out,manifest,{'result.json','protocol-freeze.json',*(f'calibration-progress-k{k}.json' for k in (10,20,40))},admission)
 flags(r,['economic_identity_pass','scientific_pass'])
 if r.get('state')!='COMPUTED_DESCRIPTIVE_MIXED_NUMERICAL_RECOVERY' or r.get('n')!=1896 or r.get('d')!=5 or type(r['n']) is not int or type(r['d']) is not int or set(r.get('results',{}))!={'10','20','40'} or r.get('authority')!=authority or r.get('mixed_ancestral_numerics') is not True or r.get('numerical_driver_new')!='evd':raise ValueError('full recovery top scope/authority')
 if r.get('input_sha256')!={'panel':'8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93','A5_mask':'12f40b15ee8f119cba7f386b5c9adf4babb5cff1bca2721dc04551d672f5e5d6'}:raise ValueError('frozen calibration inputs')
 if r.get('actual_recovery_source_SHA')!=authority['recovery'] or r.get('actual_evd_engine_SHA')!=authority['engine'] or r.get('amendment_protocol_SHA')!=authority['amendment'] or r.get('base_source_SHA')!=authority['base_source']:raise ValueError('explicit mixed authority fields')
 if r.get('settings_sha256')!=hashlib.sha256(json.dumps(frozen,sort_keys=True).encode()).hexdigest():raise ValueError('original settings SHA')
 for k,c in r['results'].items():
  admission();old=ancestral[k]
  if (c.get('n'),c.get('d'),c.get('k'))!=(1896,5,int(k)) or any(type(c[x]) is not int for x in ('n','d','k')):raise ValueError('literal graph scope')
  if c['fit']!=old['fit'] or c['calibration']!=old['calibration'] or c['held'][:len(old['held'])]!=old['held']:raise ValueError('saved334 changed/refitted')
  if c['method_quality']!='FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS':raise ValueError('oldnegative calibration cannot qualify new positive controls')
  for field,seeds in [('calibration',frozen['calibration_seeds']),('held',frozen['validation_seeds'])]:
   rows=c[field];expected=[(R,s) for R in (1,3,4,5) for s in seeds]
   if [(x['R'],x['seed']) for x in rows]!=expected or any(type(x['R']) is not int or type(x['seed']) is not int for x in rows):raise ValueError('exact360 orderedrecords')
   for row in rows:
    statistics(row);graph_metadata(row,int(k))
    if field=='held':
     nulls(row,frozen['shuffle_seed_base']+row['seed']*100)
     if row['verdict']!=negative_fit_verdict(row):raise ValueError('actual fixed-null-fit verdict mismatch')
  progress=json.loads((out/f'calibration-progress-k{k}.json').read_text())
  if progress!={x:c[x] for x in ('calibration','fit','held')}:raise ValueError('complete progress/result mismatch')
 if r.get('record_origin')!={'old334':protocol['ancestral_progress'],'new26':protocol['remaining_control_keys']}:raise ValueError('full mixed provenance')
 return r

def replay(out,authority,frozen,calibration_sha,expected_ids,input_sha,admission):
 import numpy as np
 out=Path(out);admission();manifest=json.loads((out/'manifest.json').read_text());r=json.loads((out/'result.json').read_text())
 authority_check(manifest,authority);freeze_check(out,authority,'replay')
 flags(r,['economic_identity_pass','independent_holdout','causal_pass','scientific_pass'])
 if r.get('state')!='COMPUTED_DESCRIPTIVE' or r.get('authority')!=authority or r.get('numerical_driver')!='evd' or r.get('calibration_sha256')!=calibration_sha or r.get('input_sha256')!=input_sha:raise ValueError('replay top state/provenance')
 months=[f'{y}-{m:02d}' for y in (2023,2024) for m in range(1,13)];rows=r['monthly']
 if len(rows)!=72 or [(x['month'],x['kNN']) for x in rows]!=[(m,k) for m in months for k in (10,20,40)] or any(type(x['kNN']) is not int for x in rows):raise ValueError('exact ordered72 rows')
 expected={'result.json','protocol-freeze.json','monthly-progress.json'}
 if json.loads((out/'monthly-progress.json').read_text())!=rows:raise ValueError('full72 monthlyprogress mismatch')
 for row in rows:
  admission();statistics(row);graph_metadata(row,row['kNN']);nulls(row,frozen['shuffle_seed_base']+months.index(row['month'])*100)
  if row['method_quality']!='FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS' or row['verdict']!=negative_fit_verdict(row):raise ValueError('no positive qualification from mixednegativefit')
  Kset=set(range(2,9))|({row['m']} if row['m'] is not None else set());metrics=row['metrics']
  if len(metrics)!=len(Kset) or {x['K'] for x in metrics}!=Kset or any(type(x['K']) is not int for x in metrics):raise ValueError('alloriginalK unionm')
  has_spectrum=row['spectrum_sha256'] is not None
  if (row['status']=='INCONCLUSIVE_GRAPH_ISOLATE')==has_spectrum:raise ValueError('spectrum availability')
  if has_spectrum:
   name=f"spectrum-{row['month']}-knn{row['kNN']}.npy";expected.add(name)
   if sha(out/name)!=row['spectrum_sha256']:raise ValueError('spectrum rowSHA')
   vals=np.load(out/name,allow_pickle=False)
   if vals.shape!=(1896,) or not np.isfinite(vals).all() or np.any(np.diff(vals)>0) or not np.isclose(vals[0],1.,rtol=0,atol=1e-10):raise ValueError('full1896 spectrum/invariants')
   observed_m=int(np.count_nonzero(vals>=frozen['tau_lambda']))
   if row['m']!=observed_m:raise ValueError('spectrum count/row m')
   if 1<=observed_m<1896:
    gap=float(vals[observed_m-1]-vals[observed_m]);spread=float(np.std(vals[observed_m:],ddof=0));sig=None if spread<=1e-12 else gap/spread
    if row['status']!=('DEGENERATE_BULK' if sig is None else 'COMPUTED') or not np.isclose(row['raw_gap'],gap,rtol=1e-12,atol=1e-12) or (row['sig'] is None)!=(sig is None):raise ValueError('spectrum gap/status')
    if sig is not None and not np.isclose(row['sig'],sig,rtol=1e-12,atol=1e-12):raise ValueError('spectrum sig')
    if not np.isclose(row.get('bulk_spread',float('nan')),spread,rtol=1e-12,atol=1e-12) or not np.allclose(row.get('lambda2_through_mplus2',[]),vals[1:min(observed_m+2,1896)],rtol=1e-12,atol=1e-12):raise ValueError('full tail diagnostic')
   elif row['status']!='INCONCLUSIVE_NO_BULK' or row['raw_gap'] is not None or row['sig'] is not None:raise ValueError('no bulk spectralstatus')
  for met in metrics:
   admission()
   if not {'K','status','SW','CH','S_Dbw'}<=set(met):raise ValueError('fullmetric fields')
   for key in ('SW','CH','S_Dbw'):number(met[key],key,True)
   status=met['status'];K=met['K'];available=has_spectrum and 2<=K<1896
   if not available:
    if status!='NA_GRAPH_OR_K_DOMAIN' or any(met[x] is not None for x in ('SW','CH','S_Dbw')):raise ValueError('unavailable metric schema')
   else:
    name=f"labels-{row['month']}-knn{row['kNN']}-K{K}.npz";expected.add(name)
    with np.load(out/name,allow_pickle=False) as z:
     if set(z.files)!={'territory_id','label'} or not np.array_equal(z['territory_id'],expected_ids) or z['label'].shape!=(1896,) or z['label'].dtype.kind not in ('i','u'):raise ValueError('fullmask label artifact')
     count=len(np.unique(z['label']))
     if np.any(z['label']<0) or np.any(z['label']>=K):raise ValueError('Kmeans label domain')
    if status=='NA_EMPTY_CLUSTER':
     if count==K or any(met[x] is not None for x in ('SW','CH','S_Dbw')):raise ValueError('emptycluster status')
    else:
     if status not in ('COMPUTED','NA_ZERO_GLOBAL_VARIANCE','NA_ZERO_DENSITY_DENOMINATOR'):raise ValueError('unknown metric status')
     if count!=K or met['SW'] is None or met['CH'] is None or not -1<=met['SW']<=1 or met['CH']<0:raise ValueError('actual metric domains')
     if 'S_Dbw_detail' not in met or met['S_Dbw_detail'].get('status')!=status or met['S_Dbw_detail'].get('S_Dbw')!=met['S_Dbw']:raise ValueError('S_Dbw detail')
     if status=='COMPUTED' and (met['S_Dbw'] is None or met['S_Dbw']<0):raise ValueError('computed S_Dbw finite nonnegative')
     if status in ('NA_ZERO_GLOBAL_VARIANCE','NA_ZERO_DENSITY_DENOMINATOR') and met['S_Dbw'] is not None:raise ValueError('NA S_Dbw must null')
 full_manifest(out,manifest,expected,admission);return r
