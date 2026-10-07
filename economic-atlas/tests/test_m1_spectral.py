import importlib.util
from pathlib import Path
import unittest
import tempfile,subprocess,sys,os,json
import numpy as np
S=Path(__file__).resolve().parents[1]/'src/atlas_m1_spectral.py'
spec=importlib.util.spec_from_file_location('m1',S);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class M1Tests(unittest.TestCase):
    def test_symmetry_budget_and_cosine_unit_invariance(self):
        x=m.world(45,5,1,777);w=m.graph(x,10)
        np.testing.assert_array_equal(w,w.T)
        self.assertEqual(np.count_nonzero(np.triu(w,1)),45*10//2)
        self.assertFalse(w.diagonal().any())
        np.testing.assert_array_equal(w,m.graph(x*np.arange(1,46)[:,None],10))

    def test_positive_block_spectrum_independent_operator(self):
        w=np.zeros((30,30))
        for start in (0,10,20): w[start:start+10,start:start+10]=1
        np.fill_diagonal(w,0)
        r,values,_=m.spectrum(w)
        independent=np.linalg.eigvals(w/w.sum(1)[:,None]).real
        np.testing.assert_allclose(values,np.sort(independent)[::-1],atol=1e-12)
        self.assertEqual(r['m'],3)
        self.assertAlmostEqual(r['raw_gap'],1+1/9)
        self.assertIsNone(r['sig']) # constant full bulk must not produce infinite significance
        self.assertEqual(r['status'],'DEGENERATE_BULK')

    def test_complete_noise_abstains(self):
        r,_,_=m.spectrum(np.ones((20,20))-np.eye(20))
        self.assertEqual(r['m'],1)
        self.assertEqual(m.verdict(r,None,np.array([]),[]),'ABSTAIN_M1')

    def test_graph_isolate_not_bridged(self):
        w=np.ones((8,8))-np.eye(8);w[0,:]=0;w[:,0]=0
        r,v,e=m.spectrum(w)
        self.assertEqual(r['status'],'INCONCLUSIVE_GRAPH_ISOLATE');self.assertIsNone(v)
        self.assertEqual(m.verdict(r,2,np.ones(99),[]),'INCONCLUSIVE_GRAPH_ISOLATE')

    def test_threshold_exact_separation_and_failure(self):
        self.assertEqual(m.threshold([8.,9.],[2.,4.])['sig_star'],6.)
        self.assertIsNone(m.threshold([4.],[4.])['sig_star'])
        self.assertIsNone(m.threshold([None],[1.])['sig_star'])
        self.assertIsNone(m.threshold([],[])['sig_star'])

    def test_raw_gap_strict_p95_and_sig_gates(self):
        r={'m':3,'sig':8.,'raw_gap':.5}
        self.assertEqual(m.verdict(r,4,np.full(99,.5),[]),'ABSTAIN_NULL_GAP')
        self.assertEqual(m.verdict(r,4,np.full(99,.49),[]),'REAL_GAP')
        self.assertEqual(m.verdict(r,9,np.full(99,.01),[]),'ABSTAIN_LOW_SIG')
        self.assertEqual(m.verdict(r,None,np.full(99,.01),[]),'INCONCLUSIVE_CALIBRATION')
        self.assertEqual(m.verdict(r,4,np.full(98,.01),[99]),'INCONCLUSIVE_SHUFFLE')

    def test_shuffle_column_permutation_not_row_renaming(self):
        x=m.world(40,5,1,888);seeds=[101,102]
        gaps,invalid=m.null_gaps(x,10,.95,seeds)
        expected=[];bad=[]
        for seed in seeds:
            rng=np.random.default_rng(seed)
            y=np.stack([x[rng.permutation(len(x)),j] for j in range(5)],axis=1)
            for j in range(5):np.testing.assert_array_equal(np.sort(x[:,j]),np.sort(y[:,j]))
            r,_,_=m.spectrum(m.graph(y,10))
            if r['raw_gap'] is None:bad.append(seed)
            else:expected.append(r['raw_gap'])
        np.testing.assert_allclose(gaps,expected);self.assertEqual(invalid,bad)

    def test_invalid_inputs_rejected(self):
        for x in (np.array([[1.,0],[0,0],[0,1]]),np.array([[1.,0],[0,np.nan],[0,1]]),np.array([[-1.,0],[0,1],[1,1]])):
            with self.assertRaises(ValueError):m.graph(x,1)
        with self.assertRaises(ValueError):m.spectrum(np.array([[0,1,0],[0,0,1],[1,0,0]]))

    def test_control_shape_density_and_no_hidden_real_features(self):
        for R in (1,3,4,5):
            x=m.world(60,5,R,44)
            self.assertEqual(x.shape,(60,5));np.testing.assert_allclose(x.sum(1),.72)
            self.assertTrue((x>0).all())
            for k in (10,20,40):self.assertEqual(np.count_nonzero(np.triu(m.graph(x,k),1)),60*k//2)
        with self.assertRaises(ValueError):m.world(60,4,3,44)

    def test_full_bulk_std_not_truncated_eigen_tail(self):
        x=m.world(45,5,1,908);r,vals,_=m.spectrum(m.graph(x,10))
        self.assertAlmostEqual(r['bulk_spread'],np.std(vals[r['m']:]))
        self.assertTrue(np.all(vals<=1+1e-12));self.assertTrue(np.all(vals>=-1-1e-12))

    def test_spectral_assignment_uses_actual_selected_K(self):
        x=m.world(60,5,3,900);r,vals,v=m.spectrum(m.graph(x,10))
        lab=m.labels(v,3,12)
        self.assertEqual(len(np.unique(lab)),3)
        self.assertEqual(lab.shape,(60,))

    def test_cli_rejects_changed_protocol_before_computation(self):
        protocol=Path(__file__).resolve().parents[1]/'protocols/M1_PROSPECTIVE_V1.json'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'protocol.json'
            value=json.loads(protocol.read_text());value['graph_k']=[10]
            path.write_text(json.dumps(value))
            run=subprocess.run([sys.executable,str(S),'--phase','calibrate','--repo',directory,'--protocol',str(path),'--outdir',str(Path(directory)/'out')],capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0)
            self.assertIn('modified frozen protocol',run.stderr)
            self.assertFalse((Path(directory)/'out').exists())

    def test_cli_never_overwrites_existing_run(self):
        protocol=Path(__file__).resolve().parents[1]/'protocols/M1_PROSPECTIVE_V1.json'
        with tempfile.TemporaryDirectory() as directory:
            sentinel=Path(directory)/'unchanged';sentinel.write_text('legacy')
            env=dict(os.environ)
            for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):env[name]='1'
            run=subprocess.run([sys.executable,str(S),'--phase','calibrate','--repo',directory,'--protocol',str(protocol),'--outdir',directory],capture_output=True,text=True,env=env)
            self.assertNotEqual(run.returncode,0);self.assertIn('FileExistsError',run.stderr)
            self.assertEqual(sentinel.read_text(),'legacy')

if __name__=='__main__':unittest.main()
