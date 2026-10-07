#!/usr/bin/env python3
"""Complete private ID-ledger audit; UNKNOWN successor is retained, never imputed."""
from pathlib import Path
import argparse,collections,datetime,hashlib,json,re
import pandas as pd

COLUMNS=['TER','KOD1','KOD2','KOD3','KC','RAZDEL','NAME1','Centrum','NomDescr','NomAkt','Status','DateUtv','DateVved']
def code11(value):
 c=str(value).replace('-','')
 if not re.fullmatch(r'\d{11}',c):raise ValueError('invalid native OKTMO')
 return c

def ledger(dictionary,panel,official,components):
 if dictionary.territory_id.isna().any() or dictionary.territory_id.duplicated().any():raise ValueError('dictionary ID absent or duplicate')
 if (dictionary.year_to<=dictionary.year_from).any():raise ValueError('invalid dictionary interval')
 if panel.territory_id.isna().any() or panel.date.isna().any():raise ValueError('panel native key missing')
 dictionary=dictionary.copy();dictionary['code11']=dictionary.oktmo.map(code11)
 panel=panel.copy();panel['year']=pd.to_datetime(panel.date).dt.year
 dr={int(r.territory_id):r for r in dictionary.itertuples()}
 contiguous=collections.defaultdict(list)
 for code,g in dictionary.groupby('code11'):
  for old in g.itertuples():
   for new in g.itertuples():
    if old.territory_id!=new.territory_id and old.year_to==new.year_from:
     contiguous[int(old.territory_id)].append({'native_candidate_tid':int(new.territory_id),'code11':code,'transition_year':int(new.year_from),'status':'SUCCESSOR_CANDIDATE_SAME_CODE_CONTIGUOUS_NOT_IDENTITY'})
 def identity(tid):
  r=dr.get(int(tid));c=r.code11 if r else None
  return {'territory_id':int(tid),'source_code11':c,'year_from':int(r.year_from) if r else None,'year_to':int(r.year_to) if r else None,'source_region_code':int(r.region_code) if r and hasattr(r,'region_code') else None,'source_type':str(r.type) if r and hasattr(r,'type') else None,'successor_status':'UNKNOWN_SUCCESSOR','verified_successor_tid':None,'same_code_contiguous_candidates':contiguous.get(int(tid),[]),'code_components':components.get(c,[]),'full_legal_statistical_binding_verified':False,'classifier_membership':{str(y):official[y].get(c) for y in official},'availability':'UNKNOWN','successor_resolution_class':('OFFICIAL_CODE_COMPONENT_ONLY_UNVERIFIED_FOOTPRINT' if any(x['status'].startswith('OFFICIAL') for x in components.get(c,[])) else ('PREFIX_INFERRED_CANDIDATE_ONLY' if components.get(c) else ('EXACT_NATIVE_SAME_CODE_CANDIDATE_ONLY' if contiguous.get(int(tid)) else 'NO_SUCCESSOR_EVIDENCE_FOUND_IN_AUDITED_INPUTS'))),'unknown_successor_reason':('Official/candidate code components lack verified native statistical footprint and successor ID' if components.get(c) else ('Contiguous same-code native IDs do not prove legal succession' if contiguous.get(int(tid)) else 'No exact native successor candidate or official code component in audited inputs'))}
 rows=[];summary=[];dictscope=[]
 for year,g in panel.groupby('year',sort=True):
  sizes=g.groupby('territory_id',dropna=False).size();year=int(year)
  for policy,inclusive in [('half_open',False),('inclusive_end',True)]:
   active=dictionary[(dictionary.year_from<=year)&((dictionary.year_to>=year) if inclusive else(dictionary.year_to>year))]
   active_ids=set(int(x) for x in active.territory_id);collisions={c:sorted(int(x) for x in gg.territory_id) for c,gg in active.groupby('code11') if len(gg)>1}
   counts=collections.Counter();outrows=[]
   for tid,n in sizes.items():
    r=identity(tid);native=dr.get(int(tid));matched=int(tid) in active_ids;conflict=matched and r['source_code11'] in collisions
    if native is None:reason='NO_NATIVE_DICTIONARY_ID'
    elif native.year_from>year:reason='SOURCE_INTERVAL_START_IN_FUTURE'
    elif native.year_to<year:reason='SOURCE_INTERVAL_ENDED_BEFORE_YEAR'
    elif not inclusive and native.year_to==year:reason='SOURCE_INTERVAL_ENDPOINT_UNKNOWN_SEMANTICS'
    else:reason=None
    status='DICTIONARY_CODE_COLLISION' if conflict else ('SOURCE_DICTIONARY_EXACT_ID_PROPOSED' if matched else 'DICTIONARY_INTERVAL_UNMATCHED')
    r.update(year=year,interval_policy=policy,source_rows=int(n),dictionary_interval_matched=matched,binding_status=status,unmatched_reason=reason,conflict_territory_ids=collisions.get(r['source_code11'],[]) if conflict else [],official_code_status=('PRESENT_COMPONENT_ONLY' if r['source_code11'] in official.get(year,{}) else 'ABSENT_IN_DATED_SNAPSHOT_NOT_ASOF_INVALIDITY_PROOF'),verified_current_code11=None)
    rows.append(r);outrows.append(r);counts['panel_ids']+=1;counts['panel_rows']+=int(n);counts['matched_ids']+=int(matched);counts['matched_rows']+=int(n) if matched else 0;counts['unmatched_ids']+=int(not matched);counts['unmatched_rows']+=int(n) if not matched else 0;counts['conflict_ids_within_matched']+=int(conflict);counts['conflict_rows_within_matched']+=int(n) if conflict else 0;counts['matched_nonconflict_ids']+=int(matched and not conflict);counts['official_present_ids_within_matched']+=int(matched and r['source_code11'] in official.get(year,{}));counts['official_absent_ids_within_matched']+=int(matched and r['source_code11'] not in official.get(year,{}))
   assert counts['matched_ids']+counts['unmatched_ids']==counts['panel_ids'];assert counts['matched_rows']+counts['unmatched_rows']==counts['panel_rows'];assert counts['matched_nonconflict_ids']+counts['conflict_ids_within_matched']+counts['unmatched_ids']==counts['panel_ids']
   summary.append({'year':year,'interval_policy':policy,'dictionary_active_rows':len(active),'dictionary_collision_code_count':len(collisions),'dictionary_official_present_count':int(active.code11.isin(official.get(year,{})).sum()),'dictionary_official_absent_count':int((~active.code11.isin(official.get(year,{}))).sum()),'counts':dict(counts),'all_panel_ids_preserved':True,'verified_identity_bindings':0})
   for rr in active.itertuples():dictscope.append(dict(identity(rr.territory_id),year=year,interval_policy=policy,code_collision_ids=collisions.get(rr.code11,[]),official_present=rr.code11 in official.get(year,{})))
 dictionary_coverage=[]
 for year in sorted(official):
  for policy,inclusive in [('half_open',False),('inclusive_end',True)]:
   active=dictionary[(dictionary.year_from<=year)&((dictionary.year_to>=year) if inclusive else(dictionary.year_to>year))]
   collisions=int((active.groupby('code11').territory_id.nunique()>1).sum());present=int(active.code11.isin(official[year]).sum())
   dictionary_coverage.append({'snapshot_year':year,'interval_policy':policy,'active_dictionary_records':len(active),'official_code_present_component_only':present,'official_code_absent_not_asof_invalidity_proof':len(active)-present,'dictionary_code_collision_count':collisions,'full_verified_bindings':0})
 all_dictionary=[identity(tid) for tid in sorted(dr)];finite=[r for r in all_dictionary if r['year_to']<9999]
 expired2024=[r for r in rows if r['year']==2024 and r['interval_policy']=='inclusive_end' and not r['dictionary_interval_matched']]
 half2024=[r for r in rows if r['year']==2024 and r['interval_policy']=='half_open' and not r['dictionary_interval_matched']]
 mismatch2024=[r for r in dictscope if r['year']==2024 and r['interval_policy']=='half_open' and not r['official_present']]
 return {'summary':summary,'dictionary_snapshot_coverage':dictionary_coverage,'active_dictionary_id_year_policy_ledger':dictscope,'panel_id_year_policy_ledger':rows,'all_dictionary_ledger':all_dictionary,'finite_dictionary_ledger':finite,'original_326_scope_ledger':expired2024,'halfopen_unmatched2024_ledger':half2024,'active_dictionary2024_official_missing_ledger':mismatch2024,'dictionary_id_count':len(dr),'panel_unique_id_count':int(panel.territory_id.nunique()),'panel_rows':len(panel),'panel_years':sorted(int(x) for x in panel.year.unique()),'global_panel_ids_not_in_dictionary':sorted(set(int(x) for x in panel.territory_id)-set(dr))}

