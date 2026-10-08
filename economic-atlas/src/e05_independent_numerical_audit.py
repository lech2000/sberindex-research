"""Independent formulas; stdlib import, no author numeric functions or fits.
Public execution refuses. Future verified input/IO/resource authority is separate.
"""
import math, statistics, collections, hashlib, json
ATOL=1e-10
RTOL=1e-10

def finite(x):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x):
        raise ValueError('finite nonbool numerical input required')
    return float(x)

def labels(x):
    if not x or any(type(a)is not int or a<0 for a in x):raise ValueError('nonempty integer labels; no NA fill')
    return list(x)

def points(x):
    if not x or not x[0] or any(len(r)!=len(x[0])for r in x):raise ValueError('rectangular nonempty features')
    return [[finite(v)for v in r]for r in x]

def mean(x):return math.fsum(x)/len(x)
def distance(a,b):return math.sqrt(math.fsum((u-v)**2 for u,v in zip(a,b)))
def centroid(x):return [mean([r[j]for r in x])for j in range(len(x[0]))]
def variance(x):
    c=centroid(x);return [mean([(r[j]-c[j])**2 for r in x])for j in range(len(c))]
def norm(a):return math.sqrt(math.fsum(v*v for v in a))

def groups(x,y):
    x=points(x);y=labels(y)
    if len(x)!=len(y):raise ValueError('features/labels identity cardinality')
    keys=sorted(set(y));return x,y,keys,[[x[i]for i,a in enumerate(y)if a==k]for k in keys]

def sdbw(x,y):
    x,y,keys,g=groups(x,y);k=len(keys)
    if not 1<k<len(x):return {'status':'NA_K_DOMAIN','S_Dbw':None,'K':k}
    var=[norm(variance(a))for a in g];glob=norm(variance(x))
    if glob==0:return {'status':'NA_ZERO_GLOBAL_VARIANCE','S_Dbw':None,'K':k}
    radius=math.sqrt(math.fsum(var))/k;scat=mean(var)/glob;centres=[centroid(a)for a in g];ratios=[];pairs=[]
    for i in range(k):
        for j in range(i+1,k):
            pool=g[i]+g[j];mid=[(a+b)/2 for a,b in zip(centres[i],centres[j])]
            counts=[sum(distance(p,c)<=radius for p in pool)for c in [centres[i],centres[j],mid]]
            den=max(counts[:2]);ratios.append(counts[2]/den if den else None)
            pairs.append({'i':i,'j':j,'midpoint_count':counts[2],'centre_i_count':counts[0],'centre_j_count':counts[1]})
    undefined=sum(v is None for v in ratios);density=None if undefined else mean(ratios)
    return {'status':'NA_ZERO_DENSITY_DENOMINATOR'if undefined else'COMPUTED','S_Dbw':None if undefined else scat+density,'Scat':scat,'Dens_bw':density,'radius':radius,'K':k,'centre_domain':'pair_union','undefined_pairs':undefined,'singleton_clusters':sum(len(a)==1 for a in g),'zero_variance_clusters':sum(v==0 for v in var),'pairs':pairs}

def network(a,y):
    y=labels(y);n=len(y);a=points(a)
    if len(a)!=n or any(len(r)!=n for r in a):raise ValueError('graph/labels full identity shape')
    if any(a[i][i]!=0 for i in range(n)) or any(a[i][j]<0 or abs(a[i][j]-a[j][i])>1e-12 for i in range(n)for j in range(n)):raise ValueError('symmetric nonnegative loop-free graph')
    keys=sorted(set(y));index={k:i for i,k in enumerate(keys)};k=len(keys);s=[[0.]*k for _ in keys]
    for i in range(n):
        for j in range(n):s[index[y[i]]][index[y[j]]]+=a[i][j]
    d=[math.fsum(row)for row in s];out=[d[i]-s[i][i]for i in range(k)]
    avi=mean([s[i][i]/d[i]if d[i]else 0. for i in range(k)])
    avu=math.fsum(s[i][j]/(out[i]+out[j]-s[i][j])if out[i]+out[j]-s[i][j] else 0. for i in range(k)for j in range(k)if i!=j)/k
    total=math.fsum(d);q=None if total==0 else math.fsum(s[i][i]/total-(d[i]/total)**2 for i in range(k))
    return {'AVI':avi,'AVU':avu,'Newman_Q':q}

