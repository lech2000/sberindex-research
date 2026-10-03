"""Versioned intake of migration and mobility. Unknown semantics stay explicit."""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3, unicodedata
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def normalize(d, keys):
    if d[keys].isna().any().any(): raise ValueError('null source key')
    if not np.isfinite(d.value.dropna().to_numpy(float)).all(): raise ValueError('nonfinite value')
    g = d.groupby(keys, dropna=False, sort=True).value
    if (g.nunique() > 1).any(): raise ValueError('conflicting values for natural key')
    sizes, nonmissing = g.size(), g.count()
    n = g.first().reset_index()  # Prefer an actually observed value; never invent zero.
    return n, {'raw_rows':len(d), 'normalized_rows':len(n),
               'duplicate_rows':len(d)-len(n), 'source_null_rows':int(d.value.isna().sum()),
               'normalized_null_keys':int(n.value.isna().sum()),
               'mixed_null_value_keys':int(((nonmissing>0)&(nonmissing<sizes)).sum()),
               'conflicting_keys':0}

def fullname(s):
    # Preserve municipality type, town qualifier, all words and numbers.
    # Word order/punctuation/case are presentation only; no fuzzy/short-name alias.
    s = unicodedata.normalize('NFKC', str(s)).lower().replace('ё','е')
    return ' '.join(sorted(re.findall(r'[а-яa-z0-9]+', s)))

def migration(root, assignments, out, con):
    p=root/'raw/sberindex-data-sense-2025/3_bdmo_migration.parquet'
    d=pd.read_parquet(p); keys=['territory_id','year','period','age','gender']
    if set(d.year)!={2023} or set(d.period)!={'год'}: raise ValueError('unexpected migration period')
    n,q=normalize(d,keys)
    a=pd.read_parquet(assignments).query('month == "2024-12"').copy()
    if a.territory_id.duplicated().any(): raise ValueError('duplicate Atlas key')
    total=n[n.age=='Всего'].copy()
    valid=total.dropna(subset=['value']).groupby('territory_id').gender.nunique()
    cohort=a[['territory_id','label','status']].merge(total,on='territory_id',how='left',validate='one_to_many')
    profiles=[]
    for (label,sex),g in cohort.groupby(['label','gender'],dropna=False):
        v=g.value.dropna()
        profiles.append({'label':int(label),'sex':str(sex),'n_rows':len(g),'n_observed':len(v),
                         'n_null':int(g.value.isna().sum()),'median_raw_signed_value':None if v.empty else float(v.median()),
                         'negative':int(v.lt(0).sum()),'positive':int(v.gt(0).sum()),'zero':int(v.eq(0).sum()),
                         'ambiguous_identity_rows':int(g.status.eq('ambiguous').sum())})
    n.to_parquet(out/'migration-normalized.parquet',index=False)
    for r in n.itertuples(index=False):
        dim=json.dumps({'age':r.age,'gender':r.gender},ensure_ascii=False,sort_keys=True)
        con.execute('INSERT INTO staged_observation VALUES (?,?,?,?,?,?,?,?)',
                    ('migration2023',str(r.territory_id),str(r.year),dim,None if pd.isna(r.value) else float(r.value),None,'concept_unknown',None))
    q.update({'territories':int(n.territory_id.nunique()),'total_age_rows':len(total),
              'total_age_nonnull':int(total.value.notna().sum()),'both_sexes_observed_territories':int(valid.eq(2).sum()),
              'atlas_n':len(a),'atlas_any_source_rows':int(a.territory_id.isin(n.territory_id).sum()),
              'atlas_both_total_sexes':int(a.territory_id.isin(valid[valid.eq(2)].index).sum()),
              'source_sha256':sha(p),'assignments_sha256':sha(assignments),
              'concept':'Миграция, всего (source wording only)','concept_unknown':True,'unit':None,'available_at':None,
              'scientific_predictor_admitted':False,'profiles_internal':profiles,
              'age_bins':sorted(n.age.unique().tolist()),
              'limits':['Exact Rosstat indicator/unit not supplied by original DOCX; signs do not prove net balance',
                        'No age summation: 0-4, 3-5, 5-9 overlap; total-age retained separately by sex',
                        'No zero filling, net flow, turnover, population rate or causal interpretation',
                        'Internal territory key join is not verified legal-boundary successorship']})
    return q

