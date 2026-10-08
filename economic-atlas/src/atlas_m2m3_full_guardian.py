"""One-use trusted-root full M2/M3 guardian. No scientific method changes."""
import time
ENTRY=time.monotonic()  # Before argparse, scientific imports, preflight and stages.
from pathlib import Path
import argparse,csv,datetime,hashlib,importlib.util,json,math,os,plistlib,shutil,signal,sys
sys.dont_write_bytecode=True
TOTAL=4200;FINAL=30;RESERVE=65536;OUT=268435456;RSS=FREE=1073741824
PROTOCOL_SHA='a80ab6b01141a4c700131d5ec15117d330f7b80d3830f3664759faeb17c683bf'
SCIENCE_SHA='728358b214a1a2c8b50cf35c6c197c6e36bf704c80c77d172c35f65d47050494'
LEDGER_ROOT=Path('/private/tmp/sberindex-one-use-ledger')
MONTHS=[f'{y}-{m:02d}' for y in (2023,2024) for m in range(1,13)]
SEEDS=list(range(20271001,20271006));WORLDS=['stable','drift','birth','death','split','merge','proximity'];MODES=['oracle','unsupervised'];FACTORS=[.75,1.,1.25]
SENS={f'kappa={k}_cont={c}' for k in (1.5,2.0,2.5) for c in (.6,.75)}
THREADS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text())
def require(v,msg):
 if not v:raise ValueError(msg)
def finite(v):
 require(not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v),'finite nonboolean resource value required');return v