def quality(x,y,a,guard=lambda:None):
    if y is None:return {'status':'INPUT_UNAVAILABLE'}
    x,y,keys,g=groups(x,y);n=len(x);k=len(keys);sizes={str(v):y.count(v)for v in keys}
    if not 1<k<n:return {'status':'NA_DEGENERATE','sizes':sizes}
    sil=[]
    for i,p in enumerate(x):
        guard();own=[j for j in range(n)if y[j]==y[i]and j!=i]
        if not own:sil.append(0.);continue
        ai=mean([distance(p,x[j])for j in own]);bi=min(mean([distance(p,x[j])for j in range(n)if y[j]==c])for c in keys if c!=y[i]);sil.append((bi-ai)/max(ai,bi)if max(ai,bi)else 0.)
    centre=centroid(x);between=math.fsum(len(row)*distance(centroid(row),centre)**2 for row in g);within=math.fsum(distance(p,centroid(row))**2 for row in g for p in row)
    ch=between*(n-k)/(within*(k-1))if within else 1.
    return {'status':'COMPUTED','sizes':sizes,'SW':mean(sil),'CH':ch,'S_Dbw':sdbw(x,y),'network_reference_indices':network(a,y),'MQ':'SPEC_UNRESOLVED_OWNER_EXCLUDED'}

def contingency(a,b):
    a=labels(a);b=labels(b)
    if len(a)!=len(b):raise ValueError('same full matched identity cardinality')
    c=collections.Counter(zip(a,b));return a,b,c

def agreement(a,b):
    a,b,c=contingency(a,b);n=len(a);ar=collections.Counter(a);br=collections.Counter(b);choose=lambda x:x*(x-1)/2
    if n<2:ari=1.
    else:
        pairs=choose(n);observed=sum(choose(v)for v in c.values());ra=sum(choose(v)for v in ar.values());rb=sum(choose(v)for v in br.values());expected=ra*rb/pairs;den=(ra+rb)/2-expected;ari=(observed-expected)/den if den else 1.
    ha=-math.fsum(v/n*math.log(v/n)for v in ar.values());hb=-math.fsum(v/n*math.log(v/n)for v in br.values());mi=math.fsum(v/n*math.log(v*n/(ar[i]*br[j]))for (i,j),v in c.items());nmi=2*mi/(ha+hb)if ha+hb else 1.
    return {'ARI':ari,'NMI':nmi,'contingency':{f'{i}->{j}':v for (i,j),v in c.items()},'switch_fraction':sum(u!=v for u,v in zip(a,b))/n}

def temporal(sequence):
    if not sequence:raise ValueError('nonempty month sequence')
    result=[]
    for t in range(1,len(sequence)):
        if sequence[t-1]is None or sequence[t]is None:result.append({'t':t,'status':'INPUT_UNAVAILABLE'});continue
        result.append(dict(t=t,status='COMPUTED',label_overlap_alignment_is_not_identity=True,**agreement(sequence[t-1],sequence[t])))
    return result

