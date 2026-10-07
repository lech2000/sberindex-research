"""Quantitative synthetic controls with new frozen real2023 ellipsoid thresholds; no economic PASS."""
from __future__ import annotations
import argparse, hashlib, itertools, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

SEEDS = list(range(20271001, 20271006))
WORLDS = ['stable', 'drift', 'birth', 'death', 'split', 'merge', 'proximity']
FACTORS = [.75, 1., 1.25]
MONTHS = pd.period_range('2023-01', '2024-12', freq='M').astype(str).tolist()
PURITY = .8
EVENT_KINDS = ['birth', 'disappearance', 'split_candidate', 'merge_candidate']

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def base_world(name, seed):
    """Fixed 200 points / 5 dimensions; labels used only by oracle and evaluator."""
    rng = np.random.default_rng(seed + 1000 * WORLDS.index(name))
    z = np.empty((200, 24, 5)); truth = []; structural = []
    for m in range(24):
        u = np.array(['A'] * 100 + ['B'] * 100, dtype=object)
        centers = {'A': np.array([-5., 0, 0, 0, 0]), 'B': np.array([5., 0, 0, 0, 0])}
        std = {'A': .3, 'B': .3}
        if name == 'drift':
            for k in centers: centers[k] = centers[k] + np.array([.04*m, 0, 0, 0, 0])
        elif name == 'birth' and m >= 12:
            u[90:100] = 'C'; centers['C'] = np.array([0., 5., 0, 0, 0]); std['C'] = .3
        elif name == 'death':
            if m < 18:
                u[90:100] = 'C'; centers['C'] = np.array([0., 5., 0, 0, 0]); std['C'] = .3
        elif name == 'split':
            if m < 14: std['A'] = 1.2
            else:
                u[:50] = 'A1'; u[50:100] = 'A2'
                centers['A1'] = np.array([-5., -2., 0, 0, 0]); centers['A2'] = np.array([-5., 2., 0, 0, 0])
                std['A1'] = std['A2'] = .3
        elif name == 'merge':
            if m < 14:
                u[:50] = 'A1'; u[50:100] = 'A2'
                centers['A1'] = np.array([-5., -2., 0, 0, 0]); centers['A2'] = np.array([-5., 2., 0, 0, 0])
                std['A1'] = std['A2'] = .3
            else: std['A'] = 1.2
        elif name == 'proximity':
            separation = 5. if m < 12 else 5. - (5. - .7) * (m-11)/12
            centers['A'] = np.array([-separation/2, 0, 0, 0, 0])
            centers['B'] = np.array([separation/2, 0, 0, 0, 0])
        for uid in sorted(set(u)):
            mask = u == uid
            z[mask, m, :] = rng.normal(centers[uid], std[uid], (int(mask.sum()), 5))
        truth.append(u)
    if name == 'split': structural.append((14, 'split_candidate', 'A', ('A1', 'A2')))
    if name == 'merge': structural.append((14, 'merge_candidate', 'A', ('A1', 'A2')))
    # New components of a split/merge count as structural identity births;
    # their predecessors retire after 4 misses, separately from M3 events.
    for uid in sorted(set(np.concatenate(truth))):
        where = [m for m, u in enumerate(truth) if uid in u]
        if where[0] > 0: structural.append((where[0], 'birth', uid, ()))
        retired = where[-1] + 4
        if retired < 24: structural.append((retired, 'disappearance', uid, ()))
    if any(m < 12 for m, *_ in structural): raise ValueError('truth event in 2023')
    return z, truth, structural

def world(name, seed):
    """New fixed anisotropic controls; known ontology, not economic holdout."""
    z,truth,events=base_world(name,seed)
    q=np.eye(5); angle=np.pi/4
    q[:2,:2]=[[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]]
    transform=q@np.diag([2.,.8,.4,.2,.1])
    return z@transform.T,truth,events


