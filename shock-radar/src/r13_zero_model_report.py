"""One-use status-only report. Stdlib only: never loads forecast code or commits stages."""
import time
ENTRY = time.monotonic()
import argparse, collections, hashlib, json, math, os, pathlib, resource, shutil, signal
P = pathlib.Path
ORIGINAL_PROTOCOL = '9409ccf7e7ef608bb490eccd45aab22e1dc3dc731c883a2c38431084fbedea01'
FINGERPRINT = '4a91d68779da35469f3ed66472d631c35f90a19f502d84cb53e8c2d30e7220c9'
PREPARED_SHA = '14341a08856c3e1fa0ac1e50783d8fb283a3223e74dd87de7c3c104513bbdf97'
HISTORICAL = 3893.441428624006
ACTUAL_OUT = '/private/tmp/radar-r13-full-actual-20261008-v1'
ORIGINAL_LEASE_SHA = '23b2f154606d5d7bb7f8bcc67a8446095e8200eaec90fc773e893394852a960f'
REQUIRED_CLOSED_FILES = {'fingerprint.json','supervision.json','resource-ledger.json','counters.json','row-statuses.jsonl','completion.json','terminal-accounting-deferred.json','sessions/session-001.json','metadata-reports/report-001.json','active-attempt.json'}
UNKNOWN = ('1018', 'Здоровье', '2024-01', '6', '2024-07')
REQUESTED, ELIGIBLE, EXCLUDED, CHECKPOINTS, ATTEMPTS = 294570, 282120, 12450, 44184, 33319
def digest(data): return hashlib.sha256(data).hexdigest()
def read(path): return json.loads(P(path).read_bytes())
def sha(path): return digest(P(path).read_bytes())
def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value): raise ValueError('finite nonbool wall required')
    return value