def control(sequence,truth,movers,shift):
    if not sequence or any(v is None for v in sequence):raise ValueError('control complete months; no NA truth fill')
    sequence=[labels(v)for v in sequence];n=len(sequence[0]);T=len(sequence)
    if any(len(v)!=n for v in sequence)or len(truth)!=n or any(len(row)!=T for row in truth):raise ValueError('control full tensor identities')
    if any(type(v)is not int or v not in (0,1)for row in sequence+list(truth)for v in row):raise ValueError('binary labels/truth only')
    if type(shift)is not int or not 0<shift<T:raise ValueError('frozen event shift')
    if len(set(movers))!=len(movers)or any(type(i)is not int or not 0<=i<n for i in movers):raise ValueError('unique full mover identities')
    if any(any(v!=row[0]for v in row[:shift])or any(v!=row[shift]for v in row[shift:])for row in truth):raise ValueError('single frozen truth transition')
    changed=[i for i in range(n)if truth[i][shift]!=truth[i][shift-1]]
    if not set(changed)<=set(movers):raise ValueError('truth transition outside declared movers')
    # Independently solve unique binary maximum initial agreement.
    # SciPy Hungarian tie equivalence is not established: abstain, do not guess.
    same=sum(sequence[0][i]==truth[i][0]for i in range(n))
    if same==n-same:raise ValueError('INITIAL_MAPPING_TIE_UNVERIFIED_NO_NUMERICAL_ACCEPTANCE')
    flip=same<n-same
    pred=[[1-sequence[t][i]if flip else sequence[t][i]for t in range(T)]for i in range(n)]
    delays=[]
    for i in changed:
        pre,post=truth[i][shift-1:shift+1];delay=None
        if pred[i][shift-1]==pre:
            for t in range(shift,T):
                if pred[i][t-1]==pre and pred[i][t]==post:delay=t-shift;break
        delays.append(delay)
    caught=[x for x in delays if x is not None];immediate=sum(x==0 for x in delays)/len(changed)if changed else None
    stable=[i for i in range(n)if i not in changed];den=len(stable)*(T-1);fs=sum(pred[i][t]!=pred[i][t-1]for i in stable for t in range(1,T))/den if den else None
    return {'recall':immediate,'event_recall_at_shift':immediate,'miss_fraction':1-immediate if immediate is not None else None,'eventual_event_recall':len(caught)/len(changed)if changed else None,'post_shift_state_accuracy':sum(pred[i][shift]==truth[i][shift]for i in changed)/len(changed)if changed else None,'baseline_state_accuracy':sum(pred[i][shift-1]==truth[i][shift-1]for i in range(n))/n,'expected_changed_entities':len(changed),'delays_months':delays,'median_delay':float(statistics.median(caught))if caught else None,'never_detected':sum(x is None for x in delays),'false_switch_fraction':fs,'adjacent_ARI':[agreement(sequence[t-1],sequence[t])['ARI']for t in range(1,T)],'scope':'synthetic actual transitions with correct pre-event baseline; fixed initial mapping; recall evaluated at shift; retrospective fitted labels are not online warning'}

FROZEN_PROTOCOL_SHA='b1b15d99a8094690ba532d89846206ebbf60b653f7b7bb7873307f9a5cfa931a'
FROZEN_CANONICAL_PROTOCOL_SHA='f82e404e7e909c106777a5582f76f565c62a60bc388c6c2e19c6bbb4697fb1d3'
FROZEN_ERROR_BUDGET={'stable_false_switch_fraction_max':.05,'abrupt_missed_change_fraction_max':.2,'abrupt_median_delay_months_max':2.0,'seasonal_false_switch_fraction_max':.05}