def run(inventory_path,out):
 inventory=json.loads(Path(inventory_path).read_text());sources={r['name']:r for r in inventory['sources']}
 for r in sources.values():
  if hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()!=r['sha256']:raise ValueError('input SHA changed before read: '+r['name'])
 d=pd.read_parquet(sources['dictionary']['path']);p=pd.read_parquet(sources['spending']['path'],columns=['territory_id','date']);official={}
 for year in [2023,2024,2026]:
  f=pd.read_csv(sources['official'+str(year)]['path'],sep=';',header=None,names=COLUMNS,dtype=str,low_memory=False);f['code11']=f.TER+f.KOD1+f.KOD2+f.KOD3;f=f[f.RAZDEL=='1'];assert not f.code11.duplicated().any();official[year]={row['code11']:{'dataset_source_sha256':sources['official'+str(year)]['sha256'],'native_change_number':row['NomAkt'],'native_status':row['Status'],'native_approved_date':row['DateUtv'],'native_introduction_date':row['DateVved'],'scope':'dated classifier record, not verified whole-year territorial identity/available_at'} for row in f[['code11','NomAkt','Status','DateUtv','DateVved']].fillna('').to_dict('records')}
 components=collections.defaultdict(list)
 for name,status in [('smolensk_pairs','OFFICIAL_FNS_CODE_COMPONENT_EFFECTIVE2025_NOT_IDENTITY'),('sverdlovsk_candidates','PREFIX_INFERRED_CANDIDATE_EFFECTIVE2025_NOT_IDENTITY')]:
  f=pd.read_csv(sources[name]['path'],dtype=str)
  for r in f.to_dict('records'):components[r['old_oktmo11']].append({'successor_code11':r['new_oktmo11'],'native_valid_from':r['valid_from'],'status':status,'pair_ledger_sha256':sources[name]['sha256'],'source_url':r.get('source_url',r.get('source_recode_url')),'not_applied_as2024_binding':True})
 for r in json.loads(Path(sources['kurgan_components']['path']).read_text())['rows']:
  components[r['legacy_dictionary_OKTMO11']].append({'successor_code11':r['successor_OKTMO8_confirmed_tax2024']+'000','status':'OFFICIAL_CODE_LINEAGE_COMPONENT_TAX2024_NOT_GEOMETRIC_IDENTITY','pair_ledger_sha256':sources['kurgan_components']['sha256'],'successor_tid':None,'full_crosswalk_accepted':False})
 result=ledger(d,p,official,components)
 jan=pd.read_csv(sources['official2024_jan']['path'],sep=';',header=None,names=COLUMNS,dtype=str,low_memory=False);jan['code11']=jan.TER+jan.KOD1+jan.KOD2+jan.KOD3;jan=jan[jan.RAZDEL=='1'];assert not jan.code11.duplicated().any()
 january={row['code11']:{'snapshot_date':'2024-01-01','dataset_source_sha256':sources['official2024_jan']['sha256'],'native_change_number':row['NomAkt'],'native_status':row['Status'],'native_approved_date':row['DateUtv'],'native_introduction_date':row['DateVved'],'scope':'dated classifier membership, not verified native statistical footprint/continuous validity'} for row in jan[['code11','NomAkt','Status','DateUtv','DateVved']].fillna('').to_dict('records')}
 for name,data in result.items():
  if name.endswith('_ledger'):
   for r in data:r['classifier_membership']['2024-01-01']=january.get(r['source_code11'])
 result['original326_official_snapshot_comparison']={'scope_ids':len(result['original_326_scope_ledger']),'present_jan2024':sum(r['source_code11'] in january for r in result['original_326_scope_ledger']),'present_dec2024':sum(r['source_code11'] in official[2024] for r in result['original_326_scope_ledger']),'only_jan':sum(r['source_code11'] in january and r['source_code11'] not in official[2024] for r in result['original_326_scope_ledger']),'both':sum(r['source_code11'] in january and r['source_code11'] in official[2024] for r in result['original_326_scope_ledger']),'neither':sum(r['source_code11'] not in january and r['source_code11'] not in official[2024] for r in result['original_326_scope_ledger']),'note':'Source-dictionary expiry is not legal expiry; snapshot27December already includes2025-effective changes. No numeric reassignment.'}
 result['active_halfopen_dictionary2024_january_code_coverage']={'records':int(((d.year_from<=2024)&(d.year_to>2024)).sum()),'present':sum(code11(r.oktmo) in january for r in d[(d.year_from<=2024)&(d.year_to>2024)].itertuples()),'absent':sum(code11(r.oktmo) not in january for r in d[(d.year_from<=2024)&(d.year_to>2024)].itertuples())}
 out=Path(out);out.mkdir(exist_ok=True)
 summary={k:v for k,v in result.items() if not k.endswith('_ledger')};summary.update(status='NATIONWIDE_COMPLETE_UNKNOWN_AWARE_AUDIT_NOT_HISTORICAL_IDENTITY_PASS',recorded_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),interval_semantics='UNKNOWN; both alternatives reported',original326_records_classified=len(result['original_326_scope_ledger']),halfopen2024_records_classified=len(result['halfopen_unmatched2024_ledger']),allfinite_records_classified=len(result['finite_dictionary_ledger']),active2024_official_missing_records_classified=len(result['active_dictionary2024_official_missing_ledger']),global_full_verified_identity_count=0,no_names_joined=True,no_source_values_reassigned_or_zero_imputed=True,successor_outcome_counts={name:dict(collections.Counter(r['successor_status'] for r in result[name])) for name in ['finite_dictionary_ledger','original_326_scope_ledger','active_dictionary2024_official_missing_ledger']},successor_resolution_classes={name:dict(collections.Counter(r['successor_resolution_class'] for r in result[name])) for name in ['finite_dictionary_ledger','original_326_scope_ledger','active_dictionary2024_official_missing_ledger']},caveat='Snapshot membership does not imply validity for entire reference year;2025codecomponents remainfuture. NativeIDand sourcecode retained even where interval/officialevidence ambiguous.')
 for key,data in result.items():
  if key.endswith('_ledger'):(out/(key+'.json')).write_text(json.dumps(data,ensure_ascii=False,indent=2))
 (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));receipt=[]
 for r in sources.values():receipt.append({'name':r['name'],'sha256_unchanged':hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256']})
 assert all(x['sha256_unchanged'] for x in receipt);(out/'SOURCE_IMMUTABILITY_RECEIPT.json').write_text(json.dumps(receipt,indent=2));return summary

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--inventory',required=True);a.add_argument('--out',required=True);x=a.parse_args();print(json.dumps(run(x.inventory,x.out),ensure_ascii=False,indent=2))
