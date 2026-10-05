"""Sensitivity of stored A6 labels; frozen centres, no new clustering/tuning."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from a6_temporal import build_monthly_shares,standardize_frozen
from a6_identities import track_identities


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    if a.out.exists():raise FileExistsError('new output required')
    a.out.mkdir(parents=True);r=a.repo;run=r/'economic-atlas/runs/A6_v2'
    ass=pd.read_parquet(run/'assignments.parquet');regions=pd.read_csv(run/'regions.csv');cal=json.loads((run/'calibration.json').read_text())
    panel=pd.read_parquet(r/'economic-atlas/data/panel_v1.parquet');tids,months,S,_=build_monthly_shares(panel);Z,_=standardize_frozen(S,months)
    labels=[ass[ass.month==m].set_index('territory_id').reindex(tids).label.to_numpy(int) for m in months]
    centers=[regions[regions.month==m].sort_values('cluster')[[c for c in regions if c.startswith('centre_')]].to_numpy(float) for m in months]
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    (a.out/'protocol.json').write_text(json.dumps({'client_date':'2026-10-04','purpose':'post-hoc sensitivity; never threshold selection',
      'fixed':['A6_v2 labels','stored fitted centres','2023 scaler','T','Tc'],'margin_multipliers':[.75,1.,1.25],
      'base_assignment_sha256':sha(run/'assignments.parquet'),'centres_sha256':sha(run/'regions.csv'),'calibration_sha256':sha(run/'calibration.json'),
      'code_sha256':sha(Path(__file__))},indent=2)+'\n')
    results=[];counts=[]
    for mult in [.75,1.,1.25]:
        rows,_,_=track_identities(months,labels,centers,Z,tids,cal['overlap_threshold'],cal['candidate_margin']*mult,cal['resemblance_floor'])
        d=pd.DataFrame(rows);d['territory_id']=[int(tids[j]) for j in d.ti]
        if mult==1:
            b=ass.merge(d,on=['territory_id','month'],validate='one_to_one',suffixes=('_stored','_recomputed'))
            for c in ['label','identity_id','status']:
                assert b[c+'_stored'].fillna('').equals(b[c+'_recomputed'].fillna('')),(c,'base mismatch')
        counts.append({'margin_multiplier':mult,'ambiguous_rows':int((d.status=='ambiguous').sum()),'rows':len(d)})
        q=d[d.territory_id.isin([1673,1333,2192])&d.month.isin(['2023-12','2024-03','2024-04','2024-05','2024-12'])].copy();q['margin_multiplier']=mult
        results+=q.drop(columns='ti').to_dict('records')
    pd.DataFrame(results).to_csv(a.out/'case-thresholds.csv',index=False)
    (a.out/'audit.json').write_text(json.dumps({'passed':True,'base_reproduced_exactly':True,'counts':counts,'scientific_pass':False},indent=2)+'\n')
    (a.out/'manifest.json').write_text(json.dumps({p.name:sha(p) for p in a.out.iterdir() if p.name!='manifest.json'},indent=2)+'\n')
    print(json.dumps({'complete':True,'counts':counts}))
if __name__=='__main__':main()
