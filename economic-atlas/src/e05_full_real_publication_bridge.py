"""Root-admitted real E05 publication and independent audit, one original clock.
No fits, retries, fabricated values or mock callback gates. Trusted local review
is authority to execute; receipt completeness does not prove scientific success.
"""
import hashlib, json, math, os, pathlib, stat, ctypes, sys, time
import e05_full_publication_finalizer_v5 as frozen
import e05_full_publication_validator_v5 as v
P=pathlib.Path
OPERATION_KEY=frozen.OPERATION_KEY
NONCOMPUTED=frozen.NONCOMPUTED
strict_json=frozen.strict_json
safe=frozen.safe
fsync_dir=frozen.fsync_dir
mkdir_durable=frozen.mkdir_durable
write_json=frozen.write_json
copy_bound=frozen.copy_bound
reconcile=frozen.reconcile
StatusRows=frozen.StatusRows
make_pairings=frozen.make_pairings


def canonical_path(path, *, exists=True, directory=False):
    path=P(path)
    if not path.is_absolute() or path.resolve()!=path or any(q.is_symlink() for q in (path,*path.parents)):
        raise ValueError('canonical absolute path without symlinks')
    if exists:
        s=path.stat()
        if (directory and not stat.S_ISDIR(s.st_mode)) or (not directory and not stat.S_ISREG(s.st_mode)):
            raise ValueError('regular file or directory required')
    return path


def atomic_publish_no_replace(stage,target):
    """Actual OS exclusive directory rename; refuse unsupported platform/kernel.
    Existing targets stay intact; same-filesystem operation and parent fsync.
    """
    stage=canonical_path(stage,directory=True)
    target=canonical_path(target,exists=False)
    canonical_path(target.parent,directory=True)
    if stage.parent!=target.parent or stage.stat().st_dev!=target.parent.stat().st_dev:
        raise ValueError('atomic publisher needs same-filesystem siblings')
    if target.exists() or target.is_symlink():raise FileExistsError('target already exists')
    libc=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        fn=getattr(libc,'renamex_np',None)
        if fn is None:raise RuntimeError('exclusive OS publisher unavailable')
        fn.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
        rc=fn(os.fsencode(stage),os.fsencode(target),4) # RENAME_EXCL
    elif sys.platform.startswith('linux'):
        fn=getattr(libc,'renameat2',None)
        if fn is None:raise RuntimeError('exclusive OS publisher unavailable')
        fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
        rc=fn(-100,os.fsencode(stage),-100,os.fsencode(target),1) # RENAME_NOREPLACE
    else:raise RuntimeError('exclusive OS publisher unsupported; no unsafe fallback')
    if rc!=0:
        err=ctypes.get_errno();raise OSError(err,os.strerror(err),str(target))
    fsync_dir(target.parent)


