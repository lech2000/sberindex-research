"""Stdlib-only future artifact acceptance. No generation, clustering or execution."""
import itertools, math

def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('nonnegative nonbool integer counts required')
    return value

def acceptance(spec, runs, months):
    expected=set(itertools.product(spec['seeds'], spec['worlds'],spec['modes'],spec['margin_factors']))
    keys=lambda r:(r['seed'],r['world'],r['mode'],r['margin_factor'])
    actual=[keys(r) for r in runs]
    if len(actual)!=210 or len(set(actual))!=210 or set(actual)!=expected:
        raise ValueError('complete unique210 configurations, no selected M/seed/world')
    expected_months={(k,m) for k in expected for m in range(1,24)}
    actual_months=[(keys(r),r['month_index']) for r in months]
    if len(actual_months)!=4830 or len(set(actual_months))!=4830 or set(actual_months)!=expected_months:
        raise ValueError('complete4830 postinitial month keys')
    budget=spec['error_budget']; results=[]
    for mode,factor in itertools.product(spec['modes'],spec['margin_factors']):
        selected=[r for r in runs if r['mode']==mode and r['margin_factor']==factor]
        if any(r.get('execution_status')!='COMPLETE' for r in selected):
            results.append({'mode':mode,'margin_factor':factor,'status':'INCONCLUSIVE'});continue
        fields=['tp','fp_known','fp_unknown','fn','tn','cluster_decisions','decided_clusters','abstentions']
        c={k:sum(integer(r['recognition'][k]) for r in selected) for k in fields}
        if c['decided_clusters']+c['abstentions']!=c['cluster_decisions']:
            raise ValueError('coverage/abstention denominator conservation')
        e={k:sum(integer(r['events'][k]) for r in selected) for k in ['tp','fp','fn']}
        for r in selected:
            if integer(r['negative_M3_false_events'])>r['events']['fp']:
                raise ValueError('negative M3 false events must be accounted among eventFP')
        def ratio(a,b):return a/b if b else None
        fp=c['fp_known']+c['fp_unknown']
        rates={'recognition_FDR':ratio(fp,c['tp']+fp),'recognition_FNR':ratio(c['fn'],c['tp']+c['fn']),
               'known_pair_FPR':ratio(c['fp_known'],c['fp_known']+c['tn']),
               'cluster_decision_coverage':ratio(c['decided_clusters'],c['cluster_decisions']),
               'event_FDR':ratio(e['fp'],e['tp']+e['fp']),'event_FNR':ratio(e['fn'],e['tp']+e['fn'])}
        false=sum(r['negative_M3_false_events'] for r in selected if r['world'] in ['stable','drift','proximity'])
        checks={k:v is not None and v<=budget[k+'_max'] for k,v in rates.items() if k!='cluster_decision_coverage'}
        checks['coverage']=rates['cluster_decision_coverage'] is not None and rates['cluster_decision_coverage']>=budget['cluster_decision_coverage_min']
        checks['negative_M3']=false<=budget['stable_drift_proximity_false_split_merge_max']
        status='INCONCLUSIVE' if any(v is None for v in rates.values()) else ('PASS' if all(checks.values()) else 'FAIL')
        results.append({'mode':mode,'margin_factor':factor,'status':status,'rates':rates,'checks':checks})
    state='INCONCLUSIVE' if any(x['status']=='INCONCLUSIVE' for x in results) else ('PASS' if all(x['status']=='PASS' for x in results) else 'FAIL')
    return {'status':state,'scope':'limited prospective empirical synthetic validation only','six_cells':results,'scientific_pass':False,'historical_preregistration_repaired':False}
