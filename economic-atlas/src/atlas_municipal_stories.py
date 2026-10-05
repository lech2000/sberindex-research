"""Three descriptive municipal stories on existing audited sources.

Selection is by already acquired complete annual budget pairs, not by a
favorable cluster transition. No causal inference or historical as-of claim.
"""
from pathlib import Path
import argparse, hashlib, json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

STORIES = [('Орск',1673,1668),('Курган',1333,1334),('Ишим',2192,2190)]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def finite(v):return None if pd.isna(v) else float(v)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--repo',type=Path);ap.add_argument('--migration',type=Path);ap.add_argument('--out',type=Path)
    a=ap.parse_args();r=a.repo
    if a.out.exists():raise FileExistsError('new run only')
    a.out.mkdir(parents=True)
    inputs={'panel':r/'economic-atlas/data/panel_v1.parquet','assignments':r/'economic-atlas/runs/A6_v2/assignments.parquet',
            'methods':r/'economic-atlas/runs/A5/assignments.parquet','budget':r/'economic-atlas/runs/Municipal_budget_pilot_20261004/metrics.json',
            'budget_observations':r/'economic-atlas/runs/Municipal_budget_pilot_20261004/observations.parquet','migration':a.migration}
    dump(a.out/'protocol.json',{'recorded_before_story_assembly':datetime.now(timezone.utc).isoformat(),'client_date':'2026-10-04',
        'selection':'three already acquired complete annual budget pairs; predefined contrasts from previous budget pilot',
        'cities':[x[0] for x in STORIES],'sha256':{k:sha(p) for k,p in inputs.items()},
        'scientific_pass':False,'limits':['Retrospective descriptions, not causal mechanisms',
          'All three anchor identities already known ambiguous at Dec2024; no selection on positive transitions',
          'Budget expenditure nominal, not household spending or inflation-adjusted activity',
          'Migration 2023 only, not 2024 flood consequence; ratio uses Jan1 population, not official coefficient',
          'Across-method cluster labels not aligned; compare co-membership with predetermined contrast only',
          'No complete annual budget contrast pairs; population imbalance disclosed',
          'Common spring flood family does not create three independent shocks',
          'No historical publication/vintage verification; sources stay descriptive']})
    panel=pd.read_parquet(inputs['panel']);panel['territory_id']=panel.territory_id.astype(int)
    assignments=pd.read_parquet(inputs['assignments']);methods=pd.read_parquet(inputs['methods'])
    migration=pd.read_parquet(inputs['migration'])
    budget=json.loads(inputs['budget'].read_text())
    obs=pd.read_parquet(inputs['budget_observations'])
    seed_runs=[]
    for p in sorted((r/'economic-atlas/runs/A6_v2/robustness').glob('seed-*/assignments.parquet')):
        d=pd.read_parquet(p);seed_runs.append((p.parent.name,d))
    stories=[]
    for name,tid,contrast in STORIES:
        rows=panel[panel.territory_id.eq(tid)]
        if len(rows)!=144:raise ValueError('Expected complete 24 x 6 case panel')
        grid=rows.pivot(index='ym',columns='category',values='value').astype(float)
        changes=[]
        for c in grid:
            y23=grid.loc[grid.index.str.startswith('2023'),c].mean()
            y24=grid.loc[grid.index.str.startswith('2024'),c].mean()
            changes.append({'category':c,'mean_2023':float(y23),'mean_2024':float(y24),'annual_mean_growth_pct':float(100*(y24/y23-1)),
                'April_MoM_pct':float(100*(grid.at['2024-04',c]/grid.at['2024-03',c]-1)),
                'April_YoY_pct':float(100*(grid.at['2024-04',c]/grid.at['2023-04',c]-1)),
                'May_MoM_pct':float(100*(grid.at['2024-05',c]/grid.at['2024-04',c]-1))})
        identity=assignments[(assignments.territory_id.eq(tid))&assignments.month.isin(['2023-12','2024-03','2024-04','2024-05','2024-12'])]
        sd=[]
        for seed,d in seed_runs:
            q=d[(d.territory_id.eq(tid))&(d.month=='2024-12')].iloc[0]
            sd.append({'seed':seed,'identity_status':q.status,'identity_id':q.identity_id})
        first=methods[methods.territory_id.eq(tid)].iloc[0];other=methods[methods.territory_id.eq(contrast)].iloc[0]
        consensus={c:bool(first[c]==other[c]) for c in methods if c.startswith('label_')}
        prof=sorted([p for p in budget['profiles'] if p['territory_id']==tid and p['status']=='observed'],key=lambda x:x['year'])
        if [p['year'] for p in prof]!=[2023,2024]:raise ValueError('Annual budget pair incomplete')
        expense_growth=100*(prof[1]['expense_kopecks']/prof[0]['expense_kopecks']-1)
        fiscal={'expense_2023_rub':prof[0]['expense_kopecks']/100,'expense_2024_rub':prof[1]['expense_kopecks']/100,
                'expense_growth_pct':expense_growth,'functional_shares_2023':prof[0]['functional_shares'],
                'functional_shares_2024':prof[1]['functional_shares'],'population_ratio_to_anchor':prof[0]['population_ratio_to_anchor']}
        m=migration[migration.territory_id.eq(tid)]
        mig=None if len(m)!=1 else {k:finite(m.iloc[0][k]) for k in ['net_migration_2023','start_population','net_per_1000_start_population']}
        source_rows=obs[obs.territory_id.eq(tid)]
        sources=source_rows[['source_url','source_file','source_sha256','source_locator']].drop_duplicates().to_dict('records')
        story={'municipality':name,'territory_id':tid,'contrast_territory_id':contrast,
               'consumption':changes,'budget':fiscal,'migration':mig,'identities':identity.to_dict('records'),
               'seed_checks':sd,'seed_ambiguity_count':sum(x['identity_status']=='ambiguous' for x in sd),
               'co_cluster_with_predefined_contrast':consensus,'same_cluster_methods':sum(consensus.values()),
               'method_count':len(consensus),'sources':sources,'economic_type_supported':False,'causal_effect_supported':False}
        stories.append(story)
    dump(a.out/'stories.json',{'status':'DESCRIPTIVE_NOT_ECONOMIC_PASS','stories':stories,'scientific_pass':False})
    pd.DataFrame([{'municipality':x['municipality'],**y} for x in stories for y in x['consumption']]).to_csv(a.out/'consumption-changes.csv',index=False)
    dump(a.out/'manifest.json',{p.name:sha(p) for p in sorted(a.out.iterdir()) if p.is_file() and p.name!='manifest.json'})
    print(json.dumps({'complete':True,'stories':len(stories),'all_seed_ambiguity_counts':[x['seed_ambiguity_count'] for x in stories]},ensure_ascii=False))

if __name__=='__main__':main()
