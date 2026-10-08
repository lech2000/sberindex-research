"""Small formula/boundary/generator fixtures; no fit/bootstrap/full bank/real replay."""
import os,sys,unittest
from pathlib import Path
from unittest.mock import patch
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1';sys.dont_write_bytecode=True
D=Path(__file__).resolve().parents[1]
sys.path.insert(0,'/private/tmp/sberindex-official-laws-20261007/economic-atlas/src')
sys.path.insert(0,str(D/'economic-atlas/src'))
import numpy as np
import a6_geometry_original_scope_v4 as g
import a6_geometry_original_controls_v4 as c
class Original(unittest.TestCase):
 def test_sphere_covariance_r_squared_not_divided_by_dimension(self):
  x=np.array([[-1.,0],[1.,0]])
  radius,cov=g.region_of_members(x,np.array([999.,999.]))
  self.assertEqual(radius,1);np.testing.assert_array_equal(cov,np.eye(2))
 def test_sphere_boundary_strict_euclidean(self):
  inside=g.region_inside(np.array([[2.5,0],[2.499,0]]),np.zeros(2),np.eye(2),1,2,2.5)
  self.assertEqual(inside.tolist(),[False,True])
 def test_ellipsoid_boundary_strict(self):
  self.assertEqual(g.region_inside(np.array([[5.,0],[4.999,0]]),np.zeros(2),np.diag([4.,1.]),99,10,2.5).tolist(),[False,True])
 def test_member_mean_replaces_fitted_centre(self):
  x=np.array([[-1.,0],[1.,0]])
  _,rr,_=g.track_identities(['2023-01'],[np.zeros(2,int)],[np.array([[99.,99.]])],x[:,None,:],np.arange(2),.5,.3,.1)
  self.assertEqual((rr[0]['centre_0'],rr[0]['centre_1']),(0.,0.))
 def test_margin_equality_recognised_and_rolling_state_used(self):
  x=np.array([[-1.,0],[1.,0]]);z=np.stack([x,x+[1.,0],x+[2.,0]],axis=1);calls=[]
  def bc(mu,cov,old,oldcov):calls.append(old.copy());return 1.
  with patch.object(g,'bc_cov',side_effect=bc):
   ar,rr,ev=g.track_identities(['2023-01','2023-02','2023-03'],[np.zeros(2,int)]*3,[np.zeros((1,2))]*3,z,np.arange(2),1.,1.,.1)
  self.assertEqual([r['status'] for r in rr],['initial','continuing','continuing']);np.testing.assert_allclose(calls,[np.array([0.,0]),np.array([.5,0])])
 def test_rolling_radius_sphere_covariance_consistent(self):
  old={'mu':np.array([0.,0]),'var':np.eye(2),'radius':1.};new={'mu':np.array([2.,0]),'var':np.eye(2)*9,'rms':3.,'size':2}
  value=g.rolling_region(old,new);self.assertEqual(value['radius'],2);np.testing.assert_array_equal(value['mu'],[1,0]);np.testing.assert_array_equal(value['var'],np.eye(2)*4)
 def test_birth_does_not_abstain_at_Tc(self):
  x=np.array([[-1.,0],[1.,0]]);z=np.stack([x,x+10],axis=1)
  with patch.object(g,'bc_cov',return_value=.3):
   _,rr,_=g.track_identities(['2023-01','2023-02'],[np.zeros(2,int)]*2,[np.zeros((1,2))]*2,z,np.arange(2),.5,.1,.1)
  self.assertEqual(rr[-1]['status'],'birth')
 def region(self,month,cluster,iid='',status='ambiguous',centre=(0.,0),cov=100.,size=10):
  return {'month':month,'cluster':cluster,'identity_id':iid,'status':status,'size':size,'radius':10.,'centre_0':centre[0],'centre_1':centre[1],'cov_0_0':cov,'cov_1_1':cov,'cov_0_1':0.,'cov_1_0':0.}
 def test_m3_previous_unrecognised_cluster_not_excluded(self):
  labs=[np.zeros(20,int),np.array([0]*10+[1]*10)];z=np.zeros((20,2,2));z[:10,1,0]=-1;z[10:,1,0]=1
  rr=[self.region('p',0),self.region('c',0,cov=.1),self.region('c',1,cov=.1)]
  ev,_=g.detect_split_merge(['p','c'],labs,z,[],rr,.5);self.assertTrue(any(e['kind']=='split_candidate' for e in ev))
 def test_m3_containment_exact_point_six_abstains(self):
  labs=[np.zeros(20,int),np.array([0]*10+[1]*10)];z=np.zeros((20,2,2));z[[6,7,8,9,16,17,18,19],1,0]=100
  rr=[self.region('p',0,cov=1),self.region('c',0),self.region('c',1)]
  ev,_=g.detect_split_merge(['p','c'],labs,z,[],rr,.5);self.assertFalse(any(e['kind']=='split_candidate' for e in ev))
 def test_split_with_recognised_single_continuation_excluded(self):
  labs=[np.zeros(20,int),np.array([0]*10+[1]*10)];z=np.zeros((20,2,2))
  rr=[self.region('p',0,'parent'),self.region('c',0,'parent','continuing'),self.region('c',1)]
  ev,_=g.detect_split_merge(['p','c'],labs,z,[],rr,.5);self.assertFalse(any(e['kind']=='split_candidate' for e in ev))
 def test_overlap_threshold_veto_independent_margin_failure_and_ID(self):
  labs=[np.zeros(20,int),np.array([0]*10+[1]*10)];z=np.zeros((20,2,2))
  rr=[self.region('p',0),self.region('c',0,status='ambiguous'),self.region('c',1,status='ambiguous')]
  ev,_=g.detect_split_merge(['p','c'],labs,z,[],rr,.5)
  self.assertFalse(any(e['kind']=='split_candidate' for e in ev))
 def test_overlap_equal_T_vetoes_split(self):
  labs=[np.zeros(20,int),np.array([0]*10+[1]*10)];z=np.zeros((20,2,2))
  rr=[self.region('p',0),self.region('c',0),self.region('c',1)]
  with patch.object(g,'bc_cov',return_value=.5):ev,_=g.detect_split_merge(['p','c'],labs,z,[],rr,.5)
  self.assertFalse(any(e['kind']=='split_candidate' for e in ev))
 def test_part_whole_split_and_merge_conserve_points(self):
  for world in ['split','merge']:
   z,truth,events=c.world(world,20271001)
   self.assertEqual(z.shape,(200,24,5));np.testing.assert_array_equal(z[:,13],z[:,14]);np.testing.assert_array_equal(z,np.repeat(z[:,:1],24,axis=1));self.assertNotEqual(truth[13].tolist(),truth[14].tolist());self.assertTrue(all(m>=12 for m,*_ in events))
 def test_controls_deterministic_no_mutable_alias(self):
  z,t,e=c.world('split',20271001);z2,t2,e2=c.world('split',20271001);np.testing.assert_array_equal(z,z2);self.assertEqual(e,e2);z[:,0]=999;self.assertFalse(np.array_equal(z[:,0],z[:,1]))