def pinned_protocol(raw):
    if not isinstance(raw,bytes)or hashlib.sha256(raw).hexdigest()!=FROZEN_PROTOCOL_SHA:raise ValueError('exact frozen source protocol byteSHA')
    def object_hook(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate JSON protocol key')
            result[key]=value
        return result
    p=json.loads(raw,object_pairs_hook=object_hook,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite protocol')))
    validate_frozen_protocol(p);return p

def validate_frozen_protocol(protocol):
    if canonical_sha(protocol)!=FROZEN_CANONICAL_PROTOCOL_SHA:raise ValueError('literal full frozen protocol semantics/order/source/data pins')
    if protocol['K']!=[2,5] or any(type(k)is not int for k in protocol['K']):raise ValueError('frozen K2/5')
    if len(set(protocol['seeds']))!=5 or any(type(s)is not int for s in protocol['seeds']):raise ValueError('five unique frozen real seeds')
    ctl=protocol['controls']
    if len(set(ctl['seeds']))!=5 or any(type(s)is not int for s in ctl['seeds']):raise ValueError('five unique frozen control seeds')
    if len({a['id']for a in protocol['arms']})!=18 or len({canonical_sha(a)for a in protocol['arms']})!=18:raise ValueError('eighteen unique frozen arms')
    return True

def budget(metrics,world,error_budget):
    if not isinstance(error_budget,dict)or set(error_budget)!=set(FROZEN_ERROR_BUDGET):raise ValueError('entire frozen error budget')
    for key,value in error_budget.items():
        val=finite(value)
        if val<0 or ('fraction' in key and val>1):raise ValueError('semantic budget bound domain')
    if canonical_sha(error_budget)!=canonical_sha(FROZEN_ERROR_BUDGET):raise ValueError('frozen numeric error budget cannot change')
    if world=='abrupt_shift':raw={'miss':metrics['miss_fraction'],'delay':metrics['median_delay']};bounds={'miss':error_budget['abrupt_missed_change_fraction_max'],'delay':error_budget['abrupt_median_delay_months_max']}
    elif world in ('stable','seasonal_no_identity_change'):raw={'false_switch':metrics['false_switch_fraction']};bounds={'false_switch':error_budget['stable_false_switch_fraction_max'if world=='stable'else'seasonal_false_switch_fraction_max']}
    else:raise ValueError('unknown fixed control world')
    for key,value in raw.items():
        if value is None:continue
        val=finite(value)
        if val<0 or (key in ('miss','false_switch')and val>1):raise ValueError('raw fraction [0,1] / delay nonnegativefinite domain')
    undefined=any(v is None for v in raw.values())
    return {'status':'INCONCLUSIVE_UNDEFINED'if undefined else'CONTROL_BUDGET_PASS'if all(raw[k]<=bounds[k]for k in raw)else'CONTROL_BUDGET_FAIL','raw':raw,'bounds':bounds,**({}if undefined else{'scientific_pass':False})}

def compare(expected,reported,path='metric'):
    """Strict NA/type/key checks; unrounded float comparison, never count-only PASS."""
    if isinstance(expected,dict):
        if not isinstance(reported,dict)or set(expected)!=set(reported):raise ValueError(path+': missing metric keys')
        for k,v in expected.items():compare(v,reported[k],path+'.'+k)
    elif isinstance(expected,list):
        if not isinstance(reported,list)or len(expected)!=len(reported):raise ValueError(path+': metric shape')
        for i,(a,b)in enumerate(zip(expected,reported)):compare(a,b,path+'.'+str(i))
    elif isinstance(expected,float):
        value=finite(reported)
        if not math.isclose(expected,value,rel_tol=RTOL,abs_tol=ATOL):raise ValueError(path+': unrounded numeric mismatch')
    elif type(expected)is not type(reported)or expected!=reported:raise ValueError(path+': exact status/count/NA mismatch')

def canonical_sha(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def planned(protocol):
    validate_frozen_protocol(protocol)
    cells=[{'kind':'real','arm':a,'K':k,'seed':s}for a in protocol['arms']for k in protocol['K']for s in protocol['seeds']]+[{'kind':'control','world':w,'gamma':g,'K':2,'seed':s}for w in protocol['controls']['worlds']for g in protocol['controls']['gammas']for s in protocol['controls']['seeds']]
    if len(cells)!=225 or len({canonical_sha(c)for c in cells})!=225 or len(cells[:180])!=180 or len(cells[180:])!=45:raise ValueError('entire225 cell scope')
    return cells

def audit_verified_payload(cell,payload,reported,protocol,guard):
    """Trusted future reader supplies independently SHA-verified tensors/identities.
    No file IO/model imports here. Outer full publication validator is mandatory.
    """
    validate_frozen_protocol(protocol)
    seq=payload['labels'];months=protocol['months']
    if len(seq)!=24 or len(months)!=24 or any(v is not None and len(v)!=1896 for v in seq):raise ValueError('full1896x24 saved labels')
    if cell['kind']=='real':
        feat=cell['arm']['feature']
        for t in range(24):
            available=not((feat in ('growth_mom','shares_growth_mom')and t==0)or(feat=='growth_yoy'and t<12))
            if (seq[t]is not None)!=available:raise ValueError('exact frozen available month mask')
        if len(payload['common_spending_points'])!=24:raise ValueError('all24 common metric months')
        for t in range(24):guard();compare(quality(payload['common_spending_points'][t],seq[t],payload['geo_reference'],guard),reported['quality_same_spending_space'][t],f'quality.month{t}')
        compare(temporal(seq),reported['adjacent'],'temporal')
    else:
        compare(control(seq,payload['truth'],payload['movers'],protocol['controls']['shift_month_index']),reported['control_metrics'],'control')
        compare(budget(control(seq,payload['truth'],payload['movers'],protocol['controls']['shift_month_index']),cell['world'],protocol['controls']['error_budget']),reported['budget'],'controlbudget')
    return {'numerical_values_checked':True,'scientific_pass':False,'economic_identity':False}

def execute(*args,**kwargs):raise RuntimeError('NOT_EXECUTABLE: independent full SHA/row/truth IO and original budget/resource authority not admitted')

def audit_bank(protocol,records,verify_publication,load_verified_payload,guard):
    """Future admitted full-bank callgraph; current packet grants no IO authority.
    verify_publication must independently use the pinned V5 full-file validator;
    reader must bind row keys, tensor bytes and independent truth provenance.
    It is never sufficient to supply cardinalities or unchecked booleans.
    """
    if not all(getattr(fn,'qualified_e05_audit_io',False)for fn in (verify_publication,load_verified_payload,guard)):
        raise RuntimeError('NOT_EXECUTABLE unqualified full-bank IO/resource callbacks')
    cells=planned(protocol)
    guard();verification=verify_publication()
    if verification.get('full_status_rows')!=10238400 or verification.get('cells')!=225 or verification.get('independent_full_file_readback')is not True:raise ValueError('actual full225/10238400 publication readback required')
    if len(records)!=225:raise ValueError('missing cells remain; no smaller numerical audit')
    results=[]
    for i,(record,cell)in enumerate(zip(records,cells)):
        guard()
        if record.get('key')!=i or record.get('cell')!=cell:raise ValueError('literal arm/K/seed/control identity')
        status=record['status']
        if status not in ('COMPUTED','INCONCLUSIVE','UNKNOWN_NATIVE_RESPONSE','NOT_ATTEMPTED_RESOURCE_STOP'):raise ValueError('unrecognized preserved cell status')
        if status!='COMPUTED':results.append({'key':i,'execution_status':status,'numerical_status':'UNAVAILABLE_SAVED_CELL_NOT_COMPUTED'});continue
        payload,reported=load_verified_payload(i,cell)
        if payload.get('full_keys_SHA')!=verification['cell_key_SHA'][str(i)] or payload.get('assignment_SHA')!=verification['assignment_SHA'][str(i)] or payload.get('summary_SHA')!=verification['summary_SHA'][str(i)]:raise ValueError('numerical payload bound to full manifest keys/bytes')
        proof=payload.get('independent_input_receipt',{})
        if proof.get('input_source_pins')!=protocol['data_pins'] or proof.get('common_metric_train_year')!='2023' or proof.get('actual_tensor_hashes_verified')is not True:raise ValueError('frozen input/tensor/train-only provenance')
        if cell['kind']=='control' and(proof.get('truth_generator_source_SHA')!=METHOD_SHA or proof.get('truth_cell')!=cell or not isinstance(proof.get('truth_tensor_SHA'),str)or len(proof['truth_tensor_SHA'])!=64):raise ValueError('independent frozen truth tensor/source/cell binding')
        result=audit_verified_payload(cell,payload,reported,protocol,guard)
        if cell['kind']=='real' and cell['arm']['id']!='shares':
            base=next(j for j,c in enumerate(cells[:180])if c['arm']['id']=='shares'and(c['K'],c['seed'])==(cell['K'],cell['seed']))
            saved=payload.get('saved_pair_metrics')
            if records[base]['status']!='COMPUTED':
                if saved is not None:raise ValueError('computed pairing with unavailable baseline')
                result['paired_numerical_status']='UNAVAILABLE_BASELINE'
            elif saved is None:result['paired_numerical_status']='UNAVAILABLE_METRIC_EVIDENCE'
            else:
                base_payload,_=load_verified_payload(base,cells[base])
                if base_payload.get('full_keys_SHA')!=verification['cell_key_SHA'][str(base)]or base_payload.get('assignment_SHA')!=verification['assignment_SHA'][str(base)]:raise ValueError('exact verified sameKseed baseline key/assignment binding')
                if payload.get('saved_pair_file_SHA')!=verification.get('paired_comparisons_SHA')or not verification.get('paired_comparisons_SHA'):raise ValueError('saved comparison file SHA binding')
                compare(paired_metrics(payload['labels'],base_payload['labels'],protocol['months']),saved,'paired_sameKseed')
                result['paired_numerical_status']='RECOMPUTED_MATCH'
        results.append(dict(key=i,execution_status=status,numerical_status='RECOMPUTED_MATCH',**result))
    guard()
    return {'state':'INDEPENDENT_NUMERICAL_SOURCE_CHECKS_WITH_ABSTENTIONS','cells':results,'all225_retained':True,'actual_full_numerical_gate_pass':False,'scientific_pass':False,'formal_promise_complete':False,'paired_metrics_audit':'SEPARATE_SAVED_COMPARISON_EVIDENCE_REQUIRED'}

METHOD_SHA='e5db7ad379bf2c6bcb261d05563bdb88c433a4178baec48399e3e9e0ef2ea21b'

def frozen_common(values,months,guard=lambda:None):
    """Independent shared metric cube: total+fivecategories, pooled2023 ddof0.
    Stdlib reference; no source preprocessing function used as oracle.
    """
    if not values or len(months)!=24 or months!=[f'{y}-{m:02}'for y in (2023,2024)for m in range(1,13)]:raise ValueError('frozen full24months')
    shares=[]
    for entity in values:
        guard()
        if len(entity)!=24 or any(len(row)!=6 for row in entity):raise ValueError('total+five frozen category coordinates')
        for row in entity:
            if any(finite(v)<=0 for v in row):raise ValueError('positive finite no-fill source')
        shares.append([[row[j]/row[0]for j in range(1,6)]for row in entity])
    pool=[row for entity in shares for row in entity[:12]];mu=centroid(pool);sd=[math.sqrt(v)for v in variance(pool)]
    return [[[(row[j]-mu[j])/sd[j]if sd[j]else 0. for j in range(5)]for row in entity]for entity in shares]

def paired_metrics(sequence,baseline,months):
    if len(sequence)!=24 or len(baseline)!=24 or len(months)!=24:raise ValueError('paired all24 monthly mask')
    result=[]
    for t,(x,y)in enumerate(zip(sequence,baseline)):
        if x is None or y is None:result.append({'month':months[t],'status':'INPUT_UNAVAILABLE','n':0});continue
        score=agreement(x,y);result.append({'month':months[t],'status':'COMPUTED','n':len(x),'ARI_vs_sameKseed_shares':score['ARI'],'NMI_vs_sameKseed_shares':score['NMI']})
    return result
