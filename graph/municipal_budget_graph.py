"""Add verified municipal fiscal observations to a NEW local GM3 snapshot.

Never changes the input database or claims a production graph deployment.
Integer kopecks and source cell lineage are retained beside the GM3 REAL value.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pandas as pd


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def oid(*parts):
    return hashlib.sha256('|'.join(str(p) for p in parts).encode()).hexdigest()


def build(base, base_receipt, pilot, out):
    if out.exists():
        raise FileExistsError('New graph run required')
    receipt=json.loads(base_receipt.read_text())
    if sha(base)!=receipt['db_sha256']:
        raise ValueError('Base graph checksum')
    manifest=json.loads((pilot/'manifest.json').read_text())
    for name in ['observations.parquet','sources.json','metrics.json','protocol.json']:
        if sha(pilot/name)!=manifest['files'][name]['sha256']:
            raise ValueError('Pilot checksum: '+name)
    d=pd.read_parquet(pilot/'observations.parquet')
    sources=json.loads((pilot/'sources.json').read_text())
    profiles=json.loads((pilot/'metrics.json').read_text())['profiles']
    if d.duplicated(['territory_id','year','metric']).any() or d.executed_kopecks.isna().any():
        raise ValueError('Conflicting/NULL fiscal observations')
    now=datetime.now(timezone.utc).isoformat()
    out.mkdir(parents=True)
    db=out/'graph.sqlite'
    src=sqlite3.connect('file:'+str(base)+'?mode=ro',uri=True)
    c=sqlite3.connect(db)
    src.backup(c);src.close()
    c.execute('PRAGMA foreign_keys=ON')
    before=c.execute('SELECT COUNT(*) FROM observation').fetchone()[0]
    try:
        with c:
            c.executescript('''
CREATE TABLE fiscal_cell(observation_id TEXT PRIMARY KEY REFERENCES observation(id),executed_kopecks INTEGER NOT NULL,source_unit TEXT NOT NULL,source_locator TEXT NOT NULL,source_literal TEXT,member_sha256 TEXT,decision_date TEXT,source_publication_date TEXT,historical_boundary_verified INTEGER NOT NULL CHECK(historical_boundary_verified=0),geography_match TEXT NOT NULL);
CREATE TABLE fiscal_pilot_coverage(tid INTEGER NOT NULL REFERENCES municipality(tid),year INTEGER NOT NULL,status TEXT NOT NULL,release_id TEXT REFERENCES dataset_release(id),PRIMARY KEY(tid,year));
''')
            releases={}
            for s in sources:
                rid='municipal-budget-'+s['sha256']
                releases[(s['territory_id'],s['year'])]=rid
                c.execute('INSERT INTO dataset_release VALUES(?,?,?,?,?,?,?,?,?)',
                    (rid,'Official municipal annual budget report',s['url'],s['sha256'],now,
                     s['retrieved_at'],s.get('publication_date'),None,'official_source_distribution_not_assessed'))
            for metric in sorted(d.metric.unique()):
                c.execute('INSERT INTO indicator VALUES(?,?,?,?)',
                    ('fiscal_executed_'+metric,'Executed annual fiscal amount: '+metric,'kopeck','source_unit_verified'))
            for r in d.itertuples(index=False):
                rid=releases[(int(r.territory_id),int(r.year))]
                value=int(r.executed_kopecks)
                if abs(value)>2**53:
                    raise ValueError('Amount not exactly representable in legacy GM3 REAL')
                iid='fiscal_executed_'+r.metric
                dims='{"budget_scope":"municipality","measure":"executed"}'
                obs=oid(rid,int(r.territory_id),iid,str(r.year),dims)
                c.execute('INSERT INTO observation VALUES(?,?,?,?,?,?,?,?,?)',
                    (obs,rid,int(r.territory_id),iid,str(r.year),dims,value,'observed',None))
                c.execute('INSERT INTO fiscal_cell VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (obs,value,r.source_unit,r.source_locator,r.source_literal,r.member_sha256,
                     r.decision_date,r.source_publication_date,0,r.geography_match))
            c.executemany('INSERT INTO fiscal_pilot_coverage VALUES(?,?,?,?)',
                [(p['territory_id'],p['year'],p['status'],releases.get((p['territory_id'],p['year']))) for p in profiles])
        queries={
            'total_observations':'SELECT COUNT(*) FROM observation',
            'fiscal_observations':'SELECT COUNT(*) FROM fiscal_cell',
            'fiscal_releases':'SELECT COUNT(DISTINCT release_id) FROM observation WHERE indicator_id LIKE \'fiscal_executed_%\'',
            'planned_observed_missing':"SELECT status,COUNT(*) FROM fiscal_pilot_coverage GROUP BY status ORDER BY status",
            'fiscal_orphans':"SELECT COUNT(*) FROM fiscal_cell f LEFT JOIN observation o ON f.observation_id=o.id LEFT JOIN dataset_release r ON o.release_id=r.id LEFT JOIN municipality m ON o.tid=m.tid WHERE o.id IS NULL OR r.id IS NULL OR m.tid IS NULL",
            'duplicate_natural_keys':'SELECT COUNT(*) FROM (SELECT release_id,tid,indicator_id,period,dimensions,COUNT(*) n FROM observation GROUP BY 1,2,3,4,5 HAVING n>1)',
            'integer_kopeck_mismatch':'SELECT COUNT(*) FROM fiscal_cell f JOIN observation o ON o.id=f.observation_id WHERE typeof(f.executed_kopecks)<>\'integer\' OR f.executed_kopecks<>o.value',
            'fiscal_unknown_availability':'SELECT COUNT(*) FROM fiscal_cell f JOIN observation o ON o.id=f.observation_id WHERE o.available_at IS NULL',
            'fiscal_synthetic':'SELECT COUNT(*) FROM fiscal_cell f JOIN observation o ON o.id=f.observation_id WHERE o.provenance_class<>\'observed\'',
            'fiscal_asof_2024':'SELECT COUNT(*) FROM fiscal_cell f JOIN asof_2024 o ON o.id=f.observation_id',
            'fiscal_spending_population_pairs':"SELECT COUNT(*) FROM fiscal_pilot_coverage f WHERE f.status='observed' AND EXISTS (SELECT 1 FROM observation o WHERE o.tid=f.tid AND o.indicator_id='spending' AND o.period LIKE CAST(f.year AS TEXT)||'-%') AND EXISTS (SELECT 1 FROM observation o WHERE o.tid=f.tid AND o.indicator_id='population_total_by_sex' AND o.period=CAST(f.year AS TEXT)||'-01-01')",
            'foreign_key_check':'PRAGMA foreign_key_check',
        }
        values={key:c.execute(sql).fetchall() for key,sql in queries.items()}
        assert values['total_observations']==[(before+len(d),)]
        assert values['fiscal_observations']==[(len(d),)]
        for key in ['fiscal_orphans','duplicate_natural_keys','integer_kopeck_mismatch','fiscal_synthetic','fiscal_asof_2024']:
            assert values[key]==[(0,)],(key,values[key])
        assert not values['foreign_key_check']
        assert sha(base)==receipt['db_sha256']
        c.close()
        report={'recorded_at':now,'status':'local_incremental_fiscal_observations',
            'production_ingestion':False,'gm3_complete':False,'gm4_complete':False,
            'scientific_pass':False,'base_db_sha256':receipt['db_sha256'],
            'new_db_sha256':sha(db),'pilot_manifest_sha256':sha(pilot/'manifest.json'),
            'code_sha256':sha(__file__),'before_observations':before,'added_observations':len(d),
            'query_results':values,
            'limits':['Local copy only; source graph retained unchanged',
                'Budget scope municipality and source years 2023/2024 explicit; not 2025 regional aggregates',
                'Legacy observation value is REAL; fiscal_cell stores exact integer kopecks and checks equality',
                'All available_at unknown; printed publication date and current retrieval never substituted',
                'Historical legal boundaries unverified; no succession edges',
                'No forecast input, synthetic node promotion or full graph gate acceptance']}
        (out/'coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        (out/'queries.sql').write_text('\n\n'.join('-- '+key+'\n'+sql+';' for key,sql in queries.items())+'\n')
        print(json.dumps({'added':len(d),'query_results':values},ensure_ascii=False))
    except Exception:
        c.close();raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['base','base-receipt','pilot','out']:
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();build(a.base,a.base_receipt,a.pilot,a.out)
