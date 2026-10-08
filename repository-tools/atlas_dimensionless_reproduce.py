"""Fresh fixed dimensionless diagnostic, independent audit and frozen-number check."""
from pathlib import Path
import argparse,subprocess,sys,json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'economic-atlas/runs/H5_dimensionless_scale_20261007'
def main():
    p=argparse.ArgumentParser()
    for key in ['data-sense-dir','wages','employment','reference','out']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();assert not a.out.exists();a.out.mkdir(parents=True)
    inputs={'panel':ROOT/'economic-atlas/data/panel_v1.parquet','dictionary':a.data_sense_dir/'municipal_dictionary.parquet','population':a.data_sense_dir/'2_bdmo_population.parquet','market':a.data_sense_dir/'1_market_access.parquet','wages':a.wages,'employment':a.employment,'protocol':RUN/'protocol.json','reference':a.reference}
    cmd=[sys.executable,str(ROOT/'economic-atlas/src/dimensionless_scale_audit.py')]
    for k,v in {**inputs,'out':a.out/'calculation'}.items():cmd+=['--'+k,str(v)]
    subprocess.run(cmd,check=True)
    cmd=[sys.executable,str(ROOT/'economic-atlas/src/audit_dimensionless_scale.py')]
    for k,v in {'run':a.out/'calculation','reference':a.reference,'panel':inputs['panel'],'dictionary':inputs['dictionary'],'protocol':inputs['protocol'],'out':a.out/'independent-audit.json'}.items():cmd+=['--'+k,str(v)]
    subprocess.run(cmd,check=True)
    ref=json.loads((RUN/'metrics.json').read_text());new=json.loads((a.out/'calculation/metrics.json').read_text())
    sort=lambda rows:sorted(rows,key=lambda q:(q['method'],q['k'],q['seed'],q['endpoint']))
    ref,new=sort(ref),sort(new);assert [{k:v for k,v in row.items() if k!='mse'} for row in ref]==[{k:v for k,v in row.items() if k!='mse'} for row in new]
    np.testing.assert_allclose([v['mse'] for v in ref],[v['mse'] for v in new],rtol=1e-10,atol=1e-12)
    x=json.loads((a.out/'calculation/results.json').read_text());assert x['all_full_unit_ARI1'] and x['external_oof_rows']==34944
    print('DIMENSIONLESS_REFERENCE_PASS:28MSE/34944OOF/14unit-invariant partitions; scientific_pass=false')
if __name__=='__main__':main()
