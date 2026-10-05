#!/usr/bin/env python3
"""Recompute frozen Radar baselines and bank; verify references and causality.

Offline. Original runs are read-only references. This reuses the audited Prophet
forecast cache, does not fit Prophet again, and never grants a scientific PASS.
"""
from pathlib import Path
import argparse, hashlib, json, math, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
import importlib.metadata
import uuid

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    'raw': ('8_consumption.parquet', '9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'),
    'r9': ('predictions-r9.parquet', 'b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44'),
    'pilot': ('predictions-pilot.parquet', 'eb350fffcd1b72ca70d05477f0b20968ecaf6636cd4ee734e668ab3b48053aa2'),
    'dictionary': ('municipal-dictionary.parquet', 'f25088539a896cdc834d77c8792d0e6ac909d8649b06d65f69215ce12a8eaf4a'),
    'national': ('national-consumer-spending.parquet','940efac0b7b0411ad4317d5126bd4006cf5a78a65861f2daeebc39bd7b59c030'),
}
CODES = {
    'd01_joint_bank.py': '5055b5a568cc8425c27182a488432f032cfb10616908dbd7c9b2163382cc6785',
    'radar_external_checks.py': '503d372b55bfad8e9166ca8f553150016f33f557bd532f0dc3a2117668aa9889',
    'detector_bank.py': 'c1c3478ba3f5eb2cf37658a67cb36a2c3db4890e41fc138c932116c17a2b2c4b',
    'r9_strong_baselines.py': '1cf8829c4cb40c1a49a7986de98060385345c20818e229e6e9e55f9c8a58bdf2',
    'multicategory_shocks.py': '99f6e8ce0f32ba5217668e90f47fd23fcb43e6f92cc5a2e340663aefd4779650',
    'competitive_audit.py': '8ad28f14287b0d270236786b07575f3626abdfdf3a46d030667c5eebbde485d6',
}
VERSIONS = {'numpy':'2.5.3','pandas':'3.0.6','scipy':'1.18.1','pyarrow':'25.0.1','scikit-learn':'1.9.1'}
BREF = ROOT/'shock-radar/runs/R9_strong_baselines_20261004'
DREF = ROOT/'shock-radar/runs/D04_multicategory_20261004'
NREF = ROOT/'shock-radar/runs/R10_national_h12_20261005'
FREF = ROOT/'shock-radar/runs/Flood_legal_cohort_20261005'
JREF = ROOT/'shock-radar/runs/D05_joint_bank_20261005'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def compare(expected,actual,where='metrics'):
    if isinstance(expected,dict):
        if not isinstance(actual,dict) or set(expected)!=set(actual):raise AssertionError(f'{where}: keys differ')
        for k,v in expected.items():compare(v,actual[k],f'{where}.{k}')
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(expected)!=len(actual):raise AssertionError(f'{where}: length differs')
        for i,(v,w) in enumerate(zip(expected,actual)):compare(v,w,f'{where}[{i}]')
    elif isinstance(expected,float):
        if not isinstance(actual,(float,int)) or not math.isclose(expected,actual,rel_tol=1e-10,abs_tol=1e-8):
            raise AssertionError(f'{where}: {actual} != {expected}')
    elif expected!=actual:raise AssertionError(f'{where}: {actual} != {expected}')


def frozen_reference_manifest(directory):
    manifest=json.loads((directory/'manifest.json').read_text())
    for name,digest in manifest.items():
        p=directory/name
        if not p.is_file() or sha(p)!=digest:raise ValueError(f'Frozen reference modified: {p}')
    return manifest


def run(module,args,out):
    command=[sys.executable,str(ROOT/'shock-radar/src'/module)]+[str(a) for a in args]
    print(json.dumps({'stage':module,'started':True}),flush=True)
    log_name=module+(('-'+str(args[1])) if '--mode' in args else '')+'.log'
    with (out/log_name).open('w') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    print(json.dumps({'stage':module,'completed':True}),flush=True)