def labels_for(z, truth, seed, mode, atlas):
    labels, centers, kgrid = [], [], []
    for m in range(24):
        if mode == 'oracle':
            codes = {u: i for i, u in enumerate(sorted(set(truth[m])))}
            lab = np.array([codes[u] for u in truth[m]], dtype=int)
            cen = np.stack([z[lab == c, m, :].mean(axis=0) for c in range(len(codes))])
        else:
            k, rows, _ = atlas.select_k_for_month(z[:, m, :], m, seed)
            lab, cen = atlas.fit_month(z[:, m, :], m, seed, k)
            kgrid.extend([{'month': MONTHS[m], 'k': int(r[0]), 'silhouette': float(r[1]),
                           'chosen': int(r[0]) == k} for r in rows])
        labels.append(lab); centers.append(cen)
    return labels, centers, kgrid

def subject_map(labels, truth):
    result = {}
    for m, lab in enumerate(labels):
        for c in sorted(set(lab)):
            values, counts = np.unique(truth[m][lab == c], return_counts=True)
            i = int(np.argmax(counts)); uid = str(values[i]); count = int(counts[i])
            pure = count / int((lab == c).sum()) >= PURITY
            covered = count / int((truth[m] == uid).sum()) >= PURITY
            result[(MONTHS[m], int(c))] = uid if pure and covered else None
    return result

def consistent_region_status(assignments, regions):
    states = {}
    for row in assignments:
        key = (row['month'], row['label'])
        states.setdefault(key, set()).add((row['status'], row['identity_id']))
    for row in regions:
        assert states[(row['month'], row['cluster'])] == {(row['status'], row['identity_id'])}, 'region/assignment state disagreement'

def tracker_status_check(atlas):
    x = np.array([[-1.,0],[1,0],[0,-1],[0,1]])
    T, M, Tc = .27716275979336036, .7187007760980421, .17395474720266485
    for status, distance in [('birth',50.),('birth_candidate',float(np.sqrt(-4*np.log((T+Tc)/2))))]:
        moved = x + np.array([distance,0])
        z = np.stack([x,moved],axis=1)
        ar,rr,ev = atlas.track_identities(['2023-12','2024-01'],[np.zeros(4,int)]*2,
                      [x.mean(0)[None,:],moved.mean(0)[None,:]],z,np.arange(4),T,M,Tc)
        consistent_region_status(ar,rr)
        assert rr[-1]['status'] == status
        assert sum(e['kind']==status for e in ev)==1

