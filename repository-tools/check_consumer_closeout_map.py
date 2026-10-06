"""Byte/hash and all embedded numeric values versus saved forecast keys."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
R = Path(__file__).resolve().parents[1]
folder = R/'economic-atlas/site/consumer-closeout-20261006'
manifest = json.loads((folder/'manifest.json').read_text())
for name, expected in manifest['files'].items():
    assert hashlib.sha256((folder/name).read_bytes()).hexdigest() == expected
js = next(folder.glob('consumer-map-*.js')).read_text()
data = json.loads(js.split('const D=', 1)[1].split(';const byId=', 1)[0])
original = json.loads((R/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2/anomalies.json').read_text())
assert [r['id'] for r in data] == [r['territory_id'] for r in original]
p = pd.read_parquet(R/'economic-atlas/runs/Consumer_closeout_20261006/predictions.parquet')
groups = {(int(tid), c, int(h)): g.sort_values('target')
          for (tid, c, h), g in p.groupby(['territory_id', 'category', 'horizon'])}
numbers = 0
for r, old in zip(data, original):
    assert r['name'] == old['name'] and r['region'] == old['region_name']
    assert r['supported'] == old['supported']
    assert r['market'] == old['Маркетплейсы']
    if not r['supported']:
        assert r['forecast'] is None
        continue
    for c, short in [('Все категории', 'all'), ('Маркетплейсы', 'market')]:
        for h in [1, 3, 6]:
            expected = groups[r['id'], c, h][['actual', 'profile_ses', 'one_step_zero_peer', 'direct_zero_peer']].round(6).to_numpy()
            np.testing.assert_array_equal(np.array(r['forecast'][short+str(h)]), expected)
            numbers += expected.size
assert sum(r['signal'] for r in data) == 25
assert sum(r['core'] for r in data) == 9
receipt = {'status': 'TECHNICAL_PASS', 'municipalities': len(data),
    'source_names_support_and_original_marketplace_fields_exact': True,
    'forecast_numbers_at_declared_6_decimal_precision': numbers,
    'signals': 25, 'core80': 9, 'browser_qa': 'SEPARATE'}
out = R/'docs/evidence/research-closeout-20261006/map-numeric-check.json'
out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(receipt))
