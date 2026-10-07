import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import a6_geometry_v3 as g
import a6_geometry_controls_v3 as controls

def test_covariance_threshold_and_anisotropy():
    rng=np.random.default_rng(17);pts=rng.normal(size=(60,5))*[5,.7,.3,.1,.04]
    r,cov=g.region_of_members(pts,pts.mean(0))
    assert np.linalg.eigvalsh(cov)[-1]/np.linalg.eigvalsh(cov)[0]>1000
    assert g.covariance_audit(pts,cov)['geometry']=='ellipsoid'
    _,small=g.region_of_members(pts[:9],pts[:9].mean(0))
    assert np.allclose(small,np.eye(5)*np.trace(small)/5)
    _,ten=g.region_of_members(pts[:10],pts[:10].mean(0))
    assert not np.allclose(ten,np.eye(5)*np.trace(ten)/5)

def test_covariance_rank_failure_audited_not_silent():
    pts=np.tile(np.arange(5.),(10,1));_,cov=g.region_of_members(pts,pts.mean(0))
    assert np.linalg.eigvalsh(cov).min()>=g.VAR_FLOOR*.999
    assert g.covariance_audit(pts,cov)['cov_eigenvalues_floored']==5
    with pytest.raises(ValueError):g.region_of_members(np.full((10,5),np.nan),np.zeros(5))

def test_overlap_independent_univariate_closed_form():
    for v1,v2,delta in [(1,1,0),(1,4,2),(.2,8,5)]:
        expected=np.sqrt(2*np.sqrt(v1*v2)/(v1+v2))*np.exp(-delta**2/(4*(v1+v2)))
        assert g.bc_cov([0],[[v1]],[delta],[[v2]])==pytest.approx(expected)

def test_overlap_symmetry_rotation_and_affine_invariance():
    a=np.array([[2,.4],[.4,.3]]);b=np.array([[.4,-.1],[-.1,3.]])
    u=np.array([0.,1.]);v=np.array([1.,0.]);h=np.array([[2.,.5],[-.4,3.]])
    ref=g.bc_cov(u,a,v,b)
    assert ref==pytest.approx(g.bc_cov(v,b,u,a))
    assert ref==pytest.approx(g.bc_cov(h@u,h@a@h.T,h@v,h@b@h.T))
    assert g.bc_cov(u,a,u,a)==pytest.approx(1.)
    with pytest.raises(np.linalg.LinAlgError):g.bc_cov(u,np.diag([1,-1]),v,b)

def test_mahalanobis_strict_boundary_and_long_axis():
    cov=np.diag([4.,.01]);pts=np.array([[4.9,0.],[0.,.26],[5.,0.],[0.,.25]])
    assert g.mahalanobis_inside(pts,np.zeros(2),cov,2.5).tolist()==[True,False,False,False]

def fixture_split(fraction=.7):
    # Parent geometry contains all points; two current children belong to it.
    z=np.zeros((20,2,2));z[:,0,0]=np.linspace(-1,1,20);z[:,1]=z[:,0]
    labs=[np.zeros(20,dtype=int),np.repeat([0,1],10)]
    ar=[{'month':'2023-01','ti':i,'label':0,'identity_id':'P','status':'initial'} for i in range(20)]
    ar += [{'month':'2023-02','ti':i,'label':int(labs[1][i]),'identity_id':'','status':'ambiguous'} for i in range(20)]
    rr=[{'month':'2023-01','cluster':0,'identity_id':'P','status':'initial','centre_0':0.,'centre_1':0.,'var':1.,'radius':1.,'cov_0_0':1.,'cov_0_1':0.,'cov_1_0':0.,'cov_1_1':1.}]
    for c in [0,1]:rr.append({**rr[0],'month':'2023-02','cluster':c,'identity_id':'','status':'ambiguous'})
    # six of ten child points inside yields exactly60%, which must abstain.
    for c in [0,1]:z[c*10+int(fraction*10):(c+1)*10,1,0]=4.
    return ['2023-01','2023-02'],labs,z,ar,rr

def test_m3_exact_sixty_percent_not_accepted():
    args=fixture_split(.6);events,_=g.detect_split_merge(*args)
    assert not any(e['kind']=='split_candidate' for e in events)
    args=fixture_split(.7);events,_=g.detect_split_merge(*args)
    assert sum(e['kind']=='split_candidate' for e in events)==1

def test_mahalanobis_proximity_does_not_replace_membership():
    args=list(fixture_split(1.));args[3]=[dict(r) for r in args[3]]
    for r in args[3]:
        if r['month']=='2023-01' and r['ti']>=10:r['identity_id']='OTHER'
    events,_=g.detect_split_merge(*args)
    assert not any(e['kind']=='split_candidate' for e in events)

