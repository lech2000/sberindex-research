"""SOURCE ONLY full E05 finalizer. Public execute always refuses actual IO.
All filesystem callbacks in tests concern owned synthetic schema fixtures.
No fit/generation/retry, no numerical dependencies, no replacement clock.
"""
import hashlib,json,math,os,pathlib,time
import e05_full_publication_validator_v5 as v
from e05_full_receipt_adapter_v5 import nominal_registry
P=pathlib.Path
OPERATION_KEY='E05-full-event-repaired-225cells-v1'
NONCOMPUTED={'INCONCLUSIVE':'INCONCLUSIVE_METHOD_FAILURE','UNKNOWN_NATIVE_RESPONSE':'UNKNOWN_NATIVE_RESPONSE','NOT_ATTEMPTED_RESOURCE_STOP':'NOT_ATTEMPTED_RESOURCE_STOP'}

def strict_json(raw):
 def pairs(items):
  d={}
  for k,value in items:
   if k in d:raise ValueError('duplicate JSON key')
   d[k]=value
  return d
 return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
def safe(name):
 p=P(name)
 if p.is_absolute() or '..' in p.parts or not p.parts or p.as_posix()!=name:raise ValueError('unsafe source/publication path')
 return p

def fsync_dir(directory):
 fd=os.open(directory,os.O_RDONLY)
 try:os.fsync(fd)
 finally:os.close(fd)
def mkdir_durable(path,root):
 path,root=P(path),P(root);relative=path.relative_to(root);parent=root
 for part in relative.parts:
  child=parent/part
  if child.is_symlink():raise ValueError('staging directory symlink')
  if not child.exists():child.mkdir(mode=0o700);fsync_dir(parent)
  elif not child.is_dir():raise ValueError('staging namespace collision')
  parent=child
def write_json(path,value,guard):
 guard();fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 fsync_dir(P(path).parent);guard()
def copy_bound(name,target,inventory,read_chunks,guard):
 safe(name);guard();h=hashlib.sha256()
 with target.open('xb') as f:
  for chunk in read_chunks(name):
   guard()
   if not isinstance(chunk,bytes) or len(chunk)>65536:raise ValueError('bounded byte reader contract')
   h.update(chunk);f.write(chunk)
  f.flush();os.fsync(f.fileno())
 fsync_dir(target.parent)
 if h.hexdigest()!=inventory[name]:raise ValueError('source bytes changed or false SHA')
 guard();return h.hexdigest()

def reconcile(protocol,journal_blobs):
 """Derive statuses solely from pinned durable receipts, never caller labels.
 journal_blobs iterable(path, rawbytes); detects duplicate keys/states/names.
 Detailed native API, timestamp/frontier and publication hash bindings are
 independently checked by validate_journals before final commit.
 """
 cells,native=nominal_registry(protocol);allowed={'cell/'+str(i) for i in range(225)}|{r['key'] for r in native};docs={};inventory={};seen_paths=set()
 for path,raw in journal_blobs:
  safe(path)
  if path in seen_paths:raise ValueError('duplicate journal file')
  seen_paths.add(path);doc=strict_json(raw);key=doc.get('key');state=path.rsplit('.',2)[-2]
  if key not in allowed or state not in ('STARTED','RESPONSE'):raise ValueError('unplanned durable journal key/state')
  if P(path).name!=hashlib.sha256(key.encode()).hexdigest()+'.'+state+'.json':raise ValueError('journal name/key binding')
  if (key,state) in docs:raise ValueError('duplicate journal key/state')
  docs[key,state]=(doc,hashlib.sha256(raw).hexdigest());inventory.setdefault(key,{})[state]=path
 for key,entry in inventory.items():
  if 'STARTED' not in entry:raise ValueError('response without durable STARTED')
  if 'RESPONSE' in entry and docs[key,'RESPONSE'][0].get('started_SHA')!=docs[key,'STARTED'][1]:raise ValueError('response linked to changed STARTED')
 records=[]
 for i,c in enumerate(cells):
  key='cell/'+str(i);status='NOT_ATTEMPTED_RESOURCE_STOP'
  if key in inventory:
   rq=docs[key,'STARTED'][0].get('request',{})
   if rq!={'key':i,'state':'STARTED','cell':c}:raise ValueError('exact full cell request binding')
   status='UNKNOWN_NATIVE_RESPONSE'
   if 'RESPONSE' in inventory[key]:
    status=docs[key,'RESPONSE'][0].get('result',{}).get('state')
    if status not in ('COMPUTED','INCONCLUSIVE'):raise ValueError('honest cell terminal response')
  records.append(dict(key=i,cell=c,status=status,protocol_SHA=v.PROTOCOL_SHA,method_SHA=v.METHOD_SHA))
 for r in native:
  key=r['key']
  if key in inventory:
   if records[r['cell']]['status']=='NOT_ATTEMPTED_RESOURCE_STOP':raise ValueError('native attempt without cell STARTED')
   r['status']='RESPONSE' if 'RESPONSE' in inventory[key] else 'UNKNOWN_NATIVE_RESPONSE'
 return records,native,inventory,docs

