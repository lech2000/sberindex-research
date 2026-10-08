"""One-use resource profile toolkit, SOURCE ONLY. Public execute always refuses.
Numeric worker requires future adopted external supervisor and explicit root spec.
"""
import time
ENTRY = time.monotonic()  # before preparation, scientific imports or source reads
import datetime, hashlib, importlib.util, json, math, os, pathlib
P = pathlib.Path
KEY = 'E05-resource-preflight-fullshape-v1'
CPU_ENV = ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')

def finite(x):
    if isinstance(x,bool) or not isinstance(x,(float,int)) or not math.isfinite(x):
        raise ValueError('finite nonbool number required')
    return x

def digest(path):
    h=hashlib.sha256()
    with P(path).open('rb') as f:
        for b in iter(lambda:f.read(65536),b''): h.update(b)
    return h.hexdigest()

def sync_dir(path):
    fd=os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def once(path,obj):
    path=P(path)
    if path.is_symlink() or path.parent.is_symlink(): raise ValueError('symlink')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(obj,f,allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
    sync_dir(path.parent)

def validate_spec(spec,now=None):
    for k in ('whole_seconds','final_reserve_seconds','cleanup_seconds','poll_seconds'):
        if finite(spec[k])<=0: raise ValueError(k)
    if not 0<spec['cleanup_seconds']<=spec['final_reserve_seconds']<spec['whole_seconds']: raise ValueError('reserve')
    if spec['CPU_threads']!=1 or type(spec['CPU_threads']) is not int: raise ValueError('CPU1')
    for k,v in [('RSS_bytes',1073741824),('minimum_free_bytes',1073741824),('output_bytes',134217728)]:
        if type(spec[k]) is not int or spec[k]!=v: raise ValueError('fixed '+k)
    if type(spec['receipt_reserve_bytes']) is not int or not 0<spec['receipt_reserve_bytes']<spec['output_bytes']: raise ValueError('receipt reserve')
    deadline=datetime.datetime.fromisoformat(spec['absolute_deadline_UTC'])
    if deadline.tzinfo is None or deadline.utcoffset()!=datetime.timedelta(0): raise ValueError('UTC')
    if now is not None and deadline<=now: raise ValueError('expired')
    if spec.get('external_whole_supervisor_source_accepted') is not True: raise ValueError('native blocking supervisor required')
    return deadline

def bytes_owned(roots):
    seen=set();size=0
    for root in map(P,roots):
        if root.is_symlink(): raise ValueError('symlink root')
        for p in ([root] if root.is_file() else root.rglob('*') if root.is_dir() else []):
            if p.is_symlink(): raise ValueError('symlink')
            if p.is_file():
                s=p.stat();key=(s.st_dev,s.st_ino)
                if key not in seen: seen.add(key);size+=s.st_size
    return size

class SampledGuard:
    """No signals/reentrant timer. External supervisor must bound blocking native calls.
    rss/free are trusted known-own-tree aggregate observers, not arbitrary PID probes.
    """
    def __init__(self,spec,anchor,roots,rss,free,clock=time.monotonic,utc=None):
        self.deadline=validate_spec(spec);self.spec=spec;self.anchor=finite(anchor)
        self.roots=roots;self.rss=rss;self.free=free;self.clock=clock
        self.utc=utc or (lambda:datetime.datetime.now(datetime.timezone.utc));self.active=False
        self.samples={'count':0,'max_aggregate_RSS_bytes':0,'min_free_bytes':None,'max_combined_output_bytes':0}
    def __call__(self):
        if self.active: raise RuntimeError('nonreentrant guard')
        self.active=True
        try:
            for stage in range(2):
                elapsed=self.clock()-self.anchor
                if elapsed<0 or elapsed>=self.spec['whole_seconds']-self.spec['final_reserve_seconds']: raise InterruptedError('whole/final reserve')
                if self.utc()>=self.deadline: raise InterruptedError('absolute deadline')
                if stage==0:
                    rss=finite(self.rss());free=finite(self.free());size=bytes_owned(self.roots)
                    self.samples['count']+=1;self.samples['max_aggregate_RSS_bytes']=max(rss,self.samples['max_aggregate_RSS_bytes'])
                    self.samples['min_free_bytes']=free if self.samples['min_free_bytes'] is None else min(free,self.samples['min_free_bytes'])
                    self.samples['max_combined_output_bytes']=max(size,self.samples['max_combined_output_bytes'])
                    if rss>self.spec['RSS_bytes']: raise InterruptedError('RSS')
                    if free<self.spec['minimum_free_bytes']: raise InterruptedError('free')
                    if size>self.spec['output_bytes']-self.spec['receipt_reserve_bytes']: raise InterruptedError('output')
        finally: self.active=False

def fixture_keys(n=1896,T=24):
    for t in range(T):
        for u in range(n): yield (u,t)

def verify_fixture_keys(keys,n=1896,T=24):
    it=iter(keys)
    for expected in fixture_keys(n,T):
        if next(it,None)!=expected: raise ValueError('full Cartesian order/missing/duplicate')
    if next(it,None) is not None: raise ValueError('extra')
    return n*T

def _load(path,name):
    sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);return m

