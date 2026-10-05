"""Build a self-contained point map and explanatory histories from a frozen run."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from consumption_restructuring import dump, sha


def rounded(x):
    return [None if not np.isfinite(v) else float(v) for v in np.round(x, 4)]


def build(run, template, out):
    metrics = json.loads((run/'metrics.json').read_text())
    records = json.loads((run/'anomalies.json').read_text())
    arrays = np.load(run/'deviations.npz')
    p = pd.read_parquet(run/'predictions.parquet')
    peers = pd.read_csv(run/'peers.csv')
    groups = {int(t): g for t, g in p[p.category == 'Все категории'].groupby('territory_id')}
    matched = peers.loc[peers.status == 'SUPPORTED'].groupby('territory_id')
    rows = []
    cats = ['Здоровье', 'Маркетплейсы', 'Общественное питание', 'Продовольствие', 'Транспорт']
    nominal_cats = ['Все категории']+cats
    for i, r in enumerate(records):
        record = dict(r)
        record['peers'] = matched.get_group(r['territory_id']).peer_tid.astype(int).tolist() if r['supported'] else []
        record['series'] = {}
        for k, cat in enumerate(cats):
            record['series'][cat] = {key: rounded(arrays[key][i, :, k]) for key in ['dy', 'gap', 'common_gap', 'score']}
            record['series'][cat]['flag'] = arrays['flag'][i, :, k].astype(int).tolist()
            record['series'][cat]['nominal_gap'] = rounded(arrays['nominal_gap'][i, :, nominal_cats.index(cat)])
        record['forecast'] = {}
        for h, b in groups[r['territory_id']].groupby('horizon'):
            b = b.sort_values('target')
            record['forecast'][str(int(h))] = {'origin': b.origin.tolist(),
                'actual': rounded(b.actual.to_numpy()), 'base': rounded(b.profile_ses.to_numpy()),
                'peer': rounded(b.peer_ridge.to_numpy()), 'cold': b.cold_start.astype(int).tolist()}
        rows.append(record)
    data = {'territories': rows, 'stories': metrics['story_ids'], 'categories': cats,
            'metrics': metrics, 'source_sha256': sha(run/'manifest.json')}
    text = template.read_text().replace('__DATA_JSON__', json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', '<\\/'))
    out.mkdir(parents=True, exist_ok=True)
    (out/'index.html').write_text(text)
    dump(out/'manifest.json', {'source_run': run.name, 'source_manifest_sha256': sha(run/'manifest.json'),
        'template_sha256': sha(template), 'builder_sha256': sha(__file__),
        'html_sha256': sha(out/'index.html'), 'territories': len(rows),
        'supported': metrics['supported'], 'standalone_no_network': True})


if __name__ == '__main__':
    a = argparse.ArgumentParser()
    a.add_argument('--run', type=Path, required=True)
    a.add_argument('--template', type=Path, required=True)
    a.add_argument('--out', type=Path, required=True)
    args = a.parse_args()
    build(args.run, args.template, args.out)
