"""Stdlib publication core; optional Arrow reader is lazy and never used here."""
import hashlib,itertools,json,math,pathlib
P=pathlib.Path
PROTOCOL_SHA='b1b15d99a8094690ba532d89846206ebbf60b653f7b7bb7873307f9a5cfa931a'
METHOD_SHA='e5db7ad379bf2c6bcb261d05563bdb88c433a4178baec48399e3e9e0ef2ea21b'
SOURCE_ACK_SHA='9c418c1f37284cbd6250bca1335753591fc2d2e6151c0f2cfd24d98e740395ef'
STATUS={'COMPUTED','INPUT_UNAVAILABLE','INCONCLUSIVE_METHOD_FAILURE','NOT_ATTEMPTED_RESOURCE_STOP','UNKNOWN_NATIVE_RESPONSE'}

def sha(p,guard=lambda:None):
 h=hashlib.sha256()
 with P(p).open('rb') as f:
  for x in iter(lambda:f.read(65536),b''):guard();h.update(x)
 return h.hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def planned(p):
 real=[{'kind':'real','arm':arm,'K':k,'seed':seed} for arm in p['arms'] for k in p['K'] for seed in p['seeds']]
 controls=[{'kind':'control','world':world,'gamma':gamma,'K':2,'seed':seed} for world in p['controls']['worlds'] for gamma in p['controls']['gammas'] for seed in p['controls']['seeds']]
 if len(real)!=180 or len(controls)!=45 or len({canonical(c) for c in real+controls})!=225:raise ValueError('exact225 unique cells required')
 if p['panel_expected_shape']!=[1896,24,6] or len(p['months'])!=24 or p['K']!=[2,5]:raise ValueError('full fixed panel/K universe')
 return real+controls
def available(cell,t):
 if cell['kind']=='control':return True
 f=cell['arm']['feature'];return not (f in ('growth_mom','shares_growth_mom') and t==0 or f=='growth_yoy' and t<12)
def nominal_calls(p):
 return sum(1 if (c['gamma'] if c['kind']=='control' else c['arm']['gamma'])>0 else sum(available(c,t) for t in range(24)) for c in planned(p))
def row_universe(rows,tids,months,K,cell,execution_status,guard=lambda:None):
 """Streaming exact coverage including failures/NA, no implicit fill or shrink.
 Original pandas outputs may physically store labels int64/double/null; only
 integral finite semantic labels in [0,K) are accepted, never rewritten.
 """
 if len(tids)!=len(set(tids)) or any(type(t)is not int for t in tids):raise ValueError('exact integer statistical ID universe')
 if len(months)!=len(set(months)):raise ValueError('unique month universe')
 ti={t:i for i,t in enumerate(tids)};mi={m:i for i,m in enumerate(months)};seen=bytearray(len(tids)*len(months));counts=dict.fromkeys(STATUS,0);computed_per_month=dict.fromkeys(months,0)
 for number,row in enumerate(rows):
  if number%1024==0:guard()
  if set(row)!={'territory_id','month','label','status'}:raise ValueError('exact status schema')
  tid=row['territory_id'];month=row['month']
  if type(tid)is not int or tid not in ti or month not in mi:raise ValueError('unknown ID/month no named join')
  key=mi[month]*len(tids)+ti[tid]
  if seen[key]:raise ValueError('duplicate ID/month')
  seen[key]=1;status=row['status'];label=row['label']
  if status not in STATUS:raise ValueError('unknown row status')
  counts[status]+=1
  if status=='COMPUTED':
   computed_per_month[month]+=1
   if execution_status!='COMPUTED' or not available(cell,mi[month]):raise ValueError('computed row in failed/unavailable cell-month')
   if isinstance(label,bool) or not isinstance(label,(int,float)) or not math.isfinite(label) or label!=int(label) or not 0<=label<K:raise ValueError('invalid label')
  else:
   if label is not None:raise ValueError('unknown/NA/failure label must remain null, never zero')
   if execution_status=='COMPUTED' and (status!='INPUT_UNAVAILABLE' or available(cell,mi[month])):raise ValueError('unexpected missing computed month')
   expected={'INCONCLUSIVE':'INCONCLUSIVE_METHOD_FAILURE','NOT_ATTEMPTED_RESOURCE_STOP':'NOT_ATTEMPTED_RESOURCE_STOP','UNKNOWN_NATIVE_RESPONSE':'UNKNOWN_NATIVE_RESPONSE'}
   if execution_status!='COMPUTED' and status!=expected.get(execution_status):raise ValueError('row status must conserve exact durable cell status')
 if sum(seen)!=len(seen):raise ValueError('missing full ID/month rows')
 return {'rows':len(seen),'status_counts':counts,'computed_per_month':computed_per_month}
