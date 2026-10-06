import json,urllib.request,hashlib,datetime,sys
rows=json.load(sys.stdin)
for cid,body in rows:
    req=urllib.request.Request(f'http://127.0.0.1:8300/api/corpora/{cid}/documents/integrate',data=json.dumps(body,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'})
    result=json.load(urllib.request.urlopen(req,timeout=180))
    did=result['document_id']
    readback=json.load(urllib.request.urlopen(f'http://127.0.0.1:8300/api/corpora/{cid}/documents/{did}/text',timeout=60))
    assert not readback.get('truncated') and readback['text'].strip()==body['text'].strip()
    print(json.dumps({'corpus_id':cid,'document_id':did,'full_readback_verified':True,'text_sha256':hashlib.sha256(readback['text'].encode()).hexdigest(),'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}),flush=True)
