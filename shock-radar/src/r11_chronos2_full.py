"""Frozen fair Chronos2 full evaluator: preparation defaults to zero model calls.
Persistent separate Prophet interpreter; exact cache reuse; resumable model-stage checkpoints.
"""
from pathlib import Path
import argparse,collections,ctypes,datetime,hashlib,itertools,json,math,os,platform,select,signal,subprocess,sys,threading,time
for _name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:os.environ[_name]='1'
sys.path.insert(0,str(Path(__file__).resolve().parent))
import r10_chronos2_causal as base
FULL_PROTOCOL_SHA='e350b7c0fd9964ad6b085edaf01c498a34d72a10f3d0a698c20eaf54264b1691'
SMOKE_PROTOCOL_SHA='3130f59c03c94908c491fddba63b02bb59911135ce2bab07fef1963c04226893'
BASE_RUNNER_SHA='22b1572067518fc654dcad1fb7affc63a2f6691b156dfb7ebeb9c1af5978bebe'
PROPHET_SOURCE_SHA='b9e7e993cf90e2e290001c7067fda36ed9684a900dee0ffa9d656e424ef97bf1'
UNCERTAINTY_SHA='beef21e636c46a0e6cafdec70d678134986f35308d8236b92b34d37a8f647d87'
CACHE_SHA='c450491fb34d3c7d2680e20333e77b95750ad7761feba06bc6b8fe8e0724a7a6'
KEY_COLUMNS=('territory_id','category','origin','horizon','target')

def digest_keys(keys):
    h=hashlib.sha256()
    for k in sorted(keys):h.update((json.dumps(k,ensure_ascii=False,separators=(',',':'))+'\n').encode())
    return h.hexdigest()

