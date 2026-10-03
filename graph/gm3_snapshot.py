#!/usr/bin/env python3
"""Offline evidence graph snapshot: real files, internal keys, unknown as-of.
F7b-reviewed design with independently corrected keys/lineage/time semantics.
This is a local relational graph artifact, NOT a production graph service.
"""
from __future__ import annotations
import argparse,hashlib,json,sqlite3,sys
from datetime import datetime,timezone
from pathlib import Path
import pandas as pd
SCHEMA='''
PRAGMA foreign_keys=ON;
CREATE TABLE dataset_release(id TEXT PRIMARY KEY,publisher TEXT NOT NULL,url TEXT NOT NULL,sha256 TEXT NOT NULL,recorded_at TEXT NOT NULL,retrieved_on TEXT,published_at TEXT,available_at TEXT,license_status TEXT NOT NULL);
CREATE TABLE municipality(tid INTEGER PRIMARY KEY,source_label TEXT,boundary_uncertain INTEGER NOT NULL CHECK(boundary_uncertain=1));
CREATE TABLE administrative_identity(id TEXT PRIMARY KEY,tid INTEGER REFERENCES municipality(tid),system TEXT,code TEXT,year_from INTEGER,year_to INTEGER,source_release_id TEXT REFERENCES dataset_release(id),evidence_status TEXT CHECK(evidence_status='proposed'),interval_semantics TEXT);
CREATE TABLE indicator(id TEXT PRIMARY KEY,description TEXT,unit TEXT,unit_status TEXT);
CREATE TABLE observation(id TEXT PRIMARY KEY,release_id TEXT REFERENCES dataset_release(id),tid INTEGER REFERENCES municipality(tid),indicator_id TEXT REFERENCES indicator(id),period TEXT NOT NULL,dimensions TEXT NOT NULL,value REAL NOT NULL,provenance_class TEXT NOT NULL,available_at TEXT,UNIQUE(release_id,tid,indicator_id,period,dimensions));
CREATE TABLE missing_value(release_id TEXT REFERENCES dataset_release(id),tid INTEGER REFERENCES municipality(tid),indicator_id TEXT REFERENCES indicator(id),period TEXT,dimensions TEXT,reason TEXT);
CREATE TABLE code_presence(release_id TEXT REFERENCES dataset_release(id),code TEXT,effective_date TEXT,source_status TEXT,PRIMARY KEY(release_id,code));
CREATE INDEX obs_tid ON observation(tid);
CREATE VIEW asof_2024 AS SELECT * FROM observation WHERE available_at IS NOT NULL AND available_at<='2024-12-31T23:59:59+00:00' AND provenance_class IN ('observed','source_estimate');
'''
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def oid(*parts):return hashlib.sha256('|'.join(str(x) for x in parts).encode()).hexdigest()
def norm(df,keys):
    if df.groupby(keys,dropna=False).value.nunique(dropna=True).gt(1).any():raise ValueError('conflicting source natural key')
    before=len(df)
    df=df.sort_values('value',na_position='last').drop_duplicates(keys,keep='first')
    return df,before-len(df)
def ingest(c,df,release,indicator,keys,period_fn,dim_fn,provenance):
    df,dup=norm(df,keys);rows=[];missing=[]
    for r in df.itertuples(index=False):
      period=period_fn(r);dims=json.dumps(dim_fn(r),ensure_ascii=False,sort_keys=True,separators=(',',':'))
      tid=int(r.territory_id)
      if pd.isna(r.value):missing.append((release,tid,indicator,period,dims,'source_null'))
      else:rows.append((oid(release,tid,indicator,period,dims),release,tid,indicator,period,dims,float(r.value),provenance,None))
    c.executemany('INSERT INTO observation VALUES(?,?,?,?,?,?,?,?,?)',rows)
    c.executemany('INSERT INTO missing_value VALUES(?,?,?,?,?,?)',missing)
    return {'observations':len(rows),'source_nulls':len(missing),'duplicate_keys_normalized':dup}
