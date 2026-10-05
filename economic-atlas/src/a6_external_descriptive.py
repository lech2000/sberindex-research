from pathlib import Path
import pandas as pd,json,hashlib
import argparse
from datetime import datetime,timezone
parser=argparse.ArgumentParser(description='Internal descriptive coverage/profile audit; not confirmatory economics')
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--assignments',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
if args.out.exists():raise FileExistsError('new run only')
root=args.root
a=pd.read_parquet(args.assignments).query('month == "2024-12"').copy()
fn=root/'data/fns-sme-national-municipal-snapshots-2023-2024.parquet';d=pd.read_parquet(fn)
assert not d.duplicated(['snapshot_date','territory_id']).any()
countcols=[c for c in d if c.startswith('fns_') and c != 'fns_sme_total']
assert (d[countcols].sum(axis=1)==d.fns_sme_total).all()
ma=root/'data/raw/sberindex-data-sense-2025/1_market_access.parquet';m=pd.read_parquet(ma)
assert not m.territory_id.duplicated().any()
j=a.merge(d.query('snapshot_date == "2024-10-10"'),how='left',on='territory_id',validate='one_to_one').merge(m,how='left',on='territory_id',validate='one_to_one')
poproot=root/'data/raw/sberindex-data-sense-2025/2_bdmo_population.parquet';pop=pd.read_parquet(poproot)
pop=pop[(pop.year==2024)&(pop.age=='Всего')&pop.gender.isin(['Мужчины','Женщины'])].copy()
key=['territory_id','year','period','age','gender'];z=pop.groupby(key,dropna=False).value.nunique()
assert z.max()<=1
pop=pop.drop_duplicates(key+['value']).dropna(subset=['value']).drop_duplicates(key)
p=pop.groupby('territory_id').agg(population=('value','sum'),genders=('gender','nunique'))
p=p[p.genders==2]
j=j.merge(p[['population']],left_on='territory_id',right_index=True,how='left',validate='one_to_one')
j['sme_per_1000']=j.fns_sme_total*1000/j.population.where(j.population>0)
mr=root/'data/raw/sberindex-data-sense-2025/3_bdmo_migration.parquet';migr=pd.read_parquet(mr)
rows=[]
for label,g in j.groupby('label'):
 for subset,v in [('all_address_candidates',g),('region_match_ge_90pct',g[g.region_match_rate>=.9])]:
  rows.append({'label':int(label),'subset':subset,'n_cohort':len(v),'n_fns':int(v.fns_sme_total.notna().sum()),'n_market':int(v.market_access.notna().sum()),'n_rate':int(v.sme_per_1000.notna().sum()),'n_ambiguous_identity':int((v.status=='ambiguous').sum()),'median_fns_total':float(v.fns_sme_total.median()),'median_sme_per_1000':float(v.sme_per_1000.median()),'median_market_access':float(v.market_access.median())})
report={'checked_at':datetime.now(timezone.utc).isoformat(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'status':'internal_descriptive_only_not_external_validation','n_atlas':len(a),'fns_file_rows':len(d),'fns_2024_matched_atlas':int(j.fns_sme_total.notna().sum()),'market_matched_atlas':int(j.market_access.notna().sum()),'matched_both':int((j.fns_sme_total.notna()&j.market_access.notna()).sum()),'migration_rows':len(migr),'migration_nulls':int(migr.value.isna().sum()),'migration_territories':migr.territory_id.nunique(),'migration_coverage_atlas':int(a.territory_id.isin(migr.territory_id).sum()),'by_group':rows,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [fn,ma,poproot,mr,args.assignments]},'limits':['FNS address coverage is incomplete and region_match_rate is not municipal precision','Not employment; subjects IP/organisations/farm-head are registry entities, not employees','Cluster label is December partition; ambiguous identity never treated as stable cluster','No inferred legal successorship or independently verified historical boundary','Market access is derived population/road indicator; not independent causal validation','Migration concept/unit not established; no net balance interpretation','No new test; no scientific PASS']}
args.out.parent.mkdir(parents=True,exist_ok=True)
args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
