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
  root.querySelectorAll('[data-chat-prompt]').forEach(button=>button.addEventListener('click',()=>{input.value=button.textContent; input.focus();}));
  input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();root.querySelector('form').requestSubmit();}});
  root.querySelector('form').addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;
    const question=input.value.trim();if(!question)return;
    error.hidden=true;
    await session();
    if(!signedIn){error.textContent='Войдите в Фиксар в соседней вкладке, затем вернитесь сюда и отправьте вопрос.';error.hidden=false;return;}
    busy=true;send.disabled=true;status.textContent='Ищу источники и готовлю ответ…';
    addMessage('user',question);input.value='';
    try {
      const r=await fetch(api+'/research/sberindex/chat',{method:'POST',credentials:'include',headers:headers(),body:JSON.stringify({project:root.dataset.project,message:question,history:history.slice(-6)}),signal:AbortSignal.timeout(55000)});
      const value=await r.json();
      if(!r.ok){const detail=value.detail;throw new Error(typeof detail==='string'?detail:(detail?.message||'Сервис временно недоступен. Попробуйте ещё раз.'));}
      const message=addMessage('agent',value.reply||'Ответ не получен. Попробуйте уточнить вопрос.');
      if(value.sources?.length){const list=document.createElement('ol');list.className='chat-sources';value.sources.forEach((source,index)=>{const li=document.createElement('li'),a=document.createElement('a');try{const url=new URL(source.url);if(url.protocol!=='https:')return;a.href=url.href;}catch(_){return;}a.target='_blank';a.rel='noopener noreferrer';a.textContent='['+(index+1)+'] '+source.title;li.append(a);list.append(li);});message.append(list);}
      if(value.model){const receipt=document.createElement('div');receipt.className='chat-receipt';receipt.textContent=value.model+' · '+value.checked_at+(value.receipt_sha256?' · квитанция '+value.receipt_sha256.slice(0,12):'');message.append(receipt);}
      history.push({role:'user',content:question},{role:'assistant',content:value.reply});status.textContent=value.sources?.length?'Ответ с источниками':'Источников для ответа нет';
      log.scrollTop=log.scrollHeight;
    } catch(e){input.value=question;const timedOut=e.name==='TimeoutError'||e.name==='AbortError';error.textContent=timedOut?'Подготовка ответа заняла слишком долго. Повторите вопрос.':e.message;error.hidden=false;status.textContent='Ответ не получен';}
    finally{busy=false;send.disabled=false;}
  });
  window.addEventListener('focus',session); document.addEventListener('visibilitychange',()=>{if(!document.hidden)session();});
  session();
})();
