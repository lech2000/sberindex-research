"""Prospective M1: same-size spectral count, calibrated abstention and raw-gap null.

No historical run is overwritten. CLI phases: calibrate, replay. Full spectra
make tail spread exact; real replay never recalibrates or chooses best k.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode = True
FROZEN_PROTOCOL_SHA256 = 'fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30'
import numpy as np
from scipy.linalg import eigh
from scipy.sparse.csgraph import connected_components
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, calinski_harabasz_score


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()


def clean(x):
    if isinstance(x, dict): return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (tuple, list, np.ndarray)): return [clean(v) for v in x]
    if isinstance(x, np.generic): return clean(x.item())
    if isinstance(x, float) and not np.isfinite(x): return None
    return x


def write(path, x):
    Path(path).write_text(json.dumps(clean(x), ensure_ascii=False, allow_nan=False, indent=2) + '\n')


def graph(x, k):
    """Symmetric binary sparsified cosine-kNN graph with exact edge budget."""
    x = np.asarray(x, float)
    n = len(x)
    if x.ndim != 2 or not np.isfinite(x).all() or (x < 0).any():
        raise ValueError('finite nonnegative 2-D shares required')
    if not 1 <= k < n or (np.linalg.norm(x, axis=1) == 0).any():
        raise ValueError('invalid k or zero cosine vector')
    z = x / np.linalg.norm(x, axis=1, keepdims=True)
    cos = np.clip(z @ z.T, -1, 1)
    np.fill_diagonal(cos, -np.inf)
    # Stable ties resolve to ascending original row index.
    neighbours = np.argsort(-cos, axis=1, kind='stable')[:, :k]
    candidates = set()
    for i, row in enumerate(neighbours):
        candidates.update((min(i, int(j)), max(i, int(j))) for j in row)
    ordered = sorted(candidates, key=lambda ij: (-cos[ij], ij[0], ij[1]))
    edge_budget = n * k // 2
    if len(ordered) < edge_budget: raise ValueError('insufficient union edges')
    W = np.zeros((n, n), float)
    for i, j in ordered[:edge_budget]: W[i, j] = W[j, i] = 1.
    return W


def spectrum(W, tau=.95):
    W = np.asarray(W, float)
    if W.ndim != 2 or W.shape[0] != W.shape[1] or len(W) < 3:
        raise ValueError('square graph with >=3 nodes required')
    if not np.isfinite(W).all() or (W < 0).any() or not np.allclose(W, W.T) or np.diag(W).any():
        raise ValueError('finite symmetric nonnegative zero-diagonal graph required')
    degree = W.sum(axis=1)
    meta = {'n': len(W), 'edges': int(np.count_nonzero(np.triu(W, 1))),
            'density': float(np.count_nonzero(W) / (len(W) * (len(W)-1))),
            'isolates': int(np.count_nonzero(degree == 0)),
            'components': int(connected_components(W, directed=False, return_labels=False))}
    if meta['isolates']:
        return {**meta, 'status':'INCONCLUSIVE_GRAPH_ISOLATE', 'm':None, 'sig':None, 'raw_gap':None}, None, None
    norm = W / np.sqrt(degree[:, None] * degree[None, :])
    vals, vectors = eigh(norm, check_finite=False)
    vals, vectors = vals[::-1], vectors[:, ::-1]
    if not np.isclose(vals[0], 1., atol=1e-10): raise ValueError('lambda1 invariant violated')
    m = int(np.count_nonzero(vals >= tau))
    if not 1 <= m < len(vals):
        return {**meta, 'status':'INCONCLUSIVE_NO_BULK', 'm':m, 'sig':None, 'raw_gap':None}, vals, vectors
    gap = float(vals[m-1] - vals[m]); spread = float(np.std(vals[m:], ddof=0))
    sig = None if spread <= 1e-12 else gap / spread
    return {**meta, 'status':'DEGENERATE_BULK' if sig is None else 'COMPUTED',
            'm':m, 'sig':sig, 'raw_gap':gap, 'bulk_spread':spread,
            'lambda2_through_mplus2': vals[1:min(m+2, len(vals))].tolist()}, vals, vectors


def null_gaps(x, k, tau, seeds):
    gaps, invalid = [], []
    for seed in seeds:
        rng = np.random.default_rng(seed)
        shuffled = np.column_stack([rng.permutation(x[:, j]) for j in range(x.shape[1])])
        result, _, _ = spectrum(graph(shuffled, k), tau)
        if result['raw_gap'] is None: invalid.append(int(seed))
        else: gaps.append(result['raw_gap'])
    return np.asarray(gaps), invalid


def verdict(result, sig_star, gaps, invalid):
    if result['m'] is None: return 'INCONCLUSIVE_GRAPH_ISOLATE'
    if result['m'] == 1: return 'ABSTAIN_M1'
    if sig_star is None: return 'INCONCLUSIVE_CALIBRATION'
    if result['sig'] is None: return 'INCONCLUSIVE_DEGENERATE_BULK'
    if invalid or len(gaps) < 99: return 'INCONCLUSIVE_SHUFFLE'
    if result['sig'] < sig_star: return 'ABSTAIN_LOW_SIG'
    if result['raw_gap'] <= np.quantile(gaps, .95, method='linear'): return 'ABSTAIN_NULL_GAP'
    return 'REAL_GAP'


def threshold(positive, negative):
    """Only strict separation, no fallback/quantile tuning."""
    if not positive or not negative or any(x is None or not np.isfinite(x) for x in positive + negative):
        return {'status':'INCONCLUSIVE_CALIBRATION', 'sig_star':None, 'reason':'missing_or_degenerate_statistic'}
    hi, lo = max(negative), min(positive)
    if hi >= lo: return {'status':'INCONCLUSIVE_CALIBRATION', 'sig_star':None, 'neg_max':hi, 'pos_min':lo, 'reason':'no_strict_separation'}
    return {'status':'CALIBRATED', 'sig_star':(hi+lo)/2, 'neg_max':hi, 'pos_min':lo}


def world(n, d, R, seed):
    if d != 5 or n < 2: raise ValueError('frozen five-share controls required')
    rng = np.random.default_rng(seed)
    if R == 1: return .72 * rng.dirichlet(np.ones(d), size=n)
    if R not in (3, 4, 5): raise ValueError('frozen R domain')
    group = np.arange(n) % R
    x = .02 + np.eye(d)[group] + np.abs(rng.normal(0, .015, (n, d)))
    return .72 * x / x.sum(axis=1, keepdims=True)


def labels(vectors, K, seed):
    if K < 2 or K >= len(vectors): raise ValueError('invalid K')
    embed = vectors[:, :K]
    lengths = np.linalg.norm(embed, axis=1, keepdims=True)
    embed = np.divide(embed, lengths, out=np.zeros_like(embed), where=lengths > 0)
    return KMeans(n_clusters=K, n_init=20, random_state=seed).fit_predict(embed)


def module(repo, name):
    path = Path(repo)/'economic-atlas/src'/f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec); spec.loader.exec_module(obj)
    return obj


def load_panel(repo, protocol):
    import pandas as pd
    repo = Path(repo); p = repo/'economic-atlas/data/panel_v1.parquet'
    if sha(p) != protocol['panel_sha256']: raise ValueError('frozen panel hash mismatch')
    frozen = json.loads((repo/'economic-atlas/frozen_inputs.json').read_text())
    feature = repo/'economic-atlas/runs/A5/features.parquet'
    if sha(feature) != frozen['features']['sha256']: raise ValueError('A5 mask hash mismatch')
    tids, months, shares, audit = module(repo, 'a6_temporal').build_monthly_shares(pd.read_parquet(p))
    expected = pd.read_parquet(feature, columns=['territory_id']).territory_id.sort_values().to_numpy()
    if not np.array_equal(tids, expected) or len(tids) != 1896 or len(months) != 24 or shares.shape != (1896, 24, 5):
        raise ValueError('exact frozen monthly mask/grid required; no intersection')
    return tids, months, shares, audit, {'panel':sha(p), 'A5_mask':sha(feature)}


def calibrate(n, d, p, out):
    results = {}
    for k in p['graph_k']:
        pos, neg, records = [], [], []
        for R in (1, 3, 4, 5):
            for seed in p['calibration_seeds']:
                r, _, _ = spectrum(graph(world(n, d, R, seed), k), p['tau_lambda'])
                records.append({'R':R, 'seed':seed, **r})
                (neg if R == 1 else pos).append(r['sig'])
        fit = threshold(pos, neg)
        if any(r['m'] != r['R'] for r in records if r['R'] > 1):
            fit = {'status':'INCONCLUSIVE_CALIBRATION', 'sig_star':None, 'reason':'positive_R_not_recovered'}
        held = []
        for R in (1, 3, 4, 5):
            for seed in p['validation_seeds']:
                x = world(n, d, R, seed)
                r, _, _ = spectrum(graph(x, k), p['tau_lambda'])
                nullseeds = range(p['shuffle_seed_base'] + seed*100, p['shuffle_seed_base'] + seed*100 + 99)
                gaps, invalid = null_gaps(x, k, p['tau_lambda'], nullseeds)
                v = verdict(r, fit['sig_star'], gaps, invalid)
                held.append({'R':R,'seed':seed,**r,'verdict':v,'shuffle_invalid_seeds':invalid,
                             'shuffle_raw_gaps':gaps.tolist(),'shuffle_p95':float(np.quantile(gaps,.95)) if len(gaps) else None})
                write(out/f'calibration-progress-k{k}.json', {'calibration':records,'fit':fit,'held':held})
        negatives = [r for r in held if r['R']==1]; positives = [r for r in held if r['R']>1]
        false_rate = sum(r['verdict']=='REAL_GAP' for r in negatives)/len(negatives)
        recovery = sum(r['verdict']=='REAL_GAP' and r['m']==r['R'] for r in positives)/len(positives)
        complete = all(r['m'] is not None and not r['shuffle_invalid_seeds'] for r in held)
        passed = complete and fit['sig_star'] is not None and false_rate<=.05 and recovery>=.90
        results[str(k)] = {'n':n,'d':d,'k':k,'fit':fit,'calibration':records,'held':held,
                          'negative_false_structured_fraction':false_rate,'positive_exact_R_fraction':recovery,
                          'method_quality':'PASS_FIXED_CONTROLS' if passed else 'FAIL_OR_INCONCLUSIVE_FIXED_CONTROLS'}
    return {'settings_sha256':hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest(),
            'n':n,'d':d,'results':results,'economic_identity_pass':False}


def replay(repo, p, calibration, out):
    tids, months, shares, audit, inputs = load_panel(repo, p)
    expected = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
    if calibration['settings_sha256'] != expected or calibration['n'] != len(tids) or calibration['d'] != 5:
        raise ValueError('calibration protocol/size/dimension mismatch')
    sd = module(repo,'atlas_sdbw'); tables=[]
    for t, month in enumerate(months):
        x = shares[:,t,:]
        for k in p['graph_k']:
            c=calibration['results'][str(k)]
            if c['n'] != len(x) or c['d'] != 5 or c['k'] != k: raise ValueError('calibration graph mismatch')
            result, vals, vec = spectrum(graph(x,k), p['tau_lambda'])
            gaps, invalid=null_gaps(x,k,p['tau_lambda'],range(p['shuffle_seed_base']+t*100, p['shuffle_seed_base']+t*100+99))
            v=verdict(result,c['fit']['sig_star'],gaps,invalid)
            # Failed held controls prohibit accepted real structure, retaining raw diagnostics.
            if c['method_quality'] != 'PASS_FIXED_CONTROLS' and v=='REAL_GAP': v='INCONCLUSIVE_CONTROL_QUALITY'
            metrics=[]
            for K in sorted(set(p['main_grid_K'] + ([result['m']] if result['m'] is not None else []))):
                if vec is None or not 2<=K<len(x):
                    metrics.append({'K':K,'status':'NA_GRAPH_OR_K_DOMAIN','SW':None,'CH':None,'S_Dbw':None}); continue
                lab=labels(vec,K,20261008+t)
                np.savez_compressed(out/f'labels-{month}-knn{k}-K{K}.npz',territory_id=tids,label=lab)
                if len(np.unique(lab))!=K:
                    metrics.append({'K':K,'status':'NA_EMPTY_CLUSTER','SW':None,'CH':None,'S_Dbw':None});continue
                db=sd.s_dbw(x,lab,expected_k=K)
                metrics.append({'K':K,'status':db['status'],'SW':silhouette_score(x,lab),
                                'CH':calinski_harabasz_score(x,lab),'S_Dbw':db['S_Dbw'],'S_Dbw_detail':db})
            if vals is not None:
                np.save(out/f'spectrum-{month}-knn{k}.npy',vals)
                specthash=sha(out/f'spectrum-{month}-knn{k}.npy')
            else: specthash=None
            tables.append({'month':month,'kNN':k,**result,'verdict':v,'spectrum_sha256':specthash,
                           'shuffle_raw_gaps':gaps.tolist(),'shuffle_invalid_seeds':invalid,
                           'shuffle_p95':float(np.quantile(gaps,.95)) if len(gaps) else None,
                           'shuffle_p':float((1+np.count_nonzero(gaps>=result['raw_gap']))/(1+len(gaps))) if result['raw_gap'] is not None and len(gaps) else None,
                           'method_quality':c['method_quality'],'metrics':metrics})
            write(out/'monthly-progress.json',tables)
    return {'state':'COMPUTED_DESCRIPTIVE','input_sha256':inputs,'panel_audit':audit,'monthly':tables,
            'economic_identity_pass':False,'independent_holdout':False,'causal_pass':False}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['calibrate','replay'],required=True)
    ap.add_argument('--repo',type=Path,required=True);ap.add_argument('--protocol',type=Path,required=True)
    ap.add_argument('--calibration',type=Path);ap.add_argument('--outdir',type=Path,required=True)
    args=ap.parse_args();p=json.loads(args.protocol.read_text())
    if p['version']!='m1-prospective-v1' or sha(args.protocol)!=FROZEN_PROTOCOL_SHA256:
        raise ValueError('unknown or modified frozen protocol')
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS'):
        if os.environ.get(name)!='1':raise ValueError(f'{name}=1 required before process start')
    args.outdir.mkdir(parents=True,exist_ok=False)
    write(args.outdir/'protocol-freeze.json',{'protocol_sha256':sha(args.protocol),'code_sha256':sha(__file__),'phase':args.phase,'state':'STARTED'})
    if args.phase=='calibrate':
        ids,months,x,audit,inputs=load_panel(args.repo,p)
        result=calibrate(len(ids),x.shape[-1],p,args.outdir)
        result['input_sha256']=inputs
    else:
        if args.calibration is None:raise ValueError('--calibration required for replay')
        result=replay(args.repo,p,json.loads(args.calibration.read_text()),args.outdir)
        result['calibration_sha256']=sha(args.calibration)
    write(args.outdir/'result.json',result)
    write(args.outdir/'manifest.json',{'protocol_sha256':sha(args.protocol),'code_sha256':sha(__file__),
                                    'files_sha256':{p.name:sha(p) for p in args.outdir.iterdir() if p.is_file()}})

if __name__=='__main__':main()
