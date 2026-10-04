"""Append the owner-file supplement to a NEW local graph, with typed lineage."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(base, base_receipt, supplement, out):
    if out.exists():
        raise FileExistsError('New graph run required')
    prior = json.loads(base_receipt.read_text())
    original_sha = sha(base)
    if original_sha != prior['new_db_sha256']:
        raise ValueError('Base graph checksum')
    manifest = json.loads((supplement / 'manifest.json').read_text())
    for name, meta in manifest['files'].items():
        if sha(supplement / name) != meta['sha256']:
            raise ValueError('Supplement checksum: ' + name)
    d = pd.read_parquet(supplement / 'observations.parquet')
    sources = json.loads((supplement / 'sources.json').read_text())
    if len(d) != 77 or d.territory_id.isna().any() or d.available_at.notna().any():
        raise ValueError('Supplement scope')
    out.mkdir(parents=True)
    c = sqlite3.connect(out / 'graph.sqlite')
    old = sqlite3.connect('file:' + str(base) + '?mode=ro', uri=True)
    old.backup(c)
    old.close()
    c.execute('PRAGMA foreign_keys=ON')
    before = c.execute('SELECT COUNT(*) FROM observation').fetchone()[0]
    fiscal_before = c.execute('SELECT COUNT(*) FROM fiscal_cell').fetchone()[0]
    now = datetime.now(timezone.utc).isoformat()
    with c:
        c.execute('''CREATE TABLE budget_supplement_cell(
            observation_id TEXT PRIMARY KEY REFERENCES observation(id),
            value_kopecks INTEGER, source_literal TEXT NOT NULL,
            source_unit TEXT NOT NULL, source_resolution TEXT NOT NULL,
            source_locator TEXT NOT NULL, source_formula TEXT,
            measure TEXT NOT NULL, period_kind TEXT NOT NULL,
            period_start TEXT, period_end TEXT NOT NULL,
            classification_namespace TEXT NOT NULL,
            historical_boundary_verified INTEGER NOT NULL CHECK(historical_boundary_verified=0))''')
        for s in sources:
            if s['territory_id'] is None:
                continue
            c.execute('INSERT INTO dataset_release VALUES(?,?,?,?,?,?,?,?,?)',
                ('budget-supplement-' + s['sha256'], 'Owner-supplied municipal document; online source not verified',
                 'urn:sha256:' + s['sha256'], s['sha256'], now, now[:10], None, None, 'redistribution_not_assessed'))
        for r in d.itertuples(index=False):
            rid = 'budget-supplement-' + r.source_sha256
            iid = 'budget_supplement_' + r.metric + '_' + r.measure
            unit = 'kopeck' if pd.notna(r.value_kopecks) else r.source_unit
            c.execute('INSERT OR IGNORE INTO indicator VALUES(?,?,?,?)',
                      (iid, r.classification_namespace + ': ' + r.metric + ' / ' + r.measure, unit, 'source_unit_and_resolution_verified'))
            period = str(r.year) + '-H1' if r.period_kind == 'H1' else r.period_end if r.period_kind == 'plan_as_of_July_1' else str(r.year)
            dims = json.dumps({'measure': r.measure, 'period_kind': r.period_kind,
                               'classification_namespace': r.classification_namespace}, sort_keys=True, separators=(',', ':'))
            obs = hashlib.sha256('|'.join([rid, str(r.territory_id), iid, period, dims]).encode()).hexdigest()
            amount = None if pd.isna(r.value_kopecks) else int(r.value_kopecks)
            value = float(r.reported_value) if amount is None else amount
            if amount is not None and abs(amount) > 2 ** 53:
                raise ValueError('Currency outside exact legacy REAL integer range')
            c.execute('INSERT INTO observation VALUES(?,?,?,?,?,?,?,?,?)',
                      (obs, rid, int(r.territory_id), iid, period, dims, value,
                       'source_estimate' if r.source_class == 'draft_citizen_presentation_rounded' else 'observed', None))
            c.execute('INSERT INTO budget_supplement_cell VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (obs, amount, r.reported_value, r.source_unit, r.source_resolution, r.source_locator,
                       r.source_formula, r.measure, r.period_kind, r.period_start, r.period_end,
                       r.classification_namespace, 0))
    queries = {
        'total_observations': 'SELECT COUNT(*) FROM observation',
        'supplement_observations': 'SELECT COUNT(*) FROM budget_supplement_cell',
        'currency_cells': 'SELECT COUNT(*) FROM budget_supplement_cell WHERE value_kopecks IS NOT NULL',
        'noncurrency_cells': 'SELECT COUNT(*) FROM budget_supplement_cell WHERE value_kopecks IS NULL',
        'measure_period_counts': 'SELECT measure,period_kind,COUNT(*) FROM budget_supplement_cell GROUP BY 1,2 ORDER BY 1,2',
        'new_releases': "SELECT COUNT(*) FROM dataset_release WHERE id LIKE 'budget-supplement-%'",
        'orphans': 'SELECT COUNT(*) FROM budget_supplement_cell f LEFT JOIN observation o ON o.id=f.observation_id LEFT JOIN municipality m ON m.tid=o.tid LEFT JOIN dataset_release s ON s.id=o.release_id WHERE o.id IS NULL OR m.tid IS NULL OR s.id IS NULL',
        'integer_currency_mismatch': "SELECT COUNT(*) FROM budget_supplement_cell f JOIN observation o ON o.id=f.observation_id WHERE f.value_kopecks IS NOT NULL AND (typeof(f.value_kopecks)<>'integer' OR f.value_kopecks<>o.value)",
        'duplicate_natural_keys': 'SELECT COUNT(*) FROM (SELECT release_id,tid,indicator_id,period,dimensions,COUNT(*) n FROM observation GROUP BY 1,2,3,4,5 HAVING n>1)',
        'supplement_asof_2024': 'SELECT COUNT(*) FROM budget_supplement_cell f JOIN asof_2024 o ON o.id=f.observation_id',
        'invented_availability_or_synthetic': "SELECT COUNT(*) FROM budget_supplement_cell f JOIN observation o ON o.id=f.observation_id WHERE o.available_at IS NOT NULL OR o.provenance_class NOT IN ('observed','source_estimate')",
        'primary_fiscal_cells': 'SELECT COUNT(*) FROM fiscal_cell',
        'primary_pilot_coverage': 'SELECT status,COUNT(*) FROM fiscal_pilot_coverage GROUP BY status ORDER BY status',
        'foreign_key_check': 'PRAGMA foreign_key_check',
    }
    results = {k: c.execute(sql).fetchall() for k, sql in queries.items()}
    assert results['total_observations'] == [(before + 77,)]
    assert results['currency_cells'] == [(71,)] and results['noncurrency_cells'] == [(6,)]
    assert results['primary_fiscal_cells'] == [(fiscal_before,)]
    assert results['primary_pilot_coverage'] == [('observed', 7), ('report_not_acquired', 5)]
    for k in ['orphans', 'integer_currency_mismatch', 'duplicate_natural_keys', 'supplement_asof_2024', 'invented_availability_or_synthetic']:
        assert results[k] == [(0,)], (k, results[k])
    assert not results['foreign_key_check']
    c.close()
    assert sha(base) == original_sha
    receipt = {'recorded_at': now, 'status': 'local_budget_context_increment', 'production_ingestion': False,
        'gm3_complete': False, 'gm4_complete': False, 'scientific_pass': False,
        'base_db_sha256': original_sha, 'new_db_sha256': sha(out / 'graph.sqlite'),
        'supplement_manifest_sha256': sha(supplement / 'manifest.json'), 'code_sha256': sha(__file__),
        'before_observations': before, 'added_observations': 77, 'unassigned_export_cells_excluded': 3,
        'base_unchanged': True, 'query_results': results}
    (out / 'coverage.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    (out / 'queries.sql').write_text('\n\n'.join('-- ' + k + '\n' + sql + ';' for k, sql in queries.items()) + '\n')
    print(json.dumps({'added': 77, 'total': before + 77, 'currency': 71, 'noncurrency': 6, 'checks': results}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for k in ['base', 'base-receipt', 'supplement', 'out']:
        p.add_argument('--' + k, type=Path, required=True)
    a = p.parse_args()
    build(a.base, a.base_receipt, a.supplement, a.out)
