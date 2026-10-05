"""Publish one fixed site prefix under deploy_lock. Input remains in memory."""
import base64, hashlib, json, urllib.request, urllib.parse, subprocess, sys
payload=json.load(sys.stdin)
subprocess.run(['sh','/opt/aios2/scripts/deploy_lock.sh','assert','Codex SberIndex landing RAG'],check=True)
key=payload['BUNNY_KEY']
req=urllib.request.Request('https://api.bunny.net/storagezone',headers={'AccessKey':key})
zones=json.load(urllib.request.urlopen(req,timeout=30))
zone=next(z for z in zones if z['Name']=='agrigate-pro')
assert zone['Id']==1738071
storage_key=zone['Password']
endpoint='https://storage.bunnycdn.com/agrigate-pro/sberindex-2026/'
receipts=[]
# Data/styles first, HTML last. Do not touch any other prefix or delete files.
for file in sorted(payload['files'],key=lambda f:(f['path'].endswith('index.html'),f['path'])):
    path=file['path']
    assert not path.startswith('/') and '..' not in path.split('/')
    data=base64.b64decode(file['data'])
    assert hashlib.sha256(data).hexdigest()==file['sha256']
    url=endpoint+urllib.parse.quote(path,safe='/')
    req=urllib.request.Request(url,data=data,method='PUT',headers={'AccessKey':storage_key,'Content-Type':file['content_type']})
    with urllib.request.urlopen(req,timeout=60) as response:
        assert response.status in (200,201)
    # Verify storage bytes before cache invalidation.
    req=urllib.request.Request(url,headers={'AccessKey':storage_key})
    with urllib.request.urlopen(req,timeout=60) as response:
        assert hashlib.sha256(response.read()).hexdigest()==file['sha256']
    receipts.append({'path':path,'sha256':file['sha256'],'bytes':len(data)})
    print('Published:',path,flush=True)
purge_paths=[f['path'] for f in payload['files'] if f['path'].endswith(('index.html','.js','.css','.png','.txt'))]
purge_paths += ['economic-atlas/landing/','shock-radar/landing/']
for path in purge_paths:
    page='https://agrigate.pro/sberindex-2026/'+path
    req=urllib.request.Request('https://api.bunny.net/purge?url='+urllib.parse.quote(page,safe=''),method='POST',headers={'AccessKey':key})
    with urllib.request.urlopen(req,timeout=30) as response:assert response.status in (200,201,204)
print(json.dumps({'scope':'/sberindex-2026/','files':receipts},ensure_ascii=False),flush=True)