def group_id(group):return hashlib.sha256(json.dumps(list(group),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def build_groups(rows,contexts,cache):
    groups={};excluded=[];reused=0
    for row in rows:
        g=(str(row['territory_id']),str(row['category']),str(row['origin']));cutoff,values=contexts[g]
        if sum(math.isfinite(v) for v in values)<6:excluded.append(base.key(row));continue
        item=groups.setdefault(g,{'key':g,'cutoff':cutoff,'context':values,'rows':[],'cached_prophet':{}})
        item['rows'].append(row);k=base.key(row)
        if k in cache:
            if float(cache[k]['actual'])!=float(row['actual']):raise ValueError('cache actual mismatch')
            value=float(cache[k]['pred_prophet'])
            if not math.isfinite(value):raise ValueError('cache nonfinite')
            item['cached_prophet'][str(row['target'])]=value;reused+=1
    return groups,excluded,reused

def batch_predict(pipe,items):
    """One native batch of groups sharing max required step; no crosslearning."""
    import torch
    lengths={max(base.month(x['target'])-i['cutoff'] for x in i['rows']) for i in items}
    if len(lengths)!=1:raise ValueError('batch length buckets required')
    length=next(iter(lengths));inputs=[torch.tensor(i['context'],dtype=torch.float32) for i in items]
    with torch.inference_mode():
        quantiles,medians=pipe.predict_quantiles(inputs,prediction_length=length,quantile_levels=[0.5],batch_size=len(items),context_length=24,cross_learning=False,limit_prediction_length=True)
    if len(medians)!=len(items) or len(quantiles)!=len(items):raise ValueError('native output group shape')
    output={}
    for item,median,quantile in zip(items,medians,quantiles):
        if tuple(median.shape)!=(1,length) or tuple(quantile.shape)!=(1,length,1):raise ValueError('native output shape')
        predictions={}
        for row in item['rows']:
            step=base.month(row['target'])-item['cutoff']
            if step!=int(row['horizon'])+2:raise ValueError('calendar mismatch')
            point=float(median[0,step-1].item())
            if not math.isfinite(point):raise ValueError('nonfinite native forecast')
            predictions[str(row['target'])]=point
        output[group_id(item['key'])]=predictions
    return output

def fixed_batches(groups):
    ordered=[i for g,i in sorted(groups.items())]
    for start in range(0,len(ordered),1000):
        buckets=collections.defaultdict(list)
        for item in ordered[start:start+1000]:buckets[max(base.month(r['target'])-item['cutoff'] for r in item['rows'])].append(item)
        for _,items in sorted(buckets.items()):
            for offset in range(0,len(items),16):yield items[offset:offset+16]


def cache_request(item,obs):
    series=obs[(item['key'][0],item['key'][1])]
    return {'cutoff':base.ym(item['cutoff']),'train':[[base.ym(m),v] for m,v in sorted(series.items()) if m<=item['cutoff']],
            'targets':sorted({str(r['target']) for r in item['rows'] if str(r['target']) not in item['cached_prophet']}),'seed':20260927}

def checkpoint_path(out,item):return out/'checkpoints'/ (group_id(item['key'])+'.json')

def read_checkpoint(out,item,fingerprint):
    path=checkpoint_path(out,item)
    if not path.exists():return {'fingerprint':fingerprint,'group_key':list(item['key']),'context_sha256':base.context_digest(item['context']),'status':'pending','chronos':{},'prophet':dict(item['cached_prophet'])}
    state=json.loads(path.read_text())
    if state['fingerprint']!=fingerprint or state['group_key']!=list(item['key']) or state['context_sha256']!=base.context_digest(item['context']):raise ValueError('checkpoint fingerprint/context mismatch')
    if state.get('uncertain_inflight'):raise ValueError('interrupted started call: review required; do not automatically refit')
    return state

def save_checkpoint(out,item,state):base.atomic(checkpoint_path(out,item),state)

def own_child_pids(pid):
    if platform.system()!='Darwin':
        import psutil
        return [p.pid for p in psutil.Process(pid).children(recursive=False)]
    lib=ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True);func=lib.proc_listchildpids;func.argtypes=[ctypes.c_int,ctypes.c_void_p,ctypes.c_int];func.restype=ctypes.c_int
    storage=(ctypes.c_int*256)();ctypes.set_errno(0);count=func(pid,storage,ctypes.sizeof(storage));error=ctypes.get_errno()
    if count<0 or error or count>=256:raise OSError(error,'nativechildlisting failed or truncated')
    return [int(storage[i]) for i in range(count) if storage[i]>0]

def own_descendants(pid):
    output=set();todo=[pid]
    while todo:
        for child in own_child_pids(todo.pop()):
            if child not in output:output.add(child);todo.append(child)
    return sorted(output)


def resource_preflight(out,reader=None):
    """Own child/grandchild tree probe using native psutil/libproc, zero models."""
    import psutil
    out=Path(out);out.mkdir(parents=True,exist_ok=True);proof=out/'resource-preflight.json'
    if proof.exists():raise ValueError('preserve previous probe receipt; fresh preflight path required')
    code="import subprocess,sys,json,time,os; c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)']); print(json.dumps({'pid':os.getpid(),'grandchild':c.pid}),flush=True); time.sleep(10)"
    child=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
    result={'new_model_calls':0,'new_Prophet_fits':0,'backend':'knownparent proc_listchildpids + psutil native proc_pidinfo RSS; no allPIDsysctl or externalps','owned_process_group':child.pid,'cleanup':'SIGTERM onlynewsession group spawned by thisprobe'}
    try:
        if not select.select([child.stdout],[],[],5)[0]:raise RuntimeError('resource child readiness timeout')
        ids=json.loads(child.stdout.readline());expected={child.pid,ids['grandchild']};owned=set(own_descendants(os.getpid()))
        if not expected<=owned:raise RuntimeError('resource tree enumeration omitted ownchild/grandchild')
        measurements={pid:(reader(pid) if reader else psutil.Process(pid).memory_info().rss) for pid in {os.getpid()}|expected}
        if any(not isinstance(x,int) or x<=0 for x in measurements.values()):raise RuntimeError('invalidRSS measurement')
        result.update(status='PASS_BEFORE_MODEL_CALLS',RSS_bytes_by_own_PID=measurements,known_child_grandchild_both_enumerated=True)
    except Exception as exc:result.update(status='INCONCLUSIVE_BEFORE_MODEL_CALLS',error=type(exc).__name__+': '+str(exc))
    finally:
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        child.wait(timeout=5)
        result['probe_parent_reaped']=True
        try:result['owned_group_removed']=not (set(locals().get('expected',set())) & set(own_descendants(os.getpid())))
        except Exception as cleanup_error:result['cleanup_enumeration_error']=str(cleanup_error);result['owned_group_removed']=False
        base.atomic(proof,result)
    if result['status']!='PASS_BEFORE_MODEL_CALLS' or not result['owned_group_removed']:raise RuntimeError('resourceinstrumentationpreflight failed; modelsnotstarted; receiptretained')
    return result


def stop_owned_group(process,grace=.5):
    """Only a Popen started in its own session; reap with bounded TERM/KILL."""
    if process.pid<=0 or process.pid==os.getpid():raise ValueError('invalid owned child')
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=2)

