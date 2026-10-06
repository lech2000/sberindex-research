"""Frozen N1/N2 positive control: signal regime1→2→1, never real warnings."""
import argparse,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
import pandas as pd
from d02_d03_detectors import d01_alarms,d02_alarms,d03_alarms,apply_cooldown,truncate_budget_monthly

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def synthetic(seed,family,amplitude,n=100,changed_n=10):
    rng=np.random.default_rng(seed);eps=rng.normal(size=(n,24))
    if family=='student5':eps=rng.standard_t(5,size=(n,24))*np.sqrt(3/5)
    noise=.05*eps
    changed=rng.choice(n,changed_n,replace=False);directions=rng.choice([-1.,1.],changed_n)
    shifted=noise.copy();shifted[changed,18:21]+=amplitude*.05*directions[:,None]
    months=pd.period_range('2023-01','2024-12',freq='M').astype(str).tolist()
    def frame(values):return pd.DataFrame({'tid':np.repeat([f'synthetic_{i:03d}' for i in range(n)],24),'cat':'synthetic_signal','ym':np.tile(months,n),'rel':values.ravel()})
    ids=[f'synthetic_{i:03d}' for i in changed]
    return frame(noise),frame(shifted),ids


def bank(d,protocol):
    params=protocol['parameters'];out={}
    builders={'D01':lambda:d01_alarms(d,'rel',params['D01']['k'],train_end='2024-03'),
              'D02':lambda:d02_alarms(d,'rel',params['D02']['delta'],params['D02']['lambda']),
              'D03':lambda:d03_alarms(d,'rel',params['D03']['tau'],hazard=.02,n0=10.,rmax=24,train_end='2024-03',strict_log_support=True)}
    for name,fn in builders.items():
        raw=apply_cooldown(fn(),3);period=raw.loc[raw.ym.between('2024-07','2024-12')].copy()
        kept=truncate_budget_monthly(period,24)
        assert kept.groupby('ym').size().le(24).all()
        out[name]=kept
    return out


def match(alarms,ids,onset,window):
    end=str(pd.Period(onset,freq='M')+window);delays=[];hits=[]
    for tid in ids:
        rows=alarms.loc[alarms.tid.eq(tid)&alarms.ym.between(onset,end)]
        hit=bool(len(rows));hits.append(hit)
        delays.append((pd.Period(rows.ym.min(),freq='M')-pd.Period(onset,freq='M')).n if hit else None)
    return np.array(hits,bool),delays