def load(path):
 s=importlib.util.spec_from_file_location('accepted_m1_guard',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def atomic(path,data,exclusive=False):
 path=Path(path);tmp=path if exclusive else path.with_name(path.name+'.tmp')
 fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|(os.O_EXCL if exclusive else os.O_TRUNC),0o600)
 with os.fdopen(fd,'w') as f:json.dump(data,f,allow_nan=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
 if not exclusive:os.replace(tmp,path)
 fd=os.open(path.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def reservation():
 LEDGER_ROOT.mkdir(mode=0o700,exist_ok=True);s=LEDGER_ROOT.lstat()
 require(not LEDGER_ROOT.is_symlink() and s.st_uid==os.getuid() and not s.st_mode&0o077,'canonical private UID0700 ledger required')
 return LEDGER_ROOT/(str(os.getuid())+'-M2M3-'+SCIENCE_SHA+'.json')
def size(roots):
 total=0
 for root in roots:
  if not root.exists():continue
  for p in root.rglob('*'):
   require(not p.is_symlink(),'output symlinks prohibited')
   if p.is_file():total+=p.stat().st_size
 return total

def admission(started,roots,native=None,final=False):
 elapsed=finite(time.monotonic()-started);require(elapsed>=0 and elapsed<TOTAL-(0 if final else FINAL),'total inclusive wall allowance exhausted')
 require(shutil.disk_usage(roots[0].parent).free>=FREE,'1GiB free admission')
 require(size(roots)<OUT-(0 if final else RESERVE),'combined output allowance exhausted')
 if native is not None:
  value,_=native.own_tree_rss();require(finite(value)>0 and value<=RSS,'own aggregate RSS allowance')
 return elapsed

def destinations(view,out,receipt):
 view=view.resolve();out=out.resolve();receipt=receipt.resolve()
 require(not out.exists() and not receipt.exists(),'two fresh output directories; no retry/resume')
 canonical=Path('/private/tmp/sberindex-official-laws-20261007')
 for dest in (out,receipt):require(dest!=canonical and canonical not in dest.parents and dest not in canonical.parents,'shared science repository protected')
 for a,b in ((out,receipt),(out,view),(receipt,view)):
  require(a!=b and a not in b.parents and b not in a.parents,'outputs/view must be distinct nonnested')
 require(os.stat(out.parent).st_dev==os.stat(receipt.parent).st_dev,'same disk combined accounting')
 return out,receipt

def pins(view,p):
 for name,digest in p['pins'].items():require(sha(view/name)==digest,'frozen input/source changed: '+name)

def commands(view,out):
 return [[sys.executable,str(view/'economic-atlas/src/a6_geometry_original_scope_v4.py'),'--panel',str(view/'economic-atlas/data/panel_v1.parquet'),'--outdir',str(out/'real'),'--seed','20260926'],[sys.executable,str(view/'economic-atlas/src/a6_geometry_original_controls_v4.py'),'--atlas-src',str(view/'economic-atlas/src'),'--calibration',str(out/'real/calibration.json'),'--out',str(out/'bank')]]

def real_records(rows,mask):
 require(len(mask)==1896 and len(set(mask))==1896,'A5 full unique mask')
 keys=[(x['territory_id'],x['month']) for x in rows]
 require(len(keys)==45504 and len(set(keys))==45504 and set(keys)=={(t,m) for t in mask for m in MONTHS},'full exact45504 keys and every month required')

def calibration(c):
 require(c.get('geometry_version')=='geometry-original-scope-v4.0.4' and c.get('cal_months')==list(range(12)),'fresh all2023 calibration')
 require(c.get('method')=='full covariance B=200/bootstrap 2023 only min_cluster_size=8','literal B200 method')
 raw=c.get('raw_distributions',{});require(set(raw)=={'self','other','positive_gap','negative_gap'} and all(isinstance(x,list) for x in raw.values()),'all raw bootstrap pools')
 require(c.get('counts')=={k:len(v) for k,v in raw.items()},'raw bootstrap counts conserved')
 require(c.get('calibration_status') in ('SEPARATED','INCONCLUSIVE'),'calibration status')
 require(c.get('recognition_qualified') is (c['calibration_status']=='SEPARATED'),'qualification consistency')
 # Raw pool receipt is mandatory even when missing/overlapping/nonfinite pools
 # scientifically make calibration INCONCLUSIVE; accepted controls validate policy.
 return c['calibration_status']

def configkey(r):
 require(type(r['seed']) is int and type(r['margin_factor']) in (int,float) and not isinstance(r['margin_factor'],bool),'literal config seed/factor')
 return (r['seed'],r['world'],r['mode'],r['margin_factor'])
def bank_records(b):
 configs={(s,w,m,f) for s in SEEDS for w in WORLDS for m in MODES for f in FACTORS}
 for name in ('runs','regions','events'):
  rows=b[name];require(len(rows)==210 and {configkey(x) for x in rows}==configs,'all210 unique '+name+' configs')
 for r in b['runs']:
  require(set(r['m3_sensitivity_counts'])==SENS and len(r['selected_k'])==24,'all6 M3 sensitivities/all24 K')
 for r in b['regions']:require({x['month'] for x in r['regions']}==set(MONTHS),'full24 region histories')
 labs=b['labels'];require(len(labs)==70 and {(x['seed'],x['world'],x['mode']) for x in labs}=={(s,w,m) for s in SEEDS for w in WORLDS for m in MODES},'all70 label histories')
 for r in labs:
  require(r['months']==MONTHS and r['member_ids']==list(range(200)) and len(r['labels'])==24 and all(len(a)==200 and all(type(x) is int for x in a) for a in r['labels']),'literal24x200 member labels')
 worlds=b['worlds'];require(len(worlds)==35 and {(x['seed'],x['world']) for x in worlds}=={(s,w) for s in SEEDS for w in WORLDS},'all35 world provenance')
 for r in worlds:
  require(r['cube_shape']==[200,24,5] and all(isinstance(r[x],str) and len(r[x])==64 and set(r[x])<=set('0123456789abcdef') for x in ('cube_float64_C_order_SHA','truth_SHA')),'fullcube/truth SHA')
  if r['world'] in ('split','merge'):require(r['coordinates_conserved'] is True,'literal point conservation')
 require(b['metrics'].get('n_runs')==210 and b['metrics'].get('scientific_pass') is False and b['metrics'].get('economic_truth_verified') is False,'no scientific/economic PASS')
 require(b['metrics']['acceptance']['status'] in ('PASS','FAIL','INCONCLUSIVE'),'complete negative outcomes allowed')

def verify(view,out,p,native,started,roots):
 admission(started,roots,native,final=True)
 real=out/'real';bank=out/'bank'
 require({x.name for x in real.iterdir()}=={'assignments.parquet','regions.csv','events.csv','calibration.json','k_grid.csv','metrics.json','manifest.json'},'full real output file set')
 require({x.name for x in bank.iterdir()}=={'protocol.json','metrics.json','runs.json','truth.json','events.json','months.json','k-grid.json','label-histories.json','tracker-region-histories.json','tracker-events.json','world-hashes.json'},'full bank output file set')
 mf=read(real/'manifest.json');metrics=read(real/'metrics.json');cal=read(real/'calibration.json')
 require(mf.get('protocol_sha256')==SCIENCE_SHA and mf['replay_mode']=='fresh_monthly_fits' and metrics['replay_mode']=='fresh_monthly_fits','archived labels prohibited')
 require(mf['seed']==20260926 and mf['params']['bootstrap_B']==200 and mf['params']['k_grid']==[2,8],'original seed/B/K')
 require(mf['code']=={x:p['pins']['economic-atlas/src/'+x] for x in ('a6_geometry_original_scope_v4.py','a6_temporal.py')},'real source/dependency SHA')
 require(mf['inputs']['panel']['sha256']==p['pins']['economic-atlas/data/panel_v1.parquet'] and mf['gate_pass'] is False,'panel hash/no gate claim')
 import pandas as pd  # Charged finalization and native RSS checks; no new fits.
 rows=pd.read_parquet(real/'assignments.parquet',columns=['territory_id','month']).to_dict('records');mask=pd.read_parquet(view/'economic-atlas/runs/A5/features.parquet',columns=['territory_id']).territory_id.tolist();real_records(rows,mask)
 with (real/'k_grid.csv').open() as stream:grid=list(csv.DictReader(stream))
 require(len(grid)==168 and {(x['month'],int(x['k'])) for x in grid}=={(m,k) for m in MONTHS for k in range(2,9)},'all24x7 original K-grid results')
 require(set(metrics['m3']['sensitivity'])==SENS,'real all6 M3 sensitivity results')
 admission(started,roots,native,final=True);calstatus=calibration(cal)
 bp=read(bank/'protocol.json');expected={'calibration':sha(real/'calibration.json'),'tracker':p['pins']['economic-atlas/src/a6_geometry_original_scope_v4.py'],'control_code':p['pins']['economic-atlas/src/a6_geometry_original_controls_v4.py']}
 require(bp['seeds']==SEEDS and bp['worlds']==WORLDS and bp['modes']==MODES and bp['margin_factors']==FACTORS and bp['months']==MONTHS and bp['n']==200 and bp['dimensions']==5,'literal bank specification')
 require(bp['frozen_thresholds']=={k:cal[k] for k in ('overlap_threshold','candidate_margin','resemblance_floor')},'new frozen thresholds only')
 require(bp['sha256']==expected and bp['prospective_protocol_sha256']==SCIENCE_SHA and bp['no_recalibration'] is True,'fresh calibration/control provenance')
 b={k:read(bank/name) for k,name in {'runs':'runs.json','regions':'tracker-region-histories.json','events':'tracker-events.json','labels':'label-histories.json','worlds':'world-hashes.json','metrics':'metrics.json'}.items()};bank_records(b)
 if calstatus!='SEPARATED':require(b['metrics']['acceptance']['status']=='INCONCLUSIVE','unqualified calibration blocks positive controls')
 hashes={str(x.relative_to(out)):sha(x) for x in out.rglob('*') if x.is_file()};admission(started,roots,native,final=True)
 return {'real_keys':45504,'configs':210,'labels':70,'worlds':35,'calibration_status':calstatus,'control_status':b['metrics']['acceptance']['status'],'artifacts_sha256':hashes,'positive_scientific_qualification':False}

def alarm(signum,frame):raise InterruptedError('inclusive total budget; no restart')
def plist(python,launcher,args,receipt):
 return plistlib.dumps({'Label':'local.sergey.sberindex.m2m3.full.728358','ProgramArguments':[str(python),str(launcher),*args],'RunAtLoad':True,'KeepAlive':False,'StandardOutPath':'/dev/null','StandardErrorPath':'/dev/null','EnvironmentVariables':{**{x:'1' for x in THREADS},'PYTHONDONTWRITEBYTECODE':'1'}})

def main():
 started=ENTRY;a=argparse.ArgumentParser()
 for x in ('view','protocol','binding','outdir','receipt-dir'):a.add_argument('--'+x,type=Path,required=True)
 a.add_argument('--binding-sha',required=True);args=a.parse_args();p=read(args.protocol)
 require(sha(args.protocol)==PROTOCOL_SHA,'frozen operational protocol SHA')
 out,receipt=destinations(args.view,args.outdir,args.receipt_dir);roots=(out,receipt);admission(started,roots);pins(args.view,p)
 require(sha(args.binding)==args.binding_sha,'root binding SHA');binding=read(args.binding)
 require(binding=={'launcher_sha256':sha(__file__),'protocol_sha256':PROTOCOL_SHA,'view':str(args.view.resolve()),'outdir':str(out),'receipt_dir':str(receipt),'science_protocol_sha256':SCIENCE_SHA},'exact root reviewed launcher/paths binding')
 path=reservation();record={'state':'STARTED','scientific_pass':False,'source_actions_closed':0,'automatic_restart':False,'started_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'startup_elapsed_seconds':time.monotonic()-started,'binding_sha256':args.binding_sha,'operational_protocol_sha256':PROTOCOL_SHA,'phases':[]}
 atomic(path,record,True);terminal=path.with_name(path.stem+'-terminal.json');oldalarm=signal.getsignal(signal.SIGALRM);oldterm=signal.getsignal(signal.SIGTERM)
 try:
  receipt.mkdir(mode=0o700);admission(started,roots)
  signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,max(.001,TOTAL-FINAL-(time.monotonic()-started)))
  for x in THREADS:os.environ[x]='1'
  g=load(args.view/'economic-atlas/src/atlas_m1_executor.py');signal.signal(signal.SIGTERM,g.stop_requested)
  native=g.NativeMac();admission(started,roots,native);record['preflight']=g.resource_preflight(receipt/'native-preflight',native)
  require(not native.descendants(os.getpid()),'probe owned descendants remain');admission(started,roots,native)
  g.output_bytes=lambda ignored:size(roots)
  limits=dict(g.LIMITS,wall=TOTAL-FINAL,output=OUT-RESERVE)
  for phase,command in zip(('full-real','full-bank'),commands(args.view,out)):
   admission(started,roots,native);pins(args.view,p)
   status=g.run_phase(command,receipt,phase,started,limits=limits,native=native);record['phases'].append(status)
   require(not native.descendants(os.getpid()),'owned phase tree unresolved')
   require(status['state']=='COMPLETE','full stage incomplete; no retry; all partial files retained')
   # Never skip bank after scientific FAIL/INCONCLUSIVE calibration.
  signal.setitimer(signal.ITIMER_REAL,max(.001,TOTAL-(time.monotonic()-started)))
  record['verified']=verify(args.view,out,p,native,started,roots);record['state']='FULL_DESCRIPTIVE_COMPLETE_NEEDS_INDEPENDENT_AUDIT'
 except BaseException as exc:record.update(state='INCONCLUSIVE_EXECUTION_STOP_NO_RETRY',error=type(exc).__name__+': '+str(exc))
 finally:
  signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,oldalarm);signal.signal(signal.SIGTERM,oldterm)
  try:pins(args.view,p);admission(started,roots,final=True)
  except BaseException as exc:record.update(state='INCONCLUSIVE_FINAL_GUARD',final_error=repr(exc))
  record.update(elapsed_seconds_observed=time.monotonic()-started,continuous_resource_PASS=False,final_immutable_receipt_IO_measured=False,output_bytes_observed=size(roots))
  atomic(terminal,record)
  if receipt.is_dir():atomic(receipt/'terminal.json',record)
 print(json.dumps({'state':record['state'],'canonical_terminal':str(terminal)}))
 if record['state'].startswith('INCONCLUSIVE'):raise SystemExit(1)
if __name__=='__main__':main()
