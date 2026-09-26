"""Read-only evidence for the municipal model proposal; no imputation or joins by name."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import pandas as pd

ROOT = Path(__file__).resolve().parents[1] / 'data'
OUT = Path(__file__).resolve().parent
PACK = ROOT / 'raw/sberindex-data-sense-2025'
FILES = {
    'spending': '8_consumption.parquet',
    'population': '2_bdmo_population.parquet',
    'migration': '3_bdmo_migration.parquet',
    'salary': '4_bdmo_salary.parquet',
    'market_access': '1_market_access.parquet',
    'distance': '5_connection.parquet',
}
frames = {k: pd.read_parquet(PACK / v) for k, v in FILES.items()}
report = {'checked_at': datetime.now(timezone.utc).isoformat(),
          'method': 'Direct local Parquet inspection; historical pack territory_id namespace only',
          'datasets': {}}
for name, df in frames.items():
    item = {'rows': len(df), 'columns': list(df.columns),
            'sha256': hashlib.sha256((PACK / FILES[name]).read_bytes()).hexdigest(),
            'nulls': {k: int(v) for k, v in df.isna().sum().items() if v}}
    for col in ('year', 'period', 'date', 'category', 'gender', 'okved_letter', 'age'):
        if col in df:
            values = sorted(str(v) for v in df[col].dropna().unique())
            item[col] = values
    report['datasets'][name] = item
sets = {name: set(df.territory_id.tolist()) for name, df in frames.items() if 'territory_id' in df}
dist = frames['distance']
sets['distance'] = set(dist.territory_id_x) | set(dist.territory_id_y)
report['territory_counts'] = {k: len(v) for k, v in sets.items()}
report['intersection_with_spending'] = {k: len(sets['spending'] & v) for k, v in sets.items()}
report['all_six_tables_intersection'] = len(set.intersection(*sets.values()))
report['identity_caveat'] = 'ID intersection is not complete observations, verified current boundaries, or an OKTMO crosswalk.'
s = frames['spending']
counts = s.groupby('territory_id').size()
report['spending_panel'] = {
    'duplicate_territory_date_category': int(s.duplicated(['territory_id', 'date', 'category']).sum()),
    'expected_dense_rows': len(sets['spending']) * s.date.nunique() * s.category.nunique(),
    'observed_rows': len(s),
    'rows_per_territory_min': int(counts.min()),
    'rows_per_territory_max': int(counts.max()),
    'territories_with_144_rows': int((counts == 144).sum()),
    'value_min': int(s.value.min()), 'value_max': int(s.value.max()),
}
report['complete_spending_in_all_six_tables'] = len(
    set(counts[counts == 144].index) & set.intersection(*sets.values()))
report['distances'] = {
    'duplicate_ordered_pairs': int(dist.duplicated(['territory_id_x', 'territory_id_y']).sum()),
    'self_pairs': int((dist.territory_id_x == dist.territory_id_y).sum()),
    'nonpositive_rows': int((dist.distance <= 0).sum()),
    'min': float(dist.distance.min()), 'max': float(dist.distance.max()),
    'sample': dist.head(3).to_dict(orient='records'),
}
cur = pd.read_parquet(ROOT / 'raw/sberindex-dashboard-current/municipal-consumer-spending.parquet')
mob = pd.read_parquet(ROOT / 'raw/sberindex-dashboard-current/mobility-index.parquet')
report['dashboard_spending'] = {'rows': len(cur), 'units': cur[['unit_measure','unit_mult']].drop_duplicates().to_dict(orient='records'),
    'categories': sorted(cur.category_15.unique().tolist()), 'periods': sorted(cur.period.unique().tolist()),
    'obs_status': cur.obs_status.value_counts().to_dict()}
report['mobility'] = {'rows':len(mob),'series':int(mob.indicator_id.nunique()),
    'periods':sorted(mob.period.unique().tolist()),
    'units': mob[['unit_measure','unit_mult']].drop_duplicates().to_dict(orient='records')}
report['interpretation_source'] = 'Описание_данных_для_Хакатона_2025_6_6.docx, read 2026-09-20 via OOXML text extraction'
OUT.mkdir(parents=True, exist_ok=True)
(OUT / 'loaded-data-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('datasets','dashboard_spending')},ensure_ascii=False,indent=2))