def arrow_rows(path):
 # Lazy optional dependency; actual Parquet files not opened by source tests.
 import pyarrow.parquet as pq
 import pyarrow as pa
 reader=pq.ParquetFile(path)
 schema=reader.schema_arrow
 if schema.names!=['territory_id','month','label','status']:raise ValueError('Parquet schema order')
 if not pa.types.is_integer(schema.field('territory_id').type) or not pa.types.is_string(schema.field('month').type) or not pa.types.is_string(schema.field('status').type):raise ValueError('Parquet ID/month/status types')
 if not (pa.types.is_integer(schema.field('label').type) or pa.types.is_floating(schema.field('label').type) or pa.types.is_null(schema.field('label').type)):raise ValueError('Parquet label physical type')
 for batch in reader.iter_batches(batch_size=1024):yield from batch.to_pylist()
def control_budget(metrics,world,p):
 b=p['controls']['error_budget']
 if world=='abrupt_shift':values={'miss':metrics.get('miss_fraction'),'delay':metrics.get('median_delay')};bounds={'miss':b['abrupt_missed_change_fraction_max'],'delay':b['abrupt_median_delay_months_max']}
 else:values={'false_switch':metrics.get('false_switch_fraction')};bounds={'false_switch':b['stable_false_switch_fraction_max'] if world=='stable' else b['seasonal_false_switch_fraction_max']}
 if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values.values()):return 'INCONCLUSIVE_UNDEFINED'
 return 'CONTROL_BUDGET_PASS' if all(values[k]<=bounds[k] for k in values) else 'CONTROL_BUDGET_FAIL'
def registry(p,records):
 cells=planned(p)
 if len(records)!=225 or [r['key'] for r in records]!=list(range(225)):raise ValueError('exact ordered225 registry; no omission')
 for i,r in enumerate(records):
  if r['cell']!=cells[i] or r['protocol_SHA']!=PROTOCOL_SHA or r['method_SHA']!=METHOD_SHA:raise ValueError('feature/K/seed/world/graph/protocol binding')
  if r['status'] not in {'COMPUTED','INCONCLUSIVE','NOT_ATTEMPTED_RESOURCE_STOP','UNKNOWN_NATIVE_RESPONSE'}:raise ValueError('explicit cell execution status required')
 return cells

