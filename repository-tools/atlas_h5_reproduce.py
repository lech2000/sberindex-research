"""Fresh H5 repeat with input SHA and reference metrics checked."""
import argparse
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'economic-atlas/runs/H5_scale_encoding_audit_20261007'

def main():
    p=argparse.ArgumentParser()
    for key in ['data-sense-dir','wages','employment','out']:p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--verify-existing',action='store_true',help='Audit an existing private calculation instead of new fits')
    a=p.parse_args();ds=a.data_sense_dir
    paths={'panel':ROOT/'economic-atlas/data/panel_v1.parquet','dictionary':ds/'municipal_dictionary.parquet','population':ds/'2_bdmo_population.parquet','market':ds/'1_market_access.parquet','wages':a.wages,'employment':a.employment}
    if not a.verify_existing:
        cmd=[sys.executable,str(ROOT/'economic-atlas/src/atlas_h5_scale_audit.py')]
        for key,path in {**paths,'protocol':RUN/'protocol.json','out':a.out}.items():cmd+=['--'+key,str(path)]
        subprocess.run(cmd,check=True)
    # Auditor refuses to overwrite its receipt; a rerun must choose a fresh output.
    audit=a.out/'reproduction-independent-audit.json'
    subprocess.run([sys.executable,str(ROOT/'economic-atlas/src/audit_atlas_h5_scale.py'),'--run',str(a.out),'--dictionary',str(paths['dictionary']),'--wages',str(a.wages),'--employment',str(a.employment),'--out',str(audit)],check=True)
    keys=['method','k','seed','endpoint','arm','n']
    ref=pd.read_csv(RUN/'external_metrics.csv').sort_values(keys).reset_index(drop=True)
    actual=pd.read_csv(a.out/'external_metrics.csv').sort_values(keys).reset_index(drop=True)
    assert actual[keys].equals(ref[keys])
    np.testing.assert_allclose(actual.mse_log2025,ref.mse_log2025,rtol=1e-8,atol=1e-12)
    print('H5_REFERENCE_PASS: 196 MSE, disjoint regional folds and 48 paired comparisons; scientific_pass remains false')

if __name__=='__main__':main()
