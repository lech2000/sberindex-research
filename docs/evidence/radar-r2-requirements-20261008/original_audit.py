import time
ENTRY = time.monotonic()
import sys, os, json, math, hashlib, pathlib, datetime, signal, resource

OUT = pathlib.Path('/private/tmp/sberindex-r2-requirement-audit-20261008')
P = json.loads((OUT / 'PROTOCOL.json').read_text())
SOURCE = pathlib.Path(__file__)
INPUT = pathlib.Path(P['input_path'])
MODELS = P['models']

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def guard():
    if time.monotonic() - P['original_monotonic_anchor'] >= 300:
        raise TimeoutError('original 300s operation budget exhausted; no retry')
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 2**30:
        raise MemoryError('sampled RSS exceeds 1GiB')

def timeout(*args):
    raise TimeoutError('original deadline reached; no retry')

def score(actual, predicted):
    if len(actual) != len(predicted) or len(actual) < 2:
        raise ValueError('paired arrays require at least two observations')
    if not all(math.isfinite(x) for x in actual + predicted):
        raise ValueError('nonfinite data')
    mean = math.fsum(actual) / len(actual)
    sst = math.fsum((x - mean)**2 for x in actual)
    sse = math.fsum((x - y)**2 for x, y in zip(actual, predicted))
    return {'n': len(actual), 'mae': math.fsum(abs(x-y) for x,y in zip(actual,predicted))/len(actual),
            'sse': sse, 'sst': sst, 'r2': None if sst == 0 else 1-sse/sst}

def selfcheck():
    assert score([1.,2.,3.], [1.,2.,3.])['r2'] == 1
    assert score([1.,2.,3.], [2.,2.,2.])['r2'] == 0
    assert score([1.,2.,3.], [0.,0.,0.])['r2'] == -6
    assert score([1.,1.,1.], [1.,1.,1.])['r2'] is None
    assert score([1.,1.,1.], [2.,2.,2.])['r2'] is None
    assert math.isclose(score([3.,-.5,2.,7.],[2.5,0.,2.,8.])['r2'], 1-1.5/29.1875, abs_tol=1e-14)
    assert math.isclose(score([10.,20.,30.],[0.,0.,0.])['r2'], -6, abs_tol=1e-14)
    for a,b in [([1.],[1.]),([1.,2.],[1.]),([1.,float('nan')],[1.,2.])]:
        try: score(a,b)
        except ValueError: pass
        else: raise AssertionError('invalid pair accepted')

selfcheck()
assert sha(SOURCE) == P['source_sha256']
assert sha(INPUT) == P['input_sha256']
guard()
signal.signal(signal.SIGALRM, timeout)
signal.setitimer(signal.ITIMER_REAL, max(.001,300-(time.monotonic()-P['original_monotonic_anchor'])))
if (OUT / 'CONSUMED_ONE_USE.json').exists():
    raise RuntimeError('operation already consumed')
with (OUT / 'CONSUMED_ONE_USE.json').open('x') as f:
    json.dump({'started_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':os.getpid()},f)
    f.flush();os.fsync(f.fileno())

import pyarrow.parquet as pq
CATS = {'Все категории','Здоровье','Маркетплейсы','Общественное питание','Продовольствие','Транспорт'}
TARGETS = {f'2024-{month:02}' for month in range(7,13)}
KEY = ['territory_id','category','horizon','origin','target']
def month(s):
    return int(s[:4])*12+int(s[5:7])

rows = []
keys = set()
series = {}
for batch in pq.ParquetFile(INPUT).iter_batches(batch_size=1024,columns=KEY+['actual']+MODELS,use_threads=False):
    for row in batch.to_pylist():
        key = tuple(str(row[x]) for x in KEY)
        assert key not in keys
        assert row['horizon']==12 and month(row['target'])-month(row['origin'])==12
        assert row['category'] in CATS and row['target'] in TARGETS
        assert all(isinstance(row[x],(int,float)) and math.isfinite(row[x]) for x in ['actual']+MODELS)
        keys.add(key);rows.append(row)
        series.setdefault((str(row['territory_id']),row['category']),[]).append(row)
    guard()
assert len(rows)==720 and len(series)==120 and len({k[0] for k in series})==20
for group in series.values():
    assert len(group)==6 and {r['target'] for r in group}==TARGETS
    group.sort(key=lambda r:r['target'])
key_sha = hashlib.sha256(json.dumps(sorted(keys),separators=(',',':')).encode()).hexdigest()
assert key_sha == P['expected_full_key_sha256']

pooled={m:score([r['actual'] for r in rows],[r[m] for r in rows]) for m in MODELS}
by_category={cat:{m:score([r['actual'] for r in rows if r['category']==cat],[r[m] for r in rows if r['category']==cat]) for m in MODELS} for cat in sorted(CATS)}
per_series=[{'territory_id':k[0],'category':k[1],'models':{m:score([r['actual'] for r in group],[r[m] for r in group]) for m in MODELS}} for k,group in sorted(series.items())]
macro={}
for m in MODELS:
    valid=[g['models'][m]['r2'] for g in per_series if g['models'][m]['r2'] is not None]
    sorted_valid=sorted(valid);n=len(valid)
    total_sse=math.fsum(g['models'][m]['sse'] for g in per_series)
    total_sst=math.fsum(g['models'][m]['sst'] for g in per_series)
    macro[m]={'defined_series':n,'undefined_constant_series':len(per_series)-n,
              'mean_series_r2':None if not n else math.fsum(valid)/n,
              'median_series_r2':None if not n else (sorted_valid[(n-1)//2]+sorted_valid[n//2])/2,
              'within_series_centered_r2':None if total_sst==0 else 1-total_sse/total_sst}
baseline='national_prophet';candidate='national_yoy_lag1'
defined=[g for g in per_series if g['models'][baseline]['r2'] is not None]
better=sum(g['models'][candidate]['r2']>g['models'][baseline]['r2'] for g in defined)
equal=sum(g['models'][candidate]['r2']==g['models'][baseline]['r2'] for g in defined)
assert sha(INPUT)==P['input_sha256'] and sha(SOURCE)==P['source_sha256']
guard()
result={'state':'PAIRED_R2_POSTHOC_ADDITIONAL_METRIC','checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'scope':P['scope'],'pooled':pooled,'by_category':by_category,'macro_series':macro,'per_series':per_series,
        'series_candidate_better_r2':better,'series_equal_r2':equal,'series_defined':len(defined),
        'input_sha256':sha(INPUT),'full_key_sha256':key_sha,'source_sha256':sha(SOURCE),
        'formulas':'R2=1-sum((actual-predicted)^2)/sum((actual-mean(actual))^2); constant target variance -> null, no force_finite substitution',
        'limitations':P['limitations'],'new_models_fits_bootstraps_windows':0,'scientific_pass':False,
        'elapsed_from_original_anchor_seconds':time.monotonic()-P['original_monotonic_anchor'],
        'sampled_peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
with (OUT/'RESULT.json').open('x') as f:
    json.dump(result,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
guard();signal.setitimer(signal.ITIMER_REAL,0)
print(json.dumps({k:result[k] for k in ['state','pooled','macro_series','series_candidate_better_r2','series_defined','elapsed_from_original_anchor_seconds']},ensure_ascii=False,indent=2))
