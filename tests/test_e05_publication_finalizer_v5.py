"""Stdlib schema/mock fixtures only: no actual science, Parquet or process IO."""
import pathlib,sys,os,json,hashlib,tempfile,unittest,time,types
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'economic-atlas/src'))
import e05_full_publication_finalizer_v5 as f
import e05_full_publication_validator_v5 as v
from e05_full_receipt_adapter_v5 import nominal_registry
PROTOCOL_BYTES=pathlib.Path(os.environ.get('E05_REPAIRED_PROTOCOL', str(pathlib.Path(__file__).parents[1]/'economic-atlas/protocols/E05_FULL_REMAINING_V2.json'))).read_bytes();PROTOCOL=json.loads(PROTOCOL_BYTES)
class Guard:
 source_only_mock=True
 def __init__(self):self.anchor=time.monotonic();self.whole_seconds=120;self.finalization_reserve_seconds=60;self.source_binding=dict(protocol_SHA=v.PROTOCOL_SHA,method_SHA=v.METHOD_SHA,source_ACK_SHA=v.SOURCE_ACK_SHA);self.calls=0
 def __call__(self):
  self.calls+=1
  if time.monotonic()-self.anchor>=self.whole_seconds:raise InterruptedError('same original whole allowance')
def mock(fn):fn.source_only_mock=True;return fn
def registry():return [dict(key=i,cell=c,status='NOT_ATTEMPTED_RESOURCE_STOP',protocol_SHA=v.PROTOCOL_SHA,method_SHA=v.METHOD_SHA) for i,c in enumerate(v.planned(PROTOCOL))]
def coverage(rec):return {r['key']:{'rows':45504,'computed_per_month':{m:1896 if r['status']=='COMPUTED' and v.available(r['cell'],t) else 0 for t,m in enumerate(PROTOCOL['months'])}} for r in rec}
def pairs(rec):return f.make_pairings(PROTOCOL,rec,coverage(rec),[])
class Finalizer(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.tmp.name)
 def tearDown(self):self.tmp.cleanup()
 def test_every_execute_refuses(self):
  for module in (f,v):
   with self.assertRaisesRegex(RuntimeError,'NOT_EXECUTABLE'):module.execute()
 def test_scope_full_registry(self):
  cells,native=nominal_registry(PROTOCOL);self.assertEqual(len(cells),225);self.assertEqual(len(native),8220);self.assertEqual(v.nominal_calls(PROTOCOL),4110)
 def test_materializer_all225_full_cardinality(self):
  rec=registry();count=0
  for r in rec:
   rows=f.StatusRows(range(20000,21896) if r['cell']['kind']=='real' else range(1896),PROTOCOL['months'],f.NONCOMPUTED[r['status']]);count+=len(rows);first=next(iter(rows));self.assertIsNone(first['label']);self.assertEqual(first['status'],'NOT_ATTEMPTED_RESOURCE_STOP')
  self.assertEqual(count,10238400)
 def test_streamed_full45504_exact_schema(self):
  c={'kind':'control','K':2};report=v.row_universe(f.StatusRows(range(1896),PROTOCOL['months'],'UNKNOWN_NATIVE_RESPONSE'),list(range(1896)),PROTOCOL['months'],2,c,'UNKNOWN_NATIVE_RESPONSE');self.assertEqual(report['rows'],45504)
 def test_streamed_missing45504th_rejected(self):
  import itertools
  with self.assertRaises(ValueError):v.row_universe(itertools.islice(f.StatusRows(range(1896),PROTOCOL['months'],'UNKNOWN_NATIVE_RESPONSE'),45503),list(range(1896)),PROTOCOL['months'],2,{'kind':'control'},'UNKNOWN_NATIVE_RESPONSE')
 def test_streamed_duplicate_rejected(self):
  rows=f.StatusRows(range(1896),PROTOCOL['months'],'NOT_ATTEMPTED_RESOURCE_STOP');first=next(iter(rows))
  import itertools
  with self.assertRaises(ValueError):v.row_universe(itertools.chain(rows,[first]),list(range(1896)),PROTOCOL['months'],2,{'kind':'control'},'NOT_ATTEMPTED_RESOURCE_STOP')
 def test_materializer_unknown_not_zero(self):self.assertTrue(all(r['label'] is None for r in f.StatusRows(range(1896),PROTOCOL['months'],'UNKNOWN_NATIVE_RESPONSE')))
 def test_materializer_unknown_cannot_computed(self):
  with self.assertRaises(ValueError):f.StatusRows(range(1896),PROTOCOL['months'],'COMPUTED')
 def test_materializer_rejects_ID_shrink(self):
  with self.assertRaises(ValueError):f.StatusRows(range(1895),PROTOCOL['months'],'NOT_ATTEMPTED_RESOURCE_STOP')
 def test_all180_unavailable_preserved(self):
  rec=registry();self.assertEqual(v.validate_pairing(PROTOCOL,rec,pairs(rec),coverage(rec)),180)
 def test_computed_arm_failed_baseline_honest_unavailable(self):
  rec=registry();rec[0]['status']='INCONCLUSIVE';rec[10]['status']='COMPUTED';pp=pairs(rec);row=pp[10]
  self.assertEqual(row['status'],'UNAVAILABLE');self.assertEqual(row['denominators']['arm_available_keys'],45504);self.assertEqual(row['denominators']['paired_available'],0);self.assertEqual(v.validate_pairing(PROTOCOL,rec,pp,coverage(rec)),180)
 def test_computed_arm_unknown_baseline_honest_unavailable(self):
  rec=registry();rec[0]['status']='UNKNOWN_NATIVE_RESPONSE';rec[10]['status']='COMPUTED';self.assertEqual(v.validate_pairing(PROTOCOL,rec,pairs(rec),coverage(rec)),180)
 def test_unavailable_for_successful_baseline_rejected(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';pp=pairs(rec);pp[10]['status']='UNAVAILABLE'
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,pp,coverage(rec))
 def test_unavailable_cannot_fabricate_metric(self):
  rec=registry();pp=pairs(rec);pp[10]['agreement'][0]['ARI_vs_sameKseed_shares']=1.
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,pp,coverage(rec))
 def test_empty_pairing_cannot_hide_computed_or_failed_arm(self):
  rec=registry()
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,[],coverage(rec))
 def test_baseline_binding_exact_seed(self):
  rec=registry();pp=pairs(rec);pp[10]['baseline_cell']=rec[1]['cell']
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,pp,coverage(rec))
 def test_shared_denominator_requires_actual_coverage(self):
  rec=registry();rec[0]['status']='COMPUTED';cov=coverage(rec);cov[0]['computed_per_month'][PROTOCOL['months'][0]]=1895
  with self.assertRaises(ValueError):v.pairing_schema(PROTOCOL,rec,cov)
 def test_actual_shared_keys_growth_mom(self):
  rec=registry();rec[0]['status']=rec[40]['status']='COMPUTED';pp=pairs(rec);self.assertEqual(pp[40]['denominators']['paired_available'],43608);self.assertEqual(pp[40]['denominators']['unpaired'],1896);v.validate_pairing(PROTOCOL,rec,pp,coverage(rec))
 def test_all_unattempted_reconcile(self):
  rec,native,inv,docs=f.reconcile(PROTOCOL,[]);self.assertEqual(len(rec),225);self.assertEqual(len(native),8220);self.assertEqual(inv,{})
 def cell_start(self,key=0):
  doc={'key':'cell/'+str(key),'monotonic':1.,'request':{'key':key,'state':'STARTED','cell':v.planned(PROTOCOL)[key]}};raw=json.dumps(doc).encode();name='journals/'+hashlib.sha256(doc['key'].encode()).hexdigest()+'.STARTED.json';return name,raw
 def test_started_unknown_preserved(self):
  rec,native,inv,docs=f.reconcile(PROTOCOL,[self.cell_start()]);self.assertEqual(rec[0]['status'],'UNKNOWN_NATIVE_RESPONSE');self.assertEqual(rec[1]['status'],'NOT_ATTEMPTED_RESOURCE_STOP')
 def test_duplicate_journal_rejected(self):
  with self.assertRaises(ValueError):f.reconcile(PROTOCOL,[self.cell_start(),self.cell_start()])
 def test_changed_cellseed_rejected(self):
  name,raw=self.cell_start();doc=json.loads(raw);doc['request']['cell']['seed']=0
  with self.assertRaises(ValueError):f.reconcile(PROTOCOL,[(name,json.dumps(doc).encode())])
 def test_response_without_start_rejected(self):
  name,raw=self.cell_start();name=name.replace('STARTED','RESPONSE');doc=json.loads(raw);doc['result']={'state':'COMPUTED'}
  with self.assertRaises(ValueError):f.reconcile(PROTOCOL,[(name,json.dumps(doc).encode())])
 def test_duplicateJSON_rejected(self):
  with self.assertRaises(ValueError):f.strict_json(b'{"a":1,"a":2}')
 def test_full_finalization_atomic_mock_all225(self):
  # Files are tiny JSON descriptors, NOT real Parquet or scientific outputs.
  tids=list(range(20000,21896));source={'territory-universe.json':json.dumps(tids).encode()};source[self.cell_start()[0]]=self.cell_start()[1]
  start_name,start_raw=self.cell_start(1);source[start_name]=start_raw;data_name='cell-0001/failure-assignments.parquet';meta_name='cell-0001/failure.json';source[data_name]=json.dumps({'mock_only':True,'tids':tids,'months':PROTOCOL['months'],'status':'INCONCLUSIVE_METHOD_FAILURE'}).encode();source[meta_name]=json.dumps(dict(cell=v.planned(PROTOCOL)[1],status='INCONCLUSIVE',error='owned synthetic failure',full_rows_preserved=45504)).encode();response={'key':'cell/1','started_SHA':hashlib.sha256(start_raw).hexdigest(),'monotonic':2.,'result':{'key':1,'state':'INCONCLUSIVE','rowsSHA':hashlib.sha256(source[data_name]).hexdigest(),'failureSHA':hashlib.sha256(source[meta_name]).hexdigest()}};source[start_name.replace('STARTED','RESPONSE')]=json.dumps(response).encode();inv={n:hashlib.sha256(raw).hexdigest() for n,raw in source.items()};g=Guard();calls=[]
  @mock
  def read(n):yield source[n]
  @mock
  def writer(path,rows,guard):guard();path.write_text(json.dumps({'mock_only':True,'tids':list(rows.tids),'months':list(rows.months),'status':rows.status}));calls.append((path.name,len(rows)))
  @mock
  def reader(path):
   doc=json.loads(path.read_text());self.assertTrue(doc['mock_only']);return f.StatusRows(doc['tids'],doc['months'],doc['status'])
  @mock
  def publish(stage,target):self.assertFalse(target.exists());stage.rename(target)
  spec={'whole_seconds':120,'finalization_reserve_seconds':60,'metadata_bytes_limit':1000000,'source_binding':dict(protocol_SHA=v.PROTOCOL_SHA,method_SHA=v.METHOD_SHA,source_ACK_SHA=v.SOURCE_ACK_SHA)};op={'operation':f.OPERATION_KEY,'state':'STARTED','original_anchor':g.anchor,'whole_seconds':120,'finalization_reserve_seconds':60,'source_binding':g.source_binding,'panel_SHA':PROTOCOL['data_pins']['economic-atlas/data/panel_v1.parquet'],'territory_ids_SHA':hashlib.sha256(v.canonical(tids).encode()).hexdigest()};stage=self.root/'stage';target=self.root/'published';lease=self.root/'lease'
  # Lightweight full225 publication wiring spy. Actual streamed schema validator
  # is tested separately on full45504 rows with missing/duplicate negatives.
  # This is NOT a real10,238,400-row scientific/Parquet validation receipt.
  def schema_spy(rows,tids,months,K,cell,status,guard):
   self.assertIsInstance(rows,f.StatusRows);self.assertEqual(rows.tids,tuple(tids));self.assertEqual(rows.months,tuple(months));self.assertEqual(rows.status,f.NONCOMPUTED[status]);self.assertEqual(len(rows),45504);guard()
   return {'rows':45504,'status_counts':{rows.status:45504},'computed_per_month':dict.fromkeys(months,0)}
  with patch.object(v,'row_universe',side_effect=schema_spy):result=f.finalize_mockable(PROTOCOL_BYTES,inv,read,reader,writer,publish,g,op,spec,stage,target,lease)
  self.assertEqual(result['status_rows'],10238400);self.assertEqual(result['cells'],225);self.assertFalse(result['scientific_pass']);actual=json.loads((target/'cell-registry.json').read_text());self.assertEqual(actual[0]['status'],'UNKNOWN_NATIVE_RESPONSE');self.assertEqual(actual[1]['status'],'INCONCLUSIVE');self.assertTrue(all(r['status']=='NOT_ATTEMPTED_RESOURCE_STOP' for r in actual[2:]));self.assertEqual(len(calls),224);self.assertEqual(sum(n for _,n in calls)+45504,10238400);self.assertEqual(len(json.loads((target/'native-registry.json').read_text())),8220);self.assertEqual(json.loads((target/'result.json').read_text())['original_anchor'],g.anchor)
  with self.assertRaisesRegex(ValueError,'fresh'):f.finalize_mockable(PROTOCOL_BYTES,inv,read,reader,writer,publish,g,op,spec,stage,target,lease)
 def test_real_callback_refused_before_IO(self):
  with self.assertRaises(RuntimeError):f.finalize_mockable(PROTOCOL_BYTES,{},lambda n:[],lambda p:[],lambda *a:None,lambda *a:None,Guard(),{}, {},self.root/'stage',self.root/'target',self.root/'lease')
  self.assertEqual(list(self.root.iterdir()),[])
 def test_independent_B1_completed_selfbaseline_no_global_file(self):
  rec=registry();rec[0]['status']='COMPUTED';result=f.make_pairings(PROTOCOL,rec,coverage(rec),[])
  self.assertEqual(len(result),180);self.assertEqual(result[0]['status'],'COMPUTED');self.assertEqual(result[0]['agreement'],[]);self.assertEqual(result[0]['denominators']['paired_available'],45504)
 def test_independent_B2_completed_arm_no_saved_metrics(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';base=dict(cell=rec[0]['cell'],denominators=dict(universe=45504,paired_available=45504,unpaired=0),agreement=[])
  result=f.make_pairings(PROTOCOL,rec,coverage(rec),[base]);row=result[10]
  self.assertEqual(row['status'],'UNAVAILABLE_METRIC_EVIDENCE');self.assertEqual(row['arm_execution_status'],'COMPUTED');self.assertEqual(row['baseline_execution_status'],'COMPUTED');self.assertEqual(row['denominators']['paired_available'],45504);self.assertEqual(len(row['agreement']),24);self.assertTrue(all(x['n']==1896 for x in row['agreement']))
 def test_missing_metric_month_still_preserves_mathematical_NA(self):
  rec=registry();rec[0]['status']=rec[40]['status']='COMPUTED';row=f.make_pairings(PROTOCOL,rec,coverage(rec),[])[40]
  self.assertEqual(row['agreement'][0]['status'],'INPUT_UNAVAILABLE');self.assertEqual(row['agreement'][0]['n'],0);self.assertEqual(row['denominators']['paired_available'],43608)
 def source_pair(self,rec,key=10):
  return dict(cell=rec[key]['cell'],denominators=dict(universe=45504,paired_available=45504,unpaired=0),agreement=[dict(month=m,n=1896,status='COMPUTED',ARI_vs_sameKseed_shares=0.,NMI_vs_sameKseed_shares=0.) for m in PROTOCOL['months']])
 def test_saved_numerical_pair_kept_with_file_SHA(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';source=self.source_pair(rec);raw=json.dumps([source]).encode();pin=hashlib.sha256(raw).hexdigest();result=f.make_pairings(PROTOCOL,rec,coverage(rec),[source],pin)
  self.assertEqual(result[10]['status'],'COMPUTED');self.assertEqual(result[10]['source_pairs_SHA'],pin);self.assertEqual(result[10]['agreement'],source['agreement']);self.assertEqual(v.validate_pairing(PROTOCOL,rec,result,coverage(rec),[source],pin),180)
 def test_saved_comparison_missing_SHA_rejected(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED'
  with self.assertRaises(ValueError):f.make_pairings(PROTOCOL,rec,coverage(rec),[self.source_pair(rec)])
 def test_missing_metrics_cannot_inject_ARI(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';result=f.make_pairings(PROTOCOL,rec,coverage(rec),[]);result[10]['agreement'][0]['ARI_vs_sameKseed_shares']=1.
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,result,coverage(rec))
 def test_missing_metrics_cannot_inject_fileSHA(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';result=f.make_pairings(PROTOCOL,rec,coverage(rec),[]);result[10]['source_pairs_SHA']='0'*64
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,result,coverage(rec))
 def test_wrong_saved_seed_not_downgraded_to_unknown(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';source=self.source_pair(rec);source['cell']=dict(source['cell'],seed=0)
  with self.assertRaises(ValueError):f.make_pairings(PROTOCOL,rec,coverage(rec),[source],'0'*64)
 def test_wrong_saved_denominator_not_downgraded(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';source=self.source_pair(rec);source['denominators']['paired_available']=1
  with self.assertRaises(ValueError):f.make_pairings(PROTOCOL,rec,coverage(rec),[source],'0'*64)
 def test_saved_row_requires_equal_byte_evidence(self):
  rec=registry();rec[0]['status']=rec[10]['status']='COMPUTED';source=self.source_pair(rec);pin='1'*64;result=f.make_pairings(PROTOCOL,rec,coverage(rec),[source],pin)
  with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,result,coverage(rec),[source],'2'*64)
 def test_provided_corrupt_selfsource_both_paths_reject(self):
  rec=registry();rec[0]['status']='COMPUTED';published=f.make_pairings(PROTOCOL,rec,coverage(rec),[])
  import copy
  valid=dict(cell=rec[0]['cell'],denominators=dict(universe=45504,paired_available=45504,unpaired=0),agreement=[])
  for kind in ('denominator','agreement','schema','boolean'):
   bad=copy.deepcopy(valid)
   if kind=='denominator':bad['denominators']['paired_available']=1
   elif kind=='agreement':bad['agreement']=[{'invented':True}]
   elif kind=='schema':bad['invented']=True
   else:bad['denominators']['unpaired']=False
   with self.subTest(corruption=kind):
    with self.assertRaises(ValueError):f.make_pairings(PROTOCOL,rec,coverage(rec),[bad],'a'*64)
    with self.assertRaises(ValueError):v.validate_pairing(PROTOCOL,rec,published,coverage(rec),[bad],'a'*64)
 def test_provided_valid_selfsource_both_paths_accept(self):
  rec=registry();rec[0]['status']='COMPUTED';valid=dict(cell=rec[0]['cell'],denominators=dict(universe=45504,paired_available=45504,unpaired=0),agreement=[])
  published=f.make_pairings(PROTOCOL,rec,coverage(rec),[valid],'a'*64);self.assertEqual(v.validate_pairing(PROTOCOL,rec,published,coverage(rec),[valid],'a'*64),180);self.assertEqual(published[0]['agreement'],[])
 def test_absent_selfsource_stays_valid(self):
  rec=registry();rec[0]['status']='COMPUTED';published=f.make_pairings(PROTOCOL,rec,coverage(rec),[]);self.assertEqual(v.validate_pairing(PROTOCOL,rec,published,coverage(rec)),180)
 def test_no_scientific_imports(self):self.assertFalse(set(('numpy','scipy','sklearn','pyarrow','pandas'))&set(sys.modules))
if __name__=='__main__':unittest.main()
