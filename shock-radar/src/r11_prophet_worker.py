"""Persistent private NDJSON Prophet worker. Imports model only for real fit requests."""
import contextlib,datetime,hashlib,importlib.metadata,json,math,os,platform,resource,sys
from pathlib import Path

def fit(request, function):
    cutoff=request['cutoff'];train=request['train'];targets=request['targets']
    if len(train)<6 or len({x[0] for x in train})!=len(train):raise ValueError('history/duplicate guard')
    if any(d>cutoff or not math.isfinite(float(y)) for d,y in train):raise ValueError('future/nonfinite train')
    if any(d<=cutoff for d in targets):raise ValueError('target must follow cutoff')
    pairs=[(datetime.datetime.fromisoformat(d+'-01'),float(y)) for d,y in train]
    dates=[datetime.datetime.fromisoformat(d+'-01') for d in targets]
    values=function(pairs,dates,seed=request['seed'])
    if len(values)!=len(targets) or not all(math.isfinite(float(x)) for x in values):raise ValueError('invalid forecasts')
    return {d:float(v) for d,v in zip(targets,values)}

def main():
    import importlib.util
    source=Path(sys.argv[1]);expected='b9e7e993cf90e2e290001c7067fda36ed9684a900dee0ffa9d656e424ef97bf1'
    if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:raise ValueError('Prophet source SHA mismatch')
    versions={n:importlib.metadata.version(n) for n in ['prophet','cmdstanpy','pandas','numpy']}
    if versions!={'prophet':'1.4.0','cmdstanpy':'1.3.0','pandas':'3.0.6','numpy':'2.5.3'}:raise ValueError('pinned estimator dependency versions required')
    spec=importlib.util.spec_from_file_location('frozen_prophet',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    print(json.dumps({'ready':True,'versions':versions,'source_sha256':expected}),flush=True)
    for line in sys.stdin:
        req=json.loads(line)
        if req.get('op')=='stop':return
        try:
            if req['seed']!=20260927:raise ValueError('seed guard')
            with contextlib.redirect_stdout(sys.stderr):predictions=fit(req,module.prophet_fit_predict)
            peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;childpeak=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
            result={'ok':True,'predictions':predictions,'peak_rss_bytes':peak if platform.system()=='Darwin' else peak*1024,'child_peak_rss_bytes':childpeak if platform.system()=='Darwin' else childpeak*1024,'fits':1}
        except Exception as exc:result={'ok':False,'error':type(exc).__name__+': '+str(exc)}
        print(json.dumps(result,allow_nan=False),flush=True)
if __name__=='__main__':main()
