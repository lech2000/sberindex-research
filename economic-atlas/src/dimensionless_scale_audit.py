"""Fixed unit-invariant scale diagnostic; kept separate from frozen H5."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,subprocess
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.metrics import adjusted_rand_score
from threadpoolctl import threadpool_limits
import atlas_h5_scale_audit as h5
import atlas_radar_ablation as external

def features(shares,total,train):
    median=float(np.median(total[train]))
    assert np.isfinite(median) and median>0
    return np.column_stack([shares,np.log(total/median)]),median

def run(a):
    protocol=json.loads(a.protocol.read_text());assert not a.out.exists()
    paths={key:Path(getattr(a,key)) for key in ['panel','dictionary','population','market','wages','employment']}
    assert {key:h5.sha(path) for key,path in paths.items()}==protocol['inputs']
    a.out.mkdir(parents=True);h5.write(a.out/'execution-start.json',{'checked_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':h5.sha(a.protocol),'code_sha256':h5.sha(__file__),'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()})
    panel=pd.read_parquet(paths['panel']);ids,fs=h5.feature_sets(panel)
    total=panel.loc[panel.ym.str.startswith('2023-') & panel.category.eq('Все категории')].groupby('territory_id').value.mean().reindex(ids).to_numpy(float)
    assert len(ids)==1896 and np.isfinite(total).all() and (total>0).all()
    future=panel.copy();future.loc[future.ym>'2023-12','value']*=99
    ids2,fs2=h5.feature_sets(future);np.testing.assert_array_equal(ids,ids2);np.testing.assert_array_equal(fs['shares'],fs2['shares'])
    sample,mask=external.economic_sample(ids,paths['dictionary'],paths['population'],paths['market'],paths['wages'],paths['employment']);assert len(sample)==1248 and sample.region_code.nunique()==70
    positions=pd.Index(ids).get_indexer(sample.index);shares=fs['shares'][positions];tot=total[positions]
    old_pred=pd.read_parquet(a.reference/'oof_predictions.parquet');old_labs=pd.read_parquet(a.reference/'partitions.parquet')
    rows=[];partitions=[];full=[];folds=[];fits=0
    for method,seeds in protocol['methods'].items():
      for k in protocol['ks']:
       for seed in seeds:
        x,median=features(fs['shares'],total,np.arange(len(total)))
        xu,_=features(fs['shares'],total*protocol['unit_factor'],np.arange(len(total)))
        np.testing.assert_allclose(x,xu,rtol=1e-13,atol=1e-13)
        lab,_,scaler=h5.fit(x,x,method,k,seed);ulab,_,_=h5.fit(xu,xu,method,k,seed);fits+=2
        full.append({'method':method,'k':k,'seed':seed,'ruble_to_thousand_ARI':float(adjusted_rand_score(lab,ulab)),**{ 'ARI_vs_'+arm:float(adjusted_rand_score(lab,old_labs.loc[(old_labs.method==method)&(old_labs.k==k)&(old_labs.seed==seed)&(old_labs.arm==arm)].set_index('territory_id').reindex(ids).label)) for arm in ['shares','shares_log_volume']}})
        partitions.extend((int(t),method,k,seed,int(l)) for t,l in zip(ids,lab))
        for fold,(tr,te) in enumerate(GroupKFold(5).split(sample,groups=sample.region_code)):
          assert not set(sample.region_code.iloc[tr])&set(sample.region_code.iloc[te])
          f,med=features(shares,tot,tr);fu,_=features(shares,tot*protocol['unit_factor'],tr)
          np.testing.assert_allclose(f,fu,rtol=1e-13,atol=1e-13)
          lt,le,_=h5.fit(f[tr],f[te],method,k,seed);ult,ule,_=h5.fit(fu[tr],fu[te],method,k,seed);fits+=2
          assert adjusted_rand_score(lt,ult)==1 and adjusted_rand_score(le,ule)==1
          # A holdout magnitude cannot alter the normalization learned from train.
          mutation=tot.copy();mutation[te]*=999
          _,mutated_median=features(shares,mutation,tr);assert med==mutated_median
          folds.append({'method':method,'k':k,'seed':seed,'fold':fold,'median_train':med,'train_ids':sample.index[tr].astype(int).tolist(),'test_ids':sample.index[te].astype(int).tolist(),'unit_train_ARI':1,'unit_test_ARI':1})
          for endpoint in ['wage','employment']:
            y=np.log(sample[endpoint+'2025'].to_numpy());c,d=external.controls(sample,endpoint,tr,te)
            c=np.column_stack([c,(lt[:,None]==np.arange(1,k)).astype(float)]);d=np.column_stack([d,(le[:,None]==np.arange(1,k)).astype(float)])
            pred=d@np.linalg.lstsq(c,y[tr],rcond=None)[0]
            uc,ud=external.controls(sample,endpoint,tr,te)
            uc=np.column_stack([uc,(ult[:,None]==np.arange(1,k)).astype(float)]);ud=np.column_stack([ud,(ule[:,None]==np.arange(1,k)).astype(float)])
            upred=ud@np.linalg.lstsq(uc,y[tr],rcond=None)[0]
            np.testing.assert_allclose(pred,upred,rtol=1e-10,atol=1e-10)
            rows.extend((int(sample.index[ix]),int(sample.region_code.iloc[ix]),fold,endpoint,'shares_log_relative_volume',method,k,seed,float(y[ix]),float(pred[i])) for i,ix in enumerate(te))
        print(json.dumps({'method':method,'k':k,'seed':seed,'complete':True}),flush=True)
    pred=pd.DataFrame(rows,columns=['territory_id','region','fold','endpoint','arm','method','k','seed','actual_log2025','predicted_log2025']);pred.to_parquet(a.out/'oof_predictions.parquet',index=False)
    pd.DataFrame(partitions,columns=['territory_id','method','k','seed','label']).to_parquet(a.out/'partitions.parquet',index=False)
    comparisons=[];metrics=[]
    for key,g in pred.groupby(['method','k','seed','endpoint']):
      method,k,seed,endpoint=key;ref=old_pred[(old_pred.method==method)&(old_pred.k==k)&(old_pred.seed==seed)&(old_pred.endpoint==endpoint)&old_pred.arm.isin(['shares','shares_log_volume'])]
      assert len(g)==1248 and len(ref)==2496
      metrics.append({'method':method,'k':int(k),'seed':int(seed),'endpoint':endpoint,'n':len(g),'mse':float(((g.actual_log2025-g.predicted_log2025)**2).mean())})
      if seed==protocol['primary_seed']:
       for arm in ['shares','shares_log_volume']:
        comparisons.append({'method':method,'k':int(k),'seed':int(seed),'endpoint':endpoint,**external.paired_bootstrap(pd.concat([g,ref]),'shares_log_relative_volume',arm,seed=seed,b=protocol['bootstrap'])})
    h5.write(a.out/'metrics.json',metrics);h5.write(a.out/'comparisons.json',comparisons);h5.write(a.out/'full-partitions.json',full);h5.write(a.out/'folds.json',folds)
    h5.write(a.out/'results.json',{'checked_at':datetime.now(timezone.utc).isoformat(),'status':'DIMENSIONLESS_SCALE_DIAGNOSTIC_EXECUTED','scientific_pass':False,'cluster_fits_including_unit_replays':fits,'full_partitions':len(full),'external_oof_rows':len(pred),'all_full_unit_ARI1':all(f['ruble_to_thousand_ARI']==1 for f in full),'input_sha256':protocol['inputs'],'protocol_sha256':h5.sha(a.protocol),'code_sha256':h5.sha(__file__),'reference_predictions_sha256':h5.sha(a.reference/'oof_predictions.parquet'),'comparisons':comparisons,'limits':protocol['limits']})

def main():
    p=argparse.ArgumentParser()
    for key in ['panel','dictionary','population','market','wages','employment','protocol','reference','out']:p.add_argument('--'+key,type=Path,required=True)
    with threadpool_limits(limits=1):run(p.parse_args())
if __name__=='__main__':main()
