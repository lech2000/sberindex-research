"""Future observational journal adapter; never imports numerical dependencies.
Public execute ALWAYS refuses. No modified feature, graph, K, seed or fit API.
"""
import contextlib,hashlib,json,pathlib,os,time
P=pathlib.Path

def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False)
def fingerprint(v):
 if hasattr(v,'indptr') and hasattr(v,'indices') and hasattr(v,'data'):
  return {'kind':'sparse_CSR','shape':list(v.shape),'data':fingerprint(v.data),'indices':fingerprint(v.indices),'indptr':fingerprint(v.indptr)}
 if hasattr(v,'shape') and hasattr(v,'tobytes'):
  if str(v.dtype)=='object':raise ValueError('object pointer bytes forbidden')
  return {'shape':list(v.shape),'dtype':str(v.dtype),'tensor_SHA':hashlib.sha256(v.tobytes(order='C')).hexdigest()}
 if isinstance(v,dict):return {str(k):fingerprint(x) for k,x in v.items()}
 if isinstance(v,(list,tuple)):return [fingerprint(x) for x in v]
 if v is None or type(v) in (str,int,float,bool):canonical(v);return v
 raise ValueError('unsupported native request/result type')

def nominal_registry(protocol):
 cells=[{'kind':'real','arm':arm,'K':k,'seed':seed} for arm in protocol['arms'] for k in protocol['K'] for seed in protocol['seeds']]+[{'kind':'control','world':w,'gamma':g,'K':2,'seed':seed} for w in protocol['controls']['worlds'] for g in protocol['controls']['gammas'] for seed in protocol['controls']['seeds']]
 native=[]
 for number,cell in enumerate(cells):
  if cell['kind']=='control':T=24;gamma=cell['gamma']
  else:
   feature=cell['arm']['feature'];T=23 if feature in ('growth_mom','shares_growth_mom') else 12 if feature=='growth_yoy' else 24;gamma=cell['arm']['gamma']
  for ordinal in range(1 if gamma>0 else T):
   for kind in ('eigsh','KMeans.fit_predict'):native.append({'key':f'native/{number}/{ordinal}/{kind}','cell':number,'ordinal':ordinal,'kind':kind,'status':'NOT_ATTEMPTED','nominal_only':True})
 if len(cells)!=225 or len(native)!=8220:raise ValueError('fixed225/4110decompositions/8220API receipts')
 return cells,native

class Adapter:
 def __init__(self,p,journal,guard,publication_root):
  self.publication_root=P(publication_root);self.protocol=p;self.journal=journal;self.guard=guard;self.cells,self.registry=nominal_registry(p);self.active=None;self.ordinal=0;self.stage=None;self.statuses=['NOT_ATTEMPTED_RESOURCE_STOP']*225;self.native={r['key']:r for r in self.registry}
 def cell_callback(self,record):
  key=record['key']
  if type(key)is not int or not 0<=key<225:raise ValueError('exact cell registry key')
  if record['state']=='STARTED':
   if self.active is not None or record['cell']!=self.cells[key] or self.statuses[key]!='NOT_ATTEMPTED_RESOURCE_STOP':raise ValueError('no cell change or retry')
   self.journal.start('cell/'+str(key),record);self.active=key;self.ordinal=0;self.stage='eigsh';self.statuses[key]='UNKNOWN_NATIVE_RESPONSE'
  elif record['state'] in ('COMPUTED','INCONCLUSIVE'):
   if self.active!=key or self.statuses[key]!='UNKNOWN_NATIVE_RESPONSE':raise ValueError('no unstarted/repeated cell response')
   files=[('assignments.parquet','assignmentSHA'),('summary.json','summarySHA')] if record['state']=='COMPUTED' else [('failure-assignments.parquet','rowsSHA'),('failure.json','failureSHA')]
   folder=self.publication_root/f'cell-{key:04d}'
   if folder.is_symlink():raise InterruptedError('publication symlink; no cell commit')
   for name,pin in files:
    path=folder/name
    if path.is_symlink() or not path.is_file():raise InterruptedError('published bytes missing; no cell commit')
    with path.open('rb') as f:
     h=hashlib.sha256()
     for block in iter(lambda:f.read(65536),b''):h.update(block)
     if h.hexdigest()!=record[pin]:raise InterruptedError('published SHA mismatch; no cell commit')
     os.fsync(f.fileno())
   for directory in (folder,self.publication_root):
    fd=os.open(directory,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
   if record['state']=='COMPUTED' and any(r['status']!='RESPONSE' for r in self.registry if r['cell']==key):raise InterruptedError('computed cell without all native responses')
   self.journal.response('cell/'+str(key),record);self.statuses[key]=record['state'];self.active=None
  else:raise ValueError('honest cell status required')
 def native_call(self,kind,request,fn,result_metadata):
  self.guard()
  if self.active is None or kind!=self.stage:raise ValueError('native call outside declared cell/order')
  key=f'native/{self.active}/{self.ordinal}/{kind}'
  if key not in self.native or self.native[key]['status']!='NOT_ATTEMPTED':raise ValueError('unplanned native call/retry')
  request=dict(request,binding={'cell':self.cells[self.active],'ordinal':self.ordinal,'kind':kind,'protocol_SHA':'b1b15d99a8094690ba532d89846206ebbf60b653f7b7bb7873307f9a5cfa931a','method_SHA':'e5db7ad379bf2c6bcb261d05563bdb88c433a4178baec48399e3e9e0ef2ea21b'})
  self.journal.start(key,request);self.native[key]['status']='UNKNOWN_NATIVE_RESPONSE'
  value=fn();self.journal.response(key,result_metadata(value));self.native[key]['status']='RESPONSE'
  if kind=='eigsh':self.stage='KMeans.fit_predict'
  else:self.stage='eigsh';self.ordinal+=1
  return value
 @contextlib.contextmanager
 def observe(self,library):
  original_deps=library._deps;restoration=[];cached=[]
  def deps():
   if cached:return cached[0]
   values=list(original_deps());original_eigsh=values[3];klass=values[4];original_fit=klass.fit_predict;restoration.append((klass,original_fit))
   def eigsh(matrix,*args,**kwargs):return self.native_call('eigsh',{'matrix':fingerprint(matrix),'args':fingerprint(args),'kwargs':fingerprint(kwargs)},lambda:original_eigsh(matrix,*args,**kwargs),fingerprint)
   def fit(estimator,X,*args,**kwargs):
    return self.native_call('KMeans.fit_predict',{'params':fingerprint(estimator.get_params(deep=False)),'X':fingerprint(X),'args':fingerprint(args),'kwargs':fingerprint(kwargs)},lambda:original_fit(estimator,X,*args,**kwargs),lambda labels:{'labels':fingerprint(labels),'centers':fingerprint(estimator.cluster_centers_)})
   values[3]=eigsh;klass.fit_predict=fit;cached.append(tuple(values));return cached[0]
  library._deps=deps
  try:yield self
  finally:
   library._deps=original_deps
   for klass,method in reversed(restoration):klass.fit_predict=method

def execute(*args,**kwargs):raise RuntimeError('NOT_EXECUTABLE until independent operational spec/publication integration accepted')