def build(root,official,out):
    if out.exists():raise FileExistsError('new run required')
    out.mkdir(parents=True);now=datetime.now(timezone.utc).isoformat()
    files={'dict':root/'raw/sberindex-data-sense-2025/municipal_dictionary.parquet',
      'spend':root/'raw/sberindex-data-sense-2025/8_consumption.parquet',
      'pop':root/'raw/sberindex-data-sense-2025/2_bdmo_population.parquet',
      'jan':official/'data-20240101T1101-structure-20260210T1102.csv',
      'dec':official/'data-20241227T1412-structure-20260210T1102.csv'}
    dictionary=pd.read_parquet(files['dict']);sp=pd.read_parquet(files['spend']);pop=pd.read_parquet(files['pop'])
    pop=pop[(pop.age=='Всего')&pop.gender.isin(['Мужчины','Женщины'])].copy()
    assert not dictionary.territory_id.duplicated().any()
    allids=set(dictionary.territory_id)|set(sp.territory_id)|set(pop.territory_id)
    db=out/'graph.sqlite';c=sqlite3.connect(db);c.executescript(SCHEMA)
    receipts={};hashes={k:sha(p) for k,p in files.items()};releases={k:k+'-'+v[:16] for k,v in hashes.items()}
    cols=pd.read_csv(official/'structure-20260210T1102.csv',sep=';',dtype=str)['field name'].tolist()
    sets={};meta={}
    try:
      with c:
        for k,p in files.items():
          url='https://rosstat.gov.ru/opendata/7708234640-oktmo/'+p.name if k in ['jan','dec'] else ('https://sberindex.ru/ru/research/dataset-borders-and-changes-of-municipalities' if k=='dict' else 'https://disk.yandex.ru/d/WH8yJOogD4UrOg')
          c.execute('INSERT INTO dataset_release VALUES(?,?,?,?,?,?,?,?,?)',(releases[k],'Росстат' if k in ['pop','jan','dec'] else 'СберИндекс',url,hashes[k],now,'2026-10-03' if k in ['jan','dec'] else None,None,None,'internal_analysis_only_distribution_unresolved'))
        names=dictionary.set_index('territory_id')['name'].to_dict()
        c.executemany('INSERT INTO municipality VALUES(?,?,1)',[(int(t),names.get(t)) for t in sorted(allids)])
        c.executemany('INSERT INTO administrative_identity VALUES(?,?,?,?,?,?,?,?,?)',[(oid('dict',r.territory_id),int(r.territory_id),'OKTMO',str(r.oktmo).replace('-',''),int(r.year_from),int(r.year_to),releases['dict'],'proposed','year_to half-open assumption unverified') for r in dictionary.itertuples()])
        c.executemany('INSERT INTO indicator VALUES(?,?,?,?)',[('spending','Source estimate of mean cashless resident spending',None,'unit_unconfirmed'),('population_total_by_sex','Population on 1 January, total ages by sex','people','passport_concept_only')])
        receipts['spend']=ingest(c,sp,releases['spend'],'spending',['territory_id','date','category'],lambda r:str(pd.Period(pd.Timestamp(r.date),freq='M')),lambda r:{'category':r.category},'source_estimate')
        receipts['pop']=ingest(c,pop,releases['pop'],'population_total_by_sex',['territory_id','year','period','age','gender'],lambda r:str(int(r.year))+'-01-01',lambda r:{'age':r.age,'gender':r.gender,'period':r.period},'observed')
        for k in ['jan','dec']:
          f=pd.read_csv(files[k],sep=';',header=None,names=cols,dtype=str,low_memory=False)
          f=f[f.RAZDEL=='1'].copy();f['code']=f.TER+f.KOD1+f.KOD2+f.KOD3
          if f.code.duplicated().any():raise ValueError('duplicate official code')
          effective=pd.to_datetime(f.DateVved,format='%d.%m.%Y',errors='coerce')
          c.executemany('INSERT INTO code_presence VALUES(?,?,?,?)',[(releases[k],r.code,None if pd.isna(e) else e.strftime('%Y-%m-%d'),r.Status) for r,e in zip(f.itertuples(),effective)])
          sets[k]=set(f.code);meta[k]={'section1_codes':len(f),'future_effective_after_2024':int((effective>pd.Timestamp('2024-12-31')).sum())}
      active=dictionary[(dictionary.year_from<=2024)&(2024<dictionary.year_to)].copy();active['code']=active.oktmo.str.replace('-','',regex=False)
      diff=[]
      for r in active.itertuples():diff.append({'territory_id':int(r.territory_id),'code':r.code,'jan_present':r.code in sets['jan'],'dec_present':r.code in sets['dec'],'successor':None})
      queries={
        'counts':"SELECT 'municipality',COUNT(*) FROM municipality UNION ALL SELECT 'release',COUNT(*) FROM dataset_release UNION ALL SELECT 'observation',COUNT(*) FROM observation UNION ALL SELECT 'source_null',COUNT(*) FROM missing_value",
        'orphan_lineage':"SELECT COUNT(*) FROM observation o LEFT JOIN dataset_release r ON o.release_id=r.id LEFT JOIN municipality m ON m.tid=o.tid LEFT JOIN indicator i ON i.id=o.indicator_id WHERE r.id IS NULL OR m.tid IS NULL OR i.id IS NULL",
        'duplicate_version_keys':"SELECT COUNT(*) FROM (SELECT release_id,tid,indicator_id,period,dimensions,COUNT(*) n FROM observation GROUP BY 1,2,3,4,5 HAVING n>1)",
        'asof_2024_eligible':"SELECT COUNT(*) FROM asof_2024",
        'unknown_availability':"SELECT COUNT(*) FROM observation WHERE available_at IS NULL",
        'spend_population_both':"SELECT COUNT(*) FROM (SELECT tid FROM observation WHERE indicator_id='spending' INTERSECT SELECT tid FROM observation WHERE indicator_id='population_total_by_sex')",
        'spend_population_both_2024':"SELECT COUNT(*) FROM (SELECT tid FROM observation WHERE indicator_id='spending' AND period LIKE '2024-%' INTERSECT SELECT tid FROM observation WHERE indicator_id='population_total_by_sex' AND period='2024-01-01')",
        'foreign_key_check':'PRAGMA foreign_key_check'}
      result={k:c.execute(q).fetchall() for k,q in queries.items()}
      assert result['orphan_lineage']==[(0,)] and result['duplicate_version_keys']==[(0,)] and not result['foreign_key_check']
      assert result['asof_2024_eligible']==[(0,)]
      coverage={'active_halfopen_assumption':len(active),'jan_present':sum(r['jan_present'] for r in diff),'dec_present':sum(r['dec_present'] for r in diff),'jan_not_dec':sum(r['jan_present'] and not r['dec_present'] for r in diff),'dec_not_jan':sum(r['dec_present'] and not r['jan_present'] for r in diff),'neither':sum(not r['dec_present'] and not r['jan_present'] for r in diff)}
      c.close()
      report={'recorded_at':now,'status':'local_graph_partial_real_observations','gm3_complete':False,'scientific_pass':False,'production_service_ingestion':False,'schema':'GM3-offline-v1','input_sha256':hashes,'code_sha256':sha(__file__),'db_sha256':sha(db),'receipts':receipts,'queries':result,'query_sql':queries,'dated_code_coverage':coverage,'official_snapshots':meta,'limits':['Internal territory_id is a source key, not verified external legal identity','Presence/absence in dated code release does not prove succession; successor stays null','Published_at/available_at unknown; retrieved_on only from current fetch manifest, never copied into asof','No inferred spending-population derivation edge: independent sources have observation-to-source lineage only','Only total-age male/female observations; no overlapping-age summation','Mobility, wages, employment and migration not yet ingested; GM3 source remains OPEN','Local SQLite proof artifact, not running platform graph/database','Unknown distribution permission; source DB and raw data stay outside Git']}
      (out/'coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
      (out/'dated-diff.json').write_text(json.dumps(diff,ensure_ascii=False,indent=2)+'\n')
      (out/'queries.sql').write_text('\n\n'.join('-- '+k+'\n'+v+';' for k,v in queries.items())+'\n')
      print(json.dumps({'status':report['status'],'receipts':receipts,'queries':result,'dated_code_coverage':coverage},ensure_ascii=False))
    except Exception:
      c.close();raise

def self_check():
    d=pd.DataFrame([{'tid':1,'value':3.},{'tid':1,'value':3.},{'tid':2,'value':None},{'tid':2,'value':4.}]);r,n=norm(d,['tid']);assert n==2 and r.value.sum()==7
    try:norm(pd.DataFrame([{'tid':1,'value':3.},{'tid':1,'value':4.}]),['tid'])
    except ValueError:pass
    else:raise AssertionError('conflict accepted')
    c=sqlite3.connect(':memory:');c.executescript(SCHEMA)
    assert c.execute('SELECT COUNT(*) FROM asof_2024').fetchone()[0]==0
    try:c.execute("INSERT INTO observation VALUES('o','absent',1,'absent','2024','{}',1,'observed',NULL)")
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('orphan accepted')
    assert oid('x',1)==oid('x',1) and oid('x',1)!=oid('y',1)
    print(json.dumps({'self_check':True,'checks':['exact duplicate normalization','source conflict reject','unknown-asof excluded','foreign-key enforcement','stable ID']}))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path);p.add_argument('--official',type=Path);p.add_argument('--out',type=Path);p.add_argument('--self-check',action='store_true');a=p.parse_args()
 if a.self_check:self_check();return
 if not all([a.root,a.official,a.out]):p.error('root/official/out required')
 build(a.root,a.official,a.out)
if __name__=='__main__':main()