def validate_publication(root,p,manifest,records,territory_ids,*,row_reader=arrow_rows,guard=lambda:None):
 """Full artifact acceptance, not numerical-method truth or case closure.
 Future guardian must add immutable publication manifest/225 registry; current
 library alone does not create them. No manifest = no full acceptance.
 """
 root=P(root);cells=registry(p,records)
 if len(territory_ids)!=1896 or len(set(territory_ids))!=1896 or any(type(t)is not int for t in territory_ids):raise ValueError('all1896 pinned statistical IDs')
 if manifest['protocol_SHA']!=PROTOCOL_SHA or manifest['method_SHA']!=METHOD_SHA or manifest['source_ACK_SHA']!=SOURCE_ACK_SHA:raise ValueError('manifest source review pins')
 if manifest['territory_ids_SHA']!=hashlib.sha256(canonical(territory_ids).encode()).hexdigest() or manifest['panel_SHA']!=p['data_pins']['economic-atlas/data/panel_v1.parquet']:raise ValueError('ID/panel provenance')
 files=manifest['files'];resolved=set()
 for name,h in files.items():
  guard();path=root/name
  if P(name).is_absolute() or '..' in P(name).parts or path.is_symlink() or not path.is_file() or path.resolve() in resolved:raise ValueError('exact safe manifest paths')
  resolved.add(path.resolve())
  if sha(path,guard)!=h:raise ValueError('publication file SHA')
 if not {'result.json','paired-comparisons.json','territory-universe.json','cell-registry.json','native-registry.json','journal-inventory.json'}<=set(files):raise ValueError('global publication inputs missing')
 disk_files={str(path.relative_to(root)) for path in root.rglob('*') if path.is_file()}
 if any(path.is_symlink() for path in root.rglob('*')) or disk_files!=set(files)|{'publication-manifest.json'}:raise ValueError('unmanifested bytes or symlink')
 if json.loads((root/'territory-universe.json').read_text())!=territory_ids or json.loads((root/'cell-registry.json').read_text())!=records:raise ValueError('manifest registry inputs differ from actual bytes')
 journal_inventory=json.loads((root/'journal-inventory.json').read_text())
 native_records=json.loads((root/'native-registry.json').read_text())
 validate_journals(p,records,native_records,journal_inventory,root,files,guard)
 result=json.loads((root/'result.json').read_text())
 if any(result.get(k) is not False for k in ['scientific_pass','economic_identity','causal','historical_asof','formal_promise_complete']):raise ValueError('unjustified positive claim')
 if result.get('mobility_reused_SHA')!=p['mobility_reuse_only']['SHA256'] or result.get('unknown_admin_population_confounds') is not True:raise ValueError('mobility/confounds qualifications')
 if result.get('M4_dependency')!='PENDING_SEPARATE_ACTUAL_ACCEPTANCE':raise ValueError('unknown M4 dependency cannot become satisfied')
 summaries=[];row_total=0;failures=[];controls=[];undefined=[]
 for i,(cell,record) in enumerate(zip(cells,records)):
  guard();folder=f'cell-{i:04d}/';complete=record['status']=='COMPUTED';data=folder+('assignments.parquet' if complete else 'failure-assignments.parquet');meta=folder+('summary.json' if complete else 'failure.json')
  if data not in files or meta not in files:raise ValueError('full cell publication missing; registry alone insufficient')
  summary=json.loads((root/meta).read_text())
  if summary['cell']!=cell:raise ValueError('cell summary exact method features/K/seed')
  tids=territory_ids if cell['kind']=='real' else list(range(1896));coverage=row_universe(row_reader(root/data),tids,p['months'],cell['K'],cell,record['status'],guard);row_total+=coverage['rows'];summaries.append(dict(key=i,**coverage))
  if not complete:
   if summary.get('status')!='INCONCLUSIVE' or not summary.get('error') or summary.get('full_rows_preserved')!=45504:raise ValueError('honest failed cell reason/full rows required')
   failures.append(i);continue
  if cell['kind']=='control':
   verdict=control_budget(summary['control_metrics'],cell['world'],p)
   if summary['budget']['status']!=verdict or summary.get('truth_not_training') is not True:raise ValueError('control budget/event semantics binding')
   controls.append({'key':i,'status':verdict})
  else:
   if summary['valid_month_indices']!=[t for t in range(24) if available(cell,t)] or len(summary['quality_same_spending_space'])!=24 or len(summary['adjacent'])!=23:raise ValueError('full feature/time metric status coverage')
   for t,q in enumerate(summary['quality_same_spending_space']):
    if not available(cell,t):
     if q.get('status')!='INPUT_UNAVAILABLE':raise ValueError('unavailable metric status')
    elif q.get('status')=='COMPUTED':
     if not {'SW','CH','S_Dbw','network_reference_indices','sizes'}<=set(q) or not {'AVI','AVU','Newman_Q'}<=set(q['network_reference_indices']):raise ValueError('all publication metric keys')
     if q.get('MQ')!='SPEC_UNRESOLVED_OWNER_EXCLUDED':raise ValueError('MQ is not NewmanQ')
    elif q.get('status')=='NA_DEGENERATE':undefined.append({'key':i,'month':p['months'][t]})
    else:raise ValueError('missing required quality status')
   for t,row in enumerate(summary['adjacent'],1):
    possible=available(cell,t-1) and available(cell,t)
    if row.get('t')!=t or row.get('status')!=('COMPUTED' if possible else 'INPUT_UNAVAILABLE'):raise ValueError('adjacent full time/status binding')
    if possible:
     if row.get('label_overlap_alignment_is_not_identity') is not True:raise ValueError('label overlap not economic identity')
     if sum(row['contingency'].values())!=1896 or any(type(n)is not int or n<0 for n in row['contingency'].values()):raise ValueError('transition full ID denominator')
     for metric in ('ARI','NMI','switch_fraction'):
      x=row[metric]
      if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):raise ValueError('adjacent finite metric')
     if not 0<=row['switch_fraction']<=1:raise ValueError('switch fraction bounds')
 pairs=json.loads((root/'paired-comparisons.json').read_text());saved_name='preserved-partials/original-paired-comparisons.json'
 saved_pairs=json.loads((root/saved_name).read_text()) if saved_name in files else []
 validate_pairing(p,records,pairs,{r['key']:r for r in summaries},saved_pairs,files.get(saved_name))
 unavailable_pairings=[r['key'] for r in pairs if r['status']!='COMPUTED']
 if row_total!=10238400:raise ValueError('all225x45504 rows required')
 if result.get('expected_cells')!=225 or result.get('full_technical_success')!=(not failures):raise ValueError('technical success/full expected cells honesty')
 if [r['key'] for r in result['cells']]!=list(range(225)) or [r['status'] for r in result['cells']]!=[r['status'] for r in records]:raise ValueError('result full registry disagreement')
 return {'publication_status':'FULL_FILES_WITH_EXPLICIT_FAILURES' if failures else 'FULL_FILES_WITH_UNAVAILABLE_COMPARISONS' if unavailable_pairings else 'FULL_FILES_VALIDATED','unavailable_pairings':unavailable_pairings,'cells':225,'status_rows':row_total,'failed_cells':failures,'undefined_metric_cells':undefined,'control_budgets':controls,'scientific_pass':False,'formal_promise_complete':False,'causal':False,'M4_dependency':'PENDING_SEPARATE_ACTUAL_ACCEPTANCE','unknown_admin_population_confounds':True,'M1_calibration_negative':True,'continuous_resource_pass':False,'limitation':'Files/schema/cell/budget arithmetic validation; not independent numerical metric truth or historical geography/causal acceptance.'}

