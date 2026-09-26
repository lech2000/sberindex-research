"""Integrate architecture as a proposal, data audit as evidence, without corpus rechunking.

Run in an environment with KB access and this directory plus ../data available.
Safe to retry: document integration deduplicates by text SHA-256.
"""
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
KB = 'http://10.189.141.165:8300'
OWNER = 'prn_fbab9aa00cd46169'
EXPECTED = {
    74: f'research:sberindex-2026:shared:{OWNER}',
    75: f'research:sberindex-2026:economic-atlas:{OWNER}',
    76: f'research:sberindex-2026:shock-radar:{OWNER}',
}

def request(method, path, body=None):
    raw = json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    req = Request(KB + path, data=raw, method=method, headers={'Content-Type':'application/json'})
    with urlopen(req, timeout=240) as res:
        return json.load(res)

def main():
    live = {int(c['id']): c for c in request('GET','/api/corpora')}
    for cid, name in EXPECTED.items():
        if live.get(cid,{}).get('name') != name:
            raise RuntimeError(f'Corpus identity mismatch: {cid}')
    if 62 not in live:
        raise RuntimeError('Documentation corpus missing')
    jobs = []
    for cid in (75,76):
        jobs.extend([
            (cid,ROOT/'ARCHITECTURE.md','Муниципальная модель FixAR — архитектура и лестница, предложение 20.09.2026','design_proposal'),
            (cid,ROOT/'loaded-data-audit.json','Муниципальная модель — прямой аудит загруженных файлов 20.09.2026','data_audit'),
        ])
    jobs += [
        (74,ROOT.parent/'data/DATA_CATALOG.md','СберИндекс — уточнённый каталог: средние расходы, периоды, дорожные расстояния 20.09.2026','data_catalog_revision'),
        (74,ROOT/'ANALYTIC_TOOLS.md','СберИндекс — запросы, нормализация и научные метрики 20.09.2026','deployed_analytics'),
        (62,ROOT/'PLATFORM_VERIFICATION.md','FixAR — проверенные точки расширения муниципальной модели 20.09.2026','local_code_verification'),
        (62,ROOT/'GPU_RUNTIME.md','aiOS2 — уточнение GPU backend: LM Studio/KB-Forge на Vulkan 20.09.2026','live_gpu_verification'),
    ]
    for cid in (75,76):
        jobs.append((cid,ROOT/'ANALYTIC_TOOLS.md',
                     'SberIndex — реализованные запросы, нормализация и научные метрики 20.09.2026',
                     'deployed_analytics'))
    jobs += [
        (75,ROOT.parent/'economic-atlas/protocol/question.md',
         'Экономический атлас — A0 исследовательский вопрос, PASS 20.09.2026',
         'gate_artifact'),
        (76,ROOT.parent/'shock-radar/protocol/forecast_contract.yaml',
         'Радар сдвигов — R0 forecast contract, BLOCKED по availability 20.09.2026',
         'gate_artifact'),
    ]
    receipts=[]
    for cid, path, title, kind in jobs:
        result=request('POST',f'/api/corpora/{cid}/documents/integrate',{
            'title':title,'url':f'urn:fixar:research:sberindex-2026:model-lab:{path.name}',
            'text':path.read_text(),
            'meta':{'kind':kind,'checked_on':'2026-09-20','project':'sberindex-2026',
                    'implementation_status':(
                        'proposal_only' if kind=='design_proposal'
                        else 'deployed' if kind=='deployed_analytics'
                        else 'reviewed' if kind=='gate_artifact'
                        else 'evidence')},
        })
        receipt={'corpus_id':cid,'file':path.name,'result':result}
        receipts.append(receipt)
        print(json.dumps(receipt,ensure_ascii=False),flush=True)
        (ROOT/'kb-receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n')
    checks=[]
    for cid in (75,76):
        result=request('POST',f'/api/corpora/{cid}/search',{'query':'муниципальная модель 1896 территории нарастающие зарплаты синтетические участники','limit':8})
        checks.append({'corpus_id':cid,'hits':[
            {'id':r.get('id'),'document_id':r.get('document_id'),'document_title':r.get('document_title'),'score':r.get('score')}
            for section in ('faq','distilled','chunks') for r in result.get(section,[])]})
    (ROOT/'kb-search-verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'search_checks':checks},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
