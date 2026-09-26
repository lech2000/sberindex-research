"""Attach proposal and evidence to the two existing research cases.

Run in case-service with this directory mounted/copied into a temporary location.
Uses existing internal authentication; prints no credentials.
"""
import base64
import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from shared.internal_auth import internal_service_headers

ROOT=Path(__file__).resolve().parent
OWNER='prn_fbab9aa00cd46169'
CASE='http://localhost:8013'
VAULT='http://vault-service:8019'
CASES={'economic-atlas':'case_66cae4a89ba6473f','shock-radar':'case_008f37d03cf541e5'}

def request(method,url,body=None,binary=False):
    req=urllib.request.Request(url,method=method,
        data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,
        headers={'Content-Type':'application/json',**internal_service_headers()})
    with urllib.request.urlopen(req,timeout=120) as r:
        raw=r.read()
        return raw if binary else json.loads(raw)

def main():
    receipts=[]
    for project,case_id in CASES.items():
        case=request('GET',f'{CASE}/cases/{case_id}')
        if case.get('owner_id')!=OWNER:raise RuntimeError('Unexpected case owner')
        for part,(name,mime,title) in enumerate([
            ('ARCHITECTURE.md','text/markdown','Муниципальная модель — архитектура и лестница (предложение).md'),
            ('loaded-data-audit.json','application/json','Муниципальная модель — аудит загруженных датасетов.json'),
        ],70):
            raw=(ROOT/name).read_bytes()
            digest=hashlib.sha256(raw).hexdigest()
            doc=request('POST',f'{VAULT}/vault/documents',{
                'owner_id':OWNER,'title':title,'content_b64':base64.b64encode(raw).decode(),
                'mime':mime,'kind':'file','sensitivity':'normal','domain':'software',
                'source_case_id':case_id,'in_knowledge':False,'text':raw.decode(),
            })['document']
            mat=request('POST',f'{CASE}/cases/{case_id}/materials',{
                'kind':'file','mime':mime,'title':title,'storage_ref':f"vault:{doc['id']}",
                'extracted':raw.decode(),'sensitivity':'normal','source_channel':'api','uploaded_by':OWNER,
                'client_message_id':f'sberindex-model-plan-20260920:{project}:{part}:{digest[:12]}',
                'client_request_hash':digest,'part_index':part,
            })
            query=urllib.parse.urlencode({'principal_id':OWNER})
            back=request('GET',f"{CASE}/cases/{case_id}/materials/{mat['id']}/content?{query}",binary=True)
            if hashlib.sha256(back).hexdigest()!=digest:raise RuntimeError('Attachment roundtrip mismatch')
            receipt={'project':project,'case_id':case_id,'material_id':mat['id'],'file':name,'sha256':digest,'verified':True}
            receipts.append(receipt)
            (ROOT/'fixar-receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(receipt,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