def self_check():
    compare({'n':3,'metric':[1.0,None]}, {'n':3,'metric':[1.0+1e-12,None]})
    for bad in ({'n':4,'metric':[1.0,None]}, {'n':3,'metric':[1.1,None]}, {'n':3}):
        try:compare({'n':3,'metric':[1.0,None]},bad)
        except AssertionError:pass
        else:raise AssertionError('Regression accepted')
    with tempfile.TemporaryDirectory() as t:
        p=Path(t);(p/'reference.json').write_text('{"mae":1}')
        write(p/'manifest.json',{'reference.json':sha(p/'reference.json')})
        frozen_reference_manifest(p)
        (p/'reference.json').write_text('{"mae":0}')
        try:frozen_reference_manifest(p)
        except ValueError:pass
        else:raise AssertionError('Changed reference accepted')
    print(json.dumps({'passed':True,'checks':['metric regression rejected','changed frozen reference rejected']}))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in INPUTS:p.add_argument('--'+name,type=Path)
    p.add_argument('--output-root',type=Path,default=Path('output/radar'))
    p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check:self_check();return
    # Fail before creating a result directory if environment/input/reference differ.
    observed={name:importlib.metadata.version(name) for name in VERSIONS}
    if observed!=VERSIONS:raise ValueError(f'Frozen environment required {VERSIONS}; found {observed}. See repository-tools/requirements-science.txt')
    for name,(_,expected) in INPUTS.items():
        path=getattr(a,name)
        if path is None or not path.is_file():raise FileNotFoundError(f'Missing --{name}; see repository-tools/RADAR_REPRODUCE.md')
        if sha(path)!=expected:raise ValueError(f'Frozen {name} SHA mismatch: {path}')
    for name,digest in CODES.items():
        if sha(ROOT/'shock-radar/src'/name)!=digest:raise ValueError(f'Scientific source changed: {name}; new protocol required')
    references={'baseline':frozen_reference_manifest(BREF),'bank':frozen_reference_manifest(DREF),'national':frozen_reference_manifest(NREF),'flood':frozen_reference_manifest(FREF),'joint':frozen_reference_manifest(JREF)}
    output_root=a.output_root.resolve()
    for forbidden in (ROOT/'shock-radar/runs',ROOT/'economic-atlas/runs',ROOT/'data'):
        if output_root==forbidden or forbidden in output_root.parents:raise ValueError('Output must be outside frozen inputs/runs')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    out=output_root/stamp;out.mkdir(parents=True,exist_ok=False)
    frozen=out/'inputs';frozen.mkdir();snap={}
    for name,(filename,digest) in INPUTS.items():
        destination=frozen/filename;shutil.copyfile(getattr(a,name),destination)
        if sha(destination)!=digest:raise ValueError('Source changed while snapshotting')
        destination.chmod(0o444);snap[name]=destination
    receipt={'recorded_at':datetime.now(timezone.utc).isoformat(),'kind':'offline_frozen_reproduction','versions':observed,
             'inputs':{k:{'file':'inputs/'+v[0],'sha256':v[1]} for k,v in INPUTS.items()},'scientific_code_sha256':CODES,
             'driver_sha256':sha(Path(__file__)), 'bank_entry_sha256':sha(ROOT/'shock-radar/src/detector_bank.py'), 'reference_manifests':references,'prophet_cache_reused':True,'prophet_refit':False,
             'independent_holdout':False,'historical_asof_verified':False,'scientific_pass':False}
    write(out/'snapshot.json',receipt)
    print(json.dumps({'run_directory':str(out),'snapshots_verified':True}),flush=True)
    try:
        run('r9_strong_baselines.py',['--raw',snap['raw'],'--r9',snap['r9'],'--pilot',snap['pilot'],'--out',out/'baseline'],out)
        run('detector_bank.py',['--raw',snap['raw'],'--dictionary',snap['dictionary'],'--out',out/'bank'],out)
        run('competitive_audit.py',['--raw',snap['raw'],'--r9',snap['r9'],'--baseline',out/'baseline','--detector',out/'bank','--out',out/'audit'],out)
        run('radar_external_checks.py',['--mode','national','--raw',snap['raw'],'--r9',snap['r9'],'--national',snap['national'],'--protocol',NREF/'protocol.json','--out',out/'national'],out)
        run('radar_external_checks.py',['--mode','flood','--raw',snap['raw'],'--dictionary',snap['dictionary'],'--protocol',FREF/'protocol.json','--out',out/'flood'],out)
        run('d01_joint_bank.py',['--raw',snap['raw'],'--protocol',JREF/'protocol.json','--out',out/'joint'],out)
        for source,folder in [(NREF,'national'),(FREF,'flood'),(JREF,'joint')]:
            compare(json.loads((source/'metrics.json').read_text()),json.loads((out/folder/'metrics.json').read_text()),folder)
        ref=json.loads((BREF/'metrics.json').read_text());new=json.loads((out/'baseline/metrics.json').read_text())
        for key in ['rows','results','status','scientific_pass']:compare(ref[key],new[key],f'baseline.{key}')
        import pandas as pd
        tables=[('bank','synthetic-by-seed.csv'),('bank','synthetic-summary.csv'),('bank','real-cases.csv'),('bank','real-alert-volume.csv'),
                ('audit','matched-null-summary.csv'),('audit','matched-null-by-seed.csv'),('audit','real-fixed-budget-cases.csv')]
        for folder,name in tables:
            x=pd.read_csv(DREF/name);y=pd.read_csv(out/folder/name)
            pd.testing.assert_frame_equal(x,y,check_dtype=False,check_exact=False,rtol=1e-10,atol=1e-8)
        checks=json.loads((out/'audit/audit.json').read_text())['checks']
        compare(json.loads((BREF/'independent-audit.json').read_text())['checks'],checks,'independent_checks')
        for name,(_,digest) in INPUTS.items():
            if sha(snap[name])!=digest:raise ValueError('Frozen snapshot mutated by computation')
        write(out/'result.json',{'technical_reproduction_pass':True,'reference_metrics_match':True,'reference_tables_match':len(tables),
                'checks':checks,'scientific_pass':False,'h12':'new national benchmark reproduced; old category-seasonal unsupported',
                'national_forecast_future_checks':220824,'flood':'1 exact legal identity, 6 blocked; reproduced partial result','D01_bank_extension':'D01-MV-v2: Stouffer/GLR and four controls on shared D04 multivariate signal; legacy univariate bank unchanged',
                'equal_null_fa':'pooled TEST null 3%; retrospective ROC, not independently calibrated FA',
                'real_false_alarms':None,'prophet_refit':False,'joint_bank_total_null_fa':0.03,'joint_bank_universal_improvement':False})
    except Exception as error:
        write(out/'result.json',{'technical_reproduction_pass':False,'scientific_pass':False,'error':str(error)})
        raise
    write(out/'artifact-manifest.json',{str(q.relative_to(out)):sha(q) for q in sorted(out.rglob('*')) if q.is_file() and q.name!='artifact-manifest.json'})
    print(json.dumps({'technical_reproduction_pass':True,'run_directory':str(out),'scientific_pass':False}),flush=True)

if __name__=='__main__':main()