def bounded_ready_line(stream,timeout):
    deadline=time.monotonic()+timeout;buffer=bytearray();fd=stream.fileno();os.set_blocking(fd,False)
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([fd],[],[],remaining)[0]:raise RuntimeError('Prophet worker readiness timeout')
            chunk=os.read(fd,4096)
            if not chunk:raise RuntimeError('Prophet worker unavailable/partial readiness; see private worker log')
            buffer.extend(chunk)
            if len(buffer)>65536:raise RuntimeError('oversized worker readiness')
            if b'\n' in buffer:
                line,tail=bytes(buffer).split(b'\n',1)
                if tail:raise RuntimeError('unexpected unsolicited worker output')
                return line.decode('utf-8')
    finally:os.set_blocking(fd,True)


class Worker:
    def __init__(self,python,source,out,worker_ref,_timeout=30,_command=None):
        self.stderr=(out/'prophet-worker.log').open('a');self.process=None;self.worker_ref=worker_ref
        env=os.environ.copy();(out/'prophet-tmp').mkdir(exist_ok=True);env['TMPDIR']=str((out/'prophet-tmp').resolve());env['PYTHONDONTWRITEBYTECODE']='1'
        command=_command or [python,str(Path(__file__).with_name('r11_prophet_worker.py')),str(source)]
        try:
            self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,text=True,env=env,start_new_session=True)
            worker_ref[0]=self  # Ownership exposed BEFORE any readiness wait.
            line=bounded_ready_line(self.process.stdout,_timeout)
            if not line:raise RuntimeError('Prophet worker unavailable; see private worker log')
            self.metadata=json.loads(line)
            if not self.metadata.get('ready'):raise RuntimeError('Prophet worker not ready')
        except Exception:
            try:self.close()
            finally:worker_ref[0]=None
            raise
    def fit(self,request):
        self.process.stdin.write(json.dumps(request,allow_nan=False)+'\n');self.process.stdin.flush();line=self.process.stdout.readline()
        if not line:raise RuntimeError('Prophet worker stopped')
        result=json.loads(line)
        if not result.get('ok'):raise RuntimeError(result.get('error','workerfailure'))
        return result
    def close(self):
        try:
            if self.process is not None:
                stop_owned_group(self.process)
                for stream in [self.process.stdin,self.process.stdout]:
                    if stream is not None:stream.close()
        finally:
            self.stderr.close();self.worker_ref[0]=None

def start_guard(out,full,counters,worker_ref,invocation_started=None):
    import psutil
    stop=threading.Event();start=invocation_started if invocation_started is not None else time.monotonic();prior=json.loads((out/'resource-ledger.json').read_text()) if (out/'resource-ledger.json').exists() else {'cumulative_wall_s':0}
    limits=full['prospective_resources'];master=psutil.Process(os.getpid());peak=prior.get('peak_process_tree_rss_bytes',0)
    def monitor():
        nonlocal peak
        while not stop.wait(.25):
            elapsed=time.monotonic()-start
            try:
                rss=master.memory_info().rss
                for pid in own_descendants(master.pid):
                    try:rss+=psutil.Process(pid).memory_info().rss
                    except psutil.NoSuchProcess:pass
            except (OSError,psutil.Error) as exc:
                base.atomic(out/'resource-measurement-failure.json',{'status':'INCONCLUSIVE_UNMEASURABLE_RESOURCE','error':str(exc),'scientific_pass':False})
                w=worker_ref[0]
                if w is not None:
                    try:stop_owned_group(w.process)
                    except OSError:pass
                os._exit(125)
            peak=max(peak,rss);ledger={'cumulative_wall_s':prior['cumulative_wall_s']+elapsed,'invocation_wall_s':elapsed,'peak_process_tree_rss_bytes':peak,'counters':dict(counters)};base.atomic(out/'resource-ledger.json',ledger)
            if elapsed>limits['per_invocation_wall_s_cap_proposal'] or ledger['cumulative_wall_s']>limits['wall_total_seconds_cap_proposal'] or peak>limits['rss_limit_bytes']:
                base.atomic(out/'budget-stop.json',{'status':'INCONCLUSIVE_RESOURCE_LIMIT','ledger':ledger,'scientific_pass':False})
                w=worker_ref[0]
                if w is not None:
                    try:stop_owned_group(w.process)
                    except OSError:pass
                # Worker is an owned isolated processgroup; killing it also stops itsStan descendants.
                os._exit(124)
    thread=threading.Thread(target=monitor,daemon=True);thread.start()
    def finish():
        stop.set();thread.join(timeout=1);elapsed=time.monotonic()-start
        base.atomic(out/'resource-ledger.json',{'cumulative_wall_s':prior['cumulative_wall_s']+elapsed,'invocation_wall_s':elapsed,'peak_process_tree_rss_bytes':peak,'counters':dict(counters)})
    return finish

