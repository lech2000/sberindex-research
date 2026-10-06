"""Separate scalar replay of frozen M2 calibration from real 2023 observations."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
import pandas as pd


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def overlap(mu1, variance1, mu2, variance2):
    d=len(mu1)
    common=variance1+variance2
    prefactor=(2*np.sqrt(variance1*variance2)/common)**(d/2)
    return float(prefactor*np.exp(-np.sum((mu1-mu2)**2)/(4*common)))


def replay(panel, assignments, seed):
    ids=np.sort(panel.territory_id.unique())
    cats=['Здоровье','Маркетплейсы','Общественное питание','Продовольствие','Транспорт']
    months=[f'2023-{m:02d}' for m in range(1,13)]
    index=pd.MultiIndex.from_product([ids,months],names=['territory_id','ym'])
    p=panel.loc[panel.ym.isin(months)]
    assert not p.duplicated(['territory_id','ym','category']).any()
    wide=p.pivot(index=['territory_id','ym'],columns='category',values='value').reindex(index=index,columns=['Все категории']+cats)
    cube=wide.to_numpy(float).reshape(len(ids),12,6)
    shares=cube[:,:,1:]/cube[:,:,[0]]
    pooled=shares.reshape(-1,5)
    z=(shares-pooled.mean(axis=0))/pooled.std(axis=0,ddof=0)
    a=assignments.loc[assignments.month.isin(months)]
    labs=a.pivot(index='territory_id',columns='month',values='label').reindex(index=ids,columns=months).to_numpy(int)
    rng=np.random.default_rng(seed+555555);self_scores=[];other_scores=[]
    for m in range(12):
        full={}
        for c in sorted(np.unique(labs[:,m])):
            points=z[labs[:,m]==c,m,:]
            assert len(points)>=8
            mean=points.mean(axis=0)
            variance=max(float(np.mean(np.sum((points-mean)**2,axis=1))/5),1e-6)
            full[int(c)]=(points,mean,variance)
        for c,(points,mean,variance) in full.items():
            for _ in range(200):
                draw=points[rng.integers(0,len(points),size=len(points))]
                sample_mean=draw.mean(axis=0)
                sample_var=max(float(np.mean(np.sum((draw-sample_mean)**2,axis=1))/5),1e-6)
                self_scores.append(overlap(sample_mean,sample_var,mean,variance))
                for o,(_,other_mean,other_var) in full.items():
                    if c!=o:other_scores.append(overlap(sample_mean,sample_var,other_mean,other_var))
    self_q05=float(np.quantile(self_scores,.05));other_q95=float(np.quantile(other_scores,.95));other_q50=float(np.quantile(other_scores,.5))
    return {'overlap_threshold':other_q95,'candidate_margin':max(0.,self_q05-other_q95),'resemblance_floor':other_q50,'n_self_scores':len(self_scores),'n_other_scores':len(other_scores),'cal_months':list(range(12))}


def main():
    p=argparse.ArgumentParser()
    for key in ['panel','assignments','calibration','controls_protocol','out']:
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('New audit only')
    expected=json.loads(a.calibration.read_text());cp=json.loads(a.controls_protocol.read_text())
    assert sha(a.calibration)==cp['sha256']['calibration']
    assert expected['cal_months']==list(range(12)) and not expected['fallback']
    panel=pd.read_parquet(a.panel);assignments=pd.read_parquet(a.assignments)
    measured=replay(panel,assignments,20260926)
    for key,value in measured.items():
        if isinstance(value,float):np.testing.assert_allclose(value,expected[key],rtol=1e-12,atol=1e-14)
        else:assert value==expected[key]
    future=panel.copy();future.loc[future.ym>'2023-12','value']*=19
    assert replay(future,assignments,20260926)==measured
    for key,value in cp['frozen_thresholds'].items():assert expected[key]==value
    root=Path(__file__).resolve().parents[2]
    def creation(path):
        raw=subprocess.check_output(['git','-C',str(root),'log','--diff-filter=A','--format=%H %cI','--',str(path.relative_to(root))],text=True).splitlines()
        return raw[-1]
    cal_creation=creation(a.calibration.resolve());control_creation=creation(a.controls_protocol.resolve())
    subprocess.run(['git','-C',str(root),'merge-base','--is-ancestor',cal_creation.split()[0],control_creation.split()[0]],check=True)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'INDEPENDENT_REAL_2023_CALIBRATION_REPLAY_PASS','scientific_pass':False,'thresholds':measured,'raw_calibration_municipalities':int(panel.territory_id.nunique()),'bootstrap_overlap_values':measured['n_self_scores']+measured['n_other_scores'],'future_2024_mutation_invariant':True,'synthetic_worlds_used_in_numeric_replay':False,'synthetic_protocol_reuses_exact_frozen_thresholds':True,'calibration_file_added':cal_creation,'controls_protocol_added':control_creation,'calibration_commit_is_ancestor_of_control_commit':True,'sha256':{k:sha(getattr(a,k)) for k in ['panel','assignments','calibration','controls_protocol']},'code_sha256':sha(__file__),'limits':['Replay uses archived empirical 2023 labels, not independent clustering or economic ground truth','Real 2023 threshold provenance is verified; synthetic worlds were designed afterward and may be easy controls','No predeclared scientific error budget, no confirmatory F1 gate, no real-event validation','Git chronology is repository evidence, not an external trusted timestamp']}
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
