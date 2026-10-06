import os,json,urllib.request,datetime,hashlib,sys
data=json.load(sys.stdin)
p='prn_fbab9aa00cd46169'
headers={'X-AIOS-Service-Token':os.environ['AIOS_INTERNAL_SERVICE_TOKEN'],'Content-Type':'application/json'}
def call(path,body=None,method=None):
    req=urllib.request.Request('http://case-service:8013'+path,headers=headers,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,method=method)
    try:
        with urllib.request.urlopen(req,timeout=60) as res:return json.load(res)
    except urllib.error.HTTPError as err:
        print(json.dumps({'failed_path':path,'status':err.code,'detail':err.read().decode()[:1600]},ensure_ascii=False),file=sys.stderr,flush=True)
        raise
def actions(cid):
    res=call('/cases/'+cid+'/actions?principal_id='+p)
    return res.get('actions',[]) if isinstance(res,dict) else res
def update_note(cid,aid,note):
    a=next(x for x in actions(cid) if x['id']==aid)
    assert not a['done'],(cid,aid,'already complete; do not reopen')
    if a.get('waiting_for')==note:return
    body={'principal_id':p,'waiting_for':note}
    for k in ['what','owner','due','waiting_for']:
        value=a.get(k) or (None if k=='due' else '')
        body['expected_'+k]=value
        if k!='waiting_for':body[k]=value
    call('/cases/'+cid+'/actions/'+aid,body,'PUT')
    after=next(x for x in actions(cid) if x['id']==aid)
    assert not after['done'] and after['waiting_for']==note

refs={x['corpus_id']:x['document_id'] for x in data['kb_receipts']}
assert set(refs)=={74,75,76,77}
text=data['note']+'\nТекущие документы, полностью прочитанные обратно:\n'+', '.join('KB%d №%d'%(cid,refs[cid]) for cid in sorted(refs))+'\n'
projects=[('atlas','case_66cae4a89ba6473f','act_3abcbb174d4f4511','act_c5ab2585bf8146b8','act_5533c9a1b45646d1',75),
          ('radar','case_008f37d03cf541e5','act_d0c376d044354f2e','act_e346385f69e54019','act_398bedb2669a4e2a',76),
          ('curator','case_d058db85c48a487c',None,None,None,77)]
for role,cid,aid,release,owner,cid_kb in projects:
    mid='mat_findings_closeout_20261006_'+role
    mats=call('/cases/'+cid+'/materials?for_principal='+p)['materials']
    existing=next((x for x in mats if x['id']==mid),None)
    if existing is None:call('/cases/'+cid+'/materials',{'id':mid,'kind':'text','mime':'text/markdown','title':'Итоги06.10: находки опубликованы, чистый повтор выполнен, приёмка кандидата','extracted':text,'uploaded_by':p})
    mats=call('/cases/'+cid+'/materials?for_principal='+p)['materials']
    assert next(x for x in mats if x['id']==mid)['extracted']==text
    if aid:
        a=next(x for x in actions(cid) if x['id']==aid)
        assert a['what'].startswith('13.'),(aid,a['what'])
        note='Выполнено06.10: свежийclone/2env,3make,SHA/эталоны/futureaudit,108HTTP/SHA; права/доступ проверены с оговорками. KB%d/%d, %s. TechnicalPASS; научныйPASS/подача отдельно.'%(cid_kb,refs[cid_kb],mid)
        if not a['done']:
            update_note(cid,aid,note)
            call('/cases/'+cid+'/actions/'+aid+'/complete',{'principal_id':p},'POST')
        assert next(x for x in actions(cid) if x['id']==aid)['done']
        update_note(cid,release,'Source13DONE06.10; находки/повтор KB%d/%d, общий74/%d. Публичные отчёты готовы;127файлов кандидата локально. Приёмка комплектности/критериев; владелец выбирает доступ жюри (GitPRIVATE). Не ждать R8fit/MQ/n8n/новыйдатасет.'%(cid_kb,refs[cid_kb],refs[74]))
        update_note(cid,owner,'Source13DONE06.10. Владелец: выбрать доступ жюри к коду, проверить две заявки/команду/комплект, отправить и сохранить подтверждение. Отчёты публичны; кандидат127файлов локально, безraw/cache/Gitистории. Приёмка12OPEN.')
        final=actions(cid)
        assert not next(x for x in final if x['id']==release)['done']
        assert not next(x for x in final if x['id']==owner)['done']
        if role=='radar':assert next(x for x in final if x['id']=='act_70e2fe4a16ac4e3d')['done']
    print(json.dumps({'case_id':cid,'project':role,'material_id':mid,'full_material_readback_verified':True,
                      'completed_source13':aid,'release12_open':bool(release),'owner14_open':bool(owner),
                      'scientific_pass':False,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                      'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}),flush=True)