def month_interval(values):
    """Exact paired resampling by targetmonth, row-weighted, no independence claim."""
    import numpy as np
    sums=collections.defaultdict(lambda:[0.,0])
    for row in values:
        sums[row['target']][0]+=row['difference'];sums[row['target']][1]+=1
    blocks=list(sums.values());m=len(blocks)
    if not 1<=m<=6:raise ValueError('V2 expects<=6targetblocks')
    stats=[sum(blocks[i][0] for i in choice)/sum(blocks[i][1] for i in choice) for choice in itertools.product(range(m),repeat=m)]
    lo,hi=np.percentile(stats,[2.5,97.5]);return {'low':float(lo),'high':float(hi),'blocks':m,'resamples':m**m,'unit':'targetmonth','descriptive_only':True}

def mo_interval(rows,comparator):
    import numpy as np
    blocks=collections.defaultdict(lambda:[0.,0])
    for row in rows:
        d=abs(row['actual']-row['pred_chronos2'])-abs(row['actual']-row[comparator])
        if not math.isfinite(d):raise ValueError('nonfiniteclusterpair')
        blocks[str(row['territory_id'])][0]+=d;blocks[str(row['territory_id'])][1]+=1
    if not blocks:return {'status':'NOT_AVAILABLE','units':0}
    values=np.array([blocks[k] for k in sorted(blocks)],dtype=float);rng=np.random.default_rng(20261007);stats=[]
    for _ in range(1000):
        selected=values[rng.integers(0,len(values),size=len(values))];denominator=float(selected[:,1].sum())
        if denominator<=0:raise ValueError('zero denominatorcluster')
        stats.append(float(selected[:,0].sum()/denominator))
    lo,hi=np.percentile(stats,[2.5,97.5]);return {'low':float(lo),'high':float(hi),'units':len(values),'resamples':1000,'seed':20261007,'unit':'territory_id','descriptive_only':True,'independence_claimed':False}


def metrics(records):
    result={}
    for h in (1,3,6,12):
        rows=[r for r in records if r['horizon']==h]
        if not rows:result[str(h)]={'rows':0,'status':'NOT_AVAILABLE'};continue
        differences=[{'target':r['target'],'difference':abs(r['actual']-r['pred_chronos2'])-abs(r['actual']-r['pred_prophet_lag2'])} for r in rows]
        result[str(h)]={'rows':len(rows),'chronos2_MAE':sum(abs(r['actual']-r['pred_chronos2']) for r in rows)/len(rows),'prophet_lag2_MAE':sum(abs(r['actual']-r['pred_prophet_lag2']) for r in rows)/len(rows),'paired_Chronos2_minus_Prophet_AE':sum(x['difference'] for x in differences)/len(differences),'targetmonth_CI':month_interval(differences),'MO_cluster_CI':mo_interval(rows,'pred_prophet_lag2')}
        for column in ['pred_cutoff_anchor','pred_observed_seasonal']:
            paired=[r for r in rows if r[column] is not None]
            if not paired:result[str(h)][column]={'rows':0,'status':'NOT_AVAILABLE'};continue
            d=[{'target':r['target'],'difference':abs(r['actual']-r['pred_chronos2'])-abs(r['actual']-r[column])} for r in paired]
            result[str(h)][column]={'rows':len(paired),'baseline_MAE':sum(abs(r['actual']-r[column]) for r in paired)/len(paired),'chronos2_MAE_same_rows':sum(abs(r['actual']-r['pred_chronos2']) for r in paired)/len(paired),'paired_difference':sum(x['difference'] for x in d)/len(d),'targetmonth_CI':month_interval(d),'MO_cluster_CI':mo_interval(paired,column)}
    return result

