import ast,copy,importlib.util,json,pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1];src=ROOT/'economic-atlas/src/atlas_e05_remaining_v2.py';spec=importlib.util.spec_from_file_location('pure_e05',src);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);p=json.loads((ROOT/'economic-atlas/protocols/E05_FULL_REMAINING_V2.json').read_text())
class E05(unittest.TestCase):
 def test_all_original_factors_fullscope(self):
  self.assertTrue(m.validate_protocol(p));cells=m.planned_cells(p);self.assertEqual(len(cells),225);self.assertEqual(sum(c['kind']=='real' for c in cells),180);self.assertEqual(sum(c['kind']=='control' for c in cells),45)
 def test_no_numpy_import_or_methodcalls_by_import_plan(self):
  self.assertNotIn('numpy',sys.modules);self.assertNotIn('sklearn',sys.modules);self.assertNotIn('scipy',sys.modules);tree=ast.parse(src.read_text())
  top=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom))];self.assertFalse(any('numpy' in ast.unparse(n) or 'sklearn' in ast.unparse(n) or 'scipy' in ast.unparse(n) for n in top))
 def test_narrowing_rejected(self):
  for change in ['shape','K','seed','feature','geography','temporal','mobility','control','qualification','month']:
   q=copy.deepcopy(p)
   if change=='shape':q['panel_expected_shape'][0]=101
   if change=='K':q['K']=[2]
   if change=='seed':q['seeds']=q['seeds'][:1]
   if change=='feature':q['arms']=[a for a in q['arms'] if a['feature']!='growth_mom']
   if change=='geography':q['arms']=[a for a in q['arms'] if a['alpha_geo']!=1]
   if change=='temporal':q['arms']=[a for a in q['arms'] if a['gamma']!=2]
   if change=='mobility':q['mobility_reuse_only']['no_new_fits']=False
   if change=='control':q['controls']['n']=60
   if change=='qualification':q['interpretation']['positive_scientific_pass_allowed']=True
   if change=='month':q['months']=q['months'][:-1]
   with self.subTest(change=change),self.assertRaises(ValueError):m.validate_protocol(q)
 def test_growth_missing_not_zero_filled(self):
  self.assertFalse(m.available('growth_mom',0));self.assertTrue(m.available('growth_mom',1));self.assertFalse(m.available('growth_yoy',11));self.assertTrue(m.available('growth_yoy',12));self.assertTrue(m.available('shares',0))
 def test_full_rows_and_unknown_not_hidden(self):
  rows=m.full_status_rows([10,20],['2023-01','2023-02'],[None,[0,1]]);self.assertEqual(len(rows),4);self.assertEqual(sum(r['status']=='INPUT_UNAVAILABLE' for r in rows),2);failed=m.full_status_rows([10,20],['2023-01'],[None],null_status='INCONCLUSIVE_METHOD_FAILURE');self.assertTrue(all(r['status']=='INCONCLUSIVE_METHOD_FAILURE' and r['label'] is None for r in failed))
 def test_shrinking_duplicate_mask_rejected(self):
  for tids,labels in [([1,1],[[0,1]]),([1,2],[[0]])]:
   with self.assertRaises(ValueError):m.full_status_rows(tids,['2023-01'],labels)
 def test_paired_denominator_exact_missing_keys(self):
  base=m.full_status_rows([1,2],['2023-01','2023-02'],[[0,1],[0,1]]);arm=m.full_status_rows([1,2],['2023-01','2023-02'],[None,[1,0]]);r=m.pairing(arm,base);self.assertEqual((r['universe'],r['paired_available'],r['unpaired']),(4,2,2))
  with self.assertRaises(ValueError):m.pairing(arm[:-1],base)
 def test_truthblind_permutation_alignment_and_real_switch(self):
  self.assertEqual(m.align_without_truth([[0,0,1,1],[1,1,0,0]]),[[0,0,1,1],[0,0,1,1]])
  rows=m.align_without_truth([[0,0,0,1,1,1],[1,1,0,0,0,0]]);self.assertEqual(sum(a!=b for a,b in zip(*rows)),1)
 def test_overlapping_or_undefined_control_notpass(self):
  q=m.control_budget({'miss_fraction':.21,'median_delay':1},'abrupt_shift',p);self.assertEqual(q['status'],'CONTROL_BUDGET_FAIL');self.assertFalse(q['scientific_pass'])
  for x in [None,True,float('nan'),float('inf'),-.1]:self.assertEqual(m.control_budget({'false_switch_fraction':x},'stable',p)['status'],'INCONCLUSIVE_UNDEFINED')
 def test_no_success_from_fulltechnical_only(self):
  text=src.read_text();self.assertIn("'formal_promise_complete':False",text);self.assertIn("'M4_dependency':'PENDING_SEPARATE_ACTUAL_ACCEPTANCE'",text);self.assertIn("'scientific_pass':False",text)
 def test_true_supra_not_legacy_fixedcentres(self):
  tree=ast.parse(src.read_text());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_partitions');text=ast.unparse(f);self.assertIn('sparse.block_diag',text);self.assertIn('T - 1',text);self.assertNotIn('apply_penalty',text)
 def test_scaler_train2023_literal_and_yoy_no2024_fit(self):
  tree=ast.parse(src.read_text());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_feature_cube');text=ast.unparse(f);self.assertIn('raw[:, :12, :]',text);self.assertIn('IDENTITY_DIMENSIONLESS_NO2023_YOY_DISTRIBUTION',text);self.assertIn('raw[:, 12:, :]',text)
 def test_truth_only_evaluation_not_partition(self):
  tree=ast.parse(src.read_text());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_partitions');self.assertFalse(any(isinstance(n,ast.Name) and n.id=='truth' for n in ast.walk(f)));self.assertIn('align_without_truth',ast.unparse(f))
 def test_fresh_guard_required_before_numericalimports(self):
  with self.assertRaises(ValueError):m.execute('missing','missing','missing',None,None)
  tree=ast.parse(src.read_text());f=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute');text=ast.unparse(f);self.assertLess(text.index('verify_inputs(repo, p)'),text.index('_deps()'));self.assertIn('FileExistsError',text)
