import argparse
import hashlib
import json
import math
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
for name in ['run', 'raw', 'national', 'r9']:
    parser.add_argument('--' + name, type=Path, required=True)
args = parser.parse_args()
protocol = json.loads((args.run / 'protocol.json').read_text())
metrics = json.loads((args.run / 'metrics.json').read_text())
for name in ['raw', 'r9', 'national']:
    assert digest(getattr(args, name)) == protocol['input_sha256'][name]
assert digest(args.run / 'protocol.json') == metrics['sha256']['protocol']
assert digest(args.run / 'predictions.parquet') == metrics['sha256']['predictions']
pred = pd.read_parquet(args.run / 'predictions.parquet')
raw = pd.read_parquet(args.raw)
raw['territory_id'] = raw.territory_id.astype(str)
raw['month'] = pd.PeriodIndex(raw.date, freq='M').astype(str)
lookup = {(r.territory_id, r.category, r.month): float(r.value) for r in raw.itertuples()}
national = pd.read_parquet(args.national)
national['month'] = pd.to_datetime(national.period, utc=True).dt.tz_convert('Europe/Moscow').dt.tz_localize(None).dt.to_period('M').astype(str)
N = dict(national.loc[national.type == 'Всего', ['month', 'value']].itertuples(index=False, name=None))
r9 = pd.read_parquet(args.r9)
r9['territory_id'] = r9.territory_id.astype(str)
stored = {tuple(getattr(r, k) for k in ['territory_id', 'category', 'horizon', 'origin', 'target']): r for r in r9.itertuples() if r.horizon == 12}
assert len(pred) == 720 and pred.territory_id.nunique() == metrics['municipalities']
assert set(zip(pred.territory_id, pred.category)) == {(r['territory_id'], r['category']) for r in protocol['selection_manifest']}
checks = 0
for row in pred.itertuples():
    origin = pd.Period(row.origin, freq='M')
    assert str(origin + 12) == row.target and str(origin - 1) == row.national_cutoff
    assert row.actual == lookup[row.territory_id, row.category, row.target]
    assert row.last_value == lookup[row.territory_id, row.category, row.origin]
    expected = row.last_value * float(N[str(origin - 1)]) / float(N[str(origin - 13)])
    assert math.isclose(expected, row.national_yoy_lag1, rel_tol=1e-12)
    assert row.stored_prophet == stored[row.territory_id, row.category, 12, row.origin, row.target].pred_prophet
    checks += 5
result = []
for comp in metrics['results']:
    candidate = [abs(float(r.actual) - float(getattr(r, comp['model']))) for r in pred.itertuples()]
    reference = [abs(float(r.actual) - float(getattr(r, comp['reference']))) for r in pred.itertuples()]
    mae = math.fsum(candidate) / len(candidate)
    base = math.fsum(reference) / len(reference)
    assert math.isclose(mae, comp['mae_model'], rel_tol=1e-12)
    assert math.isclose(base, comp['mae_reference'], rel_tol=1e-12)
    monthly = {}
    for row, a, b in zip(pred.itertuples(), candidate, reference):
        monthly.setdefault(row.target, []).append(b - a)
    assert sorted(monthly) == protocol['target_months'] and all(len(v) == 120 for v in monthly.values())
    means = np.array([math.fsum(monthly[m]) / 120 for m in sorted(monthly)])
    ids = np.random.default_rng(protocol['seed']).integers(0, 6, (10000, 6))
    ci = np.quantile(np.mean(means[ids], axis=1), [.025, .975])
    np.testing.assert_allclose(ci, comp['benefit_ci95_target_months'], rtol=1e-12, atol=1e-10)
    result.append({'model': comp['model'], 'reference': comp['reference'], 'mae': mae,
                   'reference_mae': base, 'ci95': ci.tolist()})
assert json.loads((args.run / 'failures.json').read_text()) == []
audit = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'INDEPENDENT_NUMERICAL_AUDIT_PASS',
         'rows': 720, 'scalar_raw_cached_formula_clock_checks': checks,
         'comparisons_independently_recomputed': len(result), 'results': result,
         'protocol_sha256': digest(args.run / 'protocol.json'), 'predictions_sha256': digest(args.run / 'predictions.parquet'),
         'audit_code_sha256': digest(__file__), 'scientific_pass': False,
         'scope': 'Separate code, same frozen data; independent technical audit, not external scientific validation or unseen holdout'}
(args.run / 'independent-audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(audit, ensure_ascii=False), flush=True)
