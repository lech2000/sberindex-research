"""Descriptive M6 source missingness versus population; no missing-value imputation."""
import argparse,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def population2023(d):
    p=d.loc[d.year.eq(2023)&d.period.eq('год')&d.age.eq('Всего')].copy()
    groups=p.groupby(['territory_id','gender']).value
    count=groups.nunique(dropna=True);values=groups.first().loc[count.eq(1)]
    table=values.unstack('gender').reindex(columns=['Женщины','Мужчины'])
    return table.sum(axis=1,min_count=2),{'ambiguous_sex_cells':int(count.gt(1).sum()),'missing_or_invalid_totals':int((table.sum(axis=1,min_count=2).isna()|table.sum(axis=1,min_count=2).le(0)).sum())}

def source_counts(raw):
    d=raw.copy();d['ym']=pd.to_datetime(d.date).dt.to_period('M').astype(str)
    if d.duplicated(['territory_id','ym','category']).any():raise ValueError('duplicate source cell')
    if len(d.category.unique())!=6:raise ValueError('expected six categories')
    if sorted(d.ym.unique())!=pd.period_range('2023-01','2024-12',freq='M').astype(str).tolist():raise ValueError('wrong source months')
    d['invalid']=~np.isfinite(d.value)|d.value.le(0)
    s=d.groupby('territory_id').agg(present=('value','size'),invalid=('invalid','sum'))
    s['missing_absent']=144-s.present;s['absent_fraction']=s.missing_absent/144
    if s.missing_absent.lt(0).any():raise ValueError('too many source cells')
    for year in [2023,2024]:s[f'missing_{year}']=72-d.loc[d.ym.str.startswith(str(year))].groupby('territory_id').size().reindex(s.index,fill_value=0)
    return s

def run(a):
    protocol=json.loads(a.protocol.read_text());paths={'raw':a.raw,'panel':a.panel,'population':a.population,'dictionary':a.dictionary}
    assert {k:sha(v) for k,v in paths.items()}==protocol['input_sha256']
    if a.out.exists():raise FileExistsError('new run only')
    raw=pd.read_parquet(a.raw);panel=pd.read_parquet(a.panel);dictionary=pd.read_parquet(a.dictionary).set_index('territory_id')
    assert dictionary.index.is_unique
    s=source_counts(raw);pop,pa=population2023(pd.read_parquet(a.population));s['population2023']=pop.reindex(s.index);s['region']=dictionary.region_code.reindex(s.index);s['type']=dictionary.type.reindex(s.index)
    ids=set(panel.territory_id.unique());assert len(ids)==1896 and ids<=set(s.index)
    assert s.loc[list(ids),'missing_absent'].eq(0).all() and s.loc[list(ids),'invalid'].eq(0).all()
    valid=s.population2023.notna()&s.population2023.gt(0)&s.region.notna()&s.type.notna();v=s.loc[valid].copy()
    rho=float(spearmanr(np.log(v.population2023),v.absent_fraction).statistic)
    rng=np.random.default_rng(20261007);groups=[g for _,g in v.groupby('region')];boots=[]
    for _ in range(2000):
        b=pd.concat([groups[j] for j in rng.integers(0,len(groups),len(groups))]);boots.append(float(spearmanr(np.log(b.population2023),b.absent_fraction).statistic))
    v['quintile']=pd.qcut(v.population2023,5,labels=False,duplicates='raise')+1
    quintiles=[{'quintile':int(q),'n':len(g),'population_min':float(g.population2023.min()),'population_max':float(g.population2023.max()),'n_with_absent_cells':int(g.missing_absent.gt(0).sum()),'municipal_fraction_with_absent_cells':float(g.missing_absent.gt(0).mean()),'absent_cell_fraction':float(g.missing_absent.sum()/(144*len(g)))} for q,g in v.groupby('quintile')]
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'M6_MISSINGNESS_SIZE_DESCRIPTIVE_AUDIT','scientific_pass':False,'source_municipalities':len(s),'source_rows':len(raw),'expected_cells_among_source_municipalities':144*len(s),'absent_cells':int(s.missing_absent.sum()),'absent_cell_fraction':float(s.missing_absent.sum()/(144*len(s))),'municipalities_with_absent_cells':int(s.missing_absent.gt(0).sum()),'municipalities_complete_present':int(s.missing_absent.eq(0).sum()),'invalid_present_cells':int(s.invalid.sum()),'analysis_population_n':len(v),'excluded_population_or_dictionary':int((~valid).sum()),'regions':len(groups),'spearman_log_population_absent_fraction':rho,'descriptive_region_block_ci95':np.nanquantile(boots,[.025,.975]).tolist(),'quintiles':quintiles,'panel_municipalities':1896,'panel_missing_cells':0,'panel_invalid_present_cells':0,'missing_indicator_can_affect_H5_clustering':False,'population_quality':pa,'input_sha256':protocol['input_sha256'],'code_sha256':sha(__file__),'limits':protocol['limits']}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))


def main():
    p=argparse.ArgumentParser()
    for key in ['raw','panel','population','dictionary','protocol','out']:p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())

if __name__=='__main__':main()