def score(labels, truth, expected, regions, events):
    subjects = subject_map(labels, truth)
    first = {u: next(m for m, a in enumerate(truth) if u in a) for u in set(np.concatenate(truth))}
    binding = {}; bound_truth = set()
    # A predicted identity is bound once, only at the true subject's first
    # appearance. Fragmented later identities cannot be relabelled into success.
    for r in regions:
        uid = subjects[(r['month'], int(r['cluster']))]
        iid = r['identity_id']; m = MONTHS.index(r['month'])
        if uid is not None and iid and first[uid] == m and uid not in bound_truth and iid not in binding and r['status'] in ['initial','birth','birth_candidate']:
            binding[iid] = uid; bound_truth.add(uid)
    counts = {'tp':0,'fp_known':0,'fp_unknown':0,'fn':0,'tn':0,
              'cluster_decisions':0,'decided_clusters':0,'abstentions':0,
              'birth_candidates':0,'ambiguous':0,'unmatchable_clusters':0}
    bymonth = []; lastseen = {u:0 for u in set(truth[0])}
    for m in range(1,24):
        current = set(truth[m]); eligible = {u for u, seen in lastseen.items() if m-seen <= 4}
        positives = {(u,u) for u in current & eligible}
        universe = set(itertools.product(current, eligible)); predicted = set(); unknown = 0
        rr = [r for r in regions if r['month'] == MONTHS[m]]
        for r in rr:
            status = r['status']; counts['cluster_decisions'] += 1
            counts['unmatchable_clusters'] += int(subjects[(r['month'],int(r['cluster']))] is None)
            decided = status in ['continuing','reemergence','birth']
            counts['decided_clusters'] += int(decided); counts['abstentions'] += int(not decided)
            counts['birth_candidates'] += int(status == 'birth_candidate'); counts['ambiguous'] += int(status == 'ambiguous')
            if status in ['continuing','reemergence']:
                a = subjects[(r['month'],int(r['cluster']))]; b = binding.get(r['identity_id'])
                if a is None or b is None or (a,b) not in universe: unknown += 1
                else: predicted.add((a,b))
        v = {'tp':len(predicted & positives),'fp_known':len(predicted-positives),
             'fp_unknown':unknown,'fn':len(positives-predicted),'tn':len(universe-(positives|predicted))}
        for k in v: counts[k] += v[k]
        bymonth.append({'month':MONTHS[m],**v,'known_pair_universe':len(universe),
                        'true_matches':len(positives),'observed_clusters':len(rr)})
        lastseen.update({u:m for u in current})
    wanted = {(MONTHS[m], kind, uid, tuple(kids)) for m,kind,uid,kids in expected}
    matched = set(); event_rows = []; ecount = {'tp':0,'fp':0,'fn':0}
    for e in events:
        kind = e['kind']
        if kind not in EVENT_KINDS: continue
        uid = None; kids = ()
        if kind == 'birth': uid = subjects.get((e['month'],int(e['cluster'])))
        elif kind == 'disappearance': uid = binding.get(e['identity_id'])
        elif kind == 'split_candidate':
            uid = binding.get(e['identity_id'])
            kids = tuple(sorted(subjects.get((e['month'],int(c))) or 'UNKNOWN' for c in e['extra_ids'].split(';')))
        else:
            uid = subjects.get((e['month'],int(e['cluster'])))
            kids = tuple(sorted(binding.get(i) or 'UNKNOWN' for i in e['extra_ids'].split(';')))
        key = (e['month'],kind,uid,kids)
        good = key in wanted and key not in matched
        if good: matched.add(key)
        ecount['tp' if good else 'fp'] += 1
        event_rows.append({'month':e['month'],'kind':kind,'subject':uid,'others':list(kids),'matched_truth':good})
    missed = sorted(wanted-matched); ecount['fn'] = len(missed)
    return counts,ecount,bymonth,event_rows,[list(x) for x in missed]

def fraction(n,d): return None if d == 0 else n/d
def rates(c):
    fp = c['fp_known']+c['fp_unknown']
    return {'fpr_known_pairs':fraction(c['fp_known'],c['fp_known']+c['tn']),
            'fdr_all_predicted_matches':fraction(fp,c['tp']+fp),
            'fnr_known_true_matches':fraction(c['fn'],c['tp']+c['fn']),
            'cluster_decision_coverage':fraction(c['decided_clusters'],c['cluster_decisions'])}

