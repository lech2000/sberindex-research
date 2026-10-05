"""Scientific fixtures and an independent scalar audit of S_Dbw.

No call to production helper/count logic in reference calculation.
Audit real saved assignments by row-key join; report components and all
density counts, not just final score. Run directly (no pytest dependency).
"""
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from a7_sdbw import s_dbw


def reference(x, labels, domain="pair_union"):
    rows = [[float(v) for v in row] for row in x]
    keys = sorted(set(labels))
    groups = [[row for row, lab in zip(rows, labels) if lab == key] for key in keys]
    d, k = len(rows[0]), len(groups)
    def mean(g):
        return [math.fsum(row[q] for row in g) / len(g) for q in range(d)]
    def varnorm(g):
        centre = mean(g)
        variances = [math.fsum((row[q] - centre[q])**2 for row in g) / len(g) for q in range(d)]
        return math.sqrt(math.fsum(v*v for v in variances))
    centres = [mean(g) for g in groups]
    v = [varnorm(g) for g in groups]
    radius = math.sqrt(math.fsum(v)) / k
    scatter = math.fsum(v) / k / varnorm(rows)
    def count(g, centre):
        return sum(math.dist(row, centre) <= radius for row in g)
    counts, terms = [], []
    for i in range(k):
        for j in range(i + 1, k):
            pool = groups[i] + groups[j]
            mid = [(a+b)/2 for a,b in zip(centres[i],centres[j])]
            num = count(pool,mid)
            di=count(pool if domain=="pair_union" else groups[i],centres[i])
            dj=count(pool if domain=="pair_union" else groups[j],centres[j])
            counts.append((num,di,dj))
            terms.append(num/max(di,dj) if max(di,dj) else None)
    density = None if None in terms else math.fsum(terms)/len(terms)
    return scatter, radius, density, counts


def fixtures():
    checks=[]
    x=np.array([[-1.],[0.],[1.],[9.],[10.],[11.]])
    y=np.array([0,0,0,1,1,1])
    r=s_dbw(x,y)
    assert math.isclose(r['scat'],2/77,rel_tol=1e-14)
    assert math.isclose(r['radius'],1/math.sqrt(3),rel_tol=1e-14)
    assert r['dens_bw']==0 and math.isclose(r['s_dbw'],2/77)
    checks.append('hand_calculated_1D_scat_radius_density')
    overlap=np.array([[-1.],[0.],[1.],[-1.],[0.],[1.]])
    u=s_dbw(overlap,y,'pair_union');o=s_dbw(overlap,y,'own_cluster')
    assert u['scat']==1 and u['dens_bw']==1 and u['s_dbw']==2
    assert o['dens_bw']==2 and o['s_dbw']==3
    checks.append('overlap_known_density_domains_distinct')
    sparse=s_dbw(np.array([[0.],[1.],[10.],[11.]]),[0,0,1,1])
    assert sparse['s_dbw'] is None and sparse['undefined_pairs']==1
    checks.append('zero_density_denominator_is_NA_not_zero')
    single=s_dbw(np.array([[-1.],[0.],[1.],[10.]]),[0,0,0,1])
    assert single['singleton_clusters']==1 and single['status']=='COMPUTED'
    checks.append('singleton_retained_flagged_not_imputed')
    for bad, lab in [(np.ones((4,2)),[0,0,1,1]),(x,[0]*6),(x,list(range(6))),
                     (np.array([[0.],[np.nan],[10.]]),[0,0,1]),(x,[0,0,0,1,1,None])]:
        try:s_dbw(bad,lab)
        except ValueError:pass
        else:raise AssertionError('invalid input accepted')
    checks.append('invalid_missing_and_degenerate_inputs_rejected')
    p=np.array([5,0,3,2,4,1])
    for xx,yy in [(x[p],y[p]+17),(x+37,y),(x*11,y)]:
        assert math.isclose(s_dbw(xx,yy)['s_dbw'],r['s_dbw'],rel_tol=1e-12)
    checks.append('row_label_translation_uniform_scale_invariance')
    # Stable synthetic examples include unequal groups and multidimensional data.
    for seed in range(4):
        rng=np.random.default_rng(seed)
        xx=np.r_[rng.normal(0,.2,(41,3)),rng.normal(1,.4,(37,3)),rng.normal(3,.1,(29,3))]
        yy=np.r_[np.zeros(41,int),np.ones(37,int),np.full(29,2,int)]
        for domain in ['pair_union','own_cluster']:
            got=s_dbw(xx,yy,domain);sc,rad,de,counts=reference(xx,yy,domain)
            assert math.isclose(got['scat'],sc,rel_tol=1e-12)
            assert math.isclose(got['radius'],rad,rel_tol=1e-12)
            assert np.allclose([(p['density_midpoint'],p['density_i'],p['density_j']) for p in got['pairs']],counts)
            assert (got['dens_bw'] is None and de is None) or math.isclose(got['dens_bw'],de,abs_tol=1e-14)
    checks.append('independent_scalar_reference_4_seeds_2_conventions')
    return checks


def real_audit(a5, run):
    f=pd.read_parquet(a5/'features.parquet');a=pd.read_parquet(a5/'assignments.parquet')
    data=f.merge(a,on='territory_id',validate='one_to_one').sort_values('territory_id')
    metrics=json.loads((run/'metrics.json').read_text());protocol=json.loads((run/'protocol.json').read_text())
    x=data[protocol['feature_columns']].to_numpy();audits=[]
    for method, entry in metrics['methods'].items():
        y=data['label_'+method].tolist()
        for domain,key in [('pair_union','primary'),('own_cluster','own_cluster_sensitivity')]:
            got=entry[key];sc,rad,de,counts=reference(x,y,domain)
            assert math.isclose(got['scat'],sc,rel_tol=1e-12)
            assert math.isclose(got['radius'],rad,rel_tol=1e-12)
            assert counts==[(p['density_midpoint'],p['density_i'],p['density_j']) for p in got['pairs']]
            assert (got['dens_bw'] is None and de is None) or math.isclose(got['dens_bw'],de,rel_tol=1e-12,abs_tol=1e-14)
            audits.append({'method':method,'convention':domain,'pairs_checked':len(counts),'counts_exact':True,
                           'components_match_rtol':1e-12})
    return audits


if __name__=='__main__':
    result={'fixtures_passed':fixtures()}
    if len(sys.argv)==3:
        result['real_audit']=real_audit(Path(sys.argv[1]),Path(sys.argv[2]))
    print(json.dumps(result,indent=2,allow_nan=False))
