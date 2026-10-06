"""Independent scalar verification of frozen news forecast outputs."""
import argparse,hashlib,json,math
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser()
    for name in ['panel','run','out']:p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('new audit receipt only')
    m=json.loads((a.run/'metrics.json').read_text());assert sha(a.panel)==m['input_sha256']['panel']
    panel=pd.read_parquet(a.panel);values={(int(row.territory_id),str(row.category),str(row.ym)):float(row.value) for row in panel.itertuples()}
    pred=pd.read_parquet(a.run/'predictions.parquet');keys=['territory_id','category','origin','target','horizon']
    assert not pred.duplicated(keys).any() and len(pred)==136512
    raw_checks=0
    for row in pred.itertuples():
        assert row.actual==values[(int(row.territory_id),str(row.category),str(row.target))]
        assert row.last==values[(int(row.territory_id),str(row.category),str(row.cutoff))]
        assert pd.Period(row.cutoff,freq='M')==pd.Period(row.origin,freq='M')-2
        assert pd.Period(row.target,freq='M')==pd.Period(row.origin,freq='M')+row.horizon
        raw_checks+=4
    arm_checks=0;category_checks=0
    for metric in m['metrics']:
        g=pred.loc[pred.horizon.eq(metric['horizon'])];col='pred_'+metric['arm']
        losses=[abs(float(row.actual)-float(getattr(row,col))) for row in g.itertuples()]
        normalized=[loss/float(row.scale) for loss,row in zip(losses,g.itertuples())]
        assert math.isclose(math.fsum(losses)/len(losses),metric['mae'],rel_tol=1e-12)
        assert math.isclose(math.fsum(normalized)/len(normalized),metric['normalized_mae'],rel_tol=1e-12)
        groups={}
        for row in g.itertuples():groups.setdefault(row.target,[]).append(abs(float(row.actual)-float(row.pred_control))-abs(float(row.actual)-float(getattr(row,col))))
        periods=sorted(groups);totals=np.array([math.fsum(groups[month]) for month in periods]);sizes=np.array([len(groups[month]) for month in periods])
        draw=np.random.default_rng(20261003).integers(0,len(periods),(10000,len(periods)))
        interval=np.quantile(totals[draw].sum(1)/sizes[draw].sum(1),[.025,.975])
        np.testing.assert_allclose(interval,metric['month_block']['ci95'],rtol=1e-10,atol=1e-10)
        assert math.isclose(math.fsum(totals)/sum(sizes),metric['month_block']['point'],rel_tol=1e-10,abs_tol=1e-10)
        for entry in metric['categories']:
            cat=g.loc[g.category.eq(entry['category'])]
            value=math.fsum(abs(float(row.actual)-float(getattr(row,col))) for row in cat.itertuples())/len(cat)
            assert math.isclose(value,entry['mae'],rel_tol=1e-12);category_checks+=1
        arm_checks+=1
    assert all(f['max_training_target']<=f['cutoff'] for f in m['fits']) and len(m['fits'])==60
    np.testing.assert_allclose(pred.pred_strict,pred.pred_control,rtol=1e-12,atol=1e-9)
    np.testing.assert_allclose(pred.pred_shifted_twelve_months,pred.pred_control,rtol=1e-12,atol=1e-9)
    receipt={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'INDEPENDENT_NEWS_NUMERICAL_AUDIT_PASS','scientific_pass':False,'scalar_actual_anchor_cutoff_horizon_checks':raw_checks,'independent_arm_MAE_normalized_error_and_interval_checks':arm_checks,'category_MAE_checks':category_checks,'training_label_time_receipts':60,'predictions_sha256':sha(a.run/'predictions.parquet'),'code_sha256':sha(__file__),'scope':'Different numerical audit of same viewed predictions; not new model fits, availability proof or external scientific review'}
    a.out.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

if __name__=='__main__':main()