def hash_token(v):return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)
def tensor(v):
 if not isinstance(v,dict):raise ValueError('tensor fingerprint required')
 if v.get('kind')=='sparse_CSR':
  for k in ('data','indices','indptr'):tensor(v[k])
 elif not hash_token(v.get('tensor_SHA')) or not v.get('dtype') or v['dtype']=='object':raise ValueError('semantic tensor SHA/dtype required')
 if not isinstance(v.get('shape'),list) or any(type(x)is not int or x<0 for x in v['shape']):raise ValueError('tensor shape')

def validate_journals(p,cell_records,native_records,inventory,root,files,guard=lambda:None):
 from e05_full_receipt_adapter_v5 import nominal_registry
 cells,expected=nominal_registry(p)
 if len(native_records)!=8220 or [r['key'] for r in native_records]!=[r['key'] for r in expected]:raise ValueError('all8220 nominal keys retained')
 keys=set();responses={}
 for r,e in zip(native_records,expected):
  guard()
  if any(r[k]!=e[k] for k in ('key','cell','ordinal','kind')) or r['status'] not in {'NOT_ATTEMPTED','UNKNOWN_NATIVE_RESPONSE','RESPONSE'}:raise ValueError('native registry binding/status')
  if r['status']=='NOT_ATTEMPTED':continue
  keys.add(r['key'])
  if r['status']=='RESPONSE':responses[r['key']]=r
 for i,c in enumerate(cell_records):
  if c['status']!='NOT_ATTEMPTED_RESOURCE_STOP':keys.add('cell/'+str(i))
  if c['status'] in ('COMPUTED','INCONCLUSIVE'):responses['cell/'+str(i)]=c
 if set(inventory)!=keys:raise ValueError('actual STARTED inventory vs all attempted keys')
 root=P(root)
 for key in keys:
  guard();entry=inventory[key];start=entry['STARTED']
  if start not in files:raise ValueError('unmanifested journal STARTED')
  st=json.loads((root/start).read_text())
  if isinstance(st.get('monotonic'),bool) or not isinstance(st.get('monotonic'),(int,float)) or not math.isfinite(st['monotonic']):raise ValueError('finite STARTED observation time')
  if st['key']!=key:raise ValueError('STARTED key mismatch')
  if key.startswith('cell/'):
   i=int(key.split('/')[1]);rq=st['request']
   if rq.get('key')!=i or rq.get('cell')!=cells[i] or rq.get('state')!='STARTED':raise ValueError('cell request binding')
  else:
   _,ci,ordinal,kind=key.split('/');cell=cells[int(ci)];rq=st['request'];seed=cell['seed']+(int(ordinal) if (cell.get('gamma',cell.get('arm',{}).get('gamma'))==0) else 0)
   if rq.get('binding')!={'cell':cell,'ordinal':int(ordinal),'kind':kind,'protocol_SHA':PROTOCOL_SHA,'method_SHA':METHOD_SHA}:raise ValueError('native request exact scientific binding')
   if kind=='eigsh':
    tensor(rq['matrix']);kw=rq['kwargs']
    if kw.get('k')!=cell['K'] or kw.get('which')!='SA' or kw.get('tol')!=1e-8 or kw.get('maxiter')!=5000:raise ValueError('frozen eigsh settings')
    tensor(kw['v0'])
   else:
    params=rq['params'];tensor(rq['X'])
    if params.get('n_clusters')!=cell['K'] or params.get('n_init')!=20 or params.get('random_state')!=seed:raise ValueError('frozen KMeans K/n_init/effective graph-index seed')
  if key in responses:
   resp=entry.get('RESPONSE')
   if resp not in files:raise ValueError('missing native/cell response')
   value=json.loads((root/resp).read_text())
   if isinstance(value.get('monotonic'),bool) or not isinstance(value.get('monotonic'),(int,float)) or not math.isfinite(value['monotonic']) or value['monotonic']<st['monotonic']:raise ValueError('RESPONSE after STARTED observation time')
   if value['key']!=key or value['started_SHA']!=files[start]:raise ValueError('response STARTED SHA binding')
   if key.startswith('native/'):
    result=value['result']
    if key.endswith('KMeans.fit_predict'):tensor(result['labels']);tensor(result['centers'])
    else:
     if not isinstance(result,list) or len(result)!=2:raise ValueError('eigen values/vectors response')
     for v in result:tensor(v)
   else:
    result=value['result'];i=int(key.split('/')[1]);c=cell_records[i]
    if result.get('key')!=i or result.get('state')!=c['status']:raise ValueError('cell response state')
    pairs=[('assignmentSHA','assignments.parquet'),('summarySHA','summary.json')] if c['status']=='COMPUTED' else [('rowsSHA','failure-assignments.parquet'),('failureSHA','failure.json')]
    for pin,name in pairs:
     if result.get(pin)!=files.get(f'cell-{i:04d}/'+name):raise ValueError('cell response publication SHA')
  elif 'RESPONSE' in entry:raise ValueError('unknown native response cannot claim committed response')
 for i,c in enumerate(cell_records):
  local=[r for r in native_records if r['cell']==i]
  states=[r['status'] for r in local];frontier=False
  for state in states:
   if frontier and state!='NOT_ATTEMPTED':raise ValueError('native attempted after unknown/unattempted frontier; no retry/order gap')
   if state!='RESPONSE':frontier=True
  if c['status']=='COMPUTED' and any(r['status']!='RESPONSE' for r in local):raise ValueError('computed cell missing native responses')
  if c['status']=='NOT_ATTEMPTED_RESOURCE_STOP' and any(r['status']!='NOT_ATTEMPTED' for r in local):raise ValueError('unstarted cell with attempted native calls')
 return {'nominal':8220,'started':len(keys),'responses':len(responses),'unknown':len(keys)-len(responses)}