def atomic(path, value):
    tmp = P(str(path)+'.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)
def reserve(path, value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump(value,f,allow_nan=False);f.flush();os.fsync(f.fileno())
def group_id(key): return digest(json.dumps(list(key), ensure_ascii=False, separators=(',', ':')).encode())
def select_status(row, state, unresolved):
    key = tuple(row['key'])
    if row.get('status') == 'INSUFFICIENT_HISTORY': return row
    status = dict(row['model_status']); date = key[4]
    for model in ('chronos', 'prophet'):
        if state:
            if date in state[model]: status[model] = 'SUCCESS'
            elif date in state['terminal'][model]: status[model] = state['terminal'][model][date]
        if status[model] == 'PENDING':
            status[model] = unresolved.get((key[:3], model, date), 'RESOURCE_NOT_ATTEMPTED:DISK_STOP')
    if key == UNKNOWN and status['prophet'] != 'ANCESTRAL_UNKNOWN_RESOURCE_STOP_NEVER_REFIT':
        raise ValueError('ancestral unknown never refit')
    return dict(row, model_status=status)
def guard(out, started, deadline, written=0):
    if time.monotonic()-started >= 600 or time.time() >= deadline: raise RuntimeError('report wall/deadline exhausted')
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname != 'Darwin': rss *= 1024
    if rss > 2147483648: raise RuntimeError('report RSS cap')
    if shutil.disk_usage(out).free < 1073741824: raise RuntimeError('report minimum free disk')
    if written > 134217728: raise RuntimeError('report phase output reserve128MiB')
def conservation(header, ledger, out):
    if header['status'] != 'STOP_REQUIRES_ZERO_MODEL_RECOVERY_REVIEW' or header.get('owned_child_reaped_and_tree_empty') is not True: raise ValueError('clean STOP required')
    if finite(header['cumulative_wall_s']) != HISTORICAL or finite(ledger['cumulative_wall_s']) != HISTORICAL or header['counters'] != ledger['counters']: raise ValueError('no reset of closed cumulative history')
    wall = 961.611384207994
    for event in header['ledger_events']:
        path = P(event['path'])
        if path.is_absolute() or '..' in path.parts or sha(out/path) != event['SHA']: raise ValueError('closed ledger receipt SHA')
        record = read(out/path)
        if finite(record['previous_cumulative_wall_s']) != wall or finite(record['cumulative_wall_s']) < wall: raise ValueError('conserved wall chain')
        wall = record['cumulative_wall_s']
    if wall != HISTORICAL: raise ValueError('closed wall chain ending')
def report(out, binding, started, deadline, phase):
    header = read(out/'supervision.json'); conservation(header, read(out/'resource-ledger.json'), out)
    states = {}; cp = header['checkpoint_sha256']; seen = set()
    for i, file in enumerate((out/'checkpoints').iterdir()):
        rel = str(file.relative_to(out)); raw = file.read_bytes()
        if rel not in cp or digest(raw) != cp[rel]: raise ValueError('checkpoint snapshot mismatch')
        s = json.loads(raw); key = tuple(s['group_key'])
        if s['fingerprint'] != FINGERPRINT or key in states: raise ValueError('checkpoint identity')
        states[key] = s; seen.add(rel)
        if i % 1024 == 0: guard(out, started, deadline)
    if seen != set(cp) or len(cp) != CHECKPOINTS: raise ValueError('exact closed checkpoint universe')
    journal = hashlib.sha256(); unresolved = {}; count = collections.Counter(); attempts = 0
    for folder in sorted((out/'attempts').iterdir()):
        blobs = {}
        for name in ('request.json','response.json','status.json','native-manifest.json'):
            file = folder/name
            if file.exists():
                raw = file.read_bytes(); blobs[name] = raw
                journal.update((str(file.relative_to(out))+' '+digest(raw)+'\n').encode())
        q = json.loads(blobs['request.json']); status = json.loads(blobs['status.json']); reply = json.loads(blobs['response.json']) if 'response.json' in blobs else None
        if q['fingerprint'] != FINGERPRINT or q['purpose'] != 'primary' or q['model'] not in ('chronos','prophet') or status['status'] not in ('COMMITTED','STARTED'): raise ValueError('journal identity')
        if status['request_SHA'] != digest(blobs['request.json']): raise ValueError('request SHA link')
        if reply is not None and (reply['request_SHA'] != digest(blobs['request.json']) or reply['fingerprint'] != FINGERPRINT or reply['model'] != q['model']): raise ValueError('response identity')
        if status['status'] == 'COMMITTED' and (reply is None or status['response_SHA'] != digest(blobs['response.json'])): raise ValueError('committed response SHA')
        if q['model'] == 'prophet' and list(UNKNOWN[:3]) in q['group_keys']: raise ValueError('ancestral unknown refitted')
        count[q['model']+'_attempts'] += 1; count[q['model']+'_success'] += reply is not None and reply.get('ok') is True
        if status['status'] != 'COMMITTED':
            value = 'UNKNOWN_STOP_REQUIRES_REVIEWED_RECOVERY_NEVER_RETRY'
            if reply is not None: value = 'DURABLE_RESPONSE_REQUIRES_REVIEWED_COMMIT' if reply['ok'] else 'FAILED_REPORTED_RESPONSE_REQUIRES_REVIEWED_COMMIT:'+str(reply['error'])
            for key in q['group_keys']:
                for date in q['target_dates'][group_id(key)]: unresolved[(tuple(key),q['model'],date)] = value
        attempts += 1
        if attempts % 1024 == 0: guard(out, started, deadline)
    if attempts != ATTEMPTS or journal.hexdigest() != header['journal_digest']: raise ValueError('exact closed journal universe/digest')
    expected = {'chronos_calls':104+count['chronos_attempts'],'prophet_fits':1006+count['prophet_attempts'],'successful_native_calls':104+count['chronos_success'],'successful_Prophet_fits':1005+count['prophet_success']}
    if expected != header['counters']: raise ValueError('conserved attempt counters')
    rows = out/'row-statuses.jsonl'; keys = set(); counts = collections.Counter(); h = hashlib.sha256(); written = 0; excluded = 0; eligible = 0
    target = phase/'row-statuses.jsonl'; tmp = phase/'row-statuses.jsonl.tmp'
    with rows.open('rb') as source, tmp.open('wb') as sink:
        for i, raw in enumerate(source):
            h.update(raw); row = json.loads(raw); key = tuple(row['key'])
            if len(key) != 5 or key in keys: raise ValueError('duplicate/malformed requested key')
            keys.add(key)
            if row.get('status') == 'INSUFFICIENT_HISTORY': excluded += 1
            else: eligible += 1
            result = select_status(row, states.get(key[:3]), unresolved)
            for model,status in result.get('model_status',{}).items(): counts[model+':'+status] += 1
            data = (json.dumps(result,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n').encode();sink.write(data);written += len(data)
            if i % 1024 == 0: guard(out, started, deadline, written)
        sink.flush(); os.fsync(sink.fileno())
    if h.hexdigest() != PREPARED_SHA or len(keys) != REQUESTED or eligible != ELIGIBLE or excluded != EXCLUDED or UNKNOWN not in keys: raise ValueError('immutable full prepared registry contract')
    guard(out, started, deadline, written);os.replace(tmp,target)
    for name,expected_sha in binding['closed_file_SHA'].items():
        if sha(out/name) != expected_sha: raise ValueError('closed old file changed during report')
    return {'state':'FULL_REQUESTED_STATUS_ONLY_REPORT','requested':len(keys),'eligible':eligible,'excluded':excluded,'registry_SHA':sha(target),'prepared_original_SHA':h.hexdigest(),'model_status_counts':dict(counts),'counters':expected,'journal_SHA':journal.hexdigest(),'original_V3':'INCONCLUSIVE','full_population_paired_risk':'UNAVAILABLE','MAE_computed':False,'scientific_pass':False,'model_calls':0,'old_files_modified':False}
def main():
    started = ENTRY
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'): os.environ[name] = '1'
    ap=argparse.ArgumentParser();ap.add_argument('--binding',type=P,required=True);ap.add_argument('--binding-sha',required=True);args=ap.parse_args()
    if sha(args.binding) != args.binding_sha: raise ValueError('root report binding SHA')
    b=read(args.binding);out=P(b['out']).resolve()
    if str(out) != ACTUAL_OUT or set(b['closed_file_SHA']) != REQUIRED_CLOSED_FILES: raise ValueError('same exact actual closed namespace/file universe')
    phase=out/'zero-model-report-v1'
    if phase.exists(): raise ValueError('preexisting sidecar not owned; reject before report lease')
    phase_owned=False
    if b['original_protocol_SHA'] != ORIGINAL_PROTOCOL or b['fingerprint'] != FINGERPRINT or b['source_SHA'] != sha(__file__) or b['historical_seconds'] != HISTORICAL or b.get('root_authoritative_parent_and_owned_tree_gone') is not True: raise ValueError('exact root report-only authority')
    fp=read(out/'fingerprint.json')
    if fp['fingerprint'] != FINGERPRINT or fp['protocol_SHA'] != ORIGINAL_PROTOCOL: raise ValueError('same original namespace')
    original_lease=P('/private/tmp/sberindex-one-use-ledger')/(str(os.getuid())+'-R13-'+ORIGINAL_PROTOCOL+'.json')
    if sha(original_lease) != ORIGINAL_LEASE_SHA: raise ValueError('original model one-use reservation unchanged')
    deadline = 1791536400.0
    guard(out,started,deadline)
    if HISTORICAL+600 > 108000: raise ValueError('inclusive total no reset')
    root=P('/private/tmp/sberindex-one-use-ledger');root.mkdir(mode=0o700,exist_ok=True);s=root.lstat()
    if root.is_symlink() or s.st_uid != os.getuid() or s.st_mode & 0o077: raise ValueError('private canonical UID ledger')
    lease=root/(str(os.getuid())+'-R13-ZERO_MODEL_REPORT-'+ORIGINAL_PROTOCOL+'.json')
    reserve(lease,{'state':'STARTED','out':str(out),'binding_SHA':args.binding_sha,'historical_seconds':HISTORICAL,'models':0})
    result={'state':'INCONCLUSIVE_REPORT_STOP_NO_RETRY','models':0,'scientific_pass':False}
    def timeout(*unused): raise RuntimeError('bounded report600s')
    old=signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,max(.001,570-(time.monotonic()-started)))
    try:
        for name,digest_value in b['closed_file_SHA'].items():
            path=P(name)
            if path.is_absolute() or '..' in path.parts or sha(out/path) != digest_value: raise ValueError('closed actual file SHA')
            guard(out,started,deadline)
        baseline=0
        for i,file in enumerate(out.rglob('*')):
            if file.is_symlink(): raise ValueError('report source symlink refused')
            if file.is_file(): baseline += file.stat().st_size
            if i % 1024 == 0: guard(out,started,deadline)
        if baseline+134217728 > 3221225472: raise ValueError('reserve128MiB within original3GiB output cap')
        phase.mkdir(mode=0o700,exist_ok=False);phase_owned=True
        result=report(out,b,started,deadline,phase)
    except BaseException as exc: result.update(error=type(exc).__name__+': '+str(exc))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,old)
        if time.monotonic()-started >= 600 or time.time() >= deadline: result.update(state='INCONCLUSIVE_REPORT_FINALIZATION_BUDGET',scientific_pass=False)
        result.update(original_cumulative_wall_s=HISTORICAL,report_elapsed_seconds=time.monotonic()-started,cumulative_wall_s=HISTORICAL+time.monotonic()-started,continuous_resource_pass=False,last_receipt_fsync_independently_timed=False)
        atomic(lease.with_name(lease.stem+'-terminal.json'),result)
        if phase_owned: atomic(phase/'terminal.json',result)
    return 0 if result['state']=='FULL_REQUESTED_STATUS_ONLY_REPORT' else 1
if __name__=='__main__': raise SystemExit(main())
