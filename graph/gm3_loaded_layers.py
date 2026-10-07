"""Offline immutable-copy loader. No network or name joins; pandas required."""
import argparse, collections, datetime, hashlib, json, pathlib, sqlite3
import pandas as pd

PERIODS={'Январь-март':'03-31','Январь-июнь':'06-30','Январь-сентябрь':'09-30','Январь-декабрь':'12-31','Год':'12-31','год':'12-31','Значение показателя за год':'12-31'}
UPPER='Муниципальное образование верхнего уровня'
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def js(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),default=str)
def period(year,label):
 if label not in PERIODS: return None
 return f'{int(year)}-01-01/{int(year)}-{PERIODS[label]}'
def exact8(code):
 s=str(code).replace('-','')
 return s[:8] if len(s)==11 and s.endswith('000') and s.isdigit() else None

def run(inventory,out):
 inv=json.loads(pathlib.Path(inventory).read_text()); sources={s['name']:s for s in inv['sources']}
 for s in sources.values():
  if sha(s['path'])!=s['sha256']:raise ValueError('Source hash changed: '+s['name'])
 out=pathlib.Path(out);out.mkdir(mode=0o700,exist_ok=False)
 base=sqlite3.connect('file:'+sources['base_graph']['path']+'?mode=ro',uri=True)
 c=sqlite3.connect(out/'graph.sqlite');base.backup(c);base.close();c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA cache_size=-262144');c.execute('PRAGMA synchronous=NORMAL')
 c.executescript('''CREATE TABLE loaded_release(release_id TEXT PRIMARY KEY REFERENCES dataset_release(id),native_version TEXT,source_sha TEXT NOT NULL,metadata_json TEXT NOT NULL);
 CREATE TABLE loaded_cell(observation_id TEXT PRIMARY KEY REFERENCES observation(id),source_row_key TEXT NOT NULL,source_sha TEXT NOT NULL,native_code TEXT,period_start TEXT,period_end TEXT,binding_basis TEXT NOT NULL,historical_boundary_verified INTEGER NOT NULL CHECK(historical_boundary_verified=0));
 CREATE TABLE loaded_quarantine(release_id TEXT NOT NULL,source_row INTEGER NOT NULL,reason TEXT NOT NULL,source_key TEXT NOT NULL,value_literal TEXT);
 DROP VIEW asof_2024;
 CREATE VIEW asof_2024 AS SELECT * FROM observation WHERE available_at IS NOT NULL AND julianday(available_at)<=julianday('2024-12-31T23:59:59+00:00') AND provenance_class IN ('observed','source_estimate');''')
 identities=c.execute('select tid,code,year_from,year_to from administrative_identity where system="OKTMO"').fetchall()
 groups=collections.defaultdict(list)
 for tid,code,start,end in identities:
  k=exact8(code)
  if k:groups[k].append((tid,code,start,end))
 exact={k:v[0] for k,v in groups.items() if len(v)==1}
 tids={tid:(code,start,end) for tid,code,start,end in identities}
 counts={}; now=datetime.datetime.now(datetime.timezone.utc).isoformat()
 manifest=json.loads(pathlib.Path(sources['tochno_manifest']['path']).read_text())
 receipt=json.loads(pathlib.Path(sources['v20260928_receipt']['path']).read_text())
 def release(name,url,publisher,version,metadata):
  s=sources[name]; rid='loaded-'+s['sha256'][:24]
  c.execute('insert into dataset_release values(?,?,?,?,?,?,?,?,?)',(rid,publisher,url,s['sha256'],now,None,None,None,'internal_analysis_only_distribution_unresolved'))
  c.execute('insert into loaded_release values(?,?,?,?)',(rid,version,s['sha256'],js(metadata)))
  return rid
 def load(name,df,rid,indicator,unit,description,provenance,rows):
  existing=c.execute('select description,unit from indicator where id=?',(indicator,)).fetchone()
  if existing and existing!=(description,unit):raise ValueError('Indicator meaning changed: '+indicator)
  if not existing:c.execute('insert into indicator values(?,?,?,?)',(indicator,description,unit,'source_explicit'))
  stats=collections.Counter(); pending=[]; keys=collections.defaultdict(list)
  for n,r in enumerate(rows):
   tid,per,dims,value,reason,native,key=r
   if reason:
    c.execute('insert into loaded_quarantine values(?,?,?,?,?)',(rid,n,reason,js(key),None if pd.isna(value) else str(value)));stats['quarantined:'+reason]+=1;continue
   keys[(tid,per,js(dims))].append((n,value,native,key))
  for (tid,per,dims),vals in keys.items():
   signatures={None if pd.isna(v) else float(v) for _,v,_,_ in vals}
   if len(signatures)>1:
    for n,v,native,key in vals:c.execute('insert into loaded_quarantine values(?,?,?,?,?)',(rid,n,'duplicate_conflict',js(key),None if pd.isna(v) else str(v)))
    stats['quarantined:duplicate_conflict']+=len(vals);continue
   stats['exact_duplicates_collapsed']+=len(vals)-1
   n,value,native,key=vals[0]
   if pd.isna(value):
    c.execute('insert into missing_value values(?,?,?,?,?,?)',(rid,tid,indicator,per,dims,'explicit_source_null'));stats['missing']+=1;continue
   oid=hashlib.sha256(js([rid,tid,indicator,per,dims]).encode()).hexdigest()
   c.execute('insert into observation values(?,?,?,?,?,?,?,?,?)',(oid,rid,tid,indicator,per,dims,float(value),provenance,None))
   start,end=(per.split('/') if '/' in per else (per,per))
   c.execute('insert into loaded_cell values(?,?,?,?,?,?,?,0)',(oid,js(key),sources[name]['sha256'],native,start,end,'native_exact_id_or_code_unique_stable_dictionary_proposed'))
   stats['loaded']+=1
   if value==0:stats['explicit_zero']+=1
  stats['input_rows']=len(df);counts[name]=dict(stats);c.commit();print(name,dict(stats),flush=True)
 # Economic source observations, both native versions; annual wages distinct concept.
 for name in ['Y48423005','Y48423007','Y48213002','Y48423005_v20260928','Y48423007_v20260928']:
  code=name.split('_')[0]; version='v20260928' if '_v' in name else 'v20250918';df=pd.read_parquet(sources[name]['path'],filters=[('year','in',[2023,2024])])
  source_meta=next(x for x in manifest['datasets'] if x['indicator_code']==code) if version=='v20250918' else next(x for x in receipt if x['indicator']==code)
  url=f'https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_{version}/indicators/section{41 if code=="Y48213002" else 32}/data_{code}_112_{version}.zip'
  rid=release(name,url,'Rosstat BD PMO processed by Tochno',version,{'scope':'2023/2024','source_metadata':source_meta,'available_at':'unknown','expiry':'unknown','key_fields':['indicator_code','indicator_name','indicator_unit','oktmo','region_id','mun_level','okved2','year','indicator_period'],'period_semantics':('annual January-December; one annual period' if code=='Y48213002' else 'cumulative January-to-end; overlapping periods not summed')})
  unit='person' if code=='Y48423005' else 'RUB'; expected='Человек' if unit=='person' else 'Рубль'
  rows=[]
  for r in df.to_dict('records'):
   key={k:r.get(k) for k in ['indicator_code','indicator_name','indicator_unit','oktmo','region_id','mun_level','okved2','year','indicator_period']}
   binding=exact.get(str(r['oktmo'])); per=period(r['year'],r['indicator_period']);reason=None
   if r['indicator_code']!=code or r['indicator_unit']!=expected:reason='concept_or_unit_conflict'
   elif per is None:reason='unsupported_period'
   elif r['mun_level']!=UPPER:reason='municipal_level_outside_upper'
   elif r['oktmo_history']!='Без изменений':reason='historical_code_change_requires_crosswalk'
   elif binding is None:reason='code_missing_or_ambiguous'
   elif binding[3]<=r['year'] or binding[2]>r['year']:reason='dictionary_interval_not_stable_core'
   elif not str(r['oktmo_year_from']).isdigit() or int(r['oktmo_year_from'])>r['year']:reason='source_interval_unknown_or_future'
   elif not str(r['oktmo_year_to']).isdigit() or int(r['oktmo_year_to'])<=r['year']:reason='source_end_year_boundary_ambiguous_or_expired'
   dims={k:key[k] for k in ['indicator_code','indicator_name','indicator_unit','oktmo','region_id','mun_level','okved2','indicator_period']}
   rows.append((binding[0] if binding else None,per,dims,r['indicator_value'],reason,str(r['oktmo']),key))
  # Separate source release populations, never treat salary definitions as revisions.
  iid=code
  load(name,df,rid,iid,unit,str(df.indicator_name.iloc[0]),'source_estimate',rows)
 # Migration: already independently compared exact values with native reference.
 name='migration_verified';df=pd.read_parquet(sources[name]['path']);rid=release(name,'https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20250918/indicators/section31/data_Y48112023_112_v20250918.zip','Rosstat BD PMO + native SberIndex exact-key comparison','v20250918',{'supporting_reference_sha':sources['migration_reference']['sha256'],'available_at':'unknown','expiry':'unknown','age_bands_overlap':'do not sum'})
 rows=[]
 for r in df.to_dict('records'):
  tid=int(r['territory_id']);binding=tids.get(tid);reason=None;key={k:r[k] for k in ['territory_id','code','year','period','age','gender']}
  if r['concept']!='net_migration_total' or r['unit']!='person' or r['year']!=2023 or r['period']!='год':reason='concept_unit_period_conflict'
  elif not r['code_globally_unique'] or not r['dictionary_time_core']:reason='dictionary_ambiguous_or_interval'
  elif not binding or binding[0]!=r['code']:reason='native_code_disagrees'
  elif r['oktmo_history']!='Без изменений':reason='historical_code_change_requires_crosswalk'
  elif pd.isna(r['value']):
   if r['_merge']!='both' or not pd.isna(r['indicator_value']):reason='missing_concept_unverified'
  elif not r['value_verified'] or r['value']!=r['indicator_value']:reason='reference_value_unverified_or_conflict'
  rows.append((tid,'2023-01-01/2023-12-31',{'age':r['age'],'gender':r['gender'],'native_code':r['code']},r['value'],reason,r['code'],key))
 load(name,df,rid,'net_migration_Y48112023','person','Annual net migration; age/sex dimensions; overlapping age bands','observed',rows)
 name='mobility_native_mapping';df=pd.read_parquet(sources[name]['path']);rid=release(name,'https://sberindex.ru/ru/research','SberIndex native REF_AREA metadata',None,{'definition':'distance residents travel when making purchases; not OD flow','available_at':'unknown','expiry':'unknown','scope':'native local snapshot 2024-12-31 only'})
 rows=[]
 for r in df.to_dict('records'):
  tid=int(r['native_source_tid']);binding=tids.get(tid);code=str(r['native_oktmo']).replace('-','');reason=None;key={k:r[k] for k in ['indicator_id','native_source_tid','source_period','local_date']}
  if r['year']!=2024:reason='period_out_of_scope'
  elif r['unit']!='km' or r['local_date']!='2024-12-31':reason='unit_or_snapshot_conflict'
  elif not r['metadata_mapping_verified'] or not binding or binding[0]!=code:reason='native_code_unverified'
  elif not r['fullname_agrees_with_native_code']:reason='native_label_type_conflict'
  elif not r['temporal_eligible_halfopen_assumption'] or binding[1]>2024 or binding[2]<=2024:reason='dictionary_interval_not_stable_core'
  rows.append((tid,r['local_date'],{'native_indicator_id':r['indicator_id'],'source_period_utc':r['source_period'],'period_kind':'local_snapshot'},r['value'],reason,code,key))
 load(name,df,rid,'mobility_purchase_distance_snapshot','km','Native purchase travel distance index; local snapshot, not municipal flows','source_estimate',rows)
 checks={'foreign_key_errors':c.execute('PRAGMA foreign_key_check').fetchall(),'quick_check':c.execute('PRAGMA quick_check').fetchone()[0],'added_observations':c.execute('select count(*) from loaded_cell').fetchone()[0],'new_asof_2024_rows':c.execute('select count(*) from asof_2024 a join loaded_cell l on a.id=l.observation_id').fetchone()[0],'new_synthetic_rows':c.execute("select count(*) from observation o join loaded_cell l on o.id=l.observation_id where provenance_class not in ('observed','source_estimate')").fetchone()[0]}
 c.commit();c.close();checks['base_sha_unchanged']=sha(sources['base_graph']['path'])==sources['base_graph']['sha256'];checks['all_input_sha_unchanged']=all(sha(s['path'])==s['sha256'] for s in sources.values())
 result={'counts':counts,'checks':checks,'limitations':['Source release labels are not historic available_at','All historical boundary identity remains proposed/unverified','No expiry invented','Missing/null not zero; overlapping ages and cumulative quarters not summed'],'graph_sha256':sha(out/'graph.sqlite')}
 (out/'RESULTS.json').write_text(json.dumps(result,indent=2,ensure_ascii=False));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--inventory',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.inventory,a.out)
