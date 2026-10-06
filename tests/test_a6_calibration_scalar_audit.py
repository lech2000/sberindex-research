import importlib.util
from pathlib import Path
import numpy as np
from scipy.integrate import quad
from scipy.stats import norm

spec=importlib.util.spec_from_file_location('calibration_audit',Path(__file__).parents[1]/'economic-atlas/src/audit_a6_calibration_source.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def test_overlap_matches_direct_density_quadrature_and_translation():
    for mu1,v1,mu2,v2 in [(0.,1.,2.,1.),(-2.,.3,1.,4.),(1.,2.,1.,2.)]:
        numeric=quad(lambda x:np.sqrt(norm.pdf(x,mu1,np.sqrt(v1))*norm.pdf(x,mu2,np.sqrt(v2))),-np.inf,np.inf,epsabs=1e-12)[0]
        analytic=audit.overlap(np.array([mu1]),v1,np.array([mu2]),v2)
        translated=audit.overlap(np.array([mu1+1e3]),v1,np.array([mu2+1e3]),v2)
        np.testing.assert_allclose(analytic,numeric,rtol=1e-10,atol=1e-12)
        np.testing.assert_allclose(translated,analytic,rtol=1e-12,atol=1e-12)