class StatusRows:
 """Full null status universe; no numerical values or guessed labels."""
 def __init__(self,tids,months,status):
  if status not in NONCOMPUTED.values() or len(tids)!=1896 or len(set(tids))!=1896 or any(type(t)is not int for t in tids) or len(months)!=24 or len(set(months))!=24:raise ValueError('exact full1896x24 status universe')
  self.tids=tuple(tids);self.months=tuple(months);self.status=status
 def __len__(self):return 45504
 def __iter__(self):
  for month in self.months:
   for tid in self.tids:yield dict(territory_id=tid,month=month,label=None,status=self.status)

def make_pairings(protocol,records,coverage,source_pairs,source_pairs_SHA=None):
 indexed={}
 cells=v.planned(protocol)
 for pair in source_pairs:
  key=v.canonical(pair['cell'])
  if key in indexed:raise ValueError('duplicate source pair')
  if key not in {v.canonical(c) for c in cells[:180]}:raise ValueError('unplanned source comparison')
  indexed[key]=pair
 result=[]
 for want in v.pairing_schema(protocol,records,coverage):
  row={k:value for k,value in want.items() if k!='shared_per_month'}
  if row['status']=='UNAVAILABLE':row['agreement']=[dict(month=m,status='UNAVAILABLE',n=0,reasons=row['reasons']) for m in protocol['months']]
  elif row['cell']['arm']['id']=='shares':
   # A self-baseline comparison has no ARI/NMI claim. Its completed full
   # assignment file plus durable cell/native response is its evidence.
   source=indexed.get(v.canonical(want['cell']))
   v.check_saved_self_source(want,source)
   row['agreement']=[]
  else:
   source=indexed.get(v.canonical(want['cell']))
   if source is None:
    row['status']='UNAVAILABLE_METRIC_EVIDENCE';row['reasons']=['NO_DURABLE_SAVED_NUMERICAL_COMPARISON']
    row['agreement']=[dict(month=m,status='UNAVAILABLE_METRIC_EVIDENCE' if n else 'INPUT_UNAVAILABLE',n=n,reasons=row['reasons']) for m,n in zip(protocol['months'],want['shared_per_month'])]
   else:
    if not v.hash_token(source_pairs_SHA):raise ValueError('saved comparison file SHA required')
    olddenom={k:row['denominators'][k] for k in ('universe','paired_available','unpaired')}
    if source['denominators']!=olddenom:raise ValueError('saved source pair shared denominator mismatch')
    row['agreement']=source['agreement'];row['source_pairs_SHA']=source_pairs_SHA
  result.append(row)
 v.validate_pairing(protocol,records,result,coverage,source_pairs,source_pairs_SHA)
 return result