def emit_statuses(out,rows,groups,excluded,fingerprint,obs,require_complete=False,collect_records=False):
    records=[];complete=True;counts=collections.Counter();tmp=out/'row-statuses.jsonl.tmp'
    with tmp.open('w') as f:
        for k in excluded:
            counts['INSUFFICIENT_HISTORY']+=1;f.write(json.dumps({'key':list(k),'status':'INSUFFICIENT_HISTORY'},ensure_ascii=False)+'\n')
        # One checkpoint state at a time: avoid 196k duplicate stateobjects beside models.
        for g,item in sorted(groups.items()):
            state=read_checkpoint(out,item,fingerprint);series=obs[(g[0],g[1])]
            for row in item['rows']:
                k=base.key(row);target=str(row['target']);entry={'key':list(k),'status':'PENDING'}
                if target in state['chronos'] and target in state['prophet']:
                    entry['status']='COMPLETE';seasonal=base.month(target)-12
                    if collect_records:
                        rec={'territory_id':g[0],'category':g[1],'origin':g[2],'horizon':int(row['horizon']),'target':target,'actual':float(row['actual']),'cutoff':base.ym(item['cutoff']),'forecast_step':base.month(target)-item['cutoff'],'nonmissing_context_points':sum(math.isfinite(x) for x in item['context']),'pred_chronos2':state['chronos'][target],'pred_prophet_lag2':state['prophet'][target],'prophet_cached':target in item['cached_prophet'],'pred_cutoff_anchor':series.get(item['cutoff']),'pred_observed_seasonal':series.get(seasonal) if seasonal<=item['cutoff'] else None}
                        if not all(math.isfinite(rec[c]) for c in ['actual','pred_chronos2','pred_prophet_lag2']):raise ValueError('finalnonfinite')
                        records.append(rec)
                else:complete=False
                counts[entry['status']]+=1;f.write(json.dumps(entry,ensure_ascii=False,allow_nan=False)+'\n')
    if sum(counts.values())!=len(rows):raise ValueError('everyrequestedkeymustaccount')
    tmp.replace(out/'row-statuses.jsonl');base.atomic(out/'coverage.json',{'requested':len(rows),'counts':dict(counts),'all_eligible_complete':complete,'scientific_pass':False})
    if require_complete and not complete:raise ValueError('fullcoverage required')
    return records,complete

def perform_controls(out,full,pipe,worker,obs,groups,states,counters):
    existing=out/'controls.json'
    if existing.exists():
        result=json.loads(existing.read_text())
        if not result.get('pass'):raise ValueError('existing failed controls')
        return result
    proofs=[]
    for h in full['horizons']:
        path=out/f'control-h{h}.json'
        if path.exists():
            previous=json.loads(path.read_text())
            if not previous.get('pass'):raise ValueError('interrupted/failedcontrols: reviewrequired, noautomaticrepeat')
            proofs.append(previous);continue
        base.atomic(path,{'status':'started','pass':False})
        selected=full['controls']['frozen_four_examples'][str(h)];k=selected['key'];g=(k[0],k[1],k[2]);item=groups[g];state=states[g];target=k[4]
        batch=next(b for b in fixed_batches(groups) if any(i['key']==g for i in b))
        mutated={m:v if m<=item['cutoff'] else v+1e6 for m,v in obs[(g[0],g[1])].items()};cutoff,values=base.causal_context(mutated,g[2],2)
        if cutoff!=item['cutoff'] or base.context_digest(values)!=base.context_digest(item['context']):raise ValueError('futurecontextdiff')
        counters['control_Chronos_calls']=counters.get('control_Chronos_calls',0)+2;base.atomic(out/'counters.json',counters)
        changed_batch=[]
        for neighbor in batch:
            ng=neighbor['key'];source=obs[(ng[0],ng[1])];changed={m:v if m<=neighbor['cutoff'] else v+1e6 for m,v in source.items()};_,nv=base.causal_context(changed,ng[2],2)
            if base.context_digest(nv)!=base.context_digest(neighbor['context']):raise ValueError('neighborfuturecontextdiff')
            changed_batch.append({**neighbor,'context':nv})
        a=batch_predict(pipe,batch)[group_id(g)][target];b=batch_predict(pipe,changed_batch)[group_id(g)][target]
        if not a==b==state['chronos'][target]:raise ValueError('Chronosrepeat/futurediff')
        counters['control_Prophet_fits']=counters.get('control_Prophet_fits',0)+2;base.atomic(out/'counters.json',counters)
        request=cache_request({**item,'cached_prophet':{}},obs);x=worker.fit(request)['predictions'][target]
        other=dict(obs);other[(g[0],g[1])]=mutated;y=worker.fit(cache_request({**item,'cached_prophet':{}},other))['predictions'][target]
        if not x==y==state['prophet'][target]:raise ValueError('Prophetrepeat/futurediff')
        proof={'horizon':h,'key':k,'forecast_step':int(h)+2,'context_sha256':base.context_digest(values),'same_native_batch_membership':len(batch),'same_max_predictionlength':max(base.month(r['target'])-item['cutoff'] for r in item['rows']),'pass':True};base.atomic(path,proof);proofs.append(proof)
    result={'pass':True,'Chronos_extra_calls':8,'Prophet_extra_fits':8,'proofs':proofs};base.atomic(existing,result);return result