def _physical_fixture_io(out,guard):
    """Future physical IO:225 distinct files, full10,238,400 rows, no acceptance bank.
    UNKNOWN null fixture labels; numeric/method outputs are never fabricated.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema=pa.schema([('fixture_unit',pa.int32()),('fixture_month',pa.int8()),('label',pa.int32()),('status',pa.string())])
    records=[];total=0;started=time.monotonic()
    for c in range(225):
        guard();path=out/f'IO-FIXTURE-{c:03}.parquet'
        with pq.ParquetWriter(path,schema,compression='zstd') as writer:
            batch=[]
            for u,t in fixture_keys():
                batch.append({'fixture_unit':u,'fixture_month':t,'label':None,'status':'RESOURCE_FIXTURE_UNKNOWN_NOT_BANK'})
                if len(batch)==4096: guard();writer.write_table(pa.Table.from_pylist(batch,schema=schema));batch=[]
            if batch: guard();writer.write_table(pa.Table.from_pylist(batch,schema=schema))
        with path.open('rb') as f: os.fsync(f.fileno())
        sync_dir(out);guard()
        def read():
            for b in pq.ParquetFile(path).iter_batches(batch_size=4096):
                guard()
                for row in b.to_pylist():
                    if row['label'] is not None or row['status']!='RESOURCE_FIXTURE_UNKNOWN_NOT_BANK': raise ValueError('fixture labels/status')
                    yield row['fixture_unit'],row['fixture_month']
        rows=verify_fixture_keys(read());total+=rows;records.append({'file':path.name,'bytes':path.stat().st_size,'SHA256':digest(path),'rows':rows})
    # Physical nominal native receipt capacity; no claim any native API was called.
    for i in range(8220):
        if i%64==0: guard()
        once(out/f'IO-NATIVE-FIXTURE-{i:04}.json',{'fixture':True,'slot':i,'state':'NOT_ATTEMPTED','native_call':False})
    guard();return {'files':records,'status_rows':total,'native_receipt_fixture_files':8220,'elapsed_seconds':time.monotonic()-started,'scientific_acceptance':False}

def qualified_worker(repo,out,ledger,spec,source_protocol,guard,cleanup_known_own):
    """NOT reachable from CLI. Future supervisor must pass accepted source/spec/anchor.
    Caller owns only this new profile worker PG; cleanup callback must reap it and
    known own descendants even successful exit; no foreign PIDs/legacy namespaces.
    """
    validate_spec(spec,datetime.datetime.now(datetime.timezone.utc));guard()
    if finite(spec['original_anchor'])>ENTRY or guard.anchor!=spec['original_anchor']: raise ValueError('earliest anchor must include imports; no clock reset')
    if spec.get('execution_authorized') is not True or source_protocol.get('execution_authorized') is not True:
        raise PermissionError('source-only NOT_EXECUTABLE')
    for k in CPU_ENV:
        if os.environ.get(k)!='1': raise ValueError('inherited CPU1 '+k)
    repo=P(repo);out=P(out);ledger=P(ledger)
    if out!=P('/private/tmp/e05-resource-preflight-fullshape-v1') or ledger!=P('/private/tmp/e05-resource-preflight-fullshape-v1-ledger'): raise ValueError('fixed own distinct namespace')
    if not {out,ledger}.issubset(set(map(P,guard.roots))): raise ValueError('guard must count output/ledger/logs')
    if out.exists() or ledger.exists() or out.is_symlink() or ledger.is_symlink(): raise FileExistsError('no consumed namespace/retry')
    if out.parent.is_symlink() or ledger.parent.is_symlink(): raise ValueError('parent symlink')
    for path,h in source_protocol['source_pins'].items():
        guard();f=repo/path
        if f.is_symlink() or digest(f)!=h: raise ValueError('source pin '+path)
    ledger.mkdir(mode=0o700);sync_dir(ledger.parent)
    once(ledger/'operation.json',{'key':KEY,'state':'STARTED','original_anchor':spec['original_anchor'],'whole_seconds':spec['whole_seconds'],'scientific_bank_started':False})
    out.mkdir(mode=0o700);sync_dir(out.parent);terminal={'state':'UNKNOWN','actual_scientific_bank':False,'resource_PASS':False};stages=[];native=[]
    def journal(obj): guard();once(ledger/f'journal-{len(native):03}.json',obj);native.append(obj)
    try:
        guard();s=time.monotonic()
        import numpy as np
        import pandas as pd
        import scipy
        import sklearn
        from scipy import sparse
        from scipy.sparse.linalg import eigsh
        from sklearn.cluster import KMeans
        method=_load(repo/'economic-atlas/src/atlas_e05_remaining_v2.py','profile_pinned_method')
        a6=_load(repo/'economic-atlas/src/a6_temporal.py','profile_pinned_a6')
        p=json.loads((repo/'economic-atlas/protocols/E05_FULL_REMAINING_V2.json').read_bytes());method.verify_inputs(repo,p)
        panel=pd.read_parquet(repo/'economic-atlas/data/panel_v1.parquet');ids,months,shares,_=a6.build_monthly_shares(panel)
        if len(ids)!=1896 or list(months)!=p['months'] or shares.shape!=(1896,24,5): raise ValueError('full shape')
        common,_=a6.standardize_frozen(shares,months)
        edges=pd.read_parquet(repo/'economic-atlas/runs/A5/edges.parquet');index={int(t):i for i,t in enumerate(ids)};i=[index[int(t)]for t in edges.u];j=[index[int(t)]for t in edges.v];w=edges.weight.to_numpy(float)
        geo=method._normalize(sparse.csr_matrix((np.r_[w,w],(np.r_[i,j],np.r_[j,i])),shape=(1896,1896)),np,sparse)
        guard();stages.append({'phase':'imports_panel_cube_A5','seconds':time.monotonic()-s,'common_shape':list(common.shape),'geo_nnz':int(geo.nnz)})
        s=time.monotonic();graphs=[]
        for t in range(24):guard();graphs.append(method._normalize(method._affinity(shares[:,t,:],20,'union',np,sparse),np,sparse))
        stages.append({'phase':'all24_raw_shares_k20_union_graphs','seconds':time.monotonic()-s})
        # Observational wrappers forward unchanged frozen numeric calls/results.
        def array_sha(a): return hashlib.sha256(a.tobytes(order='C')).hexdigest()
        def csr_sha(a):
            h=hashlib.sha256(json.dumps(list(a.shape)).encode())
            for v in (a.indptr,a.indices,a.data):h.update(v.dtype.str.encode());h.update(v.tobytes())
            return h.hexdigest()
        def observed_eigsh(a,**kwargs):
            guard();s=time.monotonic();journal({'API':'eigsh','state':'STARTED','shape':list(a.shape),'input_CSR_SHA256':csr_sha(a),'K':kwargs['k'],'tol':kwargs['tol'],'maxiter':kwargs['maxiter'],'which':kwargs['which'],'v0_SHA256':array_sha(kwargs['v0'])})
            values,v=eigsh(a,**kwargs);guard();res=np.linalg.norm(a@v-v*values[None,:],axis=0);orth=np.linalg.norm(v.T@v-np.eye(v.shape[1]))
            journal({'API':'eigsh','state':'RESPONSE','seconds':time.monotonic()-s,'eigen_residuals':res.tolist(),'orthogonality_error':float(orth),'output_SHA256':array_sha(values)+':'+array_sha(v)});return values,v
        class ObservedKMeans:
            def __init__(self,**kwargs):self.kwargs=kwargs;self.model=KMeans(**kwargs)
            def fit_predict(self,x):
                guard();s=time.monotonic();journal({'API':'KMeans.fit_predict','state':'STARTED','shape':list(x.shape),'input_SHA256':array_sha(x),'params':self.kwargs});labels=self.model.fit_predict(x);guard();journal({'API':'KMeans.fit_predict','state':'RESPONSE','seconds':time.monotonic()-s,'labels_count':len(labels),'labels_SHA256':array_sha(labels),'centres_SHA256':array_sha(self.model.cluster_centers_)});return labels
        if p['K']!=[2,5] or p['seeds'][0]!=20261008: raise ValueError('frozen maxK/firstseed')
        seed=p['seeds'][0]
        for kind in ('monthly1896_gamma0','supra45504_gamma2'):
            guard();s=time.monotonic()
            selected=graphs[0] if kind.startswith('monthly') else sparse.block_diag(graphs,format='csr')
            if kind.startswith('supra'):
                nodes=np.arange(1896)
                for t in range(23):
                    i=t*1896+nodes;j=(t+1)*1896+nodes;selected+=sparse.csr_matrix((np.full(3792,2.),(np.r_[i,j],np.r_[j,i])),shape=selected.shape)
            labels=method._partition(selected,5,seed,np,sparse,observed_eigsh,ObservedKMeans)
            guard();stages.append({'phase':kind,'seconds':time.monotonic()-s,'nodes':selected.shape[0],'K':5,'seed':seed,'label_count':len(labels),'scientific_labels_saved':False});del labels
        io=_physical_fixture_io(out,guard)
        terminal.update(state='RESOURCE_PROFILE_MEASURED_NOT_FULL_QUALIFICATION',stages=stages,native_pairs=2,IO_fixture=io,versions={'numpy':np.__version__,'scipy':scipy.__version__,'sklearn':sklearn.__version__,'pandas':pd.__version__,'python':__import__('sys').version},cost_estimate={'nominal_calls':8220,'quality_month_slots':4180,'measured_pair_extrapolation_seconds':4110*max(v['seconds']for v in stages if v['phase']in ('monthly1896_gamma0','supra45504_gamma2')),'fullbank_seconds':'UNKNOWN: variable convergence/control graphs, allqualitymetrics and225 bank serialization not bounded by two diagnostic pairs','extrapolation_is_bound':False})
    except BaseException as exc:
        terminal.update(state='INCONCLUSIVE_PROFILE_STOP',error=type(exc).__name__+': '+str(exc),cost_estimate='UNKNOWN',stages=stages)
        raise
    finally:
        # External supervisor's original anchor includes this cleanup and terminal IO.
        try: cleanup_known_own()
        except BaseException as cleanup_error:
            terminal.update(state='INCONCLUSIVE_CLEANUP_UNKNOWN',cleanup_error=type(cleanup_error).__name__,cost_estimate='UNKNOWN')
        terminal.update(sampled_resources=guard.samples,source_pins=source_protocol['source_pins'],full_input_shape=[1896,24,5],profile_K=5,profile_seed=20261008,CPU_environment={k:os.environ.get(k)for k in CPU_ENV},original_anchor=spec['original_anchor'],elapsed_before_terminal_fsync=time.monotonic()-spec['original_anchor'],final_receipt_IO_independently_timed=False,monitor='sampled; notcontinuous')
        once(ledger/'terminal.json',terminal)
    return terminal

def execute(*args,**kwargs):
    raise PermissionError('SOURCE_ONLY_NOT_EXECUTABLE: independent source/F7b and prospective root supervisor/budget required; no profile or bank now')

if __name__=='__main__': execute()
