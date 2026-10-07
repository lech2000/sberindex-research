"""Failure-accounted full registry. Numerical forecasting lives in pinned original r11."""
from pathlib import Path
import collections,hashlib,json,math,os,time

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def atomic(p,value):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(p.suffix+'.tmp')
 with tmp.open('w') as f:json.dump(value,f,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 tmp.replace(p);fd=os.open(p.parent,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def identity(p,code):return hashlib.sha256(json.dumps({'protocol_SHA':sha(p),'code_SHA':code},sort_keys=True).encode()).hexdigest()
def state_path(out,b,item):return out/'checkpoints'/(b.group_id(item['key'])+'.json')
def state(out,p,b,item,fp):
 path=state_path(out,b,item);old=Path(p['ancestral_path'])/'checkpoints'/path.name
 if path.exists():
  s=read(path)
  if s['fingerprint']!=fp or s['group_key']!=list(item['key']) or s['context_sha256']!=b.base.context_digest(item['context']):raise ValueError('new state identity/context')
  return s
 s={'fingerprint':fp,'group_key':list(item['key']),'context_sha256':b.base.context_digest(item['context']),'chronos':{},'prophet':dict(item['cached_prophet']),'terminal':{'chronos':{},'prophet':{}},'ancestry':None}
 if old.exists():
  a=read(old)
  if sha(old)!=p['ancestral_checkpoint_snapshot'][str(old.relative_to(Path(p['ancestral_path'])))] or a['fingerprint']!=p['ancestral_fingerprint'] or a['group_key']!=s['group_key'] or a['context_sha256']!=s['context_sha256']:raise ValueError('ancestral exact state/context')
  s['chronos']=a['chronos'];s['prophet']=a['prophet'];s['ancestry']={'path':str(old),'SHA':sha(old),'original_status':a['status'],'original_uncertain_inflight':a.get('uncertain_inflight')}
  if a.get('uncertain_inflight'):
   if s['group_key']!=p['unknown_ancestral_group']['group_key'] or a['uncertain_inflight']!='prophet':raise ValueError('undeclared ancestral uncertainty')
   for row in item['rows']:
    if str(row['target']) not in s['prophet']:s['terminal']['prophet'][str(row['target'])]='ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT'
 return s

def terminal(s,item):return all(str(r['target']) in s[m] or str(r['target']) in s['terminal'][m] for r in item['rows'] for m in ('chronos','prophet'))
def save(out,b,item,s):atomic(state_path(out,b,item),s)
def request_digest(request):return hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def begin(out,purpose,model,items,request,source,fp):
 root=out/'attempts';root.mkdir(exist_ok=True);identifier=f'{time.time_ns()}-{model}-{purpose}';path=root/identifier;path.mkdir()
 targets={source.group_id(i['key']):(list(request['fit']['targets']) if model=='prophet' else [str(r['target']) for r in i['rows']]) for i in items}
 payload={'schema':'r13-attempt-v1','id':identifier,'purpose':purpose,'model':model,'fingerprint':fp,'original_numerical_source_SHA':sha(Path(source.__file__)),'request':request,'group_keys':[list(i['key']) for i in items],'context_SHAs':{source.group_id(i['key']):source.base.context_digest(i['context']) for i in items},'target_dates':targets}
 atomic(path/'request.json',payload);atomic(path/'status.json',{'status':'STARTED','request_SHA':sha(path/'request.json'),'started_monotonic':time.monotonic()});atomic(out/'active-attempt.json',{'id':identifier,'path':str(path),'started_monotonic':time.monotonic(),'status':'STARTED'})
 return path,payload

def response(path,payload,values=None,error=None):
 result={'request_SHA':sha(path/'request.json'),'fingerprint':payload['fingerprint'],'model':payload['model'],'purpose':payload['purpose'],'ok':error is None,'values':values,'error':error}
 atomic(path/'response.json',result);return result

def validated_response(path,fp):
 q=read(path/'request.json');r=read(path/'response.json')
 if r['request_SHA']!=sha(path/'request.json') or r['fingerprint']!=fp or q['fingerprint']!=fp or r['model']!=q['model'] or r['purpose']!=q['purpose']:raise ValueError('response request/identity mismatch')
 if r['ok']:
  if set(r['values'])!=set(q['target_dates']):raise ValueError('response exact group coverage')
  for gid,dates in q['target_dates'].items():
   if set(r['values'][gid])!=set(dates):raise ValueError('response exact target coverage')
   if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in r['values'][gid].values()):raise ValueError('response finite forecast guard')
 return q,r

def commit(path,out,p,b,groups,fp):
 q,r=validated_response(path,fp)
 if q['purpose']=='primary':
  for key in q['group_keys']:
   item=groups[tuple(key)];s=state(out,p,b,item,fp);gid=b.group_id(item['key']);model=q['model']
   for date in q['target_dates'][gid]:
    if r['ok']:
     value=r['values'][gid][date]
     if date in s[model] and s[model][date]!=value:raise ValueError('successful forecast overwrite prohibited')
     if date in s['terminal'][model]:raise ValueError('terminal NA overwrite prohibited')
     s[model][date]=value
    elif date not in s[model]:s['terminal'][model][date]=r['error'] or 'FAILED_REPORTED'
   save(out,b,item,s)
 atomic(path/'status.json',{'status':'COMMITTED','request_SHA':sha(path/'request.json'),'response_SHA':sha(path/'response.json'),'ok':r['ok']})
 atomic(out/'active-attempt.json',{'status':'IDLE'})
 return r

def recover(out,p,b,groups,fp):
 # Durable responses replay only commits; no model callbacks. Unreturned calls terminal NA.
 for path in sorted((out/'attempts').glob('*')) if (out/'attempts').exists() else []:
  if not path.is_dir():continue
  if read(path/'status.json')['status']=='COMMITTED':validated_response(path,fp);continue
  q=read(path/'request.json')
  if not (path/'response.json').exists():response(path,q,error='UNKNOWN_STOP_BEFORE_DURABLE_RESPONSE_NEVER_RETRY')
  commit(path,out,p,b,groups,fp)
 atomic(out/'active-attempt.json',{'status':'IDLE'})

def counters(out,p,fp,write=True):
 c=dict(p['historical_counters'])
 for path in (out/'attempts').glob('*') if (out/'attempts').exists() else []:
  q=read(path/'request.json')
  if q['fingerprint']!=fp:raise ValueError('attempt foreign fingerprint')
  model=q['model'];purpose=q['purpose']
  if purpose=='primary':attempt='chronos_calls' if model=='chronos' else 'prophet_fits';success='successful_native_calls' if model=='chronos' else 'successful_Prophet_fits'
  else:attempt='control_Chronos_calls' if model=='chronos' else 'control_Prophet_fits';success='successful_'+attempt
  c[attempt]=c.get(attempt,0)+1
  if (path/'response.json').exists() and validated_response(path,fp)[1]['ok']:c[success]=c.get(success,0)+1
 if write:atomic(out/'counters.json',c)
 return c

def bump(out,purpose,model,successful=False):
 c=read(out/'counters.json')
 key=('successful_native_calls' if model=='chronos' else 'successful_Prophet_fits') if successful else ('chronos_calls' if model=='chronos' else 'prophet_fits')
 if purpose!='primary':key=('successful_' if successful else '')+('control_Chronos_calls' if model=='chronos' else 'control_Prophet_fits')
 c[key]=c.get(key,0)+1;atomic(out/'counters.json',c)
 return c

def reserve_guard(out,purpose,model):
 c=read(out/'counters.json')
 key=('chronos_calls' if model=='chronos' else 'prophet_fits') if purpose=='primary' else ('control_Chronos_calls' if model=='chronos' else 'control_Prophet_fits')
 # All historical attempts count, including the one unresolved Prophet fit.
 limit=(196574 if model=='chronos' else 135396) if purpose=='primary' else 8
 if c.get(key,0)>=limit:raise ValueError('frozen cumulative model-attempt cap; no model callback')

def journal_digest(out):
 h=hashlib.sha256()
 for directory in sorted((out/'attempts').glob('*')):
  for name in ['request.json','response.json','status.json','native-manifest.json']:
   file=directory/name
   if file.exists():h.update((str(file.relative_to(out))+' '+sha(file)+'\n').encode())
 return h.hexdigest()

def call(out,p,b,groups,fp,purpose,model,items,request,function):
 reserve_guard(out,purpose,model)
 if purpose=='primary':
  for item in items:
   s=state(out,p,b,item,fp);dates=request['fit']['targets'] if model=='prophet' else [str(r['target']) for r in item['rows']]
   if any(date in s[model] or date in s['terminal'][model] for date in dates):raise ValueError('resolved primary model stage must not execute again')
 path,q=begin(out,purpose,model,items,request,b,fp);bump(out,purpose,model)
 try:
  if not (path/'response.json').exists():
   values=function(path,q)
   if not (path/'response.json').exists():response(path,q,values=values)
 except Exception as exc:
  if not (path/'response.json').exists():response(path,q,error=type(exc).__name__+': '+str(exc))
 result=commit(path,out,p,b,groups,fp)
 if result['ok']:bump(out,purpose,model,True)
 return result

def outcome_registry(out,p,b,groups,rows,excluded,fp,obs,final=False,unresolved=None,stop_reason=None,report_deadline=None,report_guard=None):
 unresolved=unresolved or {}
 counts=collections.Counter();by_h=collections.defaultdict(collections.Counter);pairs=[];pending=0;tmp=out/'row-statuses.jsonl.tmp'
 with tmp.open('w') as f:
  for key in excluded:f.write(json.dumps({'key':list(key),'status':'INSUFFICIENT_HISTORY','chronos_status':'EXCLUDED','prophet_status':'EXCLUDED'},ensure_ascii=False)+'\n');counts['INSUFFICIENT_HISTORY']+=1
  for g,item in sorted(groups.items()):
   s=state(out,p,b,item,fp);series=obs[(g[0],g[1])]
   for row in item['rows']:
    if report_guard is not None and len(pairs)%1024==0:report_guard()
    if report_deadline is not None and time.monotonic()>report_deadline:raise RuntimeError('bounded600s zero-model reporting deadline; retain partialreport and INCONCLUSIVE')
    date=str(row['target']);statuses={m:'SUCCESS' if date in s[m] else s['terminal'][m].get(date,unresolved.get((b.group_id(item['key']),m,date),('RESOURCE_NOT_ATTEMPTED:'+stop_reason) if final and stop_reason else ('RESOURCE_NOT_ATTEMPTED' if final else 'PENDING'))) for m in ('chronos','prophet')};entry={'key':list(b.base.key(row)),'model_status':statuses,'ancestry':s['ancestry']}
    for m,status in statuses.items():counts[m+':'+status]+=1;by_h[str(row['horizon'])][m+':'+status]+=1
    if statuses['chronos']=='SUCCESS' and statuses['prophet']=='SUCCESS':
     counts['PAIRED_SUCCESS']+=1
    if final:pairs.append({'territory_id':g[0],'category':g[1],'origin':g[2],'horizon':int(row['horizon']),'target':date,'actual':float(row['actual']),'cutoff':b.base.ym(item['cutoff']),'forecast_step':b.base.month(date)-item['cutoff'],'nonmissing_context_points':sum(math.isfinite(x) for x in item['context']),'pred_chronos2':s['chronos'].get(date),'pred_prophet_lag2':s['prophet'].get(date),'chronos_status':statuses['chronos'],'prophet_status':statuses['prophet'],'paired_success':statuses['chronos']=='SUCCESS' and statuses['prophet']=='SUCCESS','prophet_cached':date in item['cached_prophet'],'pred_cutoff_anchor':series.get(item['cutoff']),'pred_observed_seasonal':series.get(b.base.month(date)-12) if b.base.month(date)-12<=item['cutoff'] else None})
    if any(v=='PENDING' or v.startswith('RESOURCE_NOT_ATTEMPTED') for v in statuses.values()):pending+=1
    f.write(json.dumps(entry,ensure_ascii=False,allow_nan=False)+'\n')
 tmp.replace(out/'row-statuses.jsonl');atomic(out/'coverage.json',{'requested':len(rows),'eligible':p['eligible_rows'],'history_excluded':len(excluded),'counts':dict(counts),'by_horizon':{k:dict(v) for k,v in by_h.items()},'pending_or_unattempted_rows':pending,'strict_original_V3':'INCONCLUSIVE','full_population_paired_risk':'UNAVAILABLE_IF_ANY_PAIR_MISSING','scientific_pass':False})
 return pairs,pending