def finalize_mockable(protocol_bytes,source_inventory,read_chunks,row_reader,row_writer,publish_no_replace,guard,original_operation,spec,stage,target,lease):
 """Inspectable finalization algorithm. REAL execution unconditionally denied.
 Injected callbacks must mark source_only_mock=True. Passing fixtures does not
 attest source authorization, real preflight, atomic OS publisher or data IO.
 """
 callbacks=(read_chunks,row_reader,row_writer,publish_no_replace,guard)
 if any(getattr(fn,'source_only_mock',False) is not True for fn in callbacks):raise RuntimeError('NOT_EXECUTABLE: actual finalization/IO authority absent')
 if hashlib.sha256(protocol_bytes).hexdigest()!=v.PROTOCOL_SHA:raise ValueError('exact immutable numerical protocol bytes')
 protocol=strict_json(protocol_bytes);v.planned(protocol)
 if original_operation.get('whole_seconds')!=spec.get('whole_seconds'):raise ValueError('no replacement whole budget')
 if original_operation.get('operation')!=OPERATION_KEY or original_operation.get('state')!='STARTED' or original_operation.get('original_anchor')!=getattr(guard,'anchor',None):raise ValueError('original operation key/anchor binding; no reset')
 for k in ('whole_seconds','finalization_reserve_seconds','metadata_bytes_limit'):
  x=spec.get(k)
  if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0:raise ValueError('prospective explicit finalization budget UNKNOWN')
 if original_operation.get('finalization_reserve_seconds')!=spec['finalization_reserve_seconds'] or getattr(guard,'finalization_reserve_seconds',None)!=spec['finalization_reserve_seconds']:raise ValueError('prospective original finalization reserve; no replacement allowance')
 if spec['finalization_reserve_seconds']>=spec['whole_seconds'] or getattr(guard,'whole_seconds',None)!=spec['whole_seconds']:raise ValueError('same original whole allowance with reserve')
 if spec.get('source_binding')!={'protocol_SHA':v.PROTOCOL_SHA,'method_SHA':v.METHOD_SHA,'source_ACK_SHA':v.SOURCE_ACK_SHA}:raise ValueError('original reviewed source binding')
 if original_operation.get('source_binding')!=spec['source_binding'] or getattr(guard,'source_binding',None)!=spec['source_binding']:raise ValueError('same source authority from original operation and guard')
 stage,target,lease=map(P,(stage,target,lease))
 if stage.parent.resolve()!=target.parent.resolve() or any(p.exists() or p.is_symlink() for p in (stage,target,lease)):raise ValueError('fresh sibling stage/target/one-use lease; no resume or overwrite')
 guard();write_json(lease,{'operation':OPERATION_KEY,'original_operation_SHA':hashlib.sha256(v.canonical(original_operation).encode()).hexdigest(),'original_anchor':guard.anchor,'state':'STARTED','fits_allowed':False},guard)
 stage.mkdir(mode=0o700);fsync_dir(stage.parent)
 try:
  for name,pin in source_inventory.items():safe(name)
  if any(not v.hash_token(pin) for pin in source_inventory.values()):raise ValueError('complete source byte hashes required')
  def small(name):
   if name not in source_inventory:raise ValueError('source metadata absent')
   chunks=[];size=0;h=hashlib.sha256()
   for chunk in read_chunks(name):
    guard()
    if not isinstance(chunk,bytes) or len(chunk)>65536:raise ValueError('bounded metadata reader')
    size+=len(chunk)
    if size>spec['metadata_bytes_limit']:raise ValueError('source metadata budget')
    chunks.append(chunk);h.update(chunk)
   if h.hexdigest()!=source_inventory[name]:raise ValueError('source metadata SHA')
   return b''.join(chunks)
  journal_names=[n for n in source_inventory if n.startswith('journals/')]
  records,native,journal_inventory,docs=reconcile(protocol,((n,small(n)) for n in journal_names))
  tids=strict_json(small('territory-universe.json'))
  if len(tids)!=1896 or len(set(tids))!=1896 or any(type(t)is not int for t in tids):raise ValueError('full exact ID universe without name joins')
  if original_operation.get('panel_SHA')!=protocol['data_pins']['economic-atlas/data/panel_v1.parquet'] or original_operation.get('territory_ids_SHA')!=hashlib.sha256(v.canonical(tids).encode()).hexdigest():raise ValueError('original admitted panel/ID universe binding')
  used={'territory-universe.json'};coverage={}
  for n in journal_names:
   dst=stage/safe(n);mkdir_durable(dst.parent,stage);copy_bound(n,dst,source_inventory,read_chunks,guard);used.add(n)
  for r in records:
   guard();i=r['key'];c=r['cell'];folder=stage/f'cell-{i:04d}';folder.mkdir(mode=0o700);fsync_dir(stage)
   complete=r['status']=='COMPUTED';data='assignments.parquet' if complete else 'failure-assignments.parquet';meta='summary.json' if complete else 'failure.json'
   if r['status'] in ('COMPUTED','INCONCLUSIVE'):
    response=docs['cell/'+str(i),'RESPONSE'][0]['result'];fields=[(data,'assignmentSHA' if complete else 'rowsSHA'),(meta,'summarySHA' if complete else 'failureSHA')]
    for name,pin in fields:
     source=f'cell-{i:04d}/'+name
     if source_inventory.get(source)!=response.get(pin):raise ValueError('published source files must match durable cell RESPONSE')
     copy_bound(source,folder/name,source_inventory,read_chunks,guard);used.add(source)
   else:
    row_writer(folder/data,StatusRows(tids if c['kind']=='real' else range(1896),protocol['months'],NONCOMPUTED[r['status']]),guard)
    with (folder/data).open('rb') as f:os.fsync(f.fileno())
    fsync_dir(folder)
    write_json(folder/meta,dict(cell=c,status='INCONCLUSIVE',execution_status=r['status'],error=r['status']+': no durable completed cell output; no labels inferred',full_rows_preserved=45504,synthetic_or_observed_estimates_added=False),guard)
   coverage[i]=v.row_universe(row_reader(folder/data),tids if c['kind']=='real' else list(range(1896)),protocol['months'],c['K'],c,r['status'],guard)
  source_pairs=strict_json(small('paired-comparisons.json')) if 'paired-comparisons.json' in source_inventory else []
  if 'paired-comparisons.json' in source_inventory:used.add('paired-comparisons.json')
  # Preserve every unused partial or original global byte under separate names;
  # no source is overwritten/deleted, no partial becomes COMPUTED evidence.
  for name in set(source_inventory)-used:
   dst=stage/'preserved-partials'/safe(name);mkdir_durable(dst.parent,stage)
   copy_bound(name,dst,source_inventory,read_chunks,guard)
  if 'paired-comparisons.json' in source_inventory:
   dst=stage/'preserved-partials'/'original-paired-comparisons.json';mkdir_durable(dst.parent,stage);copy_bound('paired-comparisons.json',dst,source_inventory,read_chunks,guard)
  pairs=make_pairings(protocol,records,coverage,source_pairs,source_inventory.get('paired-comparisons.json'))
  result={'state':'FULL_STATUS_PUBLICATION_WITH_ABSTENTIONS','expected_cells':225,'cells':[{'key':r['key'],'status':r['status']} for r in records],'full_technical_success':all(r['status']=='COMPUTED' for r in records),'scientific_pass':False,'economic_identity':False,'causal':False,'historical_asof':False,'formal_promise_complete':False,'M4_dependency':'PENDING_SEPARATE_ACTUAL_ACCEPTANCE','mobility_reused_SHA':protocol['mobility_reuse_only']['SHA256'],'unknown_admin_population_confounds':True,'M1_calibration_negative':True,'continuous_resource_pass':False,'independent_numerical_truth_audit':'NOT_PERFORMED','original_anchor':guard.anchor}
  for name,data in [('territory-universe.json',tids),('cell-registry.json',records),('native-registry.json',native),('journal-inventory.json',journal_inventory),('paired-comparisons.json',pairs),('result.json',result)]:write_json(stage/name,data,guard)
  files={str(p.relative_to(stage)):v.sha(p,guard) for p in stage.rglob('*') if p.is_file()}
  manifest={'protocol_SHA':v.PROTOCOL_SHA,'method_SHA':v.METHOD_SHA,'source_ACK_SHA':v.SOURCE_ACK_SHA,'territory_ids_SHA':hashlib.sha256(v.canonical(tids).encode()).hexdigest(),'panel_SHA':protocol['data_pins']['economic-atlas/data/panel_v1.parquet'],'files':files,'original_anchor':guard.anchor,'artifact_completeness_not_scientific_PASS':True}
  write_json(stage/'publication-manifest.json',manifest,guard)
  verdict=v.validate_publication(stage,protocol,manifest,records,tids,row_reader=row_reader,guard=guard)
  # Source-only publisher contract: atomic same-filesystem NO_REPLACE, fsync
  # parent before success. No unsafe rename fallback or overwrite is supplied.
  guard();publish_no_replace(stage,target);fsync_dir(target.parent);guard()
  write_json(P(str(lease)+'.RESPONSE'),{'operation':OPERATION_KEY,'original_anchor':guard.anchor,'publication_manifest_SHA':v.sha(target/'publication-manifest.json',guard),'artifact_status':verdict['publication_status'],'scientific_pass':False},guard)
  return verdict
 except BaseException as e:
  # Permanent STARTED remains consumed. Partial stage/target retained exactly;
  # no retry, deletion, new allowance or fake cell/native RESPONSE.
  failure=P(str(lease)+'.UNKNOWN')
  if not failure.exists():
   try:write_json(failure,{'state':'UNKNOWN_FINALIZATION','error':type(e).__name__+': '+str(e),'original_anchor':guard.anchor,'automatic_retry':False,'scientific_pass':False},guard)
   except BaseException:pass
  raise

def arrow_writer(path,rows,guard):
 """Lazy future Parquet adapter; never invoked in source-only tests."""
 import pyarrow as pa
 import pyarrow.parquet as pq
 schema=pa.schema([('territory_id',pa.int64()),('month',pa.string()),('label',pa.int64()),('status',pa.string())]);batch=[]
 with pq.ParquetWriter(path,schema,compression='zstd') as writer:
  for row in rows:
   batch.append(row)
   if len(batch)==1024:guard();writer.write_table(pa.Table.from_pylist(batch,schema=schema));batch=[]
  if batch:guard();writer.write_table(pa.Table.from_pylist(batch,schema=schema))
def execute(*args,**kwargs):raise RuntimeError('NOT_EXECUTABLE: prospective source/resource/IO authority and fullsize preflight absent; actual finalization forbidden')
if __name__=='__main__':execute()
