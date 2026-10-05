"""Reproduce the archived exploratory Atlas/Radar calculation and numeric audit."""
from pathlib import Path
import argparse,json,os,subprocess,sys,hashlib
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-sense-dir',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=Path(__file__).resolve().parents[1]
    archive=r/'economic-atlas/runs/Atlas_Radar_joint_20261005'
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
    subprocess.run([sys.executable,str(r/'economic-atlas/src/atlas_radar_joint.py'),'--repo',str(r),
        '--population',str(a.data_sense_dir/'2_bdmo_population.parquet'),'--dictionary',str(a.data_sense_dir/'municipal_dictionary.parquet'),
        '--protocol',str(archive/'protocol.json'),'--out',str(a.out)],check=True,env=env)
    subprocess.run([sys.executable,str(r/'economic-atlas/src/atlas_radar_joint_audit.py'),'--repo',str(r),
        '--data-sense-dir',str(a.data_sense_dir),'--run',str(a.out)],check=True,env=env)
    key=['municipality','category','model']
    def indexed(path):
        return {tuple(x[k] for k in key):x for x in json.loads(path.read_text())}
    expected=indexed(archive/'case-summary.json');actual=indexed(a.out/'case-summary.json')
    if expected.keys()!=actual.keys():raise ValueError('Summary mask changed')
    for k,x in expected.items():
        y=actual[k]
        for f in ['April_residual_percent','quarter_residual_percent','comparison_April_median_percent','anchor_minus_comparison_April_pp']:
            np.testing.assert_allclose(x[f],y[f],rtol=1e-10,atol=1e-8)
        for f in ['comparison_count','recovery_status','reentry_month','reentry_confirmed_month']:
            if x[f]!=y[f]:raise ValueError('Archived status changed: '+f)
    receipt={'technical_status':'PASS','archived_case_rows_verified':len(expected),'scientific_pass':False,
        'causal_effect_supported':False,'A8_full_statistics_recomputed':False}
    (a.out/'reproduction-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    manifest=json.loads((a.out/'manifest.json').read_text())
    manifest['files']={str(p.relative_to(a.out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(a.out.rglob('*')) if p.is_file() and p.name!='manifest.json'}
    (a.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt))

if __name__=='__main__':main()
