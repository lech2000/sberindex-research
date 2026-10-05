"""New simple forecasts on the exact stored R9 keys; no Prophet refits.

All fitting and seasonal bases are bounded by the origin. Method inspiration:
vakuznetzovaclaud/sberindex; this is an original implementation, with separately
declared choices. Missing bases stay unavailable and masks are reported.
"""
from pathlib import Path
import argparse, hashlib, json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

RAW_SHA = '9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61'
R9_SHA = 'b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44'
KEY = ['territory_id', 'category', 'horizon', 'origin', 'target']
NEW = ['growth_naive1', 'growth_naive3', 'conditional_ses', 'profile_ses']
ALPHAS = np.linspace(.05, .95, 19)
SEED = 20261004


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p, d): Path(p).write_text(json.dumps(d, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def ses(x):
    """Alpha minimizing past one-step absolute errors; ties first alpha."""
    x = np.asarray(x, float)
    if not len(x) or not np.isfinite(x).all(): raise ValueError('Invalid SES history')
    level = np.full(len(ALPHAS), x[0]); loss = np.zeros(len(ALPHAS))
    for v in x[1:]:
        loss += np.abs(v-level)
        level += ALPHAS*(v-level)
    k = int(np.argmin(loss))
    return float(level[k]), float(ALPHAS[k])


def predict(own, med, origin, target):
    """Series indexed by month. med is from all observed category rows."""
    own = own[own.index <= origin].sort_index().astype(float)
    med = med[med.index <= origin].sort_index()
    op, tp = pd.Period(origin, freq='M'), pd.Period(target, freq='M')
    old_o, old_t = str(op-12), str(tp-12)
    out = {m: np.nan for m in NEW}; out['category_seasonal'] = np.nan
    if origin not in own or old_o not in med or old_t not in med or old_t > origin: return out
    if med[old_o] <= 0 or med[old_t] <= 0: return out
    ratio = float(med[old_t]/med[old_o])
    out['category_seasonal'] = float(own[origin]*ratio)
    if old_o in own and old_t in own:
        out['growth_naive1'] = float(own[old_t]*own[origin]/own[old_o])
    k = min(3, op.ordinal-pd.Period('2023-01', freq='M').ordinal-11)
    recent = [str(op-j) for j in range(k)]
    prev = [str(op-j-12) for j in range(k)]
    if k >= 1 and all(m in own for m in recent+prev+[old_t]):
        out['growth_naive3'] = float(own[old_t]*own.loc[recent].sum()/own.loc[prev].sum())
    train_months = [str(pd.Period('2023-01', freq='M')+j) for j in range(op.ordinal-pd.Period('2023-01', freq='M').ordinal+1)]
    if not all(m in own and m in med for m in train_months): return out
    y = own.loc[train_months].to_numpy(float); M = med.loc[train_months].to_numpy(float)
    z = y/M
    level, _ = ses(z)
    out['conditional_ses'] = float(level*med[origin]*ratio)
    # Historical per-MO deviation, own 2023 seasonal profile, fixed shrinkage.
    u = np.log(y)-np.log(M)
    season = .7*(u[:12]-u[:12].mean())
    adjusted = u-season[np.arange(len(u)) % 12]
    level, _ = ses(adjusted)
    growth = float(np.mean(np.log(med.loc[recent].to_numpy())-np.log(med.loc[prev].to_numpy())))
    factor = float(med[old_t]*np.exp(growth))
    out['profile_ses'] = float(np.exp(level+season[tp.month-1])*factor)
    return out


def ses_matrix(x):
    level=np.repeat(x[:, :1],len(ALPHAS),axis=1)
    loss=np.zeros_like(level)
    for j in range(1,x.shape[1]):
        loss+=np.abs(x[:, j:j+1]-level)
        level+=ALPHAS[None, :]*(x[:, j:j+1]-level)
    return level[np.arange(len(x)),np.argmin(loss,axis=1)]


def predict_block(values, med, oi, ti):
    values=np.asarray(values,float); med=np.asarray(med,float)
    n=len(values); out={m:np.full(n,np.nan) for m in NEW+['category_seasonal']}
    if oi<12 or ti-12>oi or ti<12: return out
    ratio=med[ti-12]/med[oi-12]
    out['category_seasonal']=values[:,oi]*ratio
    out['growth_naive1']=values[:,ti-12]*values[:,oi]/values[:,oi-12]
    k=min(3,oi-11); recent=np.arange(oi-k+1,oi+1); prev=recent-12
    complete=np.isfinite(values[:, np.r_[recent,prev,ti-12]]).all(axis=1)
    out['growth_naive3'][complete]=values[complete,ti-12]*values[complete][:,recent].sum(1)/values[complete][:,prev].sum(1)
    complete=np.isfinite(values[:, :oi+1]).all(axis=1)
    y=values[complete,:oi+1]; M=med[:oi+1]
    out['conditional_ses'][complete]=ses_matrix(y/M)*med[oi]*ratio
    u=np.log(y)-np.log(M)
    seasonal=.7*(u[:, :12]-u[:, :12].mean(1,keepdims=True))
    adjusted=u-seasonal[:,np.arange(oi+1)%12]
    factor=med[ti-12]*np.exp(np.mean(np.log(med[recent])-np.log(med[prev])))
    out['profile_ses'][complete]=np.exp(ses_matrix(adjusted)+seasonal[:,ti%12])*factor
    return out


def summarize(d, models):
    results=[]
    rng=np.random.default_rng(SEED)
    for (window,h), g in d.groupby(['window','horizon']):
        available=g[models].notna().all(1)
        x=g.loc[available].copy()
        if not len(x): raise ValueError('Empty common mask')
        error={m:np.abs(x.actual-x[m]) for m in models}
        comparisons={}
        for m in [q for q in models if q!='category_seasonal']:
            diff=error[m]-error['category_seasonal']
            blocks=pd.DataFrame({'target':x.target,'diff':diff}).groupby('target')['diff'].agg(['sum','count'])
            ix=rng.integers(0,len(blocks),(10000,len(blocks)))
            b=blocks['sum'].to_numpy()[ix].sum(1)/blocks['count'].to_numpy()[ix].sum(1)
            per=pd.DataFrame({'tid':x.territory_id,'category':x.category,'d':diff}).groupby(['tid','category']).d.mean()
            comparisons[m]={'seasonal_benefit_mae':float(diff.mean()),'ci95_target_month_blocks':np.quantile(b,[.025,.975]).tolist(),
                            'share_series_seasonal_better':float((per>0).mean()),'n_month_blocks':len(blocks)}
        results.append({'window':window,'horizon':int(h),'original_rows':len(g),'common_rows':len(x),
                        'excluded_rows':int((~available).sum()),'missing_by_model':{m:int(g[m].isna().sum()) for m in models},
                        'mae':{m:float(e.mean()) for m,e in error.items()},'comparisons':comparisons,
                        'by_month':[{'target':t,'n':len(y),'mae':{m:float(np.abs(y.actual-y[m]).mean()) for m in models}} for t,y in x.groupby('target')],
                        'by_category':[{'category':c,'n':len(y),'mae':{m:float(np.abs(y.actual-y[m]).mean()) for m in models}} for c,y in x.groupby('category')]})
    return results


def self_check():
    months=[str(pd.Period('2023-01',freq='M')+j) for j in range(24)]
    own=pd.Series([2*(10+j) for j in range(24)],index=months,dtype=float)
    med=pd.Series([10+j for j in range(24)],index=months,dtype=float)
    a=predict(own,med,'2024-01','2024-02')
    b=own.copy();b.loc[b.index>'2024-01']=99999
    c=med.copy();c.loc[c.index>'2024-01']=99999
    assert a==predict(b,c,'2024-01','2024-02')
    assert abs(a['category_seasonal']-48.4)<1e-10
    assert abs(a['conditional_ses']-48.4)<1e-10
    assert a['growth_naive1']==a['growth_naive3']
    level,alpha=ses(np.array([2.,2.,2.])); assert level==2 and alpha==ALPHAS[0]
    m=predict(own.drop('2023-02'),med,'2024-02','2024-03')
    assert np.isnan(m['profile_ses']) and np.isnan(m['conditional_ses'])
    big=pd.Series(np.full(24,60000,dtype=np.uint16),index=months)
    assert predict(big,med,'2024-01','2024-02')['growth_naive1']==60000
    matrix=np.array([[float(own[m]) for m in months], [60000.]*24])
    vector=predict_block(matrix,med.to_numpy(),12,13)
    assert all(np.isclose(vector[m][0],a[m]) for m in NEW+['category_seasonal'])
    assert vector['growth_naive1'][1]==60000
    print(json.dumps({'self_check':True,'checks':['future invariance','known common factor','first-origin growth3 uses one month','SES ties deterministic','missing history not filled']}))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--raw',type=Path);ap.add_argument('--r9',type=Path)
    ap.add_argument('--pilot',type=Path);ap.add_argument('--out',type=Path);ap.add_argument('--self-check',action='store_true')
    a=ap.parse_args()
    if a.self_check: self_check(); return
    if a.out.exists(): raise FileExistsError('New run directory required')
    if sha(a.raw)!=RAW_SHA or sha(a.r9)!=R9_SHA: raise ValueError('Frozen inputs mismatch')
    a.out.mkdir(parents=True)
    dump(a.out/'protocol.json',{'recorded_before_results':datetime.now(timezone.utc).isoformat(),'client_date':'2026-10-04',
        'run_id':'R9_strong_baselines_20261004','raw_sha256':RAW_SHA,'r9_sha256':R9_SHA,'code_sha256':sha(__file__),
        'models':NEW,'alpha_grid':ALPHAS.tolist(),'alpha_selection':'minimum own historical one-step absolute loss; no future tuning',
        'profile_shrinkage':.7,'category_factor':'observed category median; origin and prior-year bases only',
        'national_data':False,'fitting':'new SES fits only; no Prophet refits',
        'main_mask':'exact stored R9 h1/3/6 keys; every original row retained, missing predictors marked unavailable',
        'early_window':'same 120 series and pre_R9 keys of prior frozen equal-information pilot',
        'peer_growth_naive':'prior-year target times ratio of sums last 1-3 months; exact formula, separately from one-month ratio',
        'independent_holdout':False,'historical_asof_verified':False,'scientific_pass':False,
        'limits':['Both windows and peer results already viewed; exploratory specification',
                  'SES profile fitted from one prior year; h12 unsupported',
                  'Masks and all exclusions reported; no silently reusing unequal original MAEs',
                  'Aggregate category overlaps the other five; uncertainty by target month blocks, few blocks',
                  'National factor and foundation models not reproduced by this comparison']})
    raw=pd.read_parquet(a.raw);raw['territory_id']=raw.territory_id.astype(str)
    raw['month']=pd.PeriodIndex(raw.date,freq='M').astype(str)
    if raw.duplicated(['territory_id','category','month']).any() or (raw.value<=0).any():raise ValueError('Invalid raw')
    months=[str(pd.Period('2023-01',freq='M')+j) for j in range(24)]
    tables={c:g.pivot(index='territory_id',columns='month',values='value').reindex(columns=months).astype(float) for c,g in raw.groupby('category')}
    medmap={c:g.groupby('month').value.median().reindex(months).to_numpy(float) for c,g in raw.groupby('category')}
    r9=pd.read_parquet(a.r9);r9['territory_id']=r9.territory_id.astype(str)
    r9=r9[r9.horizon.isin([1,3,6])].rename(columns={'pred_last':'last_value','pred_prophet':'stored_prophet'})
    pilot=pd.read_parquet(a.pilot);early=pilot[pilot.window=='pre_R9'].copy()
    base=pd.concat([r9.assign(window='R9'),early],ignore_index=True)
    blocks=[]
    for j,((c,o,t),g) in enumerate(base.groupby(['category','origin','target'],sort=True),1):
        table=tables[c]; values=table.to_numpy(); oi=months.index(o); ti=months.index(t)
        ix=table.index.get_indexer(g.territory_id)
        if (ix<0).any() or not np.array_equal(values[ix,ti],g.actual.to_numpy(float)) or not np.array_equal(values[ix,oi],g.last_value.to_numpy(float)):
            raise ValueError('Stored mask truth mismatch')
        pp=predict_block(values,medmap[c],oi,ti)
        blocks.append(g[KEY].assign(**{m:v[ix] for m,v in pp.items()}))
        if j%30==0: print(json.dumps({'category_origin_target_blocks':j}),flush=True)
    computed=pd.concat(blocks,ignore_index=True)
    if computed.duplicated(KEY).any(): raise ValueError('Duplicate output')
    # Drop prior pilot candidate column before replacing by recomputation.
    p=base.drop(columns=[c for c in NEW+['category_seasonal'] if c in base]).merge(computed,on=KEY,how='left',validate='one_to_one')
    p.to_parquet(a.out/'predictions.parquet',index=False)
    models=['category_seasonal']+NEW+['last_value','stored_prophet']
    results=summarize(p[p.window=='R9'],models)+summarize(p[p.window=='pre_R9'],[m for m in models if m!='stored_prophet'])
    metrics={'status':'EXPLORATORY_NOT_GATE_PASS','rows':len(p),'results':results,'scientific_pass':False,
             'versions':{'numpy':np.__version__,'pandas':pd.__version__}}
    dump(a.out/'metrics.json',metrics)
    dump(a.out/'manifest.json',{p.name:sha(p) for p in sorted(a.out.iterdir()) if p.is_file() and p.name!='manifest.json'})
    print(json.dumps({'complete':True,'rows':len(p),'scientific_pass':False}),flush=True)


if __name__=='__main__': main()
