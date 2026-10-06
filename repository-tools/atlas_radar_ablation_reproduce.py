"""Run the frozen supplemental ablation and check saved metric references."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'economic-atlas/runs/Atlas_Radar_ablation_20261006'


def main():
    p=argparse.ArgumentParser()
    for name in ['data-sense-dir','wages','employment','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();ds=a.data_sense_dir
    cmd=[sys.executable,str(ROOT/'economic-atlas/src/atlas_radar_ablation.py')]
    for name,path in [('panel',ROOT/'economic-atlas/data/panel_v1.parquet'),('dictionary',ds/'municipal_dictionary.parquet'),
                      ('population',ds/'2_bdmo_population.parquet'),('market',ds/'1_market_access.parquet'),
                      ('wages',a.wages),('employment',a.employment),('protocol',RUN/'protocol.json'),('out',a.out)]:
        cmd.extend(['--'+name,str(path)])
    subprocess.run(cmd,check=True)
    subprocess.run([sys.executable,str(ROOT/'economic-atlas/src/audit_atlas_radar_ablation.py'),'--run',str(a.out)],check=True)
    ref=pd.read_csv(RUN/'external_metrics.csv').sort_values(['endpoint','k','seed','arm']).reset_index(drop=True)
    actual=pd.read_csv(a.out/'external_metrics.csv').sort_values(['endpoint','k','seed','arm']).reset_index(drop=True)
    assert actual[['endpoint','k','seed','arm','n']].equals(ref[['endpoint','k','seed','arm','n']])
    np.testing.assert_allclose(actual[['mse','mae']],ref[['mse','mae']],rtol=1e-8,atol=1e-12)
    expected=json.loads((RUN/'results.json').read_text());observed=json.loads((a.out/'results.json').read_text())
    assert (observed['n_external_common'],observed['sample_audit']['regions'])==(1248,70)
    for x,y in zip(observed['q4_compactness'],expected['q4_compactness']):
        assert (x['k'],x['seed'],x['arm'])==(y['k'],y['seed'],y['arm'])
        np.testing.assert_allclose([x['q4_silhouette_common_space'],x['q4_within_total_dispersion']],
                                   [y['q4_silhouette_common_space'],y['q4_within_total_dispersion']],rtol=1e-8,atol=1e-12)
    print('ABLATION_REFERENCE_PASS: 96 metric rows; common masks; 36 Q4 partitions. ScientificPASS remains false.')


if __name__=='__main__':main()