def main():
    invocation_started=time.monotonic()
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['full-protocol','smoke-protocol','raw','paired','prophet-cache','prophet-source','weights-dir','uncertainty-addendum','out']:parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--mode',choices=['prepare','run'],default='prepare');parser.add_argument('--resume',action='store_true');parser.add_argument('--prophet-python',default=sys.executable);parser.add_argument('--operational-protocol',type=Path)
    args=parser.parse_args()
    if base.sha(args.uncertainty_addendum)!=UNCERTAINTY_SHA:raise ValueError('frozenMOuncertaintySHA')
    if base.sha(args.full_protocol)!=FULL_PROTOCOL_SHA or base.sha(args.smoke_protocol)!=SMOKE_PROTOCOL_SHA or base.sha(Path(base.__file__))!=BASE_RUNNER_SHA:raise ValueError('frozen protocol/helperSHA')
    full=json.loads(args.full_protocol.read_text());smoke=json.loads(args.smoke_protocol.read_text());smoke['input_paths']={'raw':str(args.raw),'paired':str(args.paired)}
    if base.sha(args.prophet_source)!=PROPHET_SOURCE_SHA or base.sha(args.prophet_cache/'predictions.parquet')!=CACHE_SHA:raise ValueError('Prophet source/cache SHA')
    if base.sha(args.prophet_cache/'manifest.json')!='5630c677fb893a25cfacca918cdca8d784f5533fec3e2c719e2987a9fdfe69cc' or base.sha(args.prophet_cache/'fingerprint.json')!='c2ac8d8248b6c0872a2aee8509755810419e39d7ecde0f688c8f282d7031f52b':raise ValueError('cachemanifest/fingerprintSHA')
    fp=json.loads((args.prophet_cache/'fingerprint.json').read_text());manifest=json.loads((args.prophet_cache/'manifest.json').read_text())
    if fp['raw_sha256']!=full['input_sha256']['raw'] or fp['seed']!=20260927 or fp['release_lag']!=2 or fp['min_train_points']!=6 or fp['code_sha256']!=PROPHET_SOURCE_SHA:raise ValueError('cache source/history/seed mismatch')
    expected={'growth':'linear','yearly_seasonality':False,'weekly_seasonality':False,'daily_seasonality':False,'n_changepoints':3,'uncertainty_samples':0}
    if any(manifest['model'].get(k)!=v for k,v in expected.items()):raise ValueError('cacheconfigmismatch')
    for name,expected_sha in [('config.json',full['model']['config_sha256']),('model.safetensors',full['model']['weight_sha256'])]:
        if base.sha(args.weights_dir/name)!=expected_sha:raise ValueError('pinnedweightsSHA')
    operational={'batch_size':16,'max_groups':1000,'uncertainty_addendum_sha256':UNCERTAINTY_SHA}
    if args.operational_protocol:
        operational.update(json.loads(args.operational_protocol.read_text()))
        if operational.get('full_protocol_sha256')!=FULL_PROTOCOL_SHA or operational['batch_size']!=16 or operational['max_groups']!=1000:raise ValueError('operationalfrozencaps')
    identity={'runner':base.sha(Path(__file__)),'worker':base.sha(Path(__file__).with_name('r11_prophet_worker.py')),'full':FULL_PROTOCOL_SHA,'smoke':SMOKE_PROTOCOL_SHA,'raw':full['input_sha256']['raw'],'paired':full['input_sha256']['paired'],'cache':CACHE_SHA,'source':PROPHET_SOURCE_SHA,'uncertainty_SHA':UNCERTAINTY_SHA,'operational_sha':base.sha(args.operational_protocol) if args.operational_protocol else None,'prophet_python':str(Path(args.prophet_python).absolute())}
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    if args.resume:
        if json.loads((args.out/'fingerprint.json').read_text())['fingerprint']!=fingerprint:raise ValueError('resumeidentitymismatch')
    else:
        if args.out.exists():raise ValueError('fresh outputrequired')
        args.out.mkdir(parents=True);base.atomic(args.out/'fingerprint.json',{'fingerprint':fingerprint,'identity':identity})
    obs,rows,contexts,_,_=base.load_inputs(smoke)
    import pandas as pd
    cacheframe=pd.read_parquet(args.prophet_cache/'predictions.parquet');cacheframe.territory_id=cacheframe.territory_id.astype(str);cache={base.key(r):r for r in cacheframe.to_dict('records')};del cacheframe
    if len(cache)!=171150:raise ValueError('cachecount/duplicate')
    groups,excluded,reused=build_groups(rows,contexts,cache);del cache,contexts
    eligible=[base.key(r) for i in groups.values() for r in i['rows']]
    if len(rows)!=294570 or len(eligible)!=282120 or digest_keys(eligible)!=full['primary_mask']['canonical_keys_sha256'] or reused!=109938 or len(groups)!=196566:raise ValueError('frozenmask/reuseguard')
    base.atomic(args.out/'preparation.json',{'status':'PREPARED_NO_MODEL_CALLS','primaryrows':len(eligible),'excluded':len(excluded),'reused_Prophet_rows':reused,'seriescutoffgroups':len(groups),'newProphetfits':sum(any(str(r['target']) not in i['cached_prophet'] for r in i['rows']) for i in groups.values()),'input_source_SHA':full['input_sha256'],'operational':operational,'scientific_pass':False})
    _,already_complete=emit_statuses(args.out,rows,groups,excluded,fingerprint,obs)
    if args.mode=='prepare':print('PREPARED_NO_MODEL_CALLS');return
    for name in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS']:os.environ[name]='1'
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    resource_preflight(args.out/('resource-probe-'+str(time.time_ns())))
    prior=json.loads((args.out/'counters.json').read_text()) if (args.out/'counters.json').exists() else {'chronos_calls':0,'prophet_fits':0};counters=prior;worker_ref=[None];finish=start_guard(args.out,full,counters,worker_ref,invocation_started);worker=None
    try:
        worker=Worker(args.prophet_python,args.prophet_source,args.out,worker_ref);base.atomic(args.out/'worker-metadata.json',worker.metadata)
        import torch,importlib.metadata
        from chronos import Chronos2Pipeline
        versions={n:importlib.metadata.version(n) for n in ['chronos-forecasting','torch','transformers','pandas','numpy','psutil']}
        if any(versions[k]!=v for k,v in {'chronos-forecasting':'2.3.2','torch':'2.14.0','transformers':'5.17.0','pandas':'2.3.3','numpy':'2.5.3'}.items()):raise ValueError('pinnedChronosdependencyversionsrequired')
        torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(20261007)
        pipe=Chronos2Pipeline.from_pretrained(str(args.weights_dir),device_map='cpu',torch_dtype=torch.float32,local_files_only=True);pipe.model.eval()
        if pipe.model.__class__.__name__!='Chronos2Model' or pipe.model.device.type!='cpu' or next(pipe.model.parameters()).dtype!=torch.float32:raise ValueError('actualmodeldevice/dtype')
        base.atomic(args.out/'model-metadata.json',{'actual_class':pipe.model.__class__.__name__,'actual_device':str(pipe.model.device),'actual_dtype':str(next(pipe.model.parameters()).dtype),'torch_threads':torch.get_num_threads(),'versions':versions,'model':full['model']})
        states={};pending=[]
        ordered=[i for g,i in sorted(groups.items())]
        for start in range(0,len(ordered),1000):
            macro=ordered[start:start+1000];candidate={i['key']:read_checkpoint(args.out,i,fingerprint) for i in macro}
            if any(st['status']!='complete' for st in candidate.values()):pending=macro;states=candidate;break
        buckets=collections.defaultdict(list)
        for item in pending:buckets[max(base.month(r['target'])-item['cutoff'] for r in item['rows'])].append(item)
        batches=[items[start:start+16] for _,items in sorted(buckets.items()) for start in range(0,len(items),16)]
        # Frozen lengthbucket membership includes alreadycomplete tasks on resume.
        for chunk in batches:
            if any(not states[i['key']]['chronos'] for i in chunk):
                items=chunk
                if counters['chronos_calls']>=full['prospective_resources']['model_call_cap_proposal']:raise ValueError('modelcallcap')
                for item in items:
                    if not states[item['key']]['chronos']:states[item['key']]['uncertain_inflight']='chronos';save_checkpoint(args.out,item,states[item['key']])
                counters['chronos_calls']+=1;base.atomic(args.out/'counters.json',counters);predictions=batch_predict(pipe,items)
                counters['successful_native_calls']=counters.get('successful_native_calls',0)+1;base.atomic(args.out/'counters.json',counters)
                for item in items:
                    state=states[item['key']]
                    if state['chronos'] and state['chronos']!=predictions[group_id(item['key'])]:raise ValueError('fixedbatch resumeequivalencediff')
                    state['chronos']=predictions[group_id(item['key'])];state.pop('uncertain_inflight',None);save_checkpoint(args.out,item,state)
            for item in chunk:
                state=states[item['key']]
                if state['status']=='complete':continue
                request=cache_request(item,obs)
                if any(t not in state['prophet'] for t in request['targets']):
                    if counters['prophet_fits']>=full['prospective_resources']['maximum_prophet_primary_fits']:raise ValueError('Prophetfitcap')
                    state['uncertain_inflight']='prophet';save_checkpoint(args.out,item,state);counters['prophet_fits']+=1;base.atomic(args.out/'counters.json',counters)
                    result=worker.fit(request);counters['successful_Prophet_fits']=counters.get('successful_Prophet_fits',0)+1;base.atomic(args.out/'counters.json',counters);state['prophet'].update(result['predictions']);state.pop('uncertain_inflight',None)
                state['status']='complete';save_checkpoint(args.out,item,state)
        _,complete=emit_statuses(args.out,rows,groups,excluded,fingerprint,obs)
        if complete:
            controls=perform_controls(args.out,full,pipe,worker,obs,groups,{g:read_checkpoint(args.out,i,fingerprint) for g,i in groups.items() if any(g==(x['key'][0],x['key'][1],x['key'][2]) for x in full['controls']['frozen_four_examples'].values())},counters)
            worker.close();worker=None;worker_ref[0]=None;del pipe
            import gc;gc.collect()
            records,_=emit_statuses(args.out,rows,groups,excluded,fingerprint,obs,require_complete=True,collect_records=True)
            frame=pd.DataFrame(records);frame.to_parquet(args.out/'predictions.parquet',index=False)
            base.atomic(args.out/'metrics.json',{'status':'EXECUTED_RETROSPECTIVE','equal_information':True,'by_horizon':metrics(records),'pooled_rowweighted':{'rows':len(records),'chronos2_MAE':sum(abs(r['actual']-r['pred_chronos2']) for r in records)/len(records),'prophet_lag2_MAE':sum(abs(r['actual']-r['pred_prophet_lag2']) for r in records)/len(records),'MO_cluster_CI':mo_interval(records,'pred_prophet_lag2')},'min12_sensitivity':metrics([r for r in records if r['nonmissing_context_points']>=12]),'MO_uncertainty_addendum_SHA':UNCERTAINTY_SHA,'controls':controls,'source_SHA':identity,'scientific_pass':False,'independent_holdout':False,'historical_asof_verified':False})
        base.atomic(args.out/'invocation-result.json',{'status':'FULL_TECHNICAL_EVALUATION_COMPLETED_REVIEW_REQUIRED' if complete else 'INCONCLUSIVE_PARTIAL_RESUMABLE','groups_this_invocation':len(pending),'counters':counters,'scientific_pass':False})
    except Exception as exc:
        base.atomic(args.out/'failure.json',{'status':'INCONCLUSIVE_FAILURE_NO_AUTOMATIC_RETRY','error':type(exc).__name__+': '+str(exc),'counters':counters,'scientific_pass':False});raise
    finally:
        if worker is not None:worker.close()
        finish()
if __name__=='__main__':main()