class BootstrapCorrection(unittest.TestCase):
 def test_midpoints_both_strictly_between(self):
  r=g.threshold_summary([.9]*10,[.1]*10,[.8]*10,[.1]*10)
  self.assertEqual(r['calibration_status'],'SEPARATED');self.assertAlmostEqual(r['overlap_threshold'],.5);self.assertAlmostEqual(r['candidate_margin'],.45)
  self.assertEqual(r['raw_distributions']['negative_gap'],[.1]*10)
 def test_overlap_and_equality_never_fallback(self):
  for own,other,pos,neg in [([.1],[.1],[.8],[.1]),([.05],[.1],[.8],[.1]),([.9],[.1],[.1],[.1]),([.9],[.1],[.05],[.1])]:
   r=g.threshold_summary(own,other,pos,neg);self.assertEqual(r['calibration_status'],'INCONCLUSIVE');self.assertFalse(r['recognition_qualified']);self.assertTrue(r['overlap_threshold'] is None or r['candidate_margin'] is None);self.assertFalse(r['fallback'])
 def test_missing_nonfinite_bool_failclosed_json(self):
  import json
  for v in [[],[float('nan')],[float('inf')],[True],['.9']]:
   r=g.threshold_summary(v,[.1],[.8],[.1]);self.assertEqual(r['calibration_status'],'INCONCLUSIVE');json.dumps(r,allow_nan=False)
 def test_missing_competitor_no_invented_negative_gap(self):
  z=np.zeros((10,1,2))
  with patch.object(g,'BOOT_B',1):r=g.calibrate_thresholds(z,[np.zeros(10,int)],[0],7)
  self.assertEqual(r['counts']['self'],1);self.assertEqual(r['counts']['negative_gap'],0);self.assertEqual(r['calibration_status'],'INCONCLUSIVE')
 def test_bootstrap_excludes_true_and_second_zero_for_one(self):
  z=np.zeros((20,1,2));z[10:,:,0]=10;lab=np.array([0]*10+[1]*10)
  with patch.object(g,'BOOT_B',1),patch.object(g,'bc_cov',side_effect=[.9,.2,.8,.3]):
   r=g.calibrate_thresholds(z,[lab],[0],7)
  np.testing.assert_allclose(r['raw_distributions']['positive_gap'],[.7,.5]);np.testing.assert_allclose(r['raw_distributions']['negative_gap'],[.2,.3]);self.assertEqual(r['counts']['other'],2)
 def test_negative_best_minus_second_two_competitors(self):
  z=np.zeros((30,1,2));lab=np.repeat(np.arange(3),10)
  with patch.object(g,'BOOT_B',1),patch.object(g,'bc_cov',side_effect=[.9,.3,.1,.9,.4,.2,.9,.2,.1]):
   r=g.calibrate_thresholds(z,[lab],[0],7)
  np.testing.assert_allclose(r['raw_distributions']['negative_gap'],[.2,.2,.1]);self.assertEqual(r['counts']['other'],6);self.assertEqual(r['counts']['negative_gap'],3)
 def test_unknown_calibration_preserves_entire_mask_no_birth_or_identity(self):
  z=np.zeros((20,3,2));labs=[np.repeat(np.arange(2),10)]*3
  ar,rr,ev=g.track_identities(['a','b','c'],labs,[np.zeros((2,2))]*3,z,np.arange(20),None,None,None)
  self.assertEqual(len(ar),60);self.assertEqual(len(rr),6);self.assertTrue(all(r['identity_id']=='' and r['status']=='calibration_unknown' for r in ar));self.assertTrue(all(e['kind']=='calibration_unknown' for e in ev));self.assertTrue(all('cov_1_1' in r for r in rr))
 def test_unknown_T_retains_unqualified_m3_geometry(self):
  labs=[np.zeros(20,int),np.repeat(np.arange(2),10)];z=np.zeros((20,2,2));z[:10,1,0]=-1;z[10:,1,0]=1
  rr=[Original().region('p',0),Original().region('c',0,cov=.1),Original().region('c',1,cov=.1)]
  ev,s=g.detect_split_merge(['p','c'],labs,z,[],rr,None)
  self.assertTrue(any(e['kind']=='split_geometry_unqualified' for e in ev));self.assertFalse(any(e['kind']=='split_candidate' for e in ev));self.assertTrue(all(v['calibration_status']=='INCONCLUSIVE' for v in s.values()))
