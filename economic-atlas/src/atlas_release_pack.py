"""Seal and verify a local review archive. Does not publish or send anything."""
from pathlib import Path
from datetime import datetime,timezone
from html.parser import HTMLParser
import hashlib,json,re,zipfile

ATLAS=Path(__file__).resolve().parents[1];ROOT=ATLAS.parent;OUT=ATLAS/'runs/A14_release_20261005';SITE=ATLAS/'site/atlas-20261005'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
write=lambda p,v:Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
qa=json.loads((SITE/'browser_qa.json').read_text());assert qa['status']=='PASS' and not qa['errors'] and not qa['external_requests']
assert sha(SITE/'index.html')==qa['page_sha256'],'Browser receipt is for another page'
primary=json.loads((OUT/'primary_readonly_verification.json').read_text());assert primary['status']=='PASS'
assert all(sha(ATLAS/p)==digest for p,digest in primary['baseline_sha256'].items())
first=(OUT/'tests.log').read_text();html=(OUT/'html_check.log').read_text();assert '10 passed' in first and '1 passed' in html
class Links(HTMLParser):
 def __init__(self):super().__init__();self.values=[]
 def handle_starttag(self,tag,attrs):
  if tag=='a':self.values += [v for k,v in attrs if k=='href' and v and not re.match(r'https?://|#',v)]
parser=Links();parser.feed((SITE/'index.html').read_text())
for link in parser.values:assert (SITE/link).is_file(),f'Broken local link: {link}'
report={'status':'PASS','checked_at_utc':datetime.now(timezone.utc).isoformat(),
        'location':'isolated Mac checkout','data_tests_passed':10,'html_tests_passed':1,
        'test_execution_note':'First full run:10 data checks passed; HTML assertion expected a machine token instead of visible wording. Corrected assertion rerun:1 passed. Data checks unchanged.',
        'browser':qa,'primary':primary,'local_links_checked':len(parser.values),
        'scientific_status':'SUPPLEMENTARY_EXPLORATORY','a8':'effective input invariance audited; no full statistical rerun',
        'publication':'local review bundle only'}
write(ATLAS/'RELEASE_VERIFICATION.json',report)
prov=json.loads((OUT/'provenance.json').read_text())
prov['dependency_code_sha256']={p:sha(ATLAS/p) for p in ['src/atlas_common.py','src/atlas_a12.py','src/a6_temporal.py','runs/A7_stories_20261004/build_stories.py','runs/A8_wages2025_validation_20261005/run_a8.py']}
prov['dependency_artifact_sha256']={p:sha(ATLAS/p) for p in ['data/panel_v1.parquet','runs/A7_stories_20261004/story_inputs.json','runs/A8_wages2025_validation_20261005/results.json','runs/A12_stable_cores_20261005/cores_2023-12.parquet','runs/A12_stable_cores_20261005/cores_2024-12.parquet']}
prov['post_build_sealed_at_utc']=datetime.now(timezone.utc).isoformat()
prov['output_sha256']={str(p.relative_to(ATLAS)):sha(p) for directory in [OUT,SITE] for p in directory.rglob('*') if p.is_file() and p.name!='provenance.json' and p.suffix!='.log'}
write(OUT/'provenance.json',prov)
(ROOT/'PACKAGE_README.md').write_text('''# Атлас расходов — локальный пакет проверки, 05.10.2026

Откройте economic-atlas/site/atlas-20261005/index.html в браузере. Страница автономна. Основной отчёт — RELEASE_REPORT_2026-10-05.md в той же папке economic-atlas. Пять историй — MUNICIPAL_STORIES_RELEASE_2026-10-05.md; инструкция — RELEASE_README.md.

Исследовательские исходники и результаты входят в архив. Внешние сырые Parquet Data Sense находятся отдельно; для нового расчёта нужны их версии с SHA из provenance. Новые проверки дополнены к основным A9–A13, основные результаты не переписаны. MQ остаётся открытым вопросом.

Архив не является публикацией или подачей формы. Код не объявляется лицензированным заново; условия конкретных источников описаны в DATA_PASSPORT_RELEASE_2026-10-05.md. Включены агрегированные исследовательские данные, без IndustryMap и индивидуальных записей ФНС.
''')
files=sorted([p for p in ATLAS.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc' and p.name!='RELEASE_MANIFEST.json'])
files += sorted((ROOT/'tests').glob('test_atlas_*.py'))
files += [ROOT/'PACKAGE_README.md']
secret_re=re.compile(r'sk-[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|Bearer [A-Za-z0-9_-]{25,}')
for p in files:
 if p.suffix in {'.py','.md','.json','.html','.cjs','.sh','.txt'}:
  assert not secret_re.search(p.read_text()),f'Potential secret: {p.relative_to(ROOT)}'
manifest={'status':'SEALED_LOCAL_REVIEW_PACKAGE','checked_at_utc':datetime.now(timezone.utc).isoformat(),
          'base_commit':'d67f80960895d77515cdc3ea7f9f197be97c2cd2','n_files_without_manifest':len(files),
          'external_raw_inputs_included':False,'files':{str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files}}
write(ATLAS/'RELEASE_MANIFEST.json',manifest);files += [ATLAS/'RELEASE_MANIFEST.json']
archive=ROOT.parent/'ATLAS_RELEASE_2026-10-05.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in files:z.write(p,'atlas-release-20261005/'+str(p.relative_to(ROOT)))
with zipfile.ZipFile(archive) as z:
 assert z.testzip() is None
 for rel,rec in manifest['files'].items():assert hashlib.sha256(z.read('atlas-release-20261005/'+rel)).hexdigest()==rec['sha256']
receipt={'status':'VERIFIED','archive':str(archive),'bytes':archive.stat().st_size,'sha256':sha(archive),'n_files':len(files),
         'zip_crc_checked':True,'all_manifest_entries_verified':True,'external_raw_inputs_included':False}
write(ROOT.parent/'ATLAS_RELEASE_DELIVERY_RECEIPT.json',receipt);print(json.dumps(receipt,ensure_ascii=False))
