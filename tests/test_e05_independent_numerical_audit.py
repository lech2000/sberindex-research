"""Closed-form tiny stdlib numeric fixtures only; no fits/source metric calls."""
import unittest,sys,pathlib,copy,math,os
sys.path.insert(0,str(pathlib.Path(__file__).parents[1]/'economic-atlas/src'))
import e05_independent_numerical_audit as a
B={'abrupt_missed_change_fraction_max':.2,'abrupt_median_delay_months_max':2.0,'stable_false_switch_fraction_max':.05,'seasonal_false_switch_fraction_max':.05}
class Audit(unittest.TestCase):
 def test_closed_form_silhouette_CH(self):
  r=a.quality([[0],[2],[10],[12]],[0,0,1,1],[[0,1,0,0],[1,0,0,0],[0,0,0,1],[0,0,1,0]])
  self.assertAlmostEqual(r['SW'],79/99);self.assertAlmostEqual(r['CH'],50);self.assertEqual(r['MQ'],'SPEC_UNRESOLVED_OWNER_EXCLUDED')
 def test_singleton_silhouette_zero(self):
  r=a.quality([[0],[2],[10]],[0,0,1],[[0,1,0],[1,0,0],[0,0,0]]);self.assertAlmostEqual(r['SW'],((1-2/10)+(1-2/8))/3)
 def test_zero_within_CH_original_convention(self):self.assertEqual(a.quality([[0],[0],[10],[10]],[0,0,1,1],[[0]*4 for _ in range(4)])['CH'],1)
 def test_SDbw_pair_union_closed_form(self):
  r=a.sdbw([[0],[1],[2],[10],[11],[12]],[0,0,0,1,1,1]);self.assertAlmostEqual(r['S_Dbw'],2/77);self.assertEqual(r['pairs'],[{'i':0,'j':1,'midpoint_count':0,'centre_i_count':1,'centre_j_count':1}]);self.assertEqual(r['centre_domain'],'pair_union')
 def test_SDbw_zero_density_denominator_NA(self):self.assertIsNone(a.sdbw([[0],[2],[10],[12]],[0,0,1,1])['S_Dbw'])
 def test_SDbw_zero_global_NA(self):self.assertEqual(a.sdbw([[0],[0],[0]],[0,0,1])['status'],'NA_ZERO_GLOBAL_VARIANCE')
 def test_SDbw_K_domain_NA(self):self.assertEqual(a.sdbw([[0],[1]],[0,1])['status'],'NA_K_DOMAIN')
 def test_network_two_isolated_communities(self):self.assertEqual(a.network([[0,1,0,0],[1,0,0,0],[0,0,0,1],[0,0,1,0]],[0,0,1,1]),{'AVI':1.,'AVU':0.,'Newman_Q':.5})
 def test_network_cross_edges(self):self.assertEqual(a.network([[0,0,1,0],[0,0,0,1],[1,0,0,0],[0,1,0,0]],[0,0,1,1]),{'AVI':0.,'AVU':1.,'Newman_Q':-.5})
 def test_network_no_edges_NA_Q(self):self.assertEqual(a.network([[0,0],[0,0]],[0,1]),{'AVI':0.,'AVU':0.,'Newman_Q':None})
 def test_graph_bad_symmetry_negative_loop(self):
  for g in [[[0,1],[0,0]],[[0,-1],[-1,0]],[[1,0],[0,0]]]:
   with self.assertRaises(ValueError):a.network(g,[0,1])
 def test_ARI_NMI_crossed_closed_form(self):
  r=a.agreement([0,0,1,1],[0,1,0,1]);self.assertAlmostEqual(r['ARI'],-.5);self.assertEqual(r['NMI'],0);self.assertEqual(sorted(r['contingency'].values()),[1]*4)
 def test_permutation_not_identity_switch(self):
  r=a.agreement([0,0,1,1],[1,1,0,0]);self.assertEqual(r['ARI'],1);self.assertEqual(r['NMI'],1);self.assertEqual(r['switch_fraction'],1)
 def test_single_cluster_NMI_ARI(self):self.assertEqual(a.agreement([0,0],[1,1])['NMI'],1)
 def test_temporal_missing_retained(self):self.assertEqual(a.temporal([[0,1],None,[1,0]]),[{'t':1,'status':'INPUT_UNAVAILABLE'},{'t':2,'status':'INPUT_UNAVAILABLE'}])
 def test_initial_only_mapping_permutation(self):
  truth=[[0,0,1,1],[1,1,1,1]];r=a.control([[1,0],[1,0],[0,0],[0,0]],truth,[0],2);self.assertEqual(r['recall'],1);self.assertEqual(r['false_switch_fraction'],0)
 def test_wrong_prestate_correct_post_no_event(self):
  r=a.control([[0,1],[1,1],[1,1],[1,1]],[[0,0,1,1],[1,1,1,1]],[0],2);self.assertEqual(r['recall'],0);self.assertEqual(r['post_shift_state_accuracy'],1);self.assertEqual(r['never_detected'],1);self.assertIsNone(r['median_delay']);self.assertEqual(a.budget(r,'abrupt_shift',B)['status'],'INCONCLUSIVE_UNDEFINED')
 def test_delayed_and_missed_denominator(self):
  truth=[[0,0,1,1],[0,0,1,1],[1,1,1,1]];r=a.control([[0,0,1],[0,0,1],[1,0,1],[1,1,1]],truth,[0,1],2);self.assertEqual(r['recall'],.5);self.assertEqual(r['eventual_event_recall'],1);self.assertEqual(r['delays_months'],[0,1]);self.assertEqual(r['median_delay'],.5);self.assertEqual(a.budget(r,'abrupt_shift',B)['status'],'CONTROL_BUDGET_FAIL')
 def test_all_changed_false_switch_NA(self):self.assertIsNone(a.control([[0,1],[0,1],[1,0],[1,0]],[[0,0,1,1],[1,1,0,0]],[0,1],2)['false_switch_fraction'])
 def test_no_changed_recall_NA(self):
  r=a.control([[0,1]]*4,[[0]*4,[1]*4],[],2);self.assertIsNone(r['recall']);self.assertEqual(a.budget(r,'stable',B)['status'],'CONTROL_BUDGET_PASS')
 def test_truth_changed_outside_movers_reject(self):
  with self.assertRaises(ValueError):a.control([[0,1],[0,1],[1,1],[1,1]],[[0,0,1,1],[1]*4],[],2)
 def test_unknown_truth_label_reject(self):
  with self.assertRaises(ValueError):a.control([[0,1]]*4,[[0]*4,[2]*4],[],2)
 def test_NA_type_bool_rounded_corruption(self):
  for x,y in [(None,0),(1,True),(.123456789,.123),(0.,float('nan'))]:
   with self.assertRaises(ValueError):a.compare(x,y)
 def test_missing_metric_contingency_corruption(self):
  r=a.agreement([0,0,1,1],[0,1,0,1]);q=copy.deepcopy(r);q['contingency']['0->0']=2
  with self.assertRaises(ValueError):a.compare(r,q)
  with self.assertRaises(ValueError):a.compare(r,{'ARI':r['ARI']})
 def test_frozen2023_transform_has_no2024_leakage(self):
  months=[f'{y}-{m:02}'for y in (2023,2024)for m in range(1,13)];x=[[[100]+[2+t+j for j in range(5)]for t in range(24)]];z=a.frozen_common(x,months);y=copy.deepcopy(x)
  for row in y[0][12:]:row[1:]=[v*100 for v in row[1:]]
  q=a.frozen_common(y,months);self.assertEqual(z[0][:12],q[0][:12]);self.assertNotEqual(z[0][12:],q[0][12:])
 def test_paired_month_mask_and_rounding(self):
  months=list(range(24));x=[[0,0,1,1]]*24;y=[[0,1,0,1]]*24;x=x[:];x[0]=None;r=a.paired_metrics(x,y,months);self.assertEqual(r[0],{'month':0,'status':'INPUT_UNAVAILABLE','n':0});self.assertAlmostEqual(r[1]['ARI_vs_sameKseed_shares'],-.5)
  q=copy.deepcopy(r);q[0]['ARI_vs_sameKseed_shares']=0
  # Missing-month numeric values must be rejected by the source V5 schema;
  # reference expected NA record deliberately has no fabricated metric key.
  self.assertNotIn('ARI_vs_sameKseed_shares',r[0])
  with self.assertRaises(ValueError):a.compare(r,q)
 def test_pair_union_overlap_differs_from_own_cluster(self):
  r=a.sdbw([[-1],[0],[1],[0],[1],[2]],[0,0,0,1,1,1]);self.assertAlmostEqual(r['S_Dbw'],30/11);self.assertEqual(r['pairs'][0]['centre_i_count'],2);self.assertEqual(r['pairs'][0]['midpoint_count'],4)
 def test_full225_metadata_callgraph_unattempted_not_numeric_PASS(self):
  p=a.pinned_protocol(pathlib.Path(os.environ['E05_REPAIRED_PROTOCOL']).read_bytes());cells=a.planned(p);records=[{'key':i,'cell':c,'status':'NOT_ATTEMPTED_RESOURCE_STOP'}for i,c in enumerate(cells)]
  def verify():return {'full_status_rows':10238400,'cells':225,'independent_full_file_readback':True}
  def load(*args):raise AssertionError('never load unavailable scientific tensor')
  def guard():pass
  for f in (verify,load,guard):f.qualified_e05_audit_io=True
  result=a.audit_bank(p,records,verify,load,guard);self.assertEqual(len(result['cells']),225);self.assertFalse(result['actual_full_numerical_gate_pass']);self.assertFalse(result['scientific_pass'])
  with self.assertRaises(ValueError):a.audit_bank(p,records[:-1],verify,load,guard)
  wrong=copy.deepcopy(records);wrong[0]['cell']['K']=9
  with self.assertRaises(ValueError):a.audit_bank(p,wrong,verify,load,guard)
 def frozen(self):return a.pinned_protocol(pathlib.Path(os.environ['E05_REPAIRED_PROTOCOL']).read_bytes())
 def test_source_protocol_pin_and_all225_unique(self):
  p=self.frozen();cells=a.planned(p);self.assertEqual(len({a.canonical_sha(c)for c in cells}),225);self.assertEqual(p['K'],[2,5]);self.assertEqual(p['seeds'],[20261008,20261009,20261010,20261011,20261012]);self.assertEqual(p['controls']['seeds'],[30261008,30261009,30261010,30261011,30261012])
 def test_source_bytes_whitespace_duplicate_or_changed_refuse(self):
  raw=pathlib.Path(os.environ['E05_REPAIRED_PROTOCOL']).read_bytes()
  for q in [raw+b' ',b'{}',b'{"a":1,"a":2}']:
   with self.assertRaises(ValueError):a.pinned_protocol(q)
 def test_duplicate_arm_K_seeds_world_gamma_false225_refuse(self):
  for field in ['arm','K','seed','world','gamma','controlseed']:
   p=self.frozen()
   if field=='arm':p['arms'][1]=copy.deepcopy(p['arms'][0])
   if field=='K':p['K'][1]=p['K'][0]
   if field=='seed':p['seeds'][1]=p['seeds'][0]
   if field=='world':p['controls']['worlds'][1]=p['controls']['worlds'][0]
   if field=='gamma':p['controls']['gammas'][1]=p['controls']['gammas'][0]
   if field=='controlseed':p['controls']['seeds'][1]=p['controls']['seeds'][0]
   with self.assertRaises(ValueError):a.planned(p)
 def test_literal_full_arm_feature_order_month_pin_change_refuse(self):
  for field in ['feature','order','month','datapin','boolK']:
   p=self.frozen()
   if field=='feature':p['arms'][1]['feature']='shares'
   if field=='order':p['arms'][1],p['arms'][2]=p['arms'][2],p['arms'][1]
   if field=='month':p['months'][0]='2025-01'
   if field=='datapin':p['data_pins']['economic-atlas/data/panel_v1.parquet']='0'*64
   if field=='boolK':p['K'][0]=True
   with self.assertRaises(ValueError):a.planned(p)
 def test_bounds_inf_bool_nan_string_negative_fraction_gt1_reject(self):
  m={'false_switch_fraction':0}
  for v in [float('inf'),float('nan'),True,'0.05',-.1,1.1]:
   b=copy.deepcopy(B);b['stable_false_switch_fraction_max']=v
   with self.assertRaises(ValueError):a.budget(m,'stable',b)
 def test_valid_domain_changed_bound_still_not_frozen(self):
  b=copy.deepcopy(B);b['stable_false_switch_fraction_max']=.1
  with self.assertRaises(ValueError):a.budget({'false_switch_fraction':0},'stable',b)
 def test_raw_fraction_semantic_domain_not_PASS(self):
  for v in [-.1,1.1,True,float('inf'),float('nan'),'0']:
   with self.assertRaises(ValueError):a.budget({'false_switch_fraction':v},'stable',B)
  self.assertEqual(a.budget({'false_switch_fraction':None},'stable',B)['status'],'INCONCLUSIVE_UNDEFINED')
 def test_delay_semantic_domain_not_PASS(self):
  for v in [-1,True,float('inf'),float('nan'),'0']:
   with self.assertRaises(ValueError):a.budget({'miss_fraction':0,'median_delay':v},'abrupt_shift',B)
  self.assertEqual(a.budget({'miss_fraction':0,'median_delay':None},'abrupt_shift',B)['status'],'INCONCLUSIVE_UNDEFINED')
 def test_initial_mapping_tie_unverified_abstains(self):
  with self.assertRaisesRegex(ValueError,'INITIAL_MAPPING_TIE_UNVERIFIED'):a.control([[0,0]]*4,[[0]*4,[1]*4],[],2)
 def test_public_execution_and_bank_refuse_unqualified(self):
  with self.assertRaises(RuntimeError):a.execute()
  with self.assertRaises(RuntimeError):a.audit_bank({},[],lambda:{},lambda:{},lambda:None)
 def test_no_numerical_imports(self):self.assertFalse({'numpy','scipy','sklearn','pandas','pyarrow'}&set(sys.modules))
if __name__=='__main__':unittest.main()