class SourceView:
    """Read-only composite view of raw artifacts, real journals and ID universe.
    Streams bounded chunks and binds SHA+inode/stat before and after each read.
    No raw artifact is rewritten or copied into the input namespace.
    """
    def __init__(self,raw_root,journal_root,territory_file,guard):
        self.guard=guard;self.paths={};self.stats={};self.inventory={}
        self.raw=canonical_path(raw_root,exists=False)
        self.raw_initially_absent=not self.raw.exists()
        if not self.raw_initially_absent:canonical_path(self.raw,directory=True)
        self.journals=canonical_path(journal_root,directory=True)
        self.directory_identity={p:(p.stat().st_dev,p.stat().st_ino) for p in (self.journals,*(() if self.raw_initially_absent else (self.raw,)))}
        self.territory=canonical_path(territory_file)
        if self.raw==self.journals or self.raw in self.journals.parents or self.journals in self.raw.parents:
            raise ValueError('disjoint raw and journal namespaces')
        for p in sorted(self.raw.rglob('*')):
            guard()
            if p.is_symlink():raise ValueError('raw source symlink')
            if p.is_dir():continue
            self._add(p.relative_to(self.raw).as_posix(),p)
        for p in sorted(self.journals.iterdir()):
            if p.is_dir() or not (p.name.endswith('.STARTED.json') or p.name.endswith('.RESPONSE.json')):
                raise ValueError('actual journal directory contains unexpected paths')
            self._add('journals/'+p.name,p)
        self._add('territory-universe.json',self.territory)

    @staticmethod
    def _stat(p):
        s=p.stat();return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns

    def _add(self,name,path):
        safe(name);path=canonical_path(path)
        if name in self.paths:raise ValueError('composite source namespace collision')
        self.guard();before=self._stat(path);pin=v.sha(path,self.guard)
        if before!=self._stat(path):raise ValueError('source changed during inventory')
        self.paths[name]=path;self.stats[name]=before;self.inventory[name]=pin

    def read_chunks(self,name):
        self.verify_namespace()
        safe(name);path=self.paths[name];canonical_path(path)
        if self._stat(path)!=self.stats[name]:raise ValueError('inventoried source rebound')
        h=hashlib.sha256()
        with path.open('rb') as f:
            while True:
                self.guard();chunk=f.read(65536)
                if not chunk:break
                h.update(chunk);yield chunk
        self.guard()
        if self._stat(path)!=self.stats[name] or h.hexdigest()!=self.inventory[name]:
            raise ValueError('inventoried source bytes changed')

    def verify_namespace(self,full=False):
        self.guard()
        if self.raw_initially_absent and (self.raw.exists() or self.raw.is_symlink()):
            raise ValueError('absent raw namespace appeared after inventory')
        for p,identity in self.directory_identity.items():
            canonical_path(p,directory=True)
            if (p.stat().st_dev,p.stat().st_ino)!=identity:
                raise ValueError('inventoried source directory rebound')
        if full:
            # One terminal bounded path-set reconciliation, rather than a full
            # rescan for every input chunk. Never omit late UNKNOWN journals.
            current={'territory-universe.json':self.territory}
            for i,p in enumerate(self.raw.rglob('*')):
                if i%1024==0:self.guard()
                if p.is_symlink():raise ValueError('late raw source symlink')
                if p.is_file():current[p.relative_to(self.raw).as_posix()]=canonical_path(p)
            for i,p in enumerate(self.journals.iterdir()):
                if i%1024==0:self.guard()
                current['journals/'+p.name]=canonical_path(p)
            if current!=self.paths:raise ValueError('source path set changed after inventory')
            for i,(name,p) in enumerate(current.items()):
                if i%1024==0:self.guard()
                if self._stat(p)!=self.stats[name]:raise ValueError('source stat changed after inventory')
            self.guard()


def validate_original_admission(admission,original_operation,guard):
    """Re-read actual independently reviewed resource report, never bool alone."""
    import e05_full_execution_controller as controller
    report=controller.validate_resource_report(admission)
    spec=admission['spec'];binding=controller.SOURCE_BINDING
    if admission.get('source_binding')!=binding or not v.hash_token(admission.get('independent_source_ACK_SHA')):
        raise ValueError('new root-reviewed source admission required')
    for key in ('operation','state','original_anchor','whole_seconds','finalization_reserve_seconds','source_binding','admissionreportSHA','territory_ids_SHA'):
        if key not in original_operation:raise ValueError('incomplete original operation')
    if original_operation['operation']!=OPERATION_KEY or original_operation['state']!='STARTED':
        raise ValueError('same original operation only')
    if original_operation['original_anchor']!=guard.anchor or original_operation['whole_seconds']!=guard.whole_seconds or spec['whole_seconds']!=guard.whole_seconds:
        raise ValueError('no replacement original clock/allowance')
    if original_operation['source_binding']!=binding or getattr(guard,'source_binding',None)!=binding:
        raise ValueError('same admitted scientific source binding')
    if original_operation['finalization_reserve_seconds']!=spec['finalization_reserve_seconds'] or getattr(guard,'finalization_reserve_seconds',None)!=spec['finalization_reserve_seconds']:
        raise ValueError('same original finalization reserve')
    if original_operation['admissionreportSHA']!=admission['real_IO_resource_report_SHA'] or getattr(guard,'resource_admission_SHA',None)!=admission['real_IO_resource_report_SHA']:
        raise ValueError('original actual admission report SHA')
    if getattr(guard,'qualified_e05_audit_io',False)is not True or getattr(guard,'phase',None)!='publication':
        raise ValueError('original qualified guardian in post-reap publication phase')
    guard();return report


def _qualified_finalize(protocol_bytes,source_inventory,read_chunks,row_reader,row_writer,publish_no_replace,guard,original_operation,spec,stage,target,lease):
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