def mobility(root, assignments, out, con, metadata):
    p=root/'raw/sberindex-dashboard-current/mobility-index.parquet'
    dp=root/'raw/sberindex-data-sense-2025/municipal_dictionary.parquet'
    d=pd.read_parquet(p); dic=pd.read_parquet(dp)
    if dic.territory_id.duplicated().any(): raise ValueError('duplicate dictionary territory_id')
    if set(d.unit_measure)!={'км'} or set(d.unit_mult)!={'0'} or set(d.freq)!={'Год'}: raise ValueError('unexpected mobility unit/frequency')
    if d.duplicated(['indicator_id','kpi_id','period']).any(): raise ValueError('duplicate mobility source key')
    if d[['indicator_id','ref_area','period','value']].isna().any().any(): raise ValueError('missing mobility key/value')
    if not np.isfinite(d.value).all() or (d.value<0).any(): raise ValueError('invalid mobility value')
    # A series must never silently change its name across snapshots.
    if d.groupby('indicator_id').ref_area.nunique().max()!=1: raise ValueError('series changed name')
    d['local_date']=pd.to_datetime(d.period,utc=True).dt.tz_convert('Europe/Moscow').dt.strftime('%Y-%m-%d')
    d['year']=pd.to_datetime(d.local_date).dt.year
    source=json.loads(metadata.read_text())
    if source['dataset_id']!='indeks-mobilnosti' or 'Северо-Западному' not in source['name']:raise ValueError('wrong official metadata')
    native=next(x['values'] for x in source['dimensions'] if x['code']=='REF_AREA')
    codes=pd.DataFrame(native)
    if codes.name.duplicated().any() or codes.code.duplicated().any():raise ValueError('ambiguous official source key')
    if not codes.code.str.fullmatch(r'[1-9][0-9]*').all():raise ValueError('noncanonical official code')
    native_lookup={r.name:int(r.code) for r in codes.itertuples(index=False)}
    native_dict={int(r.territory_id):r for r in dic.itertuples(index=False)}
    lookup={}
    for r in dic.itertuples(index=False):
        lookup.setdefault(fullname(r.name),[]).append(r)
    rows=[]
    for r in d.itertuples(index=False):
        candidates=lookup.get(fullname(r.ref_area),[])
        match=candidates[0] if len(candidates)==1 else None
        tid=native_lookup.get(r.ref_area);native_match=native_dict.get(tid)
        same=bool(native_match is not None and fullname(r.ref_area)==fullname(native_match.name))
        temporal=bool(native_match is not None and native_match.year_from<=2024<native_match.year_to)
        rows.append({'indicator_id':r.indicator_id,'source_name':r.ref_area,'source_period':r.period,
                     'local_date':r.local_date,'year':int(r.year),'value':float(r.value),
                     'unit':'km','candidate_tid':None if match is None else int(match.territory_id),
                     'candidate_count':len(candidates),'normalized_fullname':fullname(r.ref_area),'match_status':'unique_fullname_candidate' if match else ('ambiguous' if candidates else 'unmatched'),
                     'candidate_region':None if match is None else match.region_name,
                     'candidate_oktmo':None if match is None else match.oktmo,
                     'native_source_tid':tid,'metadata_mapping_verified':tid is not None,
                     'native_dictionary_name':None if native_match is None else native_match.name,
                     'native_region':None if native_match is None else native_match.region_name,
                     'native_oktmo':None if native_match is None else native_match.oktmo,
                     'fullname_agrees_with_native_code':same,'temporal_eligible_halfopen_assumption':temporal,
                     'analysis_core':same and temporal,'identity_verified':False,'available_at':None})
        dim=json.dumps({'source_name':r.ref_area,'kpi_id':r.kpi_id},ensure_ascii=False,sort_keys=True)
        con.execute('INSERT INTO staged_observation VALUES (?,?,?,?,?,?,?,?)',
                    ('mobility',r.indicator_id,r.local_date,dim,float(r.value),'km','identity_candidate',None))
    joined=pd.DataFrame(rows); joined.to_parquet(out/'mobility-candidates.parquet',index=False)
    a=pd.read_parquet(assignments).query('month == "2024-12"')
    if not joined.metadata_mapping_verified.all():raise ValueError('raw name absent from official REF_AREA dictionary')
    old=joined[(joined.year==2024)&joined.analysis_core].copy()
    if old.native_source_tid.duplicated().any(): raise ValueError('multiple source series have same territory')
    cohort=a.merge(old,left_on='territory_id',right_on='native_source_tid',how='inner',validate='one_to_one')
    profiles=[]
    for label,g in cohort.groupby('label'):
        profiles.append({'label':int(label),'n':len(g),'median_km':float(g.value.median()),
                         'ambiguous_atlas_identity':int(g.status.eq('ambiguous').sum())})
    cohort.to_parquet(out/'mobility-atlas-candidate-cohort.parquet',index=False)
    return {'rows':len(d),'series':int(d.indicator_id.nunique()),'unit':'km',
            'local_dates':sorted(d.local_date.unique().tolist()),
            'mapping_2024':joined[joined.year==2024].match_status.value_counts().to_dict(),
            'all_series_mapping':joined.drop_duplicates('indicator_id').match_status.value_counts().to_dict(),
            'atlas_core_cohort_2024':len(cohort),'historically_verified_mapping_count':0,
            'official_native_series_mapped':int(joined.drop_duplicates('indicator_id').metadata_mapping_verified.sum()),
            'native_dictionary_name_agreements':int(joined.drop_duplicates('indicator_id').fullname_agrees_with_native_code.sum()),
            'native_dictionary_name_disagreements':int((~joined.drop_duplicates('indicator_id').fullname_agrees_with_native_code).sum()),
            'native_temporal_core_2024':len(old),'metadata_sha256':sha(metadata),
            'source_definition':source['description'],'metadata_last_update':source['lastUpdate'],
            'profiles_internal':profiles,'source_sha256':sha(p),'dictionary_sha256':sha(dp),
            'limits':['Official REF_AREA native code proves current source series binding, not historical boundary equivalence',
                      'Main cohort requires native code plus unchanged full name/type and half-open dictionary year eligibility (assumption)',
                      'Exact token-preserving full-name unique join alone remains a candidate, not official verified crosswalk',
                      'No short-name/fuzzy/type substitution or inferred successor; unmatched/ambiguous stay separate',
                      '2025 snapshot excluded from 2024 profile analysis; annual frequency does not prove a whole-year mean',
                      'Not OD flows or between-municipality edges; not a historical Radar predictor']}