def test_tracker_covariance_persistence_prefix_and_status():
    rng=np.random.default_rng(31);base=np.concatenate([rng.normal(-4,.1,(12,2)),rng.normal(4,.1,(12,2))])
    z=np.stack([base,base+.005,base+.01],axis=1);labs=[np.repeat([0,1],12)]*3
    cen=[np.stack([z[labs[m]==c,m].mean(0) for c in [0,1]]) for m in range(3)]
    full=g.track_identities(['2024-01','2024-02','2024-03'],labs,cen,z,np.arange(24),.1,.1,.05)
    short=g.track_identities(['2024-01','2024-02'],labs[:2],cen[:2],z[:,:2],np.arange(24),.1,.1,.05)
    assert [r for r in full[0] if r['month']!='2024-03']==short[0]
    controls.consistent_region_status(full[0],full[1])
    assert all(r['geometry']=='ellipsoid' and 'cov_0_1' in r for r in full[1])
    assert len([e for e in full[2] if e['kind']=='continuing'])==4

def test_calibration_2023_only_and_real_paired_margin():
    rng=np.random.default_rng(11);base=np.concatenate([rng.normal(-2,.1,(12,2)),rng.normal(2,.1,(12,2))]);z=np.stack([base,base,base],1);labs=[np.repeat([0,1],12)]*3
    a=g.calibrate_thresholds(z,labs,[0,1],17);z[:,2]*=10000;b=g.calibrate_thresholds(z,labs,[0,1],17)
    assert a==b and a['n_paired_margins']==800 and a['geometry_version']=='geometry-v3.1'
    assert a['candidate_margin']==max(0,a['paired_margin_quantiles']['q05'])

def test_missing_controls_not_pass_and_affine_generator_determinism():
    budget={'recognition_FDR_max':.01,'recognition_FNR_max':.05,'coverage_min':.95,'event_FDR_max':.05,'event_FNR_max':.1,'stable_drift_proximity_split_merge_false_events_max':0}
    assert controls.evaluate_budget([],budget)['status']=='INCONCLUSIVE'
    a,t,e=controls.world('split',controls.SEEDS[0]);b,t2,e2=controls.world('split',controls.SEEDS[0]);assert np.array_equal(a,b) and e==e2

def test_merge_strict_containment_and_composition():
    months=['2023-01','2023-02'];labs=[np.repeat([0,1],10),np.zeros(20,dtype=int)]
    z=np.zeros((20,2,2))
    ar=[{'month':months[0],'ti':i,'label':int(labs[0][i]),'identity_id':('P' if i<10 else 'Q'),'status':'initial'} for i in range(20)]
    ar += [{'month':months[1],'ti':i,'label':0,'identity_id':'','status':'ambiguous'} for i in range(20)]
    base={'centre_0':0.,'centre_1':0.,'var':1.,'radius':1.,'cov_0_0':1.,'cov_0_1':0.,'cov_1_0':0.,'cov_1_1':1.}
    rr=[{**base,'month':months[0],'cluster':c,'identity_id':i,'status':'initial'} for c,i in [(0,'P'),(1,'Q')]]+[{**base,'month':months[1],'cluster':0,'identity_id':'','status':'ambiguous'}]
    z[6:10,0,0]=4.;z[16:20,0,0]=4.
    events,_=g.detect_split_merge(months,labs,z,ar,rr)
    assert not any(e['kind']=='merge_candidate' for e in events)
    z[6,0,0]=0.;z[16,0,0]=0.
    events,_=g.detect_split_merge(months,labs,z,ar,rr)
    assert sum(e['kind']=='merge_candidate' for e in events)==1

def test_new_first_birth_status_and_small_sphere_serialization():
    rng=np.random.default_rng(19);pts=rng.normal(0,.01,(8,2));z=np.stack([pts,pts+100],1);labs=[np.zeros(8,dtype=int)]*2;cen=[np.array([z[:,m].mean(0)]) for m in range(2)]
    ar,rr,events=g.track_identities(['2024-01','2024-02'],labs,cen,z,np.arange(8),.55,.3,.25)
    assert rr[-1]['status']=='birth' and rr[-1]['geometry']=='small_cluster_sphere'
    assert sum(e['kind']=='birth' for e in events)==1
    controls.consistent_region_status(ar,rr)

def test_duplicate_archive_keys_and_output_overwrite_fail_closed(tmp_path):
    import pandas as pd
    # Output directory is guarded before touching any data.
    with pytest.raises(FileExistsError):g.run_pipeline(pd.DataFrame(),tmp_path,17)
    # Nonfinite and empty geometry rejected, never zero-filled.
    with pytest.raises(ValueError):g.region_of_members(np.empty((0,2)),np.zeros(2))

def test_real_panel_replay_rejects_duplicate_and_missing_keys(tmp_path):
    import pandas as pd
    import a6_identities as legacy
    panel=legacy._toy_panel(n_tid=36,months=['2023-01','2023-02'])
    # Matching row count is insufficient if keys contain a duplicate.
    tids,months,_,_=g.build_monthly_shares(panel)
    data=[{'territory_id':int(t),'month':m,'label':int(i>=len(tids)//2)} for m in months for i,t in enumerate(tids)]
    data[0]=dict(data[1]);bad=pd.DataFrame(data)
    with pytest.raises(ValueError,match='key mismatch'):
        g.run_pipeline(panel,tmp_path/'new',17,bad)
    assert not (tmp_path/'new').exists()
