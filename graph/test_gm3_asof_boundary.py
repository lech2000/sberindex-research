"""Adversarial instant boundaries for GM3's actual SQLite view."""
import sqlite3
from graph.gm3_snapshot import SCHEMA


def test_asof_respects_timezone_and_rejects_unknown_and_synthetic():
    c = sqlite3.connect(':memory:')
    c.executescript(SCHEMA)
    c.execute("INSERT INTO dataset_release VALUES('fixture','TEST','urn:test',?,'2026-10-07',NULL,NULL,NULL,'fixture')", ('0' * 64,))
    c.execute("INSERT INTO municipality VALUES(-1,'TEST fixture',1)")
    c.execute("INSERT INTO indicator VALUES('fixture','TEST control','unit','fixture')")
    cases = [
        ('utc_boundary', 'observed', '2024-12-31T23:59:59+00:00'),
        ('offset_equivalent_boundary', 'observed', '2025-01-01T02:59:59+03:00'),
        ('offset_future', 'observed', '2024-12-31T23:30:00-03:00'),
        ('utc_future', 'observed', '2025-01-01T00:00:00+00:00'),
        ('unknown', 'observed', None),
        ('invalid', 'observed', 'not-a-date'),
        ('synthetic_past', 'synthetic_assumption', '2024-01-01T00:00:00+00:00'),
        ('model_past', 'model_estimate', '2024-01-01T00:00:00+00:00'),
        ('source_estimate_past', 'source_estimate', '2024-01-01T00:00:00+00:00'),
    ]
    c.executemany('INSERT INTO observation VALUES(?,?,?,?,?,?,?,?,?)',
                  [(key, 'fixture', -1, 'fixture', '2024', key, 0, provenance, timestamp)
                   for key, provenance, timestamp in cases])
    actual = {r[0] for r in c.execute('SELECT id FROM asof_2024')}
    assert actual == {'utc_boundary', 'offset_equivalent_boundary', 'source_estimate_past'}
    c.close()