def summarize(rows, groupfields):
    grouped = {}
    for row in rows: grouped.setdefault(tuple(row[x] for x in groupfields),[]).append(row)
    answer = []
    rng = np.random.default_rng(20261003)
    for key, members in sorted(grouped.items()):
        counts = {k:sum(x['recognition'][k] for x in members) for k in members[0]['recognition']}
        events = {k:sum(x['events'][k] for x in members) for k in ['tp','fp','fn']}
        point = rates(counts)
        point.update({'event_fdr':fraction(events['fp'],events['tp']+events['fp']),
                      'event_fnr':fraction(events['fn'],events['tp']+events['fn'])})
        # Only seeds are resampled; worlds/months/pairs are not independent units.
        perseed = {}
        for x in members: perseed.setdefault(x['seed'],[]).append(x)
        seeds = sorted(perseed); seedcounts=[]; seedevents=[]
        for seed in seeds:
            seedcounts.append({k:sum(x['recognition'][k] for x in perseed[seed]) for k in counts})
            seedevents.append({k:sum(x['events'][k] for x in perseed[seed]) for k in events})
        draws = rng.integers(0,len(seeds),size=(10000,len(seeds)))
        intervals = {}
        for metric in point:
            if metric == 'fpr_known_pairs': nums=[x['fp_known'] for x in seedcounts];dens=[x['fp_known']+x['tn'] for x in seedcounts]
            elif metric == 'fdr_all_predicted_matches': nums=[x['fp_known']+x['fp_unknown'] for x in seedcounts];dens=[x['tp']+x['fp_known']+x['fp_unknown'] for x in seedcounts]
            elif metric == 'fnr_known_true_matches': nums=[x['fn'] for x in seedcounts];dens=[x['tp']+x['fn'] for x in seedcounts]
            elif metric == 'cluster_decision_coverage': nums=[x['decided_clusters'] for x in seedcounts];dens=[x['cluster_decisions'] for x in seedcounts]
            elif metric == 'event_fdr': nums=[x['fp'] for x in seedevents];dens=[x['tp']+x['fp'] for x in seedevents]
            else: nums=[x['fn'] for x in seedevents];dens=[x['tp']+x['fn'] for x in seedevents]
            n=np.array(nums)[draws].sum(axis=1);d=np.array(dens)[draws].sum(axis=1);valid=d>0
            values=n[valid]/d[valid]
            intervals[metric]={'lo':float(np.quantile(values,.025)) if len(values) else None,
                               'hi':float(np.quantile(values,.975)) if len(values) else None,
                               'valid_draws':int(valid.sum()),'resampled_seeds':len(seeds)}
        answer.append({**dict(zip(groupfields,key)),'n_runs':len(members),'recognition':counts,'events':events,'rates':point,'seed_block_95ci':intervals})
    return answer

def self_check(src=None):
    truth=[np.array(['A','B'])]*24;labels=[np.array([0,1])]*24
    regions=[{'month':MONTHS[m],'cluster':i,'identity_id':'x'+str(i),'status':'initial' if m==0 else 'continuing'} for m in range(24) for i in range(2)]
    c,e,*_=score(labels,truth,[],regions,[])
    assert c['tp']==46 and c['tn']==46 and c['fn']==c['fp_known']==c['fp_unknown']==0
    wrong=[dict(r,identity_id='x'+str(1-r['cluster'])) if r['month']!=MONTHS[0] else r for r in regions]
    c,*_=score(labels,truth,[],wrong,[])
    assert c['tp']==0 and c['fp_known']==46 and c['fn']==46 and c['tn']==0
    silent=[dict(r,status='ambiguous') if r['month']!=MONTHS[0] else r for r in regions]
    c,*_=score(labels,truth,[],silent,[])
    assert c['fn']==46 and c['abstentions']==46 and c['decided_clusters']==0
    ev={'kind':'birth','month':MONTHS[12],'cluster':0,'identity_id':'x0','extra_ids':''}
    c,e,*_=score(labels,truth,[(12,'birth','A',())],regions,[ev,ev])
    assert e=={'tp':1,'fp':1,'fn':0}
    for name in WORLDS:
        z,t,expect=world(name,SEEDS[0]);z2,t2,e2=world(name,SEEDS[0])
        assert z.shape==(200,24,5) and np.array_equal(z,z2) and expect==e2
        assert all(m>=12 for m,*_ in expect)
    assert fraction(0,0) is None
    if src is not None:
        sys.path.insert(0,str(src)); import a6_geometry_v3 as atlas
        tracker_status_check(atlas)
    print(json.dumps({'self_check':True,'checks':['perfect/wrong/abstain recognition denominators','one-to-one duplicate event rejection','deterministic generators','2024-only truth events','zero denominator remains NA']}))

