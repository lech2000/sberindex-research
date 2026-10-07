from pathlib import Path
import importlib.util,unittest,numpy as np,json,tempfile
P=Path(__file__).resolve().parents[1]/'src/atlas_m4_channels.py';spec=importlib.util.spec_from_file_location('m4',P);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class M4Tests(unittest.TestCase):
 def test_world_only_changes_its_underlying_source_channel(self):
  n=75;seed=777001;R=3
  plain=m.world(n,R,'NONE',seed);a=m.world(n,R,'A',seed);b=m.world(n,R,'B',seed);c=m.world(n,R,'C',seed)
  np.testing.assert_array_equal(plain['mobility_km_index'],a['mobility_km_index']);np.testing.assert_array_equal(plain['mobility_km_index'],b['mobility_km_index'])
  np.testing.assert_array_equal(plain['panel'],c['panel'])
  np.testing.assert_array_equal(plain['panel'][:,0,:],b['panel'][:,0,:])
  # Multiplicative baseline cancels in dynamics, up to floating arithmetic.
  np.testing.assert_allclose(m.channel_features(plain,'B')[0],m.channel_features(a,'B')[0],atol=2e-15)
  self.assertFalse(np.array_equal(plain['panel'][:,0,:],a['panel'][:,0,:]))
 def test_B_similarity_removes_static_level(self):
  d=m.world(75,3,'NONE',777002);x=m.channel_features(d,'B')[0]
  d2={**d,'panel':d['panel']*np.linspace(.5,1.5,75)[:,None,None]}
  np.testing.assert_allclose(x,m.channel_features(d2,'B')[0],atol=2e-15)
  self.assertEqual(x.shape,(75,115));np.testing.assert_allclose(x.mean(1),0,atol=1e-16)
 def test_C_retains_km_index_augmentation_not_flow_matrix(self):
  d=m.world(75,3,'C',777003);x,metric=m.channel_features(d,'C')
  self.assertEqual(x.shape,(75,6));self.assertEqual(metric,'euclidean')
  np.testing.assert_allclose(x[:,:5],m.zscore(d['panel'][:,0,:]))
  np.testing.assert_allclose(x[:,5],.25*m.zscore(np.log1p(d['mobility_km_index'][:,None]))[:,0])
  self.assertEqual(d['mobility_km_index'].ndim,1)
 def test_all_nine_cell_graphs_have_exact_same_density(self):
  for world in m.CHANNELS:
   d=m.world(75,3,world,777004)
   for channel in m.CHANNELS:
    for k in (10,20,40):
     W=m.graph(d,channel,k)
     np.testing.assert_array_equal(W,W.T);self.assertFalse(W.diagonal().any())
     self.assertEqual(np.count_nonzero(np.triu(W,1)),75*k//2)
 def test_degree_null_exact_invariants_and_reproducibility(self):
  W=m.graph(m.world(75,3,'NONE',777005),'B',10)
  a,meta=m.degree_null(W,777006);b,meta2=m.degree_null(W,777006)
  np.testing.assert_array_equal(a.sum(1),W.sum(1));np.testing.assert_array_equal(a,a.T)
  self.assertFalse(a.diagonal().any());self.assertTrue(np.isin(a,[0,1]).all())
  np.testing.assert_array_equal(a,b);self.assertEqual(meta,meta2)
  self.assertTrue(meta['complete']);self.assertFalse(np.array_equal(a,W))
 def test_unrewirable_null_stays_inconclusive_not_resampled(self):
  W=np.ones((45,45))-np.eye(45);rewired,meta=m.degree_null(W,777007)
  self.assertFalse(meta['complete']);self.assertEqual(meta['seed'],777007)
  self.assertEqual(meta['attempts'],meta['attempt_cap']);np.testing.assert_array_equal(rewired,W)
 def test_foreign_requires_raw_m1_not_low_sig_or_failed_verdict(self):
  foreign={'channel':'C','world':'A','R':3,'m':3,'verdict':'ABSTAIN_LOW_SIG'}
  self.assertFalse(m.score_cell(foreign));self.assertTrue(m.score_cell({**foreign,'m':1,'verdict':'ABSTAIN_M1'}))
  self.assertFalse(m.score_cell({**foreign,'m':1,'null_invalid_seeds':[777]}))
  self.assertTrue(m.score_cell({**foreign,'channel':'A','verdict':'REAL_GAP'}))
  self.assertFalse(m.score_cell({**foreign,'channel':'A','m':2,'verdict':'REAL_GAP'}))
 def test_truth_never_enters_features_graphs(self):
  d=m.world(75,3,'A',777008);changed={**d,'truth':np.arange(75)[::-1],'R':5}
  for channel in m.CHANNELS:np.testing.assert_array_equal(m.graph(d,channel,10),m.graph(changed,channel,10))
 def test_no_OD_matrix_or_negative_index_accepted(self):
  d=m.world(75,3,'NONE',777009)
  for bad in (np.zeros((75,75)),np.full(75,-1.),np.full(75,np.nan)):
   with self.assertRaises(ValueError):m.channel_features({**d,'mobility_km_index':bad},'C')
 def receipt(self,p,passes=False):
  results={}
  for k in (10,20,40):
   cal=[{'R':R,'seed':seed,'m':R,'sig':2.,'raw_gap':.3,'status':'COMPUTED'} for R in (1,3,4,5) for seed in range(20261008,20261018)]
   held=[{'R':R,'seed':seed,'m':R,'sig':2.,'raw_gap':.3,'status':'COMPUTED','verdict':'ABSTAIN_M1' if R==1 else ('REAL_GAP' if passes else 'INCONCLUSIVE_CALIBRATION'),'shuffle_invalid_seeds':[],'shuffle_raw_gaps':[.1]*99} for R in (1,3,4,5) for seed in range(20261108,20261128)]
   results[str(k)]={'n':1896,'d':5,'k':k,'calibration':cal,'held':held,'fit':{'sig_star':1. if passes else None},'method_quality':'PASS_FIXED_CONTROLS' if passes else 'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'}
  r={'n':1896,'d':5,'results':results,'settings_sha256':'238ee8746c9de5b56033e00f41b3523ce41e2d2fb3fd15787cf73f4e08d14891','input_sha256':{'panel':'8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93','A5_mask':'12f40b15ee8f119cba7f386b5c9adf4babb5cff1bca2721dc04551d672f5e5d6'}};self.save(p,r);return r
 def save(self,p,r):
  (p/'result.json').write_text(json.dumps(r));(p/'manifest.json').write_text(json.dumps({'code_sha256':m.M1_SHA,'protocol_sha256':m.M1_PROTOCOL_SHA,'files_sha256':{'result.json':m.sha(p/'result.json')}}))
 def test_complete_actual_negative_unlocks_only_descriptive(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);self.receipt(p);dep=m.check_dependency(p/'result.json');self.assertFalse(dep['positive_scientific_qualification_allowed'])
   result=m.qualify({'state':'M4_CONFIRMED_SYNTHETIC_FIXED_BANK'},dep)
   self.assertTrue(result['bank_cell_requirements_all_pass']);self.assertFalse(result['positive_scientific_qualification']);self.assertFalse(result['scientific_economic_identity_pass']);self.assertIn('DESCRIPTIVE_ONLY',result['state'])
 def test_all_upstream_pass_does_not_override_negative_M4(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);self.receipt(p,True);dep=m.check_dependency(p/'result.json')
   self.assertTrue(dep['positive_scientific_qualification_allowed']);self.assertFalse(m.qualify({'state':'M4_NOT_CONFIRMED_FIXED_BANK'},dep)['positive_scientific_qualification'])
   self.assertTrue(m.qualify({'state':'M4_CONFIRMED_SYNTHETIC_FIXED_BANK'},dep)['positive_scientific_qualification'])
 def test_partial_or_duplicate_or_wrong_seed_is_blocked(self):
  for mode in ('partial','duplicate','wrongseed'):
   with tempfile.TemporaryDirectory() as t:
    p=Path(t);r=self.receipt(p);held=r['results']['10']['held']
    if mode=='partial':held.pop()
    elif mode=='duplicate':held[1]=held[0]
    else:held[0]['seed']=999999
    self.save(p,r)
    with self.assertRaisesRegex(ValueError,'exact seed records'):m.check_dependency(p/'result.json')
 def test_all99_nulls_accounted_including_invalid(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);r=self.receipt(p);x=r['results']['10']['held'][0];x['shuffle_raw_gaps'].pop();self.save(p,r)
   with self.assertRaisesRegex(ValueError,'complete99'):m.check_dependency(p/'result.json')
   x['shuffle_invalid_seeds']=[20261208+x['seed']*100];self.save(p,r);self.assertTrue(m.check_dependency(p/'result.json')['complete_verified_records'])
 def test_false_PASS_inconsistent_with_records_blocked(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);r=self.receipt(p);r['results']['10']['method_quality']='PASS_FIXED_CONTROLS';self.save(p,r)
   with self.assertRaisesRegex(ValueError,'quality disagrees'):m.check_dependency(p/'result.json')
 def test_hash_or_source_mismatch_blocks_even_full_records(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);self.receipt(p);(p/'result.json').write_text((p/'result.json').read_text()+' ')
   with self.assertRaisesRegex(ValueError,'output hash'):m.check_dependency(p/'result.json')
   self.receipt(p);manifest=json.loads((p/'manifest.json').read_text());manifest['code_sha256']='engineering PASS';(p/'manifest.json').write_text(json.dumps(manifest))
   with self.assertRaisesRegex(ValueError,'source/protocol'):m.check_dependency(p/'result.json')
 def test_nonfinite_nonnumeric_successful_gaps_are_not_complete(self):
  for bad in (None,float('nan'),float('inf'),'0.1',True):
   with tempfile.TemporaryDirectory() as t:
    p=Path(t);r=self.receipt(p,True);r['results']['10']['held'][0]['shuffle_raw_gaps']=[bad]*99;self.save(p,r)
    with self.assertRaisesRegex(ValueError,'finite numeric'):m.check_dependency(p/'result.json')
if __name__=='__main__':unittest.main()
