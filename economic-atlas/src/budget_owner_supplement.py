"""Read three SHA-pinned owner files into a separate, retrospective context run.

Never edits source workbooks, fills annual pilot gaps, or supplies as-of features.
The PDF transcription is specific to the reviewed 38-page Tyumen presentation.
"""
import argparse
import ast
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import pandas as pd
from pypdf import PdfReader
from openpyxl.formula.translate import Translator

NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
SOURCES = [
    {'file': 'buzuluk-h1-2023-2024.xlsx', 'sha256': '14a2d537b2b57cd0048b771d4cad2526a4fa783da16c9fe3a6f9fbe2ec2392e3',
     'city': 'Бузулук', 'territory_id': 1668, 'status': 'identified_supplement', 'scope': 'H1 executed spending and July 1 budget plan snapshots', 'unit': 'thousand_RUB'},
    {'file': 'incoming-report.pdf', 'sha256': '8c8aa1b147858f02657537bf1ba82d7415fbf02a0e7c3c7a8428989a5c242ef9',
     'city': 'Тюмень', 'territory_id': 2190, 'status': 'identified_supplement', 'scope': '2025 citizen presentation based on draft decision, with rounded 2023/2024 history', 'unit': 'mixed_explicit'},
    {'file': 'budget-export-20261004.xlsx', 'sha256': '66385eb19741a61d36804da60f1bba3405f6ea5ec01752f2eebba9f0e657bd66',
     'city': None, 'territory_id': None, 'status': 'unassigned_geography_and_period_start', 'scope': 'EPBS_180_002_report, as of 2026-09-28', 'unit': 'thousand_RUB'},
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def xlsx_cells(path):
    """Read raw cells without trusting workbook styles or declared dimensions."""
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError('Source ZIP CRC failure')
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            root = ET.fromstring(z.read('xl/sharedStrings.xml'))
            strings = [''.join(t.text or '' for t in s.findall('.//x:t', NS)) for s in root]
        root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        cells = {}
        shared = {}
        for c in root.findall('.//x:sheetData/x:row/x:c', NS):
            f = c.find('x:f', NS)
            if f is not None and f.get('t') == 'shared' and f.text:
                shared[f.get('si')] = (c.attrib['r'], f.text)
        for c in root.findall('.//x:sheetData/x:row/x:c', NS):
            v = c.find('x:v', NS)
            f = c.find('x:f', NS)
            typ = c.get('t', 'n')
            raw = None if v is None else v.text
            if typ == 's':
                value = strings[int(raw)]
            elif typ == 'inlineStr':
                value = ''.join(t.text or '' for t in c.findall('.//x:t', NS))
            elif raw is None:
                value = None
            elif typ == 'n':
                value = Decimal(raw)
            else:
                value = raw
            formula = None if f is None else f.text
            if f is not None and f.get('t') == 'shared' and not f.text:
                origin, original = shared[f.get('si')]
                formula = Translator('=' + original, origin=origin).translate_formula(c.attrib['r']).lstrip('=')
            cells[c.attrib['r']] = {'value': value, 'literal': raw, 'formula': formula}
        return cells, root.find('x:dimension', NS).get('ref')


def evaluate_formula(formula, cells):
    """Restricted arithmetic AST, never eval or executable spreadsheet code."""
    def visit(n):
        if isinstance(n, ast.Expression):
            return visit(n.body)
        if isinstance(n, ast.Name) and re.fullmatch(r'[A-Z]+[0-9]+', n.id):
            return cells[n.id]['value']
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return Decimal(str(n.value))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
            return -visit(n.operand) if isinstance(n.op, ast.USub) else visit(n.operand)
        if isinstance(n, ast.BinOp):
            a, b = visit(n.left), visit(n.right)
            if isinstance(n.op, ast.Add): return a + b
            if isinstance(n.op, ast.Sub): return a - b
            if isinstance(n.op, ast.Mult): return a * b
            if isinstance(n.op, ast.Div): return a / b
        raise ValueError('Unsupported formula syntax')
    return visit(ast.parse(formula.lstrip('='), mode='eval'))


def money(value, unit):
    factor = {'thousand_RUB': 100000, 'million_RUB': 100000000}[unit]
    result = value * factor
    if result != result.to_integral_value():
        raise ValueError('Sub-kopeck amount')
    return int(result)


def build(raw, out, primary):
    if out.exists():
        raise FileExistsError('New run required')
    for s in SOURCES:
        if sha(raw / s['file']) != s['sha256']:
            raise ValueError('Source checksum: ' + s['file'])
    out.mkdir(parents=True)
    records, checks, issues = [], [], []

    def emit(s, metric, year, value, unit, resolution, locator, scope, measure, namespace, start, end, formula=None):
        records.append({'territory_id': s['territory_id'], 'city': s['city'], 'year': year,
            'metric': metric, 'measure': measure, 'classification_namespace': namespace,
            'period_kind': scope, 'period_start': start, 'period_end': end,
            'reported_value': str(value), 'source_unit': unit, 'source_resolution': str(resolution),
            'value_kopecks': money(value, unit) if unit in ['thousand_RUB', 'million_RUB'] else None,
            'source_locator': locator, 'source_formula': formula, 'source_sha256': s['sha256'],
            'source_file': s['file'], 'source_url': None, 'source_channel': 'owner_supplied_file',
            'available_at': None, 'vintage': None, 'historical_boundary_verified': False,
            'source_class': 'draft_citizen_presentation_rounded' if s['file'].endswith('.pdf') else 'municipal_H1_spreadsheet'})

    s = SOURCES[0]
    cells, dimension = xlsx_cells(raw / s['file'])
    if not ('Бузулук' in str(cells['A2']['value']) and '2024' in str(cells['A2']['value']) and '2023' in str(cells['A2']['value'])):
        raise ValueError('Buzuluk city/year header')
    if 'тыс.' not in str(cells['J3']['value']) or '01.07.2023' not in str(cells['E4']['value']) or '01.07.2024' not in str(cells['G4']['value']):
        raise ValueError('Buzuluk unit/as-of header')
    for address, c in cells.items():
        if c['formula']:
            result = evaluate_formula(c['formula'], cells)
            tol = Decimal('1e-10') if address.startswith('J') else Decimal('0.00001')
            diff = abs(result - c['value'])
            checks.append({'check': 'formula_cache', 'locator': 'Расходы !' + address,
                'difference_native': str(diff), 'tolerance_native': str(tol), 'passed': diff <= tol})
    if sum(c['check'] == 'formula_cache' for c in checks) != 179:
        raise ValueError('Expected all 179 formula caches, including shared formula instances')

    parents = [r for r in range(6, 50) if cells.get('C' + str(r), {}).get('value') == '00']
    if len(parents) != 10:
        raise ValueError('Ten functional parents required')
    def amount(address):
        return cells[address]['value'].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    for r in parents + [51]:
        metric = 'expense' if r == 51 else 'function_' + cells['B' + str(r)]['value']
        for col, year, measure in [('D', 2023, 'budget_plan_snapshot'), ('E', 2023, 'executed'), ('F', 2024, 'budget_plan_snapshot'), ('G', 2024, 'executed')]:
            address = col + str(r)
            executed = measure == 'executed'
            emit(s, metric, year, amount(address), 'thousand_RUB', Decimal('0.01'), 'Расходы !' + address,
                 'H1' if executed else 'plan_as_of_July_1', measure, 'functional_budget_RZ',
                 f'{year}-01-01' if executed else None, f'{year}-06-30' if executed else f'{year}-07-01', cells[address]['formula'])
        if r != 51:
            code = cells['B' + str(r)]['value']
            children = [q for q in range(6, 51) if cells.get('B' + str(q), {}).get('value') == code and cells.get('C' + str(q), {}).get('value') != '00']
            for col in ['D', 'E', 'F', 'G']:
                diff = sum(amount(col + str(q)) for q in children) - amount(col + str(r))
                checks.append({'check': 'function_partition', 'locator': col + str(r), 'difference_thousand_RUB': str(diff), 'passed': diff == 0})
    for col in ['D', 'E', 'F', 'G']:
        diff = sum(amount(col + str(r)) for r in parents) - amount(col + '51')
        checks.append({'check': 'total_function_partition', 'locator': col + '51', 'difference_thousand_RUB': str(diff), 'passed': diff == 0})

    # Verify column J means ratio, not percent-point growth; preserve the bad J18.
    for r in range(6, 52):
        if 'E' + str(r) not in cells or 'G' + str(r) not in cells:
            continue
        a, b, c = cells['E' + str(r)]['value'], cells['G' + str(r)]['value'], cells.get('J' + str(r), {})
        if not isinstance(a, Decimal) or not isinstance(b, Decimal):
            continue
        expected = None if a == 0 else b / a
        if isinstance(c.get('value'), Decimal) and (expected is None or abs(c['value'] - expected) > Decimal('1e-10')):
            issues.append({'source': s['file'], 'locator': 'Расходы !J' + str(r), 'formula': c.get('formula'),
                'cached_value': str(c['value']), 'correct_ratio': None if expected is None else str(expected),
                'severity': 'source_ratio_not_used', 'reason': 'J must be G/E; zero denominator remains NULL'})

    s = SOURCES[1]
    pdf = PdfReader(raw / s['file'])
    pages = [p.extract_text() or '' for p in pdf.pages]
    if len(pages) != 38 or 'Тюмени' not in pages[0] or 'проекта решения' not in pages[0] or '2025' not in pages[0]:
        raise ValueError('Pinned presentation scope')
    reviewed = [
        ('revenue', 5, [44794, 49079, 49351], 'million_RUB', '1', 'fiscal_total'),
        ('expense', 5, [44884, 48696, 51713], 'million_RUB', '1', 'fiscal_total'),
        ('tax_revenue', 7, [18420, 22937, 24611], 'million_RUB', '1', 'fiscal_revenue_group'),
        ('nontax_revenue', 8, [2618, 1761, 1693], 'million_RUB', '1', 'fiscal_revenue_group'),
        ('grants', 9, [23756, 24381, 23047], 'million_RUB', '1', 'fiscal_revenue_group'),
        ('program_go_chs_spending', 28, [225, 104, 155], 'million_RUB', '1', 'municipal_program'),
        ('program_jkh_spending', 31, [944, 1346, 1129], 'million_RUB', '1', 'municipal_program'),
        ('shipped_goods', 4, ['451863.8', '495163.2', '502987.6'], 'million_RUB', '0.1', 'socioeconomic_context'),
        ('fixed_capital_investment', 4, ['139486.8', '164235.1', '160720.4'], 'million_RUB', '0.1', 'socioeconomic_context'),
        ('unemployment', 4, ['0.25', '0.18', '0.23'], 'percent', '0.01', 'socioeconomic_context'),
        ('housing_commissioned', 4, ['1377.5', '1456.0', '1721.0'], 'thousand_m2', '0.1', 'socioeconomic_context'),
    ]
    for metric, page, values, unit, resolution, namespace in reviewed:
        for year, literal in zip([2023, 2024, 2025], values):
            emit(s, metric, year, Decimal(str(literal)), unit, Decimal(resolution),
                f'PDF page {page}, {metric}, year {year}; visual review 2026-10-04',
                'annual_presentation', 'executed' if namespace != 'socioeconomic_context' else 'reported_context',
                namespace, f'{year}-01-01', f'{year}-12-31')
    for year in [2023, 2024, 2025]:
        d = {r['metric']: r['value_kopecks'] for r in records if r['source_sha256'] == s['sha256'] and r['year'] == year}
        diff = d['tax_revenue'] + d['nontax_revenue'] + d['grants'] - d['revenue']
        checks.append({'check': 'rounded_revenue_partition', 'year': year, 'difference_kopecks': diff, 'passed': diff == 0})
    baseline = pd.read_parquet(primary)
    for metric in ['revenue', 'expense']:
        b = baseline[(baseline.territory_id == 2190) & (baseline.year == 2023) & (baseline.metric == metric)]
        if len(b) != 1:
            raise ValueError('Primary Tyumen 2023 comparison')
        r = next(r for r in records if r['territory_id'] == 2190 and r['year'] == 2023 and r['metric'] == metric)
        diff = r['value_kopecks'] - int(b.iloc[0].executed_kopecks)
        checks.append({'check': 'rounded_vs_primary_2023', 'metric': metric, 'difference_kopecks': diff,
                       'tolerance_kopecks': 50000000, 'passed': abs(diff) <= 50000000})

    s = SOURCES[2]
    cells, dimension = xlsx_cells(raw / s['file'])
    if cells['A2']['value'] != 'EPBS_180_002_report' or cells['A3']['value'] != 'на 28.09.2026, тыс руб':
        raise ValueError('Electronic Budget code/cutoff/unit')
    if cells['B6']['value'] != 'Бюджет муниципального образования':
        raise ValueError('Export geography header changed; review required')
    unassigned = [{'metric': m, 'value_kopecks': money(cells[a]['value'], 'thousand_RUB'), 'source_literal': cells[a]['literal'],
                   'source_locator': 'data!' + a, 'as_of_date': '2026-09-28', 'period_start': None,
                   'territory_id': None, 'city': None, 'source_sha256': s['sha256'],
                   'source_unit': 'thousand_RUB', 'source_resolution_RUB': '0.01', 'available_at': None,
                   'status': 'unassigned_geography_and_period_start'}
                  for m, a in [('expense', 'B8'), ('revenue', 'B10'), ('signed_balance_revenue_minus_expense', 'B12')]]
    u = {r['metric']: r['value_kopecks'] for r in unassigned}
    diff = u['revenue'] - u['expense'] - u['signed_balance_revenue_minus_expense']
    checks.append({'check': 'unassigned_export_balance', 'difference_kopecks': diff, 'passed': diff == 0})
    issues.append({'source': s['file'], 'severity': 'read_only_raw_XML_fallback',
        'reason': 'Invalid color rgb=black; declared dimension A1 while cells reach B12. Source unchanged.', 'declared_dimension': dimension})

    frame = pd.DataFrame(records)
    frame['value_kopecks'] = pd.array([r['value_kopecks'] for r in records], dtype='Int64')
    if len(frame) != 77 or frame.duplicated(['territory_id', 'year', 'metric', 'measure']).any():
        raise ValueError('Unexpected supplement count or duplicate natural key')
    if not all(c['passed'] for c in checks):
        raise ValueError('Numerical check failed: ' + json.dumps([c for c in checks if not c['passed']]))
    semantic = [i for i in issues if i['severity'] == 'source_ratio_not_used']
    if len(semantic) != 1 or semantic[0]['locator'] != 'Расходы !J18':
        raise ValueError('Source semantic defects changed; review required')
    frame.to_parquet(out / 'observations.parquet', index=False)
    write_json(out / 'unassigned.json', unassigned)
    write_json(out / 'checks.json', checks)
    write_json(out / 'source_issues.json', issues)
    sources = [dict(s, source_channel='owner_supplied_file', source_url=None, available_at=None, vintage=None,
                    historical_boundary_verified=False, official_online_identity_verified=False) for s in SOURCES]
    write_json(out / 'sources.json', sources)
    profiles = []
    for metric in sorted(frame[frame.territory_id == 1668].metric.unique()):
        d = frame[(frame.territory_id == 1668) & (frame.metric == metric) & (frame.measure == 'executed')]
        a = int(d[d.year == 2023].iloc[0].value_kopecks)
        b = int(d[d.year == 2024].iloc[0].value_kopecks)
        profiles.append({'metric': metric, 'actual_H1_2023_RUB': a / 100, 'actual_H1_2024_RUB': b / 100,
                         'growth_percent': None if a == 0 else (b / a - 1) * 100})
    metrics = {'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'retrospective_context_only',
        'identified_observations': 77, 'buzuluk_executed_H1': 22, 'buzuluk_plan_snapshots': 22,
        'tyumen_rounded_annual_context': 33, 'unassigned_export_cells': 3,
        'numerical_checks': len(checks), 'failed_numerical_checks': 0, 'source_ratio_defects': len(semantic),
        'buzuluk_profiles': profiles, 'annual_primary_pilot_observed': 7, 'annual_primary_pilot_planned': 12,
        'scientific_gate_pass': False, 'asof_feature_eligible': 0,
        'primary_observations_sha256': sha(primary), 'originals_unchanged': all(sha(raw / s['file']) == s['sha256'] for s in SOURCES)}
    write_json(out / 'metrics.json', metrics)
    files = {p.name: {'sha256': sha(p), 'bytes': p.stat().st_size} for p in sorted(out.iterdir())}
    write_json(out / 'manifest.json', {'code_sha256': sha(__file__), 'files': files,
        'source_sha256': {s['file']: s['sha256'] for s in SOURCES}, 'primary_observations_sha256': sha(primary)})
    print(json.dumps({'observations': 77, 'checks': len(checks), 'failures': 0, 'issues': issues}, ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for key in ['raw', 'out', 'primary']:
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args()
    build(a.raw, a.out, a.primary)