class ReceiptAndDenominator(unittest.TestCase):
 def test_receipt_threshold_tamper_rejected(self):
  cal=g.threshold_summary([.9],[.1],[.8],[.1]);cal['cal_months']=list(range(12));g.validate_calibration(cal)
  for key,value in [('overlap_threshold',.1),('calibration_status','INCONCLUSIVE'),('counts',{})]:
   r=dict(cal);r[key]=value
   with self.assertRaises(ValueError):g.validate_calibration(r)
 def test_missing_raw_pools_rejected(self):
  cal=g.threshold_summary([.9],[.1],[.8],[.1]);cal['cal_months']=list(range(12));del cal['raw_distributions']['negative_gap']
  with self.assertRaises(ValueError):g.validate_calibration(cal)
 def test_inconclusive_retains_all_recognition_misses_and_event_truth(self):
  labs=[np.array([0,1])]*24;truth=[np.array(['A','B'])]*24
  rr=[{'month':c.MONTHS[m],'cluster':i,'identity_id':'','status':'calibration_unknown'} for m in range(24) for i in range(2)]
  counts,events,*_=c.score(labs,truth,[(14,'split_candidate','A',('A1','A2'))],rr,[])
  self.assertEqual(counts['fn'],46);self.assertEqual(counts['cluster_decisions'],46);self.assertEqual(counts['abstentions'],46);self.assertEqual(events['fn'],1);self.assertIsNone(c.rates(counts)['fdr_all_predicted_matches'])
class IndependentThresholdSeparation(unittest.TestCase):
 def test_M_failure_does_not_erase_independently_valid_T(self):
  r=g.threshold_summary([.9],[.1],[.1],[.1]);self.assertAlmostEqual(r['overlap_threshold'],.5);self.assertIsNone(r['candidate_margin']);self.assertFalse(r['recognition_qualified'])
 def test_missing_negative_gap_keeps_T_but_blocks_M2(self):
  r=g.threshold_summary([.9],[.1],[.8],[]);self.assertAlmostEqual(r['overlap_threshold'],.5);self.assertIsNone(r['candidate_margin']);self.assertEqual(r['calibration_status'],'INCONCLUSIVE')
if __name__=='__main__':unittest.main()
