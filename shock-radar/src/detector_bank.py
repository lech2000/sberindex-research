"""D01-MV bank entry: six audited multivariate channels, no retuning.

Legacy univariate D01/D02/D03 remain a separate bank. Do not combine their
null budgets with this bank or call selected real alerts false positives.
"""
from pathlib import Path
import argparse,json,subprocess,sys,hashlib
import numpy as np
from multicategory_shocks import METHODS,scores

REGISTRY = {
 'bank_id':'D01-MV-v2','source_protocol':'D04_multicategory_20261004',
 'channels':METHODS,'input':'five-category causal standardized monthly log changes',
 'stouffer':'sum(z)/sqrt(d); lower-tail and two-sided channels',
 'glr':'max over trailing windows 1,2,3 of (sum(net))**2/window',
 'null':'correlated Gaussian and t5 AR(1); empirical calibration',
 'real_budget':'24 selected alerts/month/channel with 3-month cooldown',
 'legacy_univariate_bank':'unchanged, separate input and calibration',
 'scientific_pass':False
}

def score_bank(z,precision):
 result=scores(z,precision)
 if list(result)!=METHODS:raise AssertionError('Bank registry and implementation differ')
 return result

def self_check():
 z=np.zeros((1,5,2));z[0,1]=[-2,2]
 v=score_bank(z,np.eye(2))
 assert v['stouffer_two_sided'][0,1]==0 and v['energy'][0,1]==4
 z[:]=1;v=score_bank(z,np.eye(2))
 np.testing.assert_allclose(v['glr_two_sided'][0],[2,4,6,6,6])
 altered=z.copy();altered[:,3:]*=100
 w=score_bank(altered,np.eye(2))
 for k in METHODS:np.testing.assert_array_equal(v[k][:,:3],w[k][:,:3])
 print(json.dumps({'passed':True,'checks':['opposed signs cancel in Stouffer','GLR trailing-window scalar values','future mutation all six channels']}))

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--raw',type=Path);p.add_argument('--dictionary',type=Path);p.add_argument('--out',type=Path)
 p.add_argument('--self-check',action='store_true');a=p.parse_args()
 if a.self_check:self_check();return
 if not all([a.raw,a.dictionary,a.out]):p.error('--raw --dictionary --out required')
 subprocess.run([sys.executable,str(Path(__file__).with_name('multicategory_shocks.py')),'--raw',str(a.raw),'--dictionary',str(a.dictionary),'--out',str(a.out)],check=True)
 reg=dict(REGISTRY,verified_at_source_sha256=hashlib.sha256(Path(__file__).with_name('multicategory_shocks.py').read_bytes()).hexdigest())
 (a.out/'bank-registry.json').write_text(json.dumps(reg,ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':main()
