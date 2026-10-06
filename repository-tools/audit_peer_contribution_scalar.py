from pathlib import Path
import json,math,hashlib,argparse
from datetime import datetime,timezone
import pandas as pd
import numpy as np
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description='Recheck the marginal peer contribution, distinct from the total correction')
parser.add_argument('--run',type=Path,default=root/'economic-atlas/runs/Consumer_mechanisms_20261007')
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();run=args.run
frame=pd.read_parquet(run/'predictions.parquet')
metrics=json.loads((run/'metrics.json').read_text())
assert not frame.duplicated(['territory_id','category','horizon','origin','target']).any()
results=[]
for horizon,variant in [(1,'one_step'),(3,'direct')]:
    data=frame.loc[frame.category.eq('Все категории')&frame.horizon.eq(horizon)&frame.supported].copy()
    assert len(data)==9234 and data.territory_id.nunique()==1539
    own='profile_ses__'+variant+'_zero_own';peer='profile_ses__'+variant+'_zero_peer'
    losses={name:[abs(float(row.actual)-float(getattr(row,name))) for row in data.itertuples()] for name in ['profile_ses',own,peer]}
    maes={name:math.fsum(value)/len(data) for name,value in losses.items()}
    saved=next(row for row in metrics['results'] if row['category']=='Все категории' and row['horizon']==horizon)
    for name,value in maes.items():assert math.isclose(value,saved['mae'][name],rel_tol=1e-12)
    comparison=next(row for row in saved['comparisons'] if row['reference']==own and row['model']==peer)
    gains=np.array(losses[own])-np.array(losses[peer])
    periods=sorted(data.target.unique());assert len(periods)==6
    totals=np.array([math.fsum(gains[data.target.to_numpy()==month]) for month in periods])
    sizes=np.array([int(data.target.eq(month).sum()) for month in periods])
    draws=np.random.default_rng(20261007).integers(0,6,(10000,6))
    interval=np.quantile(totals[draws].sum(axis=1)/sizes[draws].sum(axis=1),[.025,.975])
    np.testing.assert_allclose(interval,comparison['ci95_target_month_blocks'],atol=1e-10,rtol=1e-10)
    assert math.isclose(maes[own]-maes[peer],comparison['mae_gain'],rel_tol=1e-10)
    result={'horizon':horizon,'rows':len(data),'municipalities':1539,'base_mae':maes['profile_ses'],'own_only_mae':maes[own],'own_plus_peer_mae':maes[peer],
            'whole_correction_gain_percent':100*(maes['profile_ses']-maes[peer])/maes['profile_ses'],
            'incremental_peer_gain_percent':100*(maes[own]-maes[peer])/maes[own],
            'incremental_peer_gain_source_units':maes[own]-maes[peer],'incremental_peer_descriptive_month_ci95':interval.tolist(),
            'monthly_interval_includes_zero':bool(interval[0]<=0<=interval[1])}
    results.append(result)
receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'checked_where':'Mac; independent scalar math.fsum and paired month bootstrap, no model-training imports',
         'status':'SEPARATE_PEER_CONTRIBUTION_SCALAR_AUDIT_PASS','source_sha256':hashlib.sha256((run/'predictions.parquet').read_bytes()).hexdigest(),
         'auditor_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scientific_pass':False,'checks':results,
         'limit':'Same previously reviewed2024; confidence intervals descriptive across six target months. Numerical recheck does not prove external scientific validity, historicalasof or causal peer influence.'}
out=args.out;assert not out.exists();out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(receipt,ensure_ascii=False))
