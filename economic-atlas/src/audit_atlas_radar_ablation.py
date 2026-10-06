"""Independent recomputation from saved OOF rows, without importing the runner."""
import argparse, json, hashlib
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

p=argparse.ArgumentParser();p.add_argument('--run',required=True);a=p.parse_args();r=Path(a.run)
start=json.loads((r/'execution-start.json').read_text());results=json.loads((r/'results.json').read_text())
pred=pd.read_parquet(r/'oof_predictions.parquet'); metrics=pd.read_csv(r/'external_metrics.csv')
n=results['n_external_common'];checks=0
assert len(pred)==n*2*4*2*6
for row in metrics.itertuples(index=False):
    g=pred[(pred.endpoint==row.endpoint)&(pred.k==row.k)&(pred.seed==row.seed)&(pred.arm==row.arm)]
    assert len(g)==n and g.territory_id.is_unique
    error=[float(y)-float(z) for y,z in zip(g.actual_log2025,g.predicted_log2025)]
    mse=sum(x*x for x in error)/n;mae=sum(abs(x) for x in error)/n
    assert np.isclose(mse,row.mse,rtol=1e-12,atol=1e-15)
    assert np.isclose(mae,row.mae,rtol=1e-12,atol=1e-15);checks+=2
for c in results['comparisons']:
    f=metrics[(metrics.k==c['k'])&(metrics.seed==20261006)&(metrics.endpoint==c['endpoint'])].set_index('arm')
    delta=float(f.loc[c['reference'],'mse']-f.loc[c['arm'],'mse'])
    assert np.isclose(delta,c['delta_mse_reference_minus_arm'],rtol=1e-12,atol=1e-15);checks+=1
seen=set()
for fold in results['region_folds']:
    train=set(fold['train_regions']);test=set(fold['test_regions'])
    assert not train&test and not seen&test
    seen|=test;checks+=1
assert len(seen)==results['sample_audit']['regions']
assert results['future_mutation_invariance'] and results['scalar_growth1_checks']==1896*6*6
assert not results['scientific_pass']
labels=pd.read_csv(r/'labels.csv');assert len(labels)==1896 and labels.territory_id.is_unique
for col in labels.columns[1:]:assert labels[col].nunique()==(2 if '_k2_' in col else 5)
provenance=json.loads((r/'provenance.json').read_text())
for name,expected in provenance['outputs'].items():
    assert hashlib.sha256((r/name).read_bytes()).hexdigest()==expected;checks+=1
dump={'status':'TECHNICAL_AUDIT_PASS','scientific_pass':False,'checked_at_utc':datetime.now(timezone.utc).isoformat(),
      'method':'Independent scalar aggregation of saved OOF predictions; exact masks/region folds; SHA output readback. Not independent scientific review.',
      'oof_rows':len(pred),'checked_metrics_and_contracts':checks,'scalar_growth1_checks':results['scalar_growth1_checks'],
      'future_mutation_invariance':True,'regions':len(seen),'mask_n':n}
(r/'audit.json').write_text(json.dumps(dump,ensure_ascii=False,indent=2)+'\n');print(json.dumps(dump))
