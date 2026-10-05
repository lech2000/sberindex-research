(() => {
  'use strict';
  const root = document.querySelector('[data-research-chat]');
  if (!root) return;
  const api = window.FixarCore?.config?.apiOrigin;
  const input = root.querySelector('[data-chat-input]');
  const log = root.querySelector('[data-chat-log]');
  const status = root.querySelector('[data-chat-status]');
  const error = root.querySelector('[data-chat-error]');
  const send = root.querySelector('[data-chat-send]');
  const login = root.querySelector('[data-chat-login]');
  const fileInput=root.querySelector('[data-chat-file]');
  const refSelect=root.querySelector('[data-chat-reference]');
  const oldInput=root.querySelector('[data-chat-reference-file]');
  let signedIn = false, busy = false;
  const history = [];
  function headers() {
    const h = {'Content-Type':'application/json', 'X-Fixar-Request':'1'};
    // Compatibility with older authenticated FixAR sessions; never put a key in HTML.
    for (const key of ['fixar.token','fixar.start.token','aios_token']) {
      try { const token=localStorage.getItem(key); if(token){ h.Authorization='Bearer '+token; break; } } catch (_) {}
    }
    return h;
  }
  async function session() {
    if (!api || busy) return;
    try {
      const r = await fetch(api+'/entry/whoami',{credentials:'include',headers:headers(),signal:AbortSignal.timeout(8000)});
      const who = r.ok ? await r.json() : {};
      signedIn = !!who.principal_id && Number(who.assurance)>=2;
      status.textContent = signedIn ? 'Готов к вопросу' : 'Ответы после входа';
      login.textContent = signedIn ? 'Открыть Фиксар ↗' : 'Войти через Фиксар ↗';
    } catch (_) { signedIn=false; status.textContent='Проверьте вход в Фиксар'; }
  }
  function addMessage(role, text) {
    log.querySelector('.chat-welcome')?.remove();
    const message=document.createElement('div'); message.className='chat-message '+role;
    const label=document.createElement('span'); label.className='chat-message-label'; label.textContent=role==='user'?'ВАШ ВОПРОС':'ИССЛЕДОВАТЕЛЬ';
    message.append(label);
    String(text).split(/(\*\*[^*\n]+\*\*)/g).forEach(part=>{if(part.startsWith('**')&&part.endsWith('**')){const strong=document.createElement('strong');strong.textContent=part.slice(2,-2);message.append(strong);}else{message.append(document.createTextNode(part));}});
    log.append(message); log.scrollTop=log.scrollHeight; return message;
  }
  const MAX_FILE=8*1024*1024;
  const fields=()=>[fileInput,refSelect,oldInput,root.querySelector('[data-chat-keys]')].filter(Boolean);
  function fileLabel(){const file=fileInput?.files[0];root.querySelector('[data-chat-file-status]').textContent=file?file.name+' · '+(file.size/1024/1024).toFixed(2)+'МБ':'CSV, XLSX, Parquet · до8МБ';send.textContent=file?'Рассчитать ↗':'Спросить ↗';}
  fileInput?.addEventListener('change',()=>{fileLabel();if(fileInput.files[0]&&!input.value.trim())input.value=refSelect.value==='none'?'Проверь структуру, пропуски и посчитай сводную статистику числовых столбцов.':'Сравни новый выпуск с исходным: что добавлено, исчезло и пересмотрено?';});
  refSelect?.addEventListener('change',()=>{root.querySelector('[data-chat-reference-fields]').hidden=refSelect.value!=='uploaded';if(refSelect.value!=='none'&&!input.value.trim())input.value='Сравни новый выпуск с исходным: что добавлено, исчезло и пересмотрено?';});
  async function encode(file){
    if(!file||file.size===0||file.size>MAX_FILE)throw new Error('Выберите непустой файл до8МБ.');
    if(!/\.(csv|xlsx|parquet)$/i.test(file.name))throw new Error('Нужен CSV, XLSX или Parquet.');
    return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Не удалось прочитать файл.'));reader.readAsDataURL(file);});
  }
  function showTable(parent,rows){
    if(!rows?.length)return;const wrap=document.createElement('div');wrap.className='chat-result-scroll';
    const table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');
    const keys=Object.keys(rows[0]);keys.forEach(key=>{const th=document.createElement('th');th.textContent=key;tr.append(th);});head.append(tr);table.append(head);
    const body=document.createElement('tbody');rows.forEach(row=>{const line=document.createElement('tr');keys.forEach(key=>{const td=document.createElement('td');const value=row[key];td.textContent=value==null?'NA':typeof value==='number'?value.toLocaleString('ru-RU',{maximumSignificantDigits:8}):String(value);line.append(td);});body.append(line);});table.append(body);wrap.append(table);parent.append(wrap);
  }
  function showCalculation(message,value){
    if(!value.calculation)return;const c=value.calculation,d=value.dataset,box=document.createElement('section');box.className='chat-result';
    const title=document.createElement('h3');title.textContent='Результат вычислительного инструмента';box.append(title);
    const info=document.createElement('p');info.textContent=d.filename+' · '+d.rows.toLocaleString('ru-RU')+'строк · SHA '+d.sha256.slice(0,16);box.append(info);
    showTable(box,c.table);
    const formula=document.createElement('p');formula.textContent=c.formula;box.append(formula);
    if(c.version_comparison){const v=c.version_comparison,p=document.createElement('p');p.textContent='Сравнение выпусков: +'+v.added_rows+'строк, −'+v.removed_rows+'строк, пересмотрено'+v.revised_common_rows+'из'+v.common_rows+'общих строк. Прежний эталон сохранён. '+(v.same_file?'SHA идентичен.':'Для экспериментов на новом выпуске нужен отдельный прогон.');box.append(p);const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='Период, охват и схема';pre.style.whiteSpace='pre-wrap';pre.textContent=JSON.stringify({keys:v.keys,periods:v.periods,coverage:v.coverage,added_columns:v.added_columns,removed_columns:v.removed_columns,type_changes:v.type_changes},null,2);details.append(summary,pre);box.append(details);}
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Структура, пропуски и дубли';details.append(summary);showTable(details,d.columns);const note=document.createElement('p');note.textContent='Полных дублей строк: '+d.duplicate_rows+'. '+d.note+' '+d.numeric_convention;details.append(note);box.append(details);
    const download=document.createElement('button');download.type='button';download.textContent='Скачать расчёт и квитанцию';download.addEventListener('click',()=>{const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=value.run_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});box.append(download);message.append(box);
  }
  root.querySelectorAll('[data-chat-prompt]').forEach(button=>button.addEventListener('click',()=>{input.value=button.textContent; input.focus();}));
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();root.querySelector('form').requestSubmit();}});
  root.querySelector('form').addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;
    const question=input.value.trim();if(!question)return;
    error.hidden=true;
    await session();
    if(!signedIn){error.textContent='Войдите в Фиксар в соседней вкладке, затем вернитесь сюда и отправьте вопрос.';error.hidden=false;return;}
    busy=true;send.disabled=true;fields().forEach(x=>x.disabled=true);status.textContent=fileInput?.files[0]?'Проверяю файл и выполняю расчёт…':'Ищу источники и готовлю ответ…';
    addMessage('user',question);input.value='';
    try {
      const file=fileInput?.files[0],payload={project:root.dataset.project,message:question,history:history.slice(-6)};
      if(file){payload.filename=file.name;payload.content_b64=await encode(file);payload.reference=refSelect.value;if(payload.reference==='uploaded'){const previous=oldInput.files[0];payload.reference_filename=previous?.name||'';payload.reference_b64=await encode(previous);payload.key_columns=root.querySelector('[data-chat-keys]').value.split(';').map(x=>x.trim()).filter(Boolean);if(!payload.key_columns.length)throw new Error('Укажите ключевые столбцы через ; для сравнения выпусков.');}}
      const r=await fetch(api+'/research/sberindex/'+(file?'analyze':'chat'),{method:'POST',credentials:'include',headers:headers(),body:JSON.stringify(payload),signal:AbortSignal.timeout(60000)});
      const value=await r.json();
      if(!r.ok){const detail=value.detail;throw new Error(typeof detail==='string'?detail:(detail?.message||'Сервис временно недоступен. Попробуйте ещё раз.'));}
      const message=addMessage('agent',value.reply||'Ответ не получен. Попробуйте уточнить вопрос.');
      showCalculation(message,value);
      if(value.sources?.length){const list=document.createElement('ol');list.className='chat-sources';value.sources.forEach((source,index)=>{const li=document.createElement('li'),a=document.createElement('a');try{const url=new URL(source.url);if(url.protocol!=='https:')return;a.href=url.href;}catch(_){return;}a.target='_blank';a.rel='noopener noreferrer';a.textContent='['+(index+1)+'] '+source.title;li.append(a);list.append(li);});message.append(list);}
      if(value.model){const receipt=document.createElement('div');receipt.className='chat-receipt';receipt.textContent=value.model+' · '+value.checked_at+(value.receipt_sha256?' · квитанция '+value.receipt_sha256.slice(0,12):'');message.append(receipt);}
      history.push({role:'user',content:question},{role:'assistant',content:value.reply});status.textContent=value.calculation?'Расчёт готов; квитанция доступна':value.sources?.length?'Ответ с источниками':'Источников для ответа нет';
      log.scrollTop=log.scrollHeight;
    } catch(e){input.value=question;const timedOut=e.name==='TimeoutError'||e.name==='AbortError';error.textContent=timedOut?'Подготовка ответа заняла слишком долго. Повторите вопрос.':e.message;error.hidden=false;status.textContent='Ответ не получен';}
    finally{busy=false;send.disabled=false;fields().forEach(x=>x.disabled=false);}
  });
  window.addEventListener('focus',session); document.addEventListener('visibilitychange',()=>{if(!document.hidden)session();});
  session();
})();
