"""Read-only full E05 numeric input adapter. No fits or author numeric oracles.
Actual execution is refused pending independently qualified original resource/IO
admission. Arrow imports are lazy. Source helpers support tiny fixture review.
"""
import pathlib, json, hashlib, math, os, stat, time, datetime
import e05_independent_numerical_audit as numerical
import e05_full_publication_validator_v5 as publication
import e05_numpy_quality_reference as vectorized
P=pathlib.Path
CATEGORIES=['Все категории','Здоровье','Маркетплейсы','Общественное питание','Продовольствие','Транспорт']
PANEL_SCHEMA=[('date','string'),('territory_id','int16'),('category','string'),('value','int32'),('ym','string')]
EDGES_SCHEMA=[('u','int64'),('v','int64'),('distance','double'),('weight','double')]
SOURCE_PINS={'economic-atlas/src/e05_independent_numerical_audit.py': 'd1232759428269eba5c720324695d91fda3917fdaca3ead4ae2bc2fdd1d04da8', 'economic-atlas/src/e05_full_publication_validator_v5.py': 'dda073bc0bf223321b6af9f39d2ed57f1f39ad33e92ac633003f3777f9239193', 'economic-atlas/src/atlas_e05_remaining_v2.py': 'e5db7ad379bf2c6bcb261d05563bdb88c433a4178baec48399e3e9e0ef2ea21b', 'economic-atlas/src/a6_temporal.py': 'c498d5a7d145264e0182e589a7dedb2b733fb9854cb5c167227e42f2eb3c9474', 'economic-atlas/src/network_icvi.py': 'acea75f3faa87a625cab54d9a52fe65a91a824031947a3a4e8b251bb0b4ef404', 'economic-atlas/src/atlas_sdbw.py': 'fc9a83fc430028452a8a88622337df605574518baf2044f0ab068f142edfd9fa', 'economic-atlas/src/e05_numpy_quality_reference.py': 'ffdb98abf3cf4adcf6c3f8badf50ebe46ff4cd431af3e88db7d75b3d2a42ad49'}