def run(a):
    proto=json.loads(a.protocol.read_text());assert sha(a.frozen_r7)==proto['r7_manifest_sha256']
    original=json.loads(a.frozen_r7.read_text());assert proto['parameters']==original['fitted_on_validation_only'] and original['monthly_budget']==24
    if a.out.exists():raise FileExistsError('new run only')
    a.out.mkdir(parents=True);rows=[];alarms=[];audits=[]
    for family in proto['families']:
        for seed in proto['seeds']:
            null,_,_=synthetic(seed,family,4)
            nullbank=bank(null,proto)
            for amplitude in proto['amplitudes']:
                _,d,ids=synthetic(seed,family,amplitude);actual=bank(d,proto)
                for method,selected in actual.items():
                    count_null=len(nullbank[method])
                    for window in (1,2):
                        enter,enter_delay=match(selected,ids,'2024-07',window)
                        leave,leave_delay=match(selected,ids,'2024-10',window)
                        rows.append({'family':family,'seed':seed,'amplitude':amplitude,'method':method,'window_after_onset':window,'events_per_transition':len(ids),'enter_hits':int(enter.sum()),'return_hits':int(leave.sum()),'both_hits':int((enter&leave).sum()),'enter_delays':enter_delay,'return_delays':leave_delay,'null_alarms':count_null,'null_cells':100*6,'selected_alarms':len(selected),'alarms_on_unchanged_series':int((~selected.tid.isin(ids)).sum())})
                    part=selected.copy();part['family']=family;part['seed']=seed;part['amplitude']=amplitude;part['is_changed']=part.tid.isin(ids);alarms.append(part)
                # Full detector+cooldown+monthly cap prefix test, not just score-array test.
                if amplitude==4 and seed==proto['seeds'][0]:
                    prefix=d.loc[d.ym.le('2024-08')].copy();changed=d.copy();changed.loc[changed.ym.gt('2024-08'),'rel']=1e6
                    before,edited=bank(prefix,proto),bank(changed,proto)
                    for method in actual:
                        columns=['method','tid','cat','ym','score']
                        left=actual[method].loc[actual[method].ym.le('2024-08'),columns].sort_values(columns[:4]).reset_index(drop=True)
                        for variant in (before,edited):
                            right=variant[method].loc[variant[method].ym.le('2024-08'),columns].sort_values(columns[:4]).reset_index(drop=True)
                            pd.testing.assert_frame_equal(left,right,check_dtype=False)
                        audits.append({'family':family,'method':method,'prefix_equals_full_and_mutated_future':True,'retained_alerts':len(left)})
                print(json.dumps({'family':family,'seed':seed,'amplitude':amplitude,'complete':True}),flush=True)
    pd.concat(alarms,ignore_index=True).to_parquet(a.out/'alerts.parquet',index=False)
    (a.out/'by-seed.json').write_text(json.dumps(rows,indent=2)+'\n')
    summary=[]
    for family in proto['families']:
        for amplitude in proto['amplitudes']:
            for method in ('D01','D02','D03'):
                for window in (1,2):
                    group=[row for row in rows if (row['family'],row['amplitude'],row['method'],row['window_after_onset'])==(family,amplitude,method,window)]
                    entry={'family':family,'amplitude':amplitude,'method':method,'window_after_onset':window,'transition_events':sum(x['events_per_transition'] for x in group),'seed_blocks':len(group),'null_alerts':sum(x['null_alarms'] for x in group),'null_cells':sum(x['null_cells'] for x in group)}
                    for name in ('enter','return','both'):
                        hits=np.array([x[name+'_hits'] for x in group]);totals=np.array([x['events_per_transition'] for x in group]);draw=np.random.default_rng(20261007).integers(0,len(group),(10000,len(group)))
                        entry[name+'_recall']=float(hits.sum()/totals.sum());entry[name+'_hits']=int(hits.sum());entry[name+'_descriptive_seed_ci95']=np.quantile(hits[draw].sum(1)/totals[draw].sum(1),[.025,.975]).tolist()
                        if name!='both':
                            delays=[v for row in group for v in row[name+'_delays'] if v is not None];entry[name+'_median_delay_among_hits']=float(np.median(delays)) if delays else None
                    entry['null_alert_cell_rate']=entry['null_alerts']/entry['null_cells'];summary.append(entry)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'status':'N1_N2_RETURN_REGIME_CONTROL_EXECUTED','scientific_pass':False,'is_real_warning_test':False,'unit':'synthetic signal series, not municipalities or spending levels','primary_amplitude':4,'primary_window_after_onset':1,'monthly_selected_alert_cap':24,'equal_false_alarm_rates_claimed':False,'rows_by_seed':len(rows),'synthetic_bank_runs':len(proto['families'])*len(proto['seeds'])*(1+len(proto['amplitudes'])),'detector_runs':len(proto['families'])*len(proto['seeds'])*(1+len(proto['amplitudes']))*3,'prefix_tests':audits,'summary':summary,'protocol_sha256':sha(a.protocol),'code_sha256':sha(__file__),'detector_code_sha256':sha(Path(__file__).with_name('d02_d03_detectors.py')),'alerts_sha256':sha(a.out/'alerts.parquet'),'limits':proto['limits']}
    (a.out/'metrics.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'status':result['status'],'primary':[x for x in summary if x['amplitude']==4 and x['window_after_onset']==1]}))


def main():
    p=argparse.ArgumentParser()
    for key in ['frozen-r7','protocol','out']:p.add_argument('--'+key,type=Path,required=True)
    run(p.parse_args())

if __name__=='__main__':main()
