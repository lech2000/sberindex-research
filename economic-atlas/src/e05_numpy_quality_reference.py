"""Independent bounded-block implementation of the accepted scalar formulas.
No sklearn/author metric calls. NumPy is lazy; no actual fullsize timing claimed.
"""
import math

def quality(x,y,a,guard=lambda:None):
    if y is None:return {'status':'INPUT_UNAVAILABLE'}
    import numpy as np
    X=np.asarray(x,dtype=float);A=np.asarray(a,dtype=float);raw=np.asarray(y)
    if X.ndim!=2 or X.shape[1]==0 or raw.shape!=(len(X),)or not np.isfinite(X).all():raise ValueError('full finite coordinates/label shape')
    if raw.dtype.kind not in 'iu' or raw.dtype.kind=='b' or (raw<0).any():raise ValueError('integral nonnegative labels')
    keys,inv=np.unique(raw,return_inverse=True);n=len(X);k=len(keys);sizes={str(int(v)):int((raw==v).sum())for v in keys}
    if not 1<k<n:return {'status':'NA_DEGENERATE','sizes':sizes}
    if A.shape!=(n,n)or not np.isfinite(A).all()or(A<0).any()or np.diag(A).any()or not np.allclose(A,A.T,rtol=0,atol=1e-12):raise ValueError('finite symmetric nonnegative zero-diagonal geography')
    indices=[np.flatnonzero(inv==i)for i in range(k)];centres=np.array([X[g].mean(0)for g in indices]);sil=np.empty(n);block=32
    for first in range(0,n,block):
        guard();last=min(n,first+block);D=np.sqrt(np.sum((X[first:last,None,:]-X[None,:,:])**2,axis=2))
        avg=np.column_stack([D[:,g].mean(1)for g in indices])
        for local,i in enumerate(range(first,last)):
            g=indices[inv[i]]
            if len(g)==1:sil[i]=0.;continue
            own=float(D[local,g].sum()/(len(g)-1));other=float(min(avg[local,j]for j in range(k)if j!=inv[i]));den=max(own,other);sil[i]=(other-own)/den if den else 0.
    globalcentre=X.mean(0);between=sum(len(g)*float(np.sum((centres[i]-globalcentre)**2))for i,g in enumerate(indices));within=sum(float(np.sum((X[g]-centres[i])**2))for i,g in enumerate(indices));CH=between*(n-k)/(within*(k-1))if within else 1.
    # Exact accepted independent scalar arithmetic at inclusive density boundary.
    # NumPy reductions can move a point across <= radius and alter integer counts.
    from e05_independent_numerical_audit import sdbw as scalar_sdbw
    guard();sdbw=scalar_sdbw(X.tolist(),[int(v)for v in raw]);guard()
    S=np.empty((k,k))
    for i,g in enumerate(indices):
        guard()
        for j,h in enumerate(indices):S[i,j]=A[np.ix_(g,h)].sum()
    d=S.sum(1);outside=d-np.diag(S);AVI=math.fsum(float(S[i,i]/d[i])if d[i]else 0. for i in range(k))/k;AVU=math.fsum(float(S[i,j]/(outside[i]+outside[j]-S[i,j]))if outside[i]+outside[j]-S[i,j] else 0. for i in range(k)for j in range(k)if i!=j)/k;total=float(d.sum());Q=None if total==0 else math.fsum(float(S[i,i]/total-(d[i]/total)**2)for i in range(k))
    guard();return {'status':'COMPUTED','sizes':sizes,'SW':float(sil.mean()),'CH':float(CH),'S_Dbw':sdbw,'network_reference_indices':{'AVI':AVI,'AVU':AVU,'Newman_Q':Q},'MQ':'SPEC_UNRESOLVED_OWNER_EXCLUDED'}