if __name__=='__main__':unittest.main()
class InterlayerMocks(unittest.TestCase):
 def test_full_adjacent_identity_edges_not_wrap_or_cross_person(self):
  from unittest.mock import patch
  class V(list):
   def __radd__(self,scalar):return V(scalar+x for x in self)
  class Concat:
   def __getitem__(self,x):return list(x[0])+list(x[1])
  class NP:
   r_=Concat()
   arange=staticmethod(lambda n:V(range(n)))
   full=staticmethod(lambda n,v:[v]*n)
   asarray=staticmethod(lambda x,**k:list(x))
  matrices=[]
  class Mat:
   def __init__(self,shape):self.shape=shape;self.links=[]
   def __iadd__(self,other):self.links+=other.links;return self
  class Sparse:
   @staticmethod
   def block_diag(graphs,format):return Mat((len(graphs)*graphs[0].shape[0],)*2)
   @staticmethod
   def csr_matrix(spec,shape):
    z=Mat(shape);values,(i,j)=spec;z.links=list(zip(i,j,values));return z
  graphs=[Mat((3,3)) for _ in range(24)];calls=[]
  def partition(graph,K,seed,*unused):calls.append(graph);return [i%2 for i in range(graph.shape[0])]
  with patch.object(m,'_partition',side_effect=partition):labels=m._partitions(graphs,.5,2,123,NP,Sparse,None,None,lambda:None)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0].shape,(72,72));self.assertEqual(len(labels),24);self.assertTrue(all(len(v)==3 for v in labels));links=calls[0].links;self.assertEqual(len(links),23*3*2)
  for i,j,w in links:self.assertEqual(i%3,j%3);self.assertEqual(abs(i//3-j//3),1);self.assertEqual(w,.5)
 def test_independent_24_observed_calls_and_no_truth_parameter(self):
  from unittest.mock import patch
  class Mat:shape=(2,2)
  class NP:asarray=staticmethod(lambda x,**k:list(x))
  with patch.object(m,'_partition',return_value=[0,1]) as call:labels=m._partitions([Mat() for _ in range(24)],0,2,123,NP,None,None,None,lambda:None)
  self.assertEqual(call.call_count,24);self.assertEqual(len(labels),24);self.assertEqual([a.args[2] for a in call.call_args_list],list(range(123,147)))

class EventScoringRepair(unittest.TestCase):
 def fixture(self):
  before=[i%2 for i in range(10)];after=[1-v if i<2 else v for i,v in enumerate(before)]
  return before,after,[[before[i],before[i],after[i],after[i],after[i]] for i in range(10)]
 def test_correct_poststate_without_transition_is_not_detection(self):
  before,after,truth=self.fixture();labels=[[after[i]]*5 for i in range(10)]
  r=m._event_control_metrics(labels,truth,[0,1],2)
  self.assertEqual(r['post_shift_state_accuracy'],1);self.assertEqual(r['recall'],0);self.assertEqual(r['miss_fraction'],1);self.assertEqual(r['delays_months'],[None,None]);self.assertEqual(r['never_detected'],2)
  self.assertNotEqual(m.control_budget(r,'abrupt_shift',p)['status'],'CONTROL_BUDGET_PASS')
 def test_actual_immediate_transitions_pass_original_budget(self):
  before,after,truth=self.fixture();r=m._event_control_metrics(truth,truth,[0,1],2)
  self.assertEqual(r['recall'],1);self.assertEqual(r['delays_months'],[0,0]);self.assertEqual(r['median_delay'],0);self.assertEqual(m.control_budget(r,'abrupt_shift',p)['status'],'CONTROL_BUDGET_PASS')
 def test_delayed_detection_retained_but_not_immediate_recall(self):
  before,after,truth=self.fixture();labels=[[before[i]]*3+[after[i]]*2 for i in range(10)]
  r=m._event_control_metrics(labels,truth,[0,1],2)
  self.assertEqual(r['delays_months'],[1,1]);self.assertEqual(r['eventual_event_recall'],1);self.assertEqual(r['recall'],0);self.assertEqual(m.control_budget(r,'abrupt_shift',p)['status'],'CONTROL_BUDGET_FAIL')
 def test_anticipatory_switch_not_counted_as_zero_delay(self):
  before,after,truth=self.fixture();labels=[[before[i]]+[after[i]]*4 for i in range(10)]
  r=m._event_control_metrics(labels,truth,[0,1],2);self.assertEqual(r['recall'],0);self.assertEqual(r['never_detected'],2)
 def test_one_missed_event_and_delays_denom_includes_both(self):
  before,after,truth=self.fixture();labels=[row[:] for row in truth];labels[1]=[before[1]]*5
  r=m._event_control_metrics(labels,truth,[0,1],2);self.assertEqual(r['recall'],.5);self.assertEqual(r['miss_fraction'],.5);self.assertEqual(r['never_detected'],1);self.assertEqual(r['delays_months'],[0,None])
 def test_stable_false_switches_all_months_unchanged_denominator(self):
  before,after,truth=self.fixture();truth=[[v]*5 for v in before];labels=[row[:] for row in truth];labels[0][2]=1-labels[0][2]
  r=m._event_control_metrics(labels,truth,[0,1],2);self.assertIsNone(r['recall']);self.assertEqual(r['false_switch_fraction'],2/40)
 def test_no_events_not_synthetic_recall_one(self):
  before,after,truth=self.fixture();truth=[[v]*5 for v in before];r=m._event_control_metrics(truth,truth,[0,1],2)
  self.assertIsNone(r['recall']);self.assertIsNone(r['median_delay']);self.assertEqual(r['false_switch_fraction'],0);self.assertEqual(m.control_budget(r,'stable',p)['status'],'CONTROL_BUDGET_PASS')
 def test_shapes_missing_movers_and_multiple_truth_events_rejected(self):
  before,after,truth=self.fixture()
  with self.assertRaises(ValueError):m._event_control_metrics(truth[:-1],truth,[0,1],2)
  with self.assertRaises(ValueError):m._event_control_metrics(truth,truth,[0],2)
  q=[row[:] for row in truth];q[0][-1]=1-q[0][-1]
  with self.assertRaises(ValueError):m._event_control_metrics(truth,q,[0,1],2)
 def test_control_numeric_budget_and_full_scope_not_relaxed(self):
  self.assertEqual(p['controls']['error_budget'],{'stable_false_switch_fraction_max':.05,'abrupt_missed_change_fraction_max':.2,'abrupt_median_delay_months_max':2.,'seasonal_false_switch_fraction_max':.05})
  self.assertEqual(len(m.planned_cells(p)),225);self.assertEqual(p['controls']['scoring']['recall_month'],'frozen shift month, not eventual assignment accuracy')

class MappingIntegration(unittest.TestCase):
 def test_actual_control_function_does_not_pass_constant_postevent_labels(self):
  # Only 2x2 assignment and elementary arrays are mocked, not the scorer.
  import itertools,types
  from unittest.mock import patch
  class A:
   def __init__(self,data):self.data=data
   def __len__(self):return len(self.data)
   def __iter__(self):return iter(A(v) if isinstance(v,list) else v for v in self.data)
   def __getitem__(self,key):
    if isinstance(key,tuple):
     row,col=key
     if isinstance(row,slice):return A([r[col] for r in self.data[row]])
     return self.data[row][col]
    return self.data[key]
   def __eq__(self,v):return A([x==v for x in self.data])
   def __and__(self,v):return A([x and y for x,y in zip(self.data,v.data)])
   def __neg__(self):return A([[-v for v in row] for row in self.data])
  def hungarian(cost):
   best=min(itertools.permutations(range(2)),key=lambda order:sum(cost[i,order[i]] for i in range(2)))
   return range(2),best
  scipy=types.ModuleType('scipy');opt=types.ModuleType('scipy.optimize');opt.linear_sum_assignment=hungarian;scipy.optimize=opt
  np=types.SimpleNamespace(array=A,sum=lambda x:sum(x.data))
  before=[i%2 for i in range(10)];after=[1-v if i<2 else v for i,v in enumerate(before)]
  truth=A([[before[i],after[i],after[i]] for i in range(10)])
  for invert in [False,True]:
   labels=[A([1-v if invert else v for v in after]) for _ in range(3)]
   with patch.dict(sys.modules,{'scipy':scipy,'scipy.optimize':opt}):
    result=m._control_metrics(labels,truth,[0,1],1,np,lambda a,b:1. if a.data==b.data else self.fail('identical fixture labels'))
   self.assertEqual(result['post_shift_state_accuracy'],1);self.assertEqual(result['recall'],0);self.assertEqual(result['never_detected'],2)
   self.assertNotEqual(m.control_budget(result,'abrupt_shift',p)['status'],'CONTROL_BUDGET_PASS')