def self_check():
    d=pd.DataFrame({'k':['a','a','b','c','c'],'value':[2.,2.,np.nan,np.nan,3.]})
    n,q=normalize(d,['k']);assert len(n)==3 and pd.isna(n.loc[n.k=='b','value']).all() and q['mixed_null_value_keys']==1
    for bad in [pd.DataFrame({'k':['a','a'],'value':[2.,3.]}),pd.DataFrame({'k':[None],'value':[2.]}),pd.DataFrame({'k':['a'],'value':[np.inf]})]:
        try:normalize(bad,['k'])
        except ValueError:pass
        else:raise AssertionError('invalid source accepted')
    assert fullname('Выборгский муниципальный район')==fullname('муниципальный район Выборгский')
    assert fullname('Беловский городской округ')!=fullname('Беловский муниципальный район')
    assert fullname('городской округ город Пермь')!=fullname('городской округ Пермь')
    assert pd.Timestamp('2024-12-30T21:00:00Z').tz_convert('Europe/Moscow').strftime('%Y-%m-%d')=='2024-12-31'
    print(json.dumps({'self_check':True,'checks':['duplicates/conflicts/null/value normalization','nonfinite/null key rejection','type and qualifier preservation','Moscow date']}))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path);p.add_argument('--assignments',type=Path);p.add_argument('--metadata',type=Path);p.add_argument('--out',type=Path);p.add_argument('--stage',choices=['migration','mobility']);p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check:self_check();return
    if not all([a.root,a.assignments,a.out,a.stage]):p.error('root/assignments/out/stage required')
    if a.out.exists():raise FileExistsError('new run only')
    a.out.mkdir(parents=True)
    con=sqlite3.connect(a.out/'staged.sqlite');con.execute('CREATE TABLE staged_observation (source TEXT NOT NULL, source_entity TEXT NOT NULL, period TEXT NOT NULL, dimensions TEXT NOT NULL, value REAL, unit TEXT, quality TEXT NOT NULL, available_at TEXT, PRIMARY KEY(source,source_entity,period,dimensions))')
    if a.stage=='mobility' and not a.metadata:p.error('official metadata required for mobility')
    r=migration(a.root,a.assignments,a.out,con) if a.stage=='migration' else mobility(a.root,a.assignments,a.out,con,a.metadata)
    con.commit();r.update({'checked_at':datetime.now(timezone.utc).isoformat(),'code_sha256':sha(__file__),
                          'local_staged_rows':con.execute('SELECT COUNT(*) FROM staged_observation').fetchone()[0],
                          'strict_asof_2024_rows':con.execute("SELECT COUNT(*) FROM staged_observation WHERE available_at <= '2024-12-31'").fetchone()[0],
                          'scientific_pass':False,'production_ingested':False})
    con.close();r['staging_sha256']=sha(a.out/'staged.sqlite')
    (a.out/'metrics.json').write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
