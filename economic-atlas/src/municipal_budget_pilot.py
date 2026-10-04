"""Bounded, retrospective municipal-budget intake; never a forecast or causal gate.

Raw files are acquired from source URLs in sources.json with verified HTTPS.
For legacy DOC, supply textutil-converted TXT alongside the original; the
original checksum and conversion method remain in lineage. Outputs are new runs.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pandas as pd

W = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
ADAPTERS = {
    'orsk': (1673, 'RUB'),
    'kurgan': (1333, 'RUB'),
    'ishim': (2192, 'thousand_RUB'),
    'tyumen_visual_transcription': (2190, 'thousand_RUB'),
}
TYUMEN_REVIEWED_SHA = 'eb0897a594e2d43b1ab5490107f00a31ea38eac2b86cba9544194f4611ee8ee9'


def validate_source(source):
    if ADAPTERS.get(source['adapter']) != (source['territory_id'], source['unit']):
        raise ValueError('Adapter municipality/unit mismatch')
    if not source.get('report_is_annual_execution'):
        raise ValueError('Annual execution report required')
    if source['adapter'] == 'tyumen_visual_transcription' and (
        source['year'] != 2023 or source['sha256'] != TYUMEN_REVIEWED_SHA
    ):
        raise ValueError('Manual transcription is pinned to one reviewed PDF/year')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def kopecks(value, unit='RUB'):
    if value is None or str(value).strip() in ['', '-', 'X', 'x']:
        return None
    if unit not in ['RUB', 'thousand_RUB']:
        raise ValueError('Unverified unit')
    text = re.sub(r'\s+', '', str(value)).replace(',', '.')
    try:
        amount = Decimal(text) * (100 if unit == 'RUB' else 100000)
    except InvalidOperation as exc:
        raise ValueError(value) from exc
    if not amount.is_finite() or amount != amount.to_integral_value():
        raise ValueError('Nonfinite or sub-kopeck source amount')
    return int(amount)


def ratio(numerator, denominator):
    return None if numerator is None or denominator is None or denominator <= 0 else numerator / denominator


def only(items):
    items = list(items)
    if len(items) != 1:
        raise ValueError(f'Expected one source cell, got {len(items)}')
    return items[0]


def docx(data):
    with zipfile.ZipFile(__import__('io').BytesIO(data)) as z:
        if z.testzip() is not None:
            raise ValueError('DOCX CRC')
        root = ET.fromstring(z.read('word/document.xml'))
    text = ' '.join(''.join(t.text or '' for t in para.findall('.//w:t', W))
                    for para in root.findall('.//w:p', W))
    text = re.sub(r'\s+', ' ', text)
    rows = [[ ''.join(t.text or '' for t in c.findall('.//w:t', W)).strip()
              for c in r.findall('w:tc', W)] for r in root.findall('.//w:tr', W)]
    return text, rows


def orsk(path, year, emit, checks):
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError('ZIP CRC')
        members = {}
        for item in z.infolist():
            name = item.filename
            if re.search('[ΓστÑ]', name):
                name = name.encode('cp437').decode('cp866')
            if '/' in name or '\\' in name or item.file_size > 20_000_000 or item.flag_bits & 1:
                raise ValueError('Unsafe ZIP member')
            members[name.lower()] = (name, z.read(item))
    name, data = members['текст.docx']
    text, rows = docx(data)
    if f'бюджета города Орска за {year} год' not in text or '(рублей)' not in text:
        raise ValueError('Municipality/year/unit header')
    header = only((i, r) for i,r in enumerate(rows) if r == ['№ п/п','Показатели','Утверждено','Исполнено'])
    amounts = {}
    for metric, title in [('revenue','Доходы'),('expense','Расходы'),('surplus','Профицит')]:
        i,r = only((i,r) for i,r in enumerate(rows) if len(r)==4 and r[1]==title)
        amounts[metric] = kopecks(r[3])
        emit(metric,amounts[metric],f'{name}:table-row-{i+1}:column-4',r[3],data)
    checks.append({'check':'executed_balance','year':year,'city':'Орск',
                   'difference_kopecks':amounts['revenue']-amounts['expense']-amounts['surplus'],'tolerance_kopecks':0})
    name,data = only(v for k,v in members.items() if k.startswith('доходы ') and k.endswith('.docx'))
    _,rows = docx(data)
    income = {}
    for metric,title in [('tax_nontax','НАЛОГОВЫЕ И НЕНАЛОГОВЫЕ ДОХОДЫ'),('grants','БЕЗВОЗМЕЗДНЫЕ ПОСТУПЛЕНИЯ')]:
        i,r = only((i,r) for i,r in enumerate(rows) if len(r)==5 and r[1].strip().upper()==title)
        income[metric] = kopecks(r[3]);emit(metric,income[metric],f'{name}:table-row-{i+1}:column-4',r[3],data)
    checks.append({'check':'revenue_partition','year':year,'city':'Орск',
                   'difference_kopecks':sum(income.values())-amounts['revenue'],'tolerance_kopecks':0})
    name,data = only(v for k,v in members.items() if k.startswith('расходы по разделам') and k.endswith('.docx'))
    _,rows = docx(data);functions=[]
    for i,r in enumerate(rows):
        if len(r)==6 and re.fullmatch(r'\d{2}',r[0]) and r[1] in ['', '00']:
            value=kopecks(r[4]);functions.append(value)
            emit('function_'+r[0],value,f'{name}:table-row-{i+1}:column-5',r[4],data)
    checks.append({'check':'functions_partition','year':year,'city':'Орск',
                   'difference_kopecks':sum(functions)-amounts['expense'],'tolerance_kopecks':0})


def kurgan(path,year,emit,checks):
    w=openpyxl.load_workbook(path,read_only=True,data_only=True)
    s=w['Доходы'];header=' '.join(str(v) for row in list(s.values)[:12] for v in row if v is not None)
    if 'г.Курган' not in header or '37701000' not in header or '383' not in header or '0503117' not in header or str(year+1) not in header:
        raise ValueError('Municipal 0503117 header')
    if str(s['E12'].value).strip()!='Исполнено':
        raise ValueError('Executed column')
    totals={}
    for metric,sheet,title in [('revenue','Доходы','Доходы бюджета - всего'),('expense','Расходы','Расходы бюджета - всего'),('financing','Источники','Источники финансирования дефицита бюджета - всего')]:
        i,row=only((i,row) for i,row in enumerate(w[sheet].values,1) if str(row[0]).strip()==title)
        value=kopecks(row[4]);totals[metric]=value
        emit(metric,value,f'{sheet}!E{i}',row[4],None)
    checks.append({'check':'executed_balance','year':year,'city':'Курган',
                   'difference_kopecks':totals['expense']-totals['revenue']-totals['financing'],'tolerance_kopecks':10})
    income=[]
    for i,row in enumerate(w['Доходы'].values,1):
        code=re.sub(r'\s','',str(row[2] or ''))
        if re.fullmatch(r'\d{20}',code):
            # 2023 is a leaf-only statement; 2024 includes parent groups.
            # Only per-administrator top group 1/2 is used in 2024.
            if year==2023 or code[3:] in ['10000000000000000','20000000000000000']:
                income.append((i,code,kopecks(row[4])))
    if len({c for _,c,_ in income})!=len(income) or any(c.startswith('000') or v is None for _,c,v in income):
        raise ValueError('Income hierarchy/duplicate/NULL')
    for metric,kind in [('tax_nontax','1'),('grants','2')]:
        part=[(i,c,v) for i,c,v in income if c[3]==kind]
        if not part:raise ValueError('Missing income group')
        value=sum(v for _,_,v in part)
        emit(metric,value,'Доходы!E['+','.join(str(i) for i,_,_ in part)+']',None,None)
    checks.append({'check':'revenue_partition','year':year,'city':'Курган',
                   'difference_kopecks':sum(v for _,_,v in income)-totals['revenue'],'tolerance_kopecks':10})
    # Expense statements mix program/KVR ancestors and descendants. No generic
    # leaf inference is made: functional metrics stay NULL for this adapter.


def ishim(path,year,emit,checks):
    txt=path.with_suffix('.txt');text=txt.read_text();unit='thousand_RUB'
    if f'Об исполнении бюджета города Ишима за {year} год' not in text or 'РЕШЕНИЕ' not in text[:300] or 'проект' in text[:500].lower():
        raise ValueError('Approved municipality/year header')
    totals=re.search(r'по доходам в сумме ([\d ]+) тыс\. руб\., по расходам в сумме ([\d ]+) тыс\. руб\..*?в сумме ([\d ]+) тыс\. руб\.',text)
    if totals is None:raise ValueError('Annual execution totals')
    values={}
    for metric,value in zip(['revenue','expense','surplus'],totals.groups()):
        values[metric]=kopecks(value,unit);emit(metric,values[metric],'decision:paragraph-1',value,None)
    checks.append({'check':'executed_balance','year':year,'city':'Ишим',
                   'difference_kopecks':values['revenue']-values['expense']-values['surplus'],'tolerance_kopecks':0})
    lines=[(i+1,s.strip()) for i,s in enumerate(text.splitlines()) if s.strip()]
    end=only(i for i,(_,s) in enumerate(lines) if s=='ВСЕГО ДОХОДОВ')
    income=[]
    for i,(line,s) in enumerate(lines[:end]):
        if re.fullmatch(r'[12] \d{2} \d{5} \d{2} \d{4} \d{3}',s):
            admin=lines[i-1][1]
            if not re.fullmatch(r'\d{3}',admin):raise ValueError('Missing revenue administrator')
            income.append((line,admin+re.sub(r'\s','',s),kopecks(lines[i+1][1],unit)))
    if len({c for _,c,_ in income})!=len(income):raise ValueError('Duplicate admin/code')
    for metric,kind in [('tax_nontax','1'),('grants','2')]:
        part=[(line,c,v) for line,c,v in income if c[3]==kind]
        emit(metric,sum(v for _,_,v in part),'converted-TXT:revenue-code-lines['+','.join(str(i) for i,_,_ in part)+']',None,None)
    checks.append({'check':'revenue_partition','year':year,'city':'Ишим',
                   'difference_kopecks':sum(v for _,_,v in income)-values['revenue'],
                   'tolerance_kopecks':(len(income)+1)*50000,'tolerance_reason':'Worst-case independent rounding of printed thousand-RUB cells'})
    after=text.split('Приложение 3\n',1)[1].split('ВСЕГО РАСХОДОВ',1)[0]
    lines=[(i+1,s.strip()) for i,s in enumerate(after.splitlines()) if s.strip()];functions=[]
    for i,(line,s) in enumerate(lines):
        if re.fullmatch(r'\d{2}',s) and lines[i+1][1]=='00' and re.fullmatch(r'[\d ]+',lines[i+2][1]):
            value=kopecks(lines[i+2][1],unit);functions.append(value)
            emit('function_'+s,value,f'converted-TXT:appendix-3:relative-line-{lines[i+2][0]}',lines[i+2][1],None)
    if len(functions)<7:raise ValueError('Incomplete functional table')
    checks.append({'check':'functions_partition','year':year,'city':'Ишим',
                   'difference_kopecks':sum(functions)-values['expense'],
                   'tolerance_kopecks':(len(functions)+1)*50000,'tolerance_reason':'Printed thousand-RUB precision'})


def self_check():
    assert kopecks('1\u00a0234,56')==123456
    assert kopecks('-1 234', 'thousand_RUB')==-123400000
    assert kopecks('-') is None and kopecks('0')==0
    for value,unit in [('NaN','RUB'),('0.001','RUB'),('1','million_RUB')]:
        try:kopecks(value,unit)
        except ValueError:pass
        else:raise AssertionError('Invalid value/unit accepted')
    assert ratio(1,0) is None and ratio(None,3) is None and ratio(-3,6)==-.5
    try:only([1,2])
    except ValueError:pass
    else:raise AssertionError('Duplicate source cell')
    reviewed = {'adapter':'tyumen_visual_transcription','territory_id':2190,
                'unit':'thousand_RUB','year':2023,'sha256':TYUMEN_REVIEWED_SHA,
                'report_is_annual_execution':True}
    validate_source(reviewed)
    for key,value in [('unit','RUB'),('territory_id',1673),('year',2024),
                      ('sha256','0'*64),('report_is_annual_execution',False)]:
        try:validate_source({**reviewed,key:value})
        except ValueError:pass
        else:raise AssertionError('Unreviewed source accepted')
    print('PASS: units, signed amounts, missing-vs-zero, invalid values, denominator, duplicates, manual source/year pin')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--self-check',action='store_true')
    for arg in ['raw','protocol','sources','population','out']:p.add_argument('--'+arg,type=Path)
    args=p.parse_args()
    if args.self_check:self_check();return
    if not all([args.raw,args.protocol,args.sources,args.population,args.out]):p.error('All paths required')
    if args.out.exists():raise FileExistsError('New run only')
    protocol=json.loads(args.protocol.read_text());sources=json.loads(args.sources.read_text())
    if sha(args.protocol)!='670251e6bac301e9354ce45524b9fef0aef6cd22aedea54e239813c6e1a5b9e6' or sha(args.population)!=protocol['source_sha256']['population']:
        raise ValueError('Frozen protocol/population checksum mismatch')
    cells=[];checks=[];source_audit=[]
    for source in sources:
        validate_source(source)
        path=args.raw/source['file']
        if sha(path)!=source['sha256']:raise ValueError('Source checksum')
        tid=source['territory_id'];year=source['year']
        if tid not in [r['territory_id'] for r in protocol['cohort']] or year not in protocol['years']:raise ValueError('Unfrozen municipality/year')
        def emit(metric,value,locator,literal,data):
            cells.append({'territory_id':tid,'year':year,'metric':metric,'executed_kopecks':value,
                'source_file':source['file'],'source_sha256':source['sha256'],'source_url':source['url'],
                'source_unit':source['unit'],'source_locator':locator,'source_literal':None if literal is None else str(literal),
                'member_sha256':None if data is None else hashlib.sha256(data).hexdigest(),
                'decision_date':source.get('decision_date'),'source_publication_date':source.get('publication_date'),
                'retrieved_at':source['retrieved_at'],'available_at':None,'vintage':None,'historical_boundary_verified':False,
                'geography_match':source['geography_match']})
        if source['adapter']=='orsk':orsk(path,year,emit,checks)
        elif source['adapter']=='kurgan':kurgan(path,year,emit,checks)
        elif source['adapter']=='ishim':
            converted=path.with_suffix('.txt');source_audit.append({'original':source['file'],'converted_txt_sha256':sha(converted),'conversion':'macOS textutil -convert txt; original preserved'})
            ishim(path,year,emit,checks)
        elif source['adapter']=='tyumen_visual_transcription':
            # Printed decision, page 3, visually verified at acquisition. The
            # fixed original hash prevents trusting these amounts for a new PDF.
            for metric,value in [('revenue','44793681'),('expense','44883751'),('deficit','90070')]:
                emit(metric,kopecks(value,'thousand_RUB'),'PDF:page-3:decision-89:paragraph-1:manual-visual-review',value,None)
            checks.append({'check':'executed_balance','year':year,'city':'Тюмень',
                           'difference_kopecks':kopecks('44883751','thousand_RUB')-kopecks('44793681','thousand_RUB')-kopecks('90070','thousand_RUB'),'tolerance_kopecks':0})
        else:raise ValueError('Unknown adapter')
    if any(abs(c['difference_kopecks'])>c['tolerance_kopecks'] for c in checks):raise ValueError(checks)
    d=pd.DataFrame(cells);d['executed_kopecks']=d.executed_kopecks.astype('Int64')
    if d.duplicated(['territory_id','year','metric']).any():raise ValueError('Duplicate observation')
    population=pd.read_parquet(args.population)
    population=population[(population.period=='год')&(population.age=='Всего')&population.gender.isin(['Мужчины','Женщины'])&population.year.isin(protocol['years'])]
    keys=['territory_id','year','gender']
    if (population.groupby(keys).value.nunique()>1).any():raise ValueError('Conflicting population')
    population=population.drop_duplicates(keys+['value']);pop={}
    for k,g in population.groupby(['territory_id','year']):
        if len(g)==2 and g.value.notna().all():pop[k]=int(g.value.sum())
    profiles=[]
    for cohort in protocol['cohort']:
        for year in protocol['years']:
            part=d[(d.territory_id==cohort['territory_id'])&(d.year==year)]
            v={r.metric:int(r.executed_kopecks) for r in part.itertuples() if pd.notna(r.executed_kopecks)}
            total=v.get('revenue');expense=v.get('expense');n=pop.get((cohort['territory_id'],year))
            record={**cohort,'year':year,'population_start':n,'status':'observed' if total is not None and expense is not None else 'report_not_acquired',
                'revenue_kopecks':total,'expense_kopecks':expense,'tax_nontax_kopecks':v.get('tax_nontax'),
                'expense_per_person_rub':ratio(None if expense is None else expense/100,n),
                'tax_nontax_share':ratio(v.get('tax_nontax'),total),
                'deficit_to_revenue':ratio(None if total is None or expense is None else expense-total,total),
                'functional_shares':{k[9:]:ratio(value,expense) for k,value in v.items() if k.startswith('function_')}}
            profiles.append(record)
    results={'checked_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':sha(args.protocol),'code_sha256':sha(__file__),
        'planned_municipality_years':len(profiles),'observed_municipality_years':sum(r['status']=='observed' for r in profiles),
        'source_count':len(sources),'cell_count':len(d),'checks':checks,'conversion_audit':source_audit,
        'status':'partial_retrospective_descriptive_pilot','scientific_pass':False,'forecast_input':False,
        'limitations':['Incomplete frozen cohort; no substitutions','Only December-2023 partition labels; identity status ambiguous for label 1',
          'Very imbalanced populations; ratios are not size/region adjustment','No causal flood or cluster validation inference',
          'Reported source precision varies (RUB and thousand RUB)','Historical online availability and boundaries unverified',
          'Kurgan functions and Tyumen tax/functional mix unparsed, remain missing'],
        'profiles':profiles}
    args.out.mkdir(parents=True)
    d.to_parquet(args.out/'observations.parquet',index=False)
    (args.out/'metrics.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:results[k] for k in ['observed_municipality_years','planned_municipality_years','source_count','cell_count','scientific_pass']},ensure_ascii=False))


if __name__=='__main__':main()