def strict_json(raw):
    def object_hook(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('duplicate JSON key')
            out[k]=v
        return out
    return json.loads(raw,object_pairs_hook=object_hook,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def safe_file(root,name):
    root=P(root)
    if not root.is_absolute() or root!=root.resolve():raise ValueError('canonical absolute input root')
    relative=P(name)
    if relative.is_absolute()or '..'in relative.parts or str(relative)!=name:raise ValueError('safe relative input path')
    path=root/relative
    for p in (path,*path.parents):
        if p.is_symlink():raise ValueError('no input symlink')
    s=path.stat()
    if not stat.S_ISREG(s.st_mode):raise ValueError('regular input file')
    return path


def verified_file(root,name,pin,guard):
    path=safe_file(root,name);before=path.stat();value=publication.sha(path,guard);after=path.stat()
    if not publication.hash_token(pin)or value!=pin or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('input byteSHA or immutable stat changed')
    return path


def parquet_rows(path,schema,guard):
    import pyarrow.parquet as pq
    reader=pq.ParquetFile(path)
    if [(f.name,str(f.type))for f in reader.schema_arrow]!=schema:raise ValueError('exact discovered native Parquet physical schema')
    for batch in reader.iter_batches(batch_size=1024):guard();yield from batch.to_pylist()


def input_cube(rows,tids,months):
    if len(tids)!=len(set(tids))or any(type(t)is not int for t in tids)or sorted(tids)!=list(tids):raise ValueError('sorted unique native IDs')
    if len(months)!=len(set(months)):raise ValueError('unique full month axis')
    ti={t:i for i,t in enumerate(tids)};mi={m:i for i,m in enumerate(months)};ci={c:i for i,c in enumerate(CATEGORIES)}
    cube=[[[None]*6 for _ in months]for _ in tids];count=0
    for row in rows:
        if set(row)!={n for n,_ in PANEL_SCHEMA}:raise ValueError('native panel schema')
        tid=row['territory_id'];date=row['date'];month=row['ym'];cat=row['category']
        if type(tid)is not int or tid not in ti or type(date)is not str or type(month)is not str or month not in mi or cat not in ci:raise ValueError('native ID/month/category not in frozen axes')
        parsed=date if len(date)==7 else datetime.date.fromisoformat(date[:10]).strftime('%Y-%m')
        if parsed!=month:raise ValueError('native date/ym disagreement')
        value=numerical.finite(row['value'])
        if value<=0:raise ValueError('finite positive source, no silent fill')
        i,t,c=ti[tid],mi[month],ci[cat]
        if cube[i][t][c]is not None:raise ValueError('duplicate native source key')
        cube[i][t][c]=value;count+=1
    if count!=len(tids)*len(months)*6:raise ValueError('full source rectangle missing rows')
    return cube


def geography(rows,tids):
    idx={tid:i for i,tid in enumerate(tids)}
    if len(idx)!=len(tids):raise ValueError('native geography identity duplicates')
    a=[[0.]*len(tids)for _ in tids]
    for row in rows:
        if set(row)!={n for n,_ in EDGES_SCHEMA}:raise ValueError('native A5 edge schema')
        u,v=row['u'],row['v'];w=numerical.finite(row['weight']);d=numerical.finite(row['distance'])
        if type(u)is not int or type(v)is not int or u not in idx or v not in idx or u==v or w<=0 or d<0:raise ValueError('literal edge endpoint/weight/distance')
        i,j=idx[u],idx[v];a[i][j]+=w;a[j][i]+=w
    degree=[math.fsum(row)for row in a]
    if any(d<=0 for d in degree):raise ValueError('original isolate cannot be repaired by synthetic bridge')
    scale=[1/math.sqrt(d)for d in degree]
    for i,row in enumerate(a):
        for j,w in enumerate(row):
            if w:row[j]=w*scale[i]*scale[j]
    return a


def sequences(rows,tids,months,K,cell,status,guard=lambda:None):
    # Exact full mask is checked independently from the validator's first read.
    rows=list(rows);coverage=publication.row_universe(iter(rows),tids,months,K,cell,status,guard)
    index={tid:i for i,tid in enumerate(tids)};mi={m:t for t,m in enumerate(months)};seq=[[None]*len(tids)for _ in months]
    for row in rows:
        if row['status']=='COMPUTED':seq[mi[row['month']]][index[row['territory_id']]]=int(row['label'])
    result=[]
    for t,values in enumerate(seq):
        if all(v is None for v in values):result.append(None)
        elif any(v is None for v in values):raise ValueError('partial month never enters metric as full cohort')
        else:result.append(values)
    return result,coverage


def full_key_sha(tids,months):
    h=hashlib.sha256()
    for month in months:
        for tid in tids:h.update((publication.canonical({'territory_id':tid,'month':month})+'\n').encode())
    return h.hexdigest()


def fixed_truth(cell,protocol,n=None,T=None):
    """Independent deterministic truth only, not X/noise/RNG/world generation.
    _controls truth is parity initially; fixed leading movers flip at shift only
    for abrupt_shift. Seed affects Xnoise, not this declared truth construction.
    """
    ctl=protocol['controls'];n=ctl['n']if n is None else n;T=ctl['months']if T is None else T;shift=ctl['shift_month_index']
    if cell['kind']!='control'or cell['world']not in ctl['worlds']or cell['gamma']not in ctl['gammas']or cell['seed']not in ctl['seeds']or not 0<shift<T:raise ValueError('exact control cell/shift binding')
    movers=list(range(int(n*ctl['shift_fraction'])));truth=[]
    for i in range(n):truth.append([((i%2)^1)if cell['world']=='abrupt_shift'and i<len(movers) and t>=shift else i%2 for t in range(T)])
    return truth,movers


def publication_envelope(protocol,records,manifest,tids,result):
    numerical.validate_frozen_protocol(protocol);publication.registry(protocol,records)
    if len(tids)!=1896 or sorted(tids)!=tids or len(set(tids))!=1896 or any(type(t)is not int for t in tids):raise ValueError('full sorted1896 identity axis')
    if result['cells']!=225 or result['status_rows']!=10238400:raise ValueError('actual V5 status_rows full scope')
    keys={'real':full_key_sha(tids,protocol['months']),'control':full_key_sha(list(range(1896)),protocol['months'])}
    key_sha={};assignment_sha={};summary_sha={}
    for i,record in enumerate(records):
        key_sha[str(i)]=keys[record['cell']['kind']]
        if record['status']=='COMPUTED':
            a=manifest['files'][f'cell-{i:04d}/assignments.parquet'];b=manifest['files'][f'cell-{i:04d}/summary.json']
            if not publication.hash_token(a)or not publication.hash_token(b):raise ValueError('typed complete artifact SHA maps')
            assignment_sha[str(i)]=a;summary_sha[str(i)]=b
    pair_sha=manifest['files']['paired-comparisons.json']
    if not publication.hash_token(pair_sha):raise ValueError('paired file SHA')
    return {'cells':225,'full_status_rows':result['status_rows'],'independent_full_file_readback':True,'cell_key_SHA':key_sha,'assignment_SHA':assignment_sha,'summary_SHA':summary_sha,'paired_comparisons_SHA':pair_sha,'validator_receipt':result}


class Admission:
    """Metadata validator; real guard remains externally independently admitted.
    It does not reset a clock, create a model lease or start an owned process.
    """
    def __init__(self,binding,guard,now=None):
        now=numerical.finite(time.monotonic()if now is None else now)
        for k in ('anchor_monotonic','whole_seconds','prior_elapsed_floor','receipt_reserve_seconds','rss_limit_bytes','output_limit_bytes','minimum_free_bytes'):
            numerical.finite(binding[k])
        if any(type(binding[k])is not int for k in ('rss_limit_bytes','output_limit_bytes','minimum_free_bytes')):raise ValueError('integer byte budgets')
        if binding['CPU_threads']!=1 or type(binding['CPU_threads'])is not int:raise ValueError('one CPU thread')
        if binding['anchor_monotonic']>now or binding['prior_elapsed_floor']<0 or binding['whole_seconds']<=0 or not 0<binding['receipt_reserve_seconds']<binding['whole_seconds']:raise ValueError('original inclusive clock/budget')
        if max(now-binding['anchor_monotonic'],binding['prior_elapsed_floor'])+binding['receipt_reserve_seconds']>=binding['whole_seconds']:raise ValueError('original budget exhausted; no reset')
        if not 0<binding['rss_limit_bytes']<=1024**3 or not 0<binding['output_limit_bytes']<=128*1024**2 or binding['minimum_free_bytes']<1024**3:raise ValueError('prospective resource cap domain')
        if not publication.hash_token(binding.get('independent_resource_IO_admission_SHA'))or binding.get('resource_cost_qualified')is not True or getattr(guard,'qualified_e05_audit_io',False)is not True:raise RuntimeError('UNKNOWN resource/IO cost refuses actual audit')
        if getattr(guard,'anchor',None)!=binding['anchor_monotonic']or getattr(guard,'whole_seconds',None)!=binding['whole_seconds']:raise ValueError('actual same original guardian clock')
        self.binding=binding;self.guard=guard


class Adapter:
    def __init__(self,repo,root,admission,protocol_bytes):
        if not isinstance(admission,Admission):raise RuntimeError('explicit validated original-budget admission required')
        self.repo=P(repo);self.root=P(root);self.guard=admission.guard;self.protocol=numerical.pinned_protocol(protocol_bytes);self._labels={};self._prepared=False
        for name,pin in SOURCE_PINS.items():verified_file(self.repo,name,pin,self.guard)
        if P(vectorized.__file__).resolve()!=self.repo/'economic-atlas/src/e05_numpy_quality_reference.py':raise ValueError('actual vectorized evaluator pinned file')
        if P(numerical.__file__).resolve()!=self.repo/'economic-atlas/src/e05_independent_numerical_audit.py' or P(publication.__file__).resolve()!=self.repo/'economic-atlas/src/e05_full_publication_validator_v5.py':raise ValueError('actual loaded modules must be pinned repo files')

    def bind_control_inputs(self):
        if hasattr(self,'control_pins'):raise RuntimeError('validated input control namespace cannot be rebound')
        self.control_pins={};self.control_stats={}
        for name in ('publication-manifest.json','cell-registry.json','territory-universe.json','paired-comparisons.json'):
            path=safe_file(self.root,name);pin=publication.sha(path,self.guard)
            verified_file(self.root,name,pin,self.guard);self.control_pins[name]=pin
            st=path.stat();self.control_stats[name]=(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
        return self.control_pins

    def verify_control_inputs(self):
        for name,pin in self.control_pins.items():
            path=verified_file(self.root,name,pin,self.guard);st=path.stat()
            if (st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)!=self.control_stats[name]:raise ValueError('validated control file immutable stat changed')

    def verify_publication(self):
        guard=self.guard;guard();root=self.root;self.bind_control_inputs()
        self.manifest=strict_json(safe_file(root,'publication-manifest.json').read_bytes());self.records=strict_json(safe_file(root,'cell-registry.json').read_bytes());self.tids=strict_json(safe_file(root,'territory-universe.json').read_bytes())
        if sorted(self.tids)!=self.tids:raise ValueError('original sorted native identity axis')
        result=publication.validate_publication(root,self.protocol,self.manifest,self.records,self.tids,guard=guard)
        self.pairs=strict_json(safe_file(root,'paired-comparisons.json').read_bytes());self.pairindex={p['key']:p for p in self.pairs}
        self.verify_control_inputs()
        self.envelope=publication_envelope(self.protocol,self.records,self.manifest,self.tids,result)
        self.envelope['validated_control_file_SHA']=dict(self.control_pins)
        panel='economic-atlas/data/panel_v1.parquet';edges='economic-atlas/runs/A5/edges.parquet';panel_pin=self.protocol['data_pins'][panel];edge_pin=self.protocol['source_pins'][edges]
        pp=verified_file(self.repo,panel,panel_pin,guard);ep=verified_file(self.repo,edges,edge_pin,guard)
        values=input_cube(parquet_rows(pp,PANEL_SCHEMA,guard),self.tids,self.protocol['months']);self.common=numerical.frozen_common(values,self.protocol['months'],guard);self.geo=geography(parquet_rows(ep,EDGES_SCHEMA,guard),self.tids)
        # Shared source byteSHA and independently derived tensor hashes; these
        # are not claims that the legacy executor persisted its raw X/truth.
        self.input_receipt={'input_source_pins':dict(self.protocol['data_pins']),'common_metric_train_year':'2023','actual_tensor_hashes_verified':True,'panel_byte_SHA':panel_pin,'edge_byte_SHA':edge_pin,'common_tensor_SHA':numerical.canonical_sha(self.common),'geo_tensor_SHA':numerical.canonical_sha(self.geo),'tensor_hash_basis':'INDEPENDENTLY_DERIVED_FROM_PINNED_SOURCE_BYTES_AND_FROZEN_LOGIC', 'legacy_raw_tensor_capture_equality_verified':False, 'truth_provenance':'INDEPENDENT_FIXED_SOURCE_LOGIC_NOT_LEGACY_CAPTURE','no_source_numerical_oracle':True}
        verified_file(self.repo,panel,panel_pin,guard);verified_file(self.repo,edges,edge_pin,guard)
        import numpy as np
        self.geo=np.asarray(self.geo,dtype=float);self._prepared=True;guard();return self.envelope

    def load_verified_payload(self,i,cell):
        if not self._prepared or self.records[i]['cell']!=cell or self.records[i]['status']!='COMPUTED':raise ValueError('prepared exact computed cell only')
        guard=self.guard;guard();folder=f'cell-{i:04d}/';a=folder+'assignments.parquet';s=folder+'summary.json'
        if i in self._labels:return self._labels[i]
        ap=verified_file(self.root,a,self.manifest['files'][a],guard);sp=verified_file(self.root,s,self.manifest['files'][s],guard);summary=strict_json(sp.read_bytes())
        tids=self.tids if cell['kind']=='real'else list(range(1896));seq,_=sequences(publication.arrow_rows(ap),tids,self.protocol['months'],cell['K'],cell,'COMPUTED',guard)
        verified_file(self.root,a,self.manifest['files'][a],guard);verified_file(self.root,s,self.manifest['files'][s],guard)
        proof=dict(self.input_receipt);payload={'labels':seq,'full_keys_SHA':self.envelope['cell_key_SHA'][str(i)],'assignment_SHA':self.manifest['files'][a],'summary_SHA':self.manifest['files'][s],'independent_input_receipt':proof}
        if cell['kind']=='real':
            payload['common_spending_points']=[[self.common[j][t]for j in range(1896)]for t in range(24)];payload['geo_reference']=self.geo
            pair=self.pairindex[i]
            if pair['status']=='COMPUTED'and cell['arm']['id']!='shares':payload['saved_pair_metrics']=pair['agreement'];payload['saved_pair_file_SHA']=self.envelope['paired_comparisons_SHA']
        else:
            truth,movers=fixed_truth(cell,self.protocol);payload.update(truth=truth,movers=movers);proof.update(truth_generator_source_SHA=numerical.METHOD_SHA,truth_cell=cell,truth_tensor_SHA=numerical.canonical_sha(truth))
        if cell['kind']=='real'and cell['arm']['id']=='shares':self._labels[i]=(payload,summary)
        return payload,summary

    def audit(self):
        self.guard();self.verify_publication()
        # Bound wrappers expose qualified-library IO, not a security capability.
        def verify():self.guard();return self.envelope
        def load(i,c):return self.load_verified_payload(i,c)
        verify.qualified_e05_audit_io=load.qualified_e05_audit_io=True
        result=numerical.audit_bank(self.protocol,self.records,verify,load,self.guard,quality_backend=vectorized.quality)
        for name,pin in self.manifest['files'].items():verified_file(self.root,name,pin,self.guard)
        self.verify_control_inputs();self.guard();return dict(result,publication_manifest_SHA=self.control_pins['publication-manifest.json'],validated_control_file_SHA=dict(self.control_pins),independent_input_receipt=self.input_receipt,actual_resource_cost_PASS=False)


def execute(*args,**kwargs):raise RuntimeError('NOT_EXECUTABLE_SOURCE_ONLY: real fullsize performance/IO/source/resource admission and root one-use binding required')
