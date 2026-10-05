"""Hand fixtures, invariances, scalar edge audit, and original A5 reconstruction."""
import ast
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

from a7_economic_graph_audit import economic_graph, network_scores


def scalar(a, labels):
    groups = [[i for i, y in enumerate(labels) if y == c] for c in sorted(set(labels))]
    # Independent sums over vertex sets, not the production edge accumulator.
    s = [[math.fsum(float(a[i, j]) for i in g for j in h) for h in groups] for g in groups]
    k = len(groups)
    v = [math.fsum(row) for row in s]
    e = [math.fsum(s[i][j] for j in range(k) if i != j) for i in range(k)]
    avi = math.fsum(s[i][i]/v[i] if v[i] else 0 for i in range(k))/k
    avu = math.fsum(s[i][j]/(e[i]+e[j]-s[i][j]) if e[i]+e[j]-s[i][j] else 0
                    for i in range(k) for j in range(k) if i != j)/k
    total = math.fsum(v)
    # Direct vertex-pair Newman expression, rather than the block expression.
    degree = [math.fsum(row) for row in a]
    q = math.fsum(a[i,j]-degree[i]*degree[j]/total
                 for i in range(len(a)) for j in range(len(a)) if labels[i]==labels[j])/total if total else None
    return avi, avu, q


def close(a, b):
    assert math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), (a, b)


def fixtures():
    a = np.array([[0.,2,0,0],[2,0,1,0],[0,1,0,2],[0,0,2,0]])
    labels = np.array([0,0,1,1])
    r = network_scores(a, labels)
    close(r['AVI'],.8);close(r['AVU'],1);close(r['ANUI'],4/9);close(r['modularity_newman'],.3)
    a[1,2] = a[2,1] = 0
    r = network_scores(a, labels)
    close(r['AVI'],1);close(r['AVU'],0);close(r['modularity_newman'],.5)
    # Explicit counterexample to the unqualified 'AVU always equals 1 for K=2'.
    assert r['AVU_zero_denominator_ordered_pairs'] == 2
    zero = network_scores(np.zeros((3,3)),[0,1,2])
    assert zero['AVI']==zero['AVU']==0 and zero['modularity_newman'] is None
    for seed in range(20):
        rng = np.random.default_rng(seed)
        upper = np.triu(rng.uniform(0,3,(23,23))*(rng.random((23,23))<.35),k=1)
        graph = upper+upper.T
        labs = np.arange(23) % (2 + seed % 6)
        r = network_scores(graph,labs)
        for key, expected in zip(['AVI','AVU','modularity_newman'],scalar(graph,labs)):
            close(r[key],expected)
        permutation = rng.permutation(23)
        for graph2, labs2 in [(graph*3.25,labs+20),(graph[np.ix_(permutation,permutation)],labs[permutation])]:
            other = network_scores(graph2,labs2)
            for key in ['AVI','AVU','ANUI','modularity_newman']:close(r[key],other[key])
        if r['K']==2:close(r['AVU'],1)
        if r['K']==3:close(r['AVU'],2/3)
    for bad, labs in [(np.ones((2,2)),[0,1]),(np.array([[0.,1],[0,0]]),[0,1]),
                      (np.array([[0.,-1],[-1,0]]),[0,1]),(np.zeros((2,2)),[0,None]),
                      (np.array([[0.,np.nan],[np.nan,0]]),[0,1])]:
        try:network_scores(bad,labs)
        except ValueError:pass
        else:raise AssertionError('invalid graph accepted')
    # Stable tie rule and zero-distance duplicates; no self-loops.
    z=np.array([[0.],[0.],[1.],[3.]])
    recovered,audit=economic_graph(z,1)
    assert recovered[0,1]==1 and recovered[0,0]==0 and np.array_equal(recovered,recovered.T)
    return ['hand_weighted_graph', 'disconnected_AVU_counterexample', 'edgeless_Q_NA',
            '20_random_scalar_reference', 'weight_scale_label_and_vertex_permutation',
            'K2_K3_with_cross_edges', 'invalid_inputs', 'knn_ties_and_duplicates']


def real_audit(root, run):
    root, run = Path(root), Path(run)
    a5=root/'economic-atlas/runs/A5'
    f=pd.read_parquet(a5/'features.parquet').sort_values('territory_id')
    labels=pd.read_parquet(a5/'assignments.parquet').sort_values('territory_id')
    assert np.array_equal(f.territory_id,labels.territory_id)
    z=f[[c for c in f if c.startswith('z_')]].to_numpy()
    recovered,audit=economic_graph(z,5)
    # Execute only the original trusted local A5 matrix-construction statements.
    # No model fitting, file mutation, or external reference code is executed.
    source=ast.parse((root/'economic-atlas/src/a5_graph.py').read_text())
    pipeline=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='run_pipeline')
    start=next(i for i,n in enumerate(pipeline.body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='D2')
    end=next(i for i,n in enumerate(pipeline.body) if i>start and isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='W')
    block=ast.Module(body=pipeline.body[start:end],type_ignores=[])
    scope={'np':np,'Z':z,'mask':f.territory_id.tolist(),'k_feat':5}
    exec(compile(block,'original_A5_matrix_only','exec'),scope)
    assert np.array_equal(recovered,scope['F'])
    m=json.loads((run/'manifest.json').read_text())
    geo=np.zeros_like(recovered)
    pos={int(t):i for i,t in enumerate(f.territory_id)}
    for e in pd.read_parquet(a5/'edges.parquet').itertuples(index=False):
        geo[pos[e.u],pos[e.v]]=geo[pos[e.v],pos[e.u]]=e.weight
    comparisons=[]
    for name,graph in [('economic_knn5',recovered),('geographic_A5_control',geo)]:
        for col in labels:
            if col=='territory_id':continue
            # Block-sum audit on the real graph; direct Q on 1896 vertices is manageable.
            expected=scalar(graph,labels[col].to_numpy())
            got=m['metrics'][name][col.removeprefix('label_')]
            for key,value in zip(['AVI','AVU','modularity_newman'],expected):close(got[key],value)
            comparisons.append(name+':'+col)
    return {'A5_reconstructed_matrix_bitwise_equal':True,'real_comparisons':comparisons,
            'test_code_sha256':__import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest()}


if __name__=='__main__':
    result={'fixtures':fixtures()}
    if len(sys.argv)==3:result['real_audit']=real_audit(sys.argv[1],sys.argv[2])
    print(json.dumps(result,indent=2))
