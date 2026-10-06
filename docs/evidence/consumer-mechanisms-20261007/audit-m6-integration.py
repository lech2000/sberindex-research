"""Independent array/rank replay of source missingness and population association."""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json
import numpy as np
import pandas as pd
from scipy.stats import rankdata

r=Path(__file__).resolve().parents[3]
x=Path('/Users/sergey/projects/sberindex-research-accelerated-public-20261003')
paths={'raw':x/'data/raw/sberindex-data-sense-2025/8_consumption.parquet','panel':r/'economic-atlas/data/panel_v1.parquet','population':x/'output/atlas-radar-ablation-20261006/data-sense/2_bdmo_population.parquet','dictionary':x/'data/frozen/radar/municipal-dictionary.parquet'}
run=r/'economic-atlas/runs/H5_scale_encoding_audit_20261007'
expected=json.loads((run/'missingness-size-audit.json').read_text())
protocol=json.loads((run/'missingness-protocol.json').read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert {k:sha(p) for k,p in paths.items()}==protocol['input_sha256']
raw=pd.read_parquet(paths['raw'])
months=pd.to_datetime(raw.date).dt.strftime('%Y-%m')
keys=pd.MultiIndex.from_arrays([raw.territory_id,months,raw.category])
assert keys.is_unique and len(months.unique())==24 and raw.category.nunique()==6
present=raw.groupby('territory_id').size().sort_index()
missing=144-present
checks={'source_municipalities':len(present),'source_rows':len(raw),'expected_cells_among_source_municipalities':144*len(present),'absent_cells':int(missing.sum()),'absent_cell_fraction':float(missing.sum()/(144*len(present))),'municipalities_with_absent_cells':int((missing>0).sum()),'municipalities_complete_present':int((missing==0).sum()),'invalid_present_cells':int((~np.isfinite(raw.value)|raw.value.le(0)).sum())}
assert all(v==expected[k] for k,v in checks.items())
panel=pd.read_parquet(paths['panel']);panelids=set(map(int,panel.territory_id.unique()))
assert len(panelids)==1896 and missing.loc[sorted(panelids)].eq(0).all()
population=pd.read_parquet(paths['population'])
population=population.loc[population.year.eq(2023)&population.period.eq('год')&population.age.eq('Всего')]
sex={}
for (tid,gender),g in population.groupby(['territory_id','gender']):
 values=g.value.dropna().unique()
 if len(values)==1 and gender in ('Женщины','Мужчины'):sex[(int(tid),gender)]=float(values[0])
dictionary=pd.read_parquet(paths['dictionary']).set_index('territory_id');assert dictionary.index.is_unique
ids=[];sizes=[];fractions=[];regions=[]
for tid,n in present.items():
 tid=int(tid)
 if (tid,'Женщины') not in sex or (tid,'Мужчины') not in sex or tid not in dictionary.index:continue
 total=sex[(tid,'Женщины')]+sex[(tid,'Мужчины')]
 region=dictionary.loc[tid,'region_code'];kind=dictionary.loc[tid,'type']
 if not np.isfinite(total) or total<=0 or pd.isna(region) or pd.isna(kind):continue
 ids.append(tid);sizes.append(total);fractions.append((144-int(n))/144);regions.append(int(region))
sizes=np.asarray(sizes);fractions=np.asarray(fractions);regions=np.asarray(regions)
assert len(sizes)==expected['analysis_population_n']==2078 and len(present)-len(sizes)==expected['excluded_population_or_dictionary']
def correlation(a,b):return float(np.corrcoef(rankdata(a),rankdata(b))[0,1])
rho=correlation(np.log(sizes),fractions)
np.testing.assert_allclose(rho,expected['spearman_log_population_absent_fraction'],rtol=0,atol=1e-14)
groups=[np.flatnonzero(regions==region) for region in sorted(set(regions))]
rng=np.random.default_rng(20261007);boots=[]
for _ in range(2000):
 indices=np.concatenate([groups[i] for i in rng.integers(0,len(groups),len(groups))])
 boots.append(correlation(np.log(sizes[indices]),fractions[indices]))
ci=np.nanquantile(boots,[.025,.975])
np.testing.assert_allclose(ci,expected['descriptive_region_block_ci95'],rtol=0,atol=1e-14)
boundaries=np.quantile(sizes,[.2,.4,.6,.8]);quintile=np.searchsorted(boundaries,sizes,side='left')+1
for row in expected['quintiles']:
 mask=quintile==row['quintile']
 assert int(mask.sum())==row['n'] and int((fractions[mask]>0).sum())==row['n_with_absent_cells']
 np.testing.assert_allclose([sizes[mask].min(),sizes[mask].max(),(fractions[mask]>0).mean(),fractions[mask].mean()],[row['population_min'],row['population_max'],row['municipal_fraction_with_absent_cells'],row['absent_cell_fraction']],rtol=0,atol=1e-14)
receipt={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'status':'INDEPENDENT_M6_ARRAY_RANK_AUDIT_PASS','scientific_pass':False,'source_counts':checks,'population_association_n':len(sizes),'regions':len(groups),'spearman_rho':rho,'descriptive_region_ci95':ci.tolist(),'bootstrap_draws':2000,'quintiles_checked':5,'panel_missing_indicator_constant_zero':True,'input_sha256':protocol['input_sha256'],'code_sha256':sha(Path(__file__)),'scope':'Different array/rank implementation on the same viewed raw snapshots. Complete-panel selection is retrospective; no causal suppression or representative-population claim.'}
out=Path(__file__).with_name('m6-integration-audit.json');assert not out.exists()
out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False))