def complete_and_audit(*,repo,raw_root,publication_root,stage_root,journal_root,
                       territory_file,guard,original_operation,admission,
                       finalization_lease):
    """Real full artifacts+read-only numeric audit, same original owned operation.
    Caller must have reaped all owned workers before switching guardian phase.
    Finite data/solver truth limitations remain explicit. No automatic action close.
    """
    import e05_full_numeric_adapter as numeric
    report=validate_original_admission(admission,original_operation,guard)
    repo=canonical_path(repo,directory=True)
    if P(numeric.__file__).resolve()!=repo/'economic-atlas/src/e05_full_numeric_adapter.py' or P(frozen.__file__).resolve()!=repo/'economic-atlas/src/e05_full_publication_finalizer_v5.py' or P(v.__file__).resolve()!=repo/'economic-atlas/src/e05_full_publication_validator_v5.py':
        raise ValueError('loaded immutable adapters belong to admitted repo')
    # Controller already verified complete source pins before registration;
    # repeat our substantive source bindings before real publication/IO.
    import e05_full_execution_controller as controller
    for name in ('economic-atlas/src/e05_full_real_publication_bridge.py',
                 'economic-atlas/src/e05_full_publication_finalizer_v5.py',
                 'economic-atlas/src/e05_full_publication_validator_v5.py',
                 'economic-atlas/src/e05_full_numeric_adapter.py'):
        if v.sha(canonical_path(repo/name),guard)!=admission['source_pins'][name]:
            raise ValueError('admitted bridge source pin')
    target=canonical_path(publication_root,exists=False)
    stage=canonical_path(stage_root,exists=False)
    lease=canonical_path(finalization_lease,exists=False)
    roots=[canonical_path(p,exists=False) for p in guard.roots]
    if any(not any(p==r or r in p.parents for r in roots) for p in (target,stage,lease)):
        raise ValueError('whole guard must count publication, stage and lease')
    protocol_bytes=(repo/'economic-atlas/protocols/E05_FULL_REMAINING_V2.json').read_bytes()
    view=SourceView(raw_root,journal_root,territory_file,guard)
    spec=dict(admission['spec'],source_binding=admission['source_binding'])
    verdict=_qualified_finalize(protocol_bytes,view.inventory,view.read_chunks,
        v.arrow_rows,frozen.arrow_writer,atomic_publish_no_replace,guard,
        original_operation,spec,stage,target,lease)
    # The scalar/NumPy reference independently derives inputs and frozen truth.
    # It never fits/retries clustering and does not infer lost raw tensors.
    binding={'anchor_monotonic':guard.anchor,'whole_seconds':spec['whole_seconds'],
        'prior_elapsed_floor':time.monotonic()-guard.anchor,
        'receipt_reserve_seconds':spec['audit_receipt_reserve_seconds'],
        'rss_limit_bytes':spec['RSS_bytes'],'output_limit_bytes':spec['output_bytes'],
        'minimum_free_bytes':spec['minimum_free_bytes'],'CPU_threads':spec['CPU_threads'],
        'independent_resource_IO_admission_SHA':admission['real_IO_resource_report_SHA'],
        'resource_cost_qualified':report['remaining_quality_control_cost_state']=='INDEPENDENTLY_ADMITTED'}
    numeric_admission=numeric.Admission(binding,guard)
    audited=numeric.Adapter(repo,target,numeric_admission,protocol_bytes).audit()
    guard();controller.validate_resource_report(admission);guard()
    # Preserve the audited manifest binding; a replacement cannot become a new
    # accepted outer SHA after independent metric validation has completed.
    numeric.verified_file(target,'publication-manifest.json',audited['publication_manifest_SHA'],guard)
    view.verify_namespace(full=True)
    result={'state':'FULL_STATUS_AND_INDEPENDENT_METRIC_AUDIT_COMPLETED',
        'operation':OPERATION_KEY,'original_anchor':guard.anchor,
        'publication_verdict':verdict,'independent_metric_audit':audited,
        'publication_manifest_SHA':audited['publication_manifest_SHA'],
        'actual_resource_report_SHA':admission['real_IO_resource_report_SHA'],
        'solver_numeric_audit':'UNKNOWN_FINGERPRINTS_ONLY_NOT_RESIDUALS',
        'scientific_pass':False,'economic_identity':False,'causal':False,
        'formal_promise_complete':False,'source_actions_closed':0,
        'actual_whole_resource_PASS':False,'monitor':'sampled, not continuous',
        'last_receipt_IO_independently_timed':False}
    write_json(P(str(lease)+'.METRIC_AUDIT'),result,guard)
    return result


def execute(*args,**kwargs):
    raise RuntimeError('Use independently reviewed original controller binding; no standalone or mock-bank execution')

if __name__=='__main__':execute()