def pairing_schema(p,records,coverage):
 """All180 real entries, including explicit unavailable comparisons.
 Actual shared counts come from validated full assignment/status key universes.
 No estimates or math-potential denominator substitutes for observed keys.
 """
 cells=registry(p,records);expected=[]
 for i,cell in enumerate(cells[:180]):
  baseline=next(j for j,c in enumerate(cells[:180]) if c['arm']['id']=='shares' and c['K']==cell['K'] and c['seed']==cell['seed'])
  counts=[]
  for key in (i,baseline):
   if key not in coverage:raise ValueError('full validated assignment coverage required')
   c=coverage[key]
   if c['rows']!=45504 or set(c['computed_per_month'])!=set(p['months']):raise ValueError('full coverage denominator')
   values=[c['computed_per_month'][m] for m in p['months']]
   exact=[1896 if records[key]['status']=='COMPUTED' and available(cells[key],t) else 0 for t in range(24)]
   if values!=exact:raise ValueError('observed assignment key counts disagree with durable cell state')
   counts.append(values)
  shared=[min(x,y) for x,y in zip(*counts)];n=sum(shared)
  successful=records[i]['status']=='COMPUTED' and records[baseline]['status']=='COMPUTED'
  reasons=[]
  if records[i]['status']!='COMPUTED':reasons.append('ARM_'+records[i]['status'])
  if records[baseline]['status']!='COMPUTED':reasons.append('BASELINE_'+records[baseline]['status'])
  expected.append({'key':i,'cell':cell,'baseline_key':baseline,'baseline_cell':cells[baseline],'arm_execution_status':records[i]['status'],'baseline_execution_status':records[baseline]['status'],'status':'COMPUTED' if successful else 'UNAVAILABLE','reasons':reasons,'denominators':{'universe':45504,'arm_available_keys':sum(counts[0]),'baseline_available_keys':sum(counts[1]),'paired_available':n,'unpaired':45504-n},'shared_per_month':shared})
 return expected

