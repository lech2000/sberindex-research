"""Tiny schema/read-only provenance fixtures; no realbank/model/generator/native."""
import pathlib,sys,unittest,tempfile,copy,json,math,os
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'economic-atlas/src'))
import e05_full_numeric_adapter as a
class Test(unittest.TestCase):
 def rows(self):return [dict(date='2023-01',ym='2023-01',territory_id=i,category=c,value=10+k)for i in [1,2]for k,c in enumerate(a.CATEGORIES)]
 def test_real_native_schema_tiny_Arrow(self):
  import pyarrow as pa,pyarrow.parquet as pq
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'panel.parquet';schema=pa.schema([('date',pa.string()),('territory_id',pa.int16()),('category',pa.string()),('value',pa.int32()),('ym',pa.string())]);pq.write_table(pa.Table.from_pylist(self.rows(),schema=schema),p);rows=list(a.parquet_rows(p,a.PANEL_SCHEMA,lambda:None));self.assertEqual(a.input_cube(rows,[1,2],['2023-01'])[0][0],[10.,11.,12.,13.,14.,15.])
 def test_schema_wrong_dtype_refused(self):
  import pyarrow as pa,pyarrow.parquet as pq
  with tempfile.TemporaryDirectory()as d:
   p=pathlib.Path(d)/'p';pq.write_table(pa.Table.from_pylist(self.rows()),p)
   with self.assertRaises(ValueError):list(a.parquet_rows(p,a.PANEL_SCHEMA,lambda:None))
 def test_full_rectangle_missing_duplicate_unknownID(self):
  for rows in [self.rows()[:-1],self.rows()+self.rows()[:1],[dict(self.rows()[0],territory_id=9)]+self.rows()[1:]]:
   with self.assertRaises(ValueError):a.input_cube(rows,[1,2],['2023-01'])
 def test_native_date_ym_disagreement(self):
  rows=self.rows();rows[0]['date']='2024-01-01'
  with self.assertRaises(ValueError):a.input_cube(rows,[1,2],['2023-01'])
 def test_positivefinite_no_zero_nan_bool(self):
  for value in [0,-1,True,float('nan'),float('inf'),None]:
   rows=self.rows();rows[0]['value']=value
   with self.assertRaises(ValueError):a.input_cube(rows,[1,2],['2023-01'])
 def test_geo_normalization_closed_form(self):
  row={'u':1,'v':2,'distance':3.,'weight':4.};self.assertEqual(a.geography([row],[1,2]),[[0.,1.],[1.,0.]])
 def test_geography_unknown_endpoint_selfloop_negative_weight_isolate(self):
  base={'u':1,'v':2,'distance':3.,'weight':4.}
  for rows in [[dict(base,u=8)],[dict(base,v=1)],[dict(base,weight=-1)],[]]:
   with self.assertRaises(ValueError):a.geography(rows,[1,2])
 def protocol(self):return a.numerical.pinned_protocol((pathlib.Path(__file__).parents[1]/'economic-atlas/protocols/E05_FULL_REMAINING_V2.json').read_bytes())
 def test_truth_allthreeworlds_exact_frozen_logic(self):
  p=self.protocol();cell=a.numerical.planned(p)[180];cell=dict(cell,world='abrupt_shift');truth,m=a.fixed_truth(cell,p,n=10,T=24);self.assertEqual(m,[0,1]);self.assertEqual(truth[0][:12],[0]*12);self.assertEqual(truth[0][12:],[1]*12);self.assertEqual(truth[2],[0]*24)
  for world in ['stable','seasonal_no_identity_change']:
   t,_=a.fixed_truth(dict(cell,world=world),p,n=10,T=24);self.assertEqual(t[0],[0]*24)
 def test_control_world_seed_gamma_binding(self):
  p=self.protocol();c=a.numerical.planned(p)[180]
  for k,v in [('world','other'),('seed',0),('gamma',9)]:
   with self.assertRaises(ValueError):a.fixed_truth(dict(c,**{k:v}),p,n=10,T=24)
 def test_truth_doesnot_generateX_or_fit(self):
  import inspect
  s=inspect.getsource(a.fixed_truth);self.assertNotIn('random.',s);self.assertNotIn('_controls(',s);self.assertNotIn('fit_predict',s)
 def test_separation_noise_change_protocol_denied_before_adapter(self):
  p=self.protocol();p['controls']['separation']=0
  with self.assertRaises(ValueError):a.numerical.planned(p)
 def test_full225_not_only_recordcount(self):
  p=self.protocol();self.assertEqual(len(a.numerical.planned(p)),225);p['arms'][1]=copy.deepcopy(p['arms'][0])
  with self.assertRaises(ValueError):a.numerical.planned(p)
 def test_safetree_byteSHA_change_symlink(self):
  import hashlib
  with tempfile.TemporaryDirectory()as d:
   root=pathlib.Path(d).resolve();p=root/'x';p.write_bytes(b'old');sha=hashlib.sha256(b'old').hexdigest();self.assertEqual(a.verified_file(root,'x',sha,lambda:None),p);p.write_bytes(b'new')
   with self.assertRaises(ValueError):a.verified_file(root,'x',sha,lambda:None)
   (root/'alias').symlink_to(p)
   with self.assertRaises(ValueError):a.safe_file(root,'alias')
 def spec(self):return dict(anchor_monotonic=100.,whole_seconds=1000.,prior_elapsed_floor=10.,receipt_reserve_seconds=30.,rss_limit_bytes=1024**3,output_limit_bytes=128*1024**2,minimum_free_bytes=1024**3,CPU_threads=1,independent_resource_IO_admission_SHA='a'*64,resource_cost_qualified=True)
 def guard(self):
  def g():pass
  g.qualified_e05_audit_io=True;g.anchor=100.;g.whole_seconds=1000.;return g
 def test_resource_metadata_valid_only_not_measuredPASS(self):a.Admission(self.spec(),self.guard(),now=110.)
 def test_resource_nan_bool_negative_reset_or_mismatchedclock(self):
  for k,v in [('whole_seconds',float('nan')),('anchor_monotonic',True),('prior_elapsed_floor',-1),('CPU_threads',True),('anchor_monotonic',111.),('whole_seconds',1),('rss_limit_bytes',2*1024**3),('independent_resource_IO_admission_SHA','bad')]:
   b=self.spec();b[k]=v
   with self.assertRaises((ValueError,RuntimeError)):a.Admission(b,self.guard(),now=110.)
 def test_UNKNOWN_cost_refuses_actual_admission(self):
  b=self.spec();b['resource_cost_qualified']=False
  with self.assertRaises(RuntimeError):a.Admission(b,self.guard(),now=110.)
 def test_keySHA_native_identity_order_sensitive(self):self.assertNotEqual(a.full_key_sha([1,2],['2023-01']),a.full_key_sha([2,1],['2023-01']))
 def test_strict_JSON_nonfinite_duplicate(self):
  for raw in ['{"x":NaN}','{"x":1,"x":2}']:
   with self.assertRaises(ValueError):a.strict_json(raw)
 def test_vectorized_independent_closed_forms_and_scalar_agreement(self):
  import e05_numpy_quality_reference as v
  for X,y in [([[0],[2],[10],[12]],[0,0,1,1]),([[-1],[0],[1],[0],[1],[2]],[0,0,0,1,1,1]),([[0],[0],[10],[10]],[0,0,1,1]),([[0],[2],[10]],[0,0,1]),([[0],[0],[0]],[0,0,1])]:
   n=len(X);A=[[1. if i!=j and y[i]==y[j]else 0. for j in range(n)]for i in range(n)];a.numerical.compare(a.numerical.quality(X,y,A),v.quality(X,y,A))
 def test_vectorized_truth_NA_graph_finite_refusals(self):
  import e05_numpy_quality_reference as v
  self.assertEqual(v.quality(None,None,None),{'status':'INPUT_UNAVAILABLE'})
  for X,y,A in [([[0],[1],[2]],[True,False,True],[[0]*3 for _ in range(3)]),([[0],[float('nan')],[2]],[0,0,1],[[0]*3 for _ in range(3)]),([[0],[1],[2]],[0,0,1],[[1,0,0],[0,0,0],[0,0,0]])]:
   with self.assertRaises(ValueError):v.quality(X,y,A)
 def test_sequences_integral_double_labels_and_unknown_kept(self):
  c={'kind':'control'};rows=[dict(territory_id=i,month=m,label=float(i-1),status='COMPUTED')for m in ['2023-01','2023-02']for i in [1,2]];seq,coverage=a.sequences(rows,[1,2],['2023-01','2023-02'],2,c,'COMPUTED');self.assertEqual(seq,[[0,1],[0,1]]);self.assertEqual(coverage['rows'],4)
  rows=[dict(r,label=None,status='UNKNOWN_NATIVE_RESPONSE')for r in rows];self.assertEqual(a.sequences(rows,[1,2],['2023-01','2023-02'],2,c,'UNKNOWN_NATIVE_RESPONSE')[0],[None,None])
  rows[0]['label']=0
  with self.assertRaises(ValueError):a.sequences(rows,[1,2],['2023-01','2023-02'],2,c,'UNKNOWN_NATIVE_RESPONSE')
 def test_partial_label_month_not_silently_filled(self):
  rows=[dict(territory_id=1,month='2023-01',label=0,status='COMPUTED'),dict(territory_id=2,month='2023-01',label=None,status='INPUT_UNAVAILABLE')]
  with self.assertRaises(ValueError):a.sequences(rows,[1,2],['2023-01'],2,{'kind':'control'},'COMPUTED')
 def test_nonfinite_now_and_fractionalbyte_budgets_reject(self):
  with self.assertRaises(ValueError):a.Admission(self.spec(),self.guard(),now=float('nan'))
  b=self.spec();b['output_limit_bytes']=.5
  with self.assertRaises(ValueError):a.Admission(b,self.guard(),now=110.)
 def test_V5_actual_schema_bridge_all225maps_source_spy_only(self):
  from unittest.mock import patch
  p=self.protocol();records=[dict(key=i,cell=c,status='NOT_ATTEMPTED_RESOURCE_STOP',protocol_SHA=a.publication.PROTOCOL_SHA,method_SHA=a.publication.METHOD_SHA)for i,c in enumerate(a.numerical.planned(p))];manifest={'files':{'paired-comparisons.json':'a'*64}};v={'cells':225,'status_rows':10238400}
  with patch.object(a,'full_key_sha',return_value='b'*64)as spy:
   envelope=a.publication_envelope(p,records,manifest,list(range(1896)),v);self.assertEqual(len(envelope['cell_key_SHA']),225);self.assertEqual(envelope['full_status_rows'],10238400);self.assertEqual(spy.call_count,2);self.assertEqual(envelope['assignment_SHA'],{})
   with self.assertRaises(ValueError):a.publication_envelope(p,records[:-1],manifest,list(range(1896)),v)
   with self.assertRaises(ValueError):a.publication_envelope(p,records,manifest,list(range(1896)),dict(v,status_rows=1))
 def test_bridge_computed_SHA_missing_or_nonfinite_reject(self):
  from unittest.mock import patch
  p=self.protocol();records=[dict(key=i,cell=c,status='NOT_ATTEMPTED_RESOURCE_STOP',protocol_SHA=a.publication.PROTOCOL_SHA,method_SHA=a.publication.METHOD_SHA)for i,c in enumerate(a.numerical.planned(p))];records[0]['status']='COMPUTED';manifest={'files':{'paired-comparisons.json':'a'*64,'cell-0000/assignments.parquet':'bad','cell-0000/summary.json':'b'*64}}
  with patch.object(a,'full_key_sha',return_value='b'*64):
   with self.assertRaises(ValueError):a.publication_envelope(p,records,manifest,list(range(1896)),{'cells':225,'status_rows':10238400})
 def test_publicexecute_refuses(self):
  with self.assertRaises(RuntimeError):a.execute()
 def test_SDbw_inclusive_radius_boundary_exact_scalar_counts(self):
  import e05_numpy_quality_reference as v
  X=[[.1],[.2],[.3],[.1591751709536137]];y=[0,0,0,1];A=[[float(i!=j)for j in range(4)]for i in range(4)]
  expected=a.numerical.sdbw(X,y);actual=v.quality(X,y,A)['S_Dbw'];self.assertEqual(actual,expected);self.assertEqual(actual['pairs'][0]['centre_i_count'],2);self.assertEqual(actual['Dens_bw'],1.);self.assertEqual(actual['S_Dbw'],1.6274509803921569)
 def control_adapter(self,root):
  obj=object.__new__(a.Adapter);obj.root=root;obj.guard=lambda:None
  for name in ('publication-manifest.json','cell-registry.json','territory-universe.json','paired-comparisons.json'):(root/name).write_text('{}')
  obj.bind_control_inputs();return obj
 def test_published_control_eachfile_changed_refuses_end(self):
  for name in ('publication-manifest.json','cell-registry.json','territory-universe.json','paired-comparisons.json'):
   with tempfile.TemporaryDirectory()as d:
    obj=self.control_adapter(pathlib.Path(d).resolve());obj.verify_control_inputs();(obj.root/name).write_text('{"changed":true}')
    with self.assertRaises(ValueError):obj.verify_control_inputs()
 def test_manifest_tamper_after_numeric_callback_rejected(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory()as d:
   obj=self.control_adapter(pathlib.Path(d).resolve());obj.manifest={'files':{}};obj.envelope={};obj.protocol={};obj.records=[];obj.input_receipt={};obj.verify_publication=lambda:None
   def mutate(*args,**kwargs):(obj.root/'publication-manifest.json').write_text('{"replaced":true}');return {'numeric':'old'}
   with patch.object(a.numerical,'audit_bank',side_effect=mutate):
    with self.assertRaises(ValueError):obj.audit()
 def test_samebytes_replacement_stat_refuses_and_no_namespace_rebind(self):
  with tempfile.TemporaryDirectory()as d:
   obj=self.control_adapter(pathlib.Path(d).resolve());p=obj.root/'publication-manifest.json';new=obj.root/'replace';new.write_bytes(p.read_bytes());new.replace(p)
   with self.assertRaises(ValueError):obj.verify_control_inputs()
   with self.assertRaises(RuntimeError):obj.bind_control_inputs()
if __name__=='__main__':unittest.main()