def evaluate_budget(results,budget):
    """Fixed empirical budget, evaluated separately for both primary modes."""
    outcomes=[]
    for mode in ['oracle','unsupervised']:
        selected=[r for r in results if r['mode']==mode and r['margin_factor']==1.]
        if len(selected)!=35 or len({(r['seed'],r['world']) for r in selected})!=35:
            outcomes.append({'mode':mode,'status':'INCONCLUSIVE','reason':'incomplete primary mask'}); continue
        c={k:sum(r['recognition'][k] for r in selected) for k in selected[0]['recognition']}
        e={k:sum(r['events'][k] for r in selected) for k in ['tp','fp','fn']}
        measured=rates(c)
        measured.update(event_fdr=fraction(e['fp'],e['tp']+e['fp']),event_fnr=fraction(e['fn'],e['tp']+e['fn']))
        if any(v is None for v in measured.values()):
            outcomes.append({'mode':mode,'status':'INCONCLUSIVE','rates':measured}); continue
        false_m3=sum(r['negative_m3_false_events'] for r in selected)
        checks={'recognition_FDR':measured['fdr_all_predicted_matches']<=budget['recognition_FDR_max'],
                'recognition_FNR':measured['fnr_known_true_matches']<=budget['recognition_FNR_max'],
                'coverage':measured['cluster_decision_coverage']>=budget['coverage_min'],
                'event_FDR':measured['event_fdr']<=budget['event_FDR_max'],
                'event_FNR':measured['event_fnr']<=budget['event_FNR_max'],
                'negative_M3_false_events':false_m3<=budget['stable_drift_proximity_split_merge_false_events_max']}
        outcomes.append({'mode':mode,'status':'PASS' if all(checks.values()) else 'FAIL','rates':measured,'negative_M3_false_events':false_m3,'checks':checks})
    status='INCONCLUSIVE' if any(r['status']=='INCONCLUSIVE' for r in outcomes) else ('PASS' if all(r['status']=='PASS' for r in outcomes) else 'FAIL')
    return {'status':status,'scope':'fixed synthetic suite empirical error budget; not economic identity acceptance','scientific_pass':False,'modes':outcomes,'threshold_retuning_permitted':False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--atlas-src',type=Path);p.add_argument('--calibration',type=Path)
    p.add_argument('--out',type=Path);p.add_argument('--self-check',action='store_true');a=p.parse_args()
    if a.self_check: self_check(a.atlas_src);return
    if not all([a.atlas_src,a.calibration,a.out]): p.error('atlas-src/calibration/out required')
    if a.out.exists(): raise FileExistsError('new run only')
    sys.path.insert(0,str(a.atlas_src));import a6_geometry_v3 as atlas
    cal=json.loads(a.calibration.read_text())
    spec_path=Path(__file__).resolve().parents[1]/'protocol/geometry-v3-20261007/protocol.json'
    spec=json.loads(spec_path.read_text())
    if cal.get('geometry_version')!='geometry-v3.1': raise ValueError('new ellipsoid calibration required; legacy thresholds incompatible')
    if spec['controls']['seeds']!=SEEDS or spec['controls']['worlds']!=WORLDS: raise ValueError('protocol/code controls mismatch')
    if cal['cal_months'] != list(range(12)) or cal['fallback']: raise ValueError('invalid frozen calibration')
    a.out.mkdir(parents=True)
    protocol={'recorded_before_calculation':datetime.now(timezone.utc).isoformat(),'seeds':SEEDS,'worlds':WORLDS,'margin_factors':FACTORS,
              'modes':['oracle','unsupervised'],'fixed_purity_and_recall':PURITY,'n':200,'dimensions':5,'months':MONTHS,
              'frozen_thresholds':{k:cal[k] for k in ['overlap_threshold','candidate_margin','resemblance_floor']},
              'truth_events_2024_only':True,'no_recalibration':True,'bootstrap_seed_blocks':10000,
              'recognition_fpr':'FP_known/(FP_known+TN) over current true subject x eligible prior true identity; unknown predictions reported separately',
              'recognition_fdr':'(FP_known+FP_unknown)/(TP+FP_known+FP_unknown)',
              'recognition_miss':'FN/(TP+FN), abstentions count as misses of true matches',
              'coverage':'continuing/reemergence/birth cluster decisions divided by all postinitial cluster decisions; ambiguous/birth_candidate abstain',
              'event_matching':'exact month/kind/subject/child-or-parent set; subject requires >=.8 purity AND >=.8 coverage; one-to-one; duplicate predictions FP',
              'identity_binding':'once only at true first appearance; no retrospective remapping of fragmented IDs',
              'birth_semantics':'new latent component, including split children and merged component; predecessors retire after four misses',
              'event_fpr':None,'event_fpr_note':'no predefined TN event universe; report FDR/FNR instead',
              'sha256':{'calibration':sha(a.calibration),'tracker':sha(a.atlas_src/'a6_geometry_v3.py'),'control_code':sha(__file__)},
              'scientific_pass':False,'empirical_panel_changed':False,'geometry_version':'geometry-v3.1','prospective_protocol_sha256':sha(spec_path),'error_budget':spec['error_budget'],'generator':spec['controls']['generator']}
    (a.out/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
    results=[];allmonths=[];allevents=[];krows=[];truth_rows=[]
    for seed in SEEDS:
        for name in WORLDS:
            z,truth,expected=world(name,seed)
            truth_rows.append({'seed':seed,'world':name,'expected':expected})
            for mode in ['oracle','unsupervised']:
                labs,centers,kgrid=labels_for(z,truth,seed,mode,atlas)
                krows.extend([{'seed':seed,'world':name,'mode':mode,**x} for x in kgrid])
                for factor in FACTORS:
                    ar,rr,events=atlas.track_identities(MONTHS,labs,centers,z,np.arange(200),
                                cal['overlap_threshold'],cal['candidate_margin']*factor,cal['resemblance_floor'])
                    consistent_region_status(ar,rr)
                    sm,sensitivity=atlas.detect_split_merge(MONTHS,labs,z,ar,rr)
                    c,e,bymonth,erows,missed=score(labs,truth,expected,rr,events+sm)
                    key={'seed':seed,'world':name,'mode':mode,'margin_factor':factor}
                    results.append({**key,'recognition':c,'events':e,'missed_events':missed,
                                    'negative_m3_false_events':sum(not e['matched_truth'] and e['kind'] in ['split_candidate','merge_candidate'] for e in erows) if name in ['stable','drift','proximity'] else 0,'m3_sensitivity_counts':sensitivity,'selected_k':[int(len(set(x))) for x in labs]})
                    allmonths.extend([{**key,**x} for x in bymonth]);allevents.extend([{**key,**x} for x in erows])
            print(json.dumps({'seed':seed,'world':name,'complete':True}),flush=True)
    versions={name:__import__(name).__version__ for name in ['numpy','pandas','scipy','sklearn']}
    metrics={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'quantitative_frozen_threshold_synthetic_controls',
             'n_runs':len(results),'n_seeds':5,'primary_margin_factor':1.,'summary':summarize(results,['mode','margin_factor']),
             'by_world':summarize(results,['mode','margin_factor','world']),'versions':{'python':sys.version.split()[0],**versions},
             'sha256':protocol['sha256'],'scientific_pass':False,'economic_truth_verified':False,
             'limits':['Known generator hypotheses, not real economic events; toy geometries are not calibrated to observed municipal distributions',
                       'Oracle mode receives true membership, Unsupervised K-selection-to-M2/M3 never receives truth; raw-spending/scaler pipeline is not tested by these generators',
                       'Real frozen 2023 T/M/Tc transfer to synthetic five-dimensional stress worlds; no threshold retuning',
                       'Five independent seeds only; descriptive seed-block CIs may degenerate and do not imply zero population error',
                       'False recognition pairs have a fixed known candidate universe; unknown predictions separate. No TN universe claimed for events',
                       'Structural component births/deaths may co-occur with split/merge; ontology and four-miss delay declared before computation',
                       'Fixed prospective error budget applies only to this known-ontology synthetic suite; negative/inconclusive outcomes retained; no economic scientific PASS']}
    metrics['acceptance']=evaluate_budget(results,spec['error_budget'])
    for name,value in [('metrics.json',metrics),('runs.json',results),('truth.json',truth_rows),('events.json',allevents),('months.json',allmonths),('k-grid.json',krows)]:
        (a.out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'status':metrics['status'],'n_runs':len(results),'summary':metrics['summary']},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
