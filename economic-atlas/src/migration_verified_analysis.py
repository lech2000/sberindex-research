"""Confirm observed migration cells against a specific public Rosstat/Tochno indicator."""
from __future__ import annotations
import argparse,hashlib,json,re
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
import pandas as pd
from supplementary_audit import normalize

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def oktmo(s):
    s=str(s).strip().replace('-','')
    if not re.fullmatch(r'[0-9]{8}([0-9]{3})?',s):raise ValueError('invalid OKTMO form')
    return s+'000' if len(s)==8 else s

def run(root,reference,normalized,assignments,panel,out):
    columns=['indicator_code','indicator_name','migr','grup_2','vozr','oktmo','oktmo_stable','oktmo_history','year','indicator_value','indicator_unit','indicator_period','mun_level']
    ref=pd.read_parquet(reference,columns=columns,filters=[('migr','==','Миграция — всего'),('mun_level','==','Муниципальное образование верхнего уровня')])
    if set(ref.indicator_code)!={'Y48112023'} or set(ref.indicator_unit)!={'Человек'} or set(ref.year)!={2023}:raise ValueError('wrong reference code/unit/year')
    if set(ref.indicator_period)!={'Значение показателя за год'}:raise ValueError('wrong reference period')
    ref=ref[ref.grup_2.isin(['Мужчины','Женщины'])].copy();ref['code']=ref.oktmo.map(oktmo);ref['gender']=ref.grup_2;ref['age']=ref.vozr.str.replace('‒','-',regex=False)
    key=['code','year','age','gender']
    if ref.duplicated(key).any():raise ValueError('duplicate reference natural key')
    dicpath=root/'raw/sberindex-data-sense-2025/municipal_dictionary.parquet';dic=pd.read_parquet(dicpath)
    if dic.territory_id.duplicated().any():raise ValueError('duplicate source territory ID')
    dic['code']=dic.oktmo.map(oktmo);dic['code_globally_unique']=~dic.code.duplicated(keep=False)
    dic['dictionary_time_core']=dic.year_from.le(2023)&dic.year_to.eq(9999)
    m=pd.read_parquet(normalized)
    if m.duplicated(['territory_id','year','period','age','gender']).any():raise ValueError('normalized source keys not unique')
    m=m.merge(dic[['territory_id','code','code_globally_unique','dictionary_time_core','region_name']],on='territory_id',validate='many_to_one')
    merged=m.merge(ref[key+['indicator_value','oktmo_history','oktmo_stable']],on=key,how='left',validate='many_to_one',indicator=True)
    both=merged.value.notna()&merged.indicator_value.notna();merged['value_verified']=both&merged.value.eq(merged.indicator_value)
    mismatch=both&~merged.value_verified
    # Mismatches, if found, stay excluded; never weaken exact comparison.
    merged['reference_available_at']=None
    merged['concept']=np.where(merged.value_verified,'net_migration_total','concept_unknown')
    merged['unit']=np.where(merged.value_verified,'person',None)
    total=merged[merged.age.eq('Всего')&merged.gender.isin(['Мужчины','Женщины'])].copy()
    counts=total.groupby('territory_id').agg(verified=('value_verified','sum'),
           unchanged=('oktmo_history',lambda x:int(x.eq('Без изменений').sum())),
           globally_unique=('code_globally_unique','all'),time_core=('dictionary_time_core','all'))
    core_ids=counts.index[(counts.verified==2)&(counts.unchanged==2)&counts.globally_unique&counts.time_core]
    core=total[total.territory_id.isin(core_ids)].groupby('territory_id').agg(net_migration_2023=('value','sum'),region_name=('region_name','first'))
    poppath=root/'raw/sberindex-data-sense-2025/2_bdmo_population.parquet';pop=pd.read_parquet(poppath)
    pop=pop[pop.year.eq(2023)&pop.age.eq('Всего')&pop.gender.isin(['Мужчины','Женщины'])].copy()
    pop,pop_audit=normalize(pop,['territory_id','year','period','age','gender'])
    pop=pop.dropna(subset=['value']);pc=pop.groupby('territory_id').agg(nsex=('gender','nunique'),start_population=('value','sum'));pc=pc[pc.nsex.eq(2)&pc.start_population.gt(0)]
    a=pd.read_parquet(assignments).query('month == "2024-12"')
    if a.territory_id.duplicated().any():raise ValueError('duplicate Atlas assignment')
    cohort=a.merge(core,left_on='territory_id',right_index=True,how='inner',validate='one_to_one').merge(pc[['start_population']],left_on='territory_id',right_index=True,how='inner',validate='one_to_one')
    cohort['net_per_1000_start_population']=cohort.net_migration_2023/cohort.start_population*1000
    # Defined descriptive exposure, NOT official coefficient using annual mean population.
    spending=pd.read_parquet(panel);sp=spending[spending.category.eq('Все категории')].copy();sp['year']=pd.to_datetime(sp.date).dt.year
    if sp.duplicated(['territory_id','date']).any():raise ValueError('duplicate total spending source key')
    g=sp.groupby(['territory_id','year']).value.agg(['mean','count'])
    if not g['count'].eq(12).all():raise ValueError('frozen spending annual means require twelve months')
    annual=g['mean'].unstack('year');annual['spending_growth_log']=np.log(annual[2024]/annual[2023]);cohort=cohort.merge(annual[['spending_growth_log']],left_on='territory_id',right_index=True,validate='one_to_one')
    if not np.isfinite(cohort[['net_migration_2023','start_population','net_per_1000_start_population','spending_growth_log']]).all().all():raise ValueError('nonfinite derived descriptive measure')
    profiles=[]
    for label,v in cohort.groupby('label'):
        profiles.append({'december_partition_label':int(label),'n':len(v),'ambiguous_identity':int(v.status.eq('ambiguous').sum()),
                         'median_net_count':float(v.net_migration_2023.median()),
                         'median_net_per_1000_start_population':float(v.net_per_1000_start_population.median()),
                         'net_positive_share':float(v.net_migration_2023.gt(0).mean()),
                         'median_spending_growth_log':float(v.spending_growth_log.median())})
    # Correlation is exploratory on an explicitly restricted cohort; no p-value/causal interpretation.
    rank_corr=cohort[['net_per_1000_start_population','spending_growth_log']].rank().corr().iloc[0,1]
    merged.to_parquet(out/'migration-reference-comparison.parquet',index=False);cohort.to_parquet(out/'atlas-verified-core.parquet',index=False)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'verified_subset_descriptive_integration',
      'reference_indicator_code':'Y48112023','rosstat_indicator_number':'8112023','reference_indicator_name':'Миграционный прирост (убыль)',
      'reference_flow':'Миграция — всего','unit':'person','year':2023,'source_unique_rows':len(m),
      'n_reference_comparable_nonmissing_cells':int(both.sum()),'n_exact_value_verified_cells':int(merged.value_verified.sum()),
      'n_value_mismatches':int(mismatch.sum()),'n_total_age_exact_verified_cells':int(total.value_verified.sum()),
      'n_source_nonmissing_without_exact_reference':int((merged.value.notna()&~merged.value_verified).sum()),
      'n_raw_same_code_duplicate_dictionary_rows':int((~dic.code_globally_unique).sum()),
      'n_both_total_sexes_verified_territories':int(counts.verified.eq(2).sum()),
      'n_strict_reference_core_territories':len(core),'n_atlas_both_sexes_verified':int(a.territory_id.isin(counts.index[counts.verified.eq(2)]).sum()),
      'n_atlas_strict_core_with_population':len(cohort),'n_atlas_excluded':len(a)-len(cohort),
      'region_counts':cohort.region_name.value_counts().to_dict(),'profiles_internal':profiles,
      'spearman_net_startpop_vs_spending_growth_exploratory':float(rank_corr),
      'population_normalization_audit':pop_audit,'historical_asof_verified':False,'strict_asof_predictor_admitted':False,
      'scientific_pass':False,'production_ingested':False,
      'sha256':{'reference':sha(reference),'normalized_source':sha(normalized),'dictionary':sha(dicpath),'population':sha(poppath),'assignments':sha(assignments),'panel':sha(panel),'code':sha(__file__)},
      'limits':['Only exact-code/year/age/sex/nonmissing value matches receive confirmed concept/unit; other cells remain quarantined',
                'Source native code duplicates (55 dictionary rows) excluded from strict core, not collapsed by name/value',
                'Core requires reference history Без изменений and dictionary year_from<=2023/year_to9999; still no independent legal-boundary proof',
                'Male+female annual total-age net counts summed only after both values individually verified; no other age summation',
                'Ratio uses January1 2023 start population, not annual mean and not official migration coefficient',
                'Already viewed fixed December2024 partition; ambiguous identities explicit, no stable economic-type claim',
                'Spending means are resident cashless spending, not local business turnover; no p-value/regression/causality',
                'Tochno2025 release and metadata cannot serve as verified 2023 historical available_at; no Radar backdating',
                'Both data sources ultimately derive from Rosstat; matching verifies semantics/provenance, not independent measurement replication']}
    (out/'metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return result

def self_check():
    assert oktmo('79-701-000-000')==oktmo('79701000')=='79701000000'
    assert oktmo('40908000')!=oktmo('40908000001')
    for bad in ['123','12345678.0','123456789012']:
        try:oktmo(bad)
        except ValueError:pass
        else:raise AssertionError('invalid code accepted')
    # Verified sex totals can be negative. Missing counterpart never becomes zero.
    d=pd.DataFrame({'tid':[1,1,2,2],'gender':['m','f','m','f'],'value':[10.,-3.,5.,np.nan]})
    good=d.groupby('tid').value.count().eq(2);assert d[d.tid.isin(good[good].index)].value.sum()==7.
    print(json.dumps({'self_check':True,'checks':['8/11-digit OKTMO equivalence without decimal/fuzzy aliases','distinct lower-level code preserved','signed sex totals and missing counterpart']}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path);p.add_argument('--reference',type=Path);p.add_argument('--normalized',type=Path);p.add_argument('--assignments',type=Path);p.add_argument('--panel',type=Path);p.add_argument('--out',type=Path);p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check:self_check();return
    if not all([a.root,a.reference,a.normalized,a.assignments,a.panel,a.out]):p.error('all data paths/out required')
    if a.out.exists():raise FileExistsError('new run only')
    a.out.mkdir(parents=True);r=run(a.root,a.reference,a.normalized,a.assignments,a.panel,a.out)
    print(json.dumps({k:v for k,v in r.items() if k not in ['region_counts','sha256','limits','profiles_internal']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