def check_saved_self_source(want,source):
 """Only PROVIDED evidence is checked; absent selfsource is legitimate.
 The numerical method writes exactly cell/denominators/agreement. Both
 finalizer and independent validator enforce the same actual-key schema.
 """
 if source is None:return
 expected={k:want['denominators'][k] for k in ('universe','paired_available','unpaired')}
 if set(source)!={'cell','denominators','agreement'} or source['cell']!=want['cell']:raise ValueError('saved self-baseline source schema/cell')
 denom=source['denominators']
 if not isinstance(denom,dict) or set(denom)!=set(expected) or any(type(x)is not int for x in denom.values()) or denom!=expected or source['agreement']!=[]:raise ValueError('corrupt saved self-baseline actual denominators/empty agreement required')

def validate_pairing(p,records,pairs,coverage,saved_pairs=None,saved_pairs_SHA=None):
 expected=pairing_schema(p,records,coverage);saved={}
 for source in (saved_pairs or []):
  key=canonical(source['cell'])
  if key in saved:raise ValueError('duplicate saved comparison')
  if key not in {canonical(c) for c in planned(p)[:180]}:raise ValueError('unplanned saved source comparison')
  saved[key]=source
 if len(pairs)!=180 or [r['key'] for r in pairs]!=list(range(180)):raise ValueError('all180 unique ordered real pairing entries required')
 for row,want in zip(pairs,expected):
  absent=want['status']=='COMPUTED' and want['cell']['arm']['id']!='shares' and canonical(want['cell']) not in saved
  if absent:want=dict(want,status='UNAVAILABLE_METRIC_EVIDENCE',reasons=['NO_DURABLE_SAVED_NUMERICAL_COMPARISON'])
  if any(row.get(k)!=value for k,value in want.items() if k!='shared_per_month'):raise ValueError('exact pairing binding/status/reasons/actual key denominators')
  agreement=row['agreement'];cell=want['cell']
  if want['status']=='UNAVAILABLE':
   exact=[{'month':m,'status':'UNAVAILABLE','n':0,'reasons':want['reasons']} for m in p['months']]
   if agreement!=exact:raise ValueError('unavailable comparison cannot contain invented numeric results')
  elif want['status']=='UNAVAILABLE_METRIC_EVIDENCE':
   exact=[{'month':m,'status':'UNAVAILABLE_METRIC_EVIDENCE' if n else 'INPUT_UNAVAILABLE','n':n,'reasons':want['reasons']} for m,n in zip(p['months'],want['shared_per_month'])]
   if agreement!=exact or 'source_pairs_SHA' in row:raise ValueError('missing numerical evidence cannot fabricate metrics or source SHA')
  elif cell['arm']['id']=='shares':
   check_saved_self_source(want,saved.get(canonical(cell)))
   if agreement:raise ValueError('baseline self comparison schema')
  else:
   source=saved[canonical(cell)]
   if not hash_token(saved_pairs_SHA) or row.get('source_pairs_SHA')!=saved_pairs_SHA or source.get('agreement')!=agreement or source.get('denominators')!={k:want['denominators'][k] for k in ('universe','paired_available','unpaired')}:raise ValueError('successful metrics require exact saved comparison byte SHA and cell/denominators')
   if len(agreement)!=24:raise ValueError('all24 paired month statuses')
   for t,rec in enumerate(agreement):
    n=want['shared_per_month'][t]
    if rec['month']!=p['months'][t] or rec['n']!=n or rec['status']!=('COMPUTED' if n else 'INPUT_UNAVAILABLE'):raise ValueError('shared actual ID/month key denominator')
    if n:
     for k in ('ARI_vs_sameKseed_shares','NMI_vs_sameKseed_shares'):
      x=rec[k]
      if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):raise ValueError('paired finite metric')
    elif set(rec)!={'month','n','status'}:raise ValueError('unavailable feature month cannot contain numeric results')
 return 180

def execute(*args,**kwargs):raise RuntimeError('NOT_EXECUTABLE until independently accepted source/resource spec and original-anchor audit admission')
