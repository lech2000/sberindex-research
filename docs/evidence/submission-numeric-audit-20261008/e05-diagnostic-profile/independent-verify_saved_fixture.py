import pathlib,json,hashlib,datetime,math
import pyarrow.parquet as pq
R=pathlib.Path('/private/tmp/e05-physical-profile-independent-review-20261008'); O=pathlib.Path('/private/tmp/e05-resource-preflight-fullshape-v1'); C=pathlib.Path('/private/tmp/e05-resource-profile-control-v1'); L=pathlib.Path('/private/tmp/e05-resource-preflight-fullshape-v1-ledger')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
worker=json.loads((L/'terminal.json').read_text()); ct=json.loads((C/'controller-terminal.json').read_text()); post=json.loads((C/'controller-post-IO.json').read_text())
inv=[]
for root in (O,C,L):
 for p in sorted(root.iterdir()):
  assert p.is_file() and not p.is_symlink()
  s=p.stat(); inv.append(dict(root=root.name,name=p.name,bytes=s.st_size,sha256=sha(p),mtime_ns=s.st_mtime_ns))
ps=sorted(O.glob('*.parquet')); js=sorted(O.glob('*.json'))
assert [p.name for p in ps]==[f'IO-FIXTURE-{i:03}.parquet' for i in range(225)]
assert [p.name for p in js]==[f'IO-NATIVE-FIXTURE-{i:04}.json' for i in range(8220)]
assert len(set(sha(p) for p in ps))==1
metadata_rows=0
schema=None
for p in ps:
 pf=pq.ParquetFile(p); assert pf.metadata.num_rows==45504
 metadata_rows+=pf.metadata.num_rows
 if schema is None: schema=str(pf.schema_arrow)
 assert str(pf.schema_arrow)==schema
rows=pq.read_table(ps[0]).to_pylist(); assert len(rows)==45504
assert len({(r['fixture_unit'],r['fixture_month']) for r in rows})==45504
assert {(r['fixture_unit'],r['fixture_month']) for r in rows}=={(i,m) for i in range(1896) for m in range(24)}
assert all(r['label'] is None and r['status']=='RESOURCE_FIXTURE_UNKNOWN_NOT_BANK' for r in rows)
for i,p in enumerate(js): assert json.loads(p.read_text())=={'fixture':True,'slot':i,'state':'NOT_ATTEMPTED','native_call':False}
# The report lists every physical Parquet digest; independently compare exact filename/bytes/hash.
fixture=worker['IO_fixture']; listed={x['file']:x for x in fixture['files']}
assert len(listed)==225
for p in ps:
 x=listed[p.name]; assert x['SHA256']==sha(p) and x['bytes']==p.stat().st_size and x['rows']==45504
assert fixture['status_rows']==metadata_rows==10238400 and fixture['native_receipt_fixture_files']==8220
journals=sorted(L.glob('journal-*.json'))
assert len(journals)==8
native=[]
for p in journals: native.append(json.loads(p.read_text()))
assert ct['ENTRY']==worker['original_anchor']
assert ct['exit']==0 and post['terminal_written'] is True and post['post_IO_gate'] is True
assert ct['cleanup']['worker_reaped'] and ct['cleanup']['known_owned_survivors']==0 and ct['cleanup']['registered_owned_PG_survivors']==0
assert not ct['resource_PASS'] and not worker['resource_PASS'] and not worker['actual_scientific_bank']
assert post['elapsed_through_terminal_fsync']<ct['whole_seconds']==900
assert worker['native_pairs']==2
for d in native:
 if 'residuals' in d: assert all(math.isfinite(v) and v>=0 for v in d['residuals'])
res={'observed_UTC':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fixture_parquet_files':225,'full_metadata_status_rows':metadata_rows,'representative_rows_validated':45504,'all225_bytes_identical':True,'row_validation_method':'One complete Cartesian fixture is read; identical SHA256 proves same bytes for all225. All225 Parquet schemas and rowcount metadata independently read. This is not a reread of scientific bank rows.','native_fixture_files':8220,'native_fixture_calls':0,'actual_native_journal_files':8,'actual_diagnostic_pairs':2,'schema':schema,'physical_owned_bytes':sum(x['bytes'] for x in inv),'controller_terminal':ct,'controller_post_IO':post,'worker_native':native,'worker_stage_results':worker['stages'],'cost_estimate':worker['cost_estimate'],'scientific_bank_false':True,'full_resource_qualification':False}
(R/'PHYSICAL_FILE_INVENTORY.json').write_text(json.dumps(inv,indent=2)+'\n');(R/'CHECK_RESULTS.json').write_text(json.dumps(res,indent=2)+'\n')
print(json.dumps({'PASS':True,'rows':metadata_rows,'files':len(inv),'bytes':res['physical_owned_bytes']}))
