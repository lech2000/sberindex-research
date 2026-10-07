'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../presentation/landing-common/research-chat.js'), 'utf8');

class Element {
  constructor() { this.children=[]; this.listeners={}; this.files=[]; this.value=''; this.dataset={}; }
  append(...items) { this.children.push(...items); }
  before(item) { this.beforeItem=item; }
  remove() {}
  focus() {}
  querySelector(selector) { return this.selectors?.[selector] || null; }
  querySelectorAll() { return []; }
  addEventListener(name,fn) { this.listeners[name]=fn; }
}
const tick = () => new Promise(resolve => setImmediate(resolve));

async function browser(store, {project='atlas', registered=false, cookieAccepted=true, staleLegacy=false}={}) {
  const selectors={};
  for (const key of ['form','[data-chat-input]','[data-chat-log]','[data-chat-status]',
    '[data-chat-error]','[data-chat-send]','[data-chat-login]','[data-chat-file]',
    '[data-chat-reference]','[data-chat-reference-file]','[data-chat-keys]']) selectors[key]=new Element();
  selectors['[data-chat-reference]'].value='none';
  const root=new Element(); root.dataset.project=project; root.selectors=selectors;
  const requests=[];
  const fetch=async (url,options={})=>{
    assert.equal(options.credentials,'include');
    assert.equal(options.headers['X-Fixar-Request'],'1');
    if(options.headers.Authorization) {
      assert.equal(staleLegacy,true);
      assert.equal(new URL(url).pathname,'/entry/whoami');
      return {ok:false,status:401,json:async()=>({})};
    }
    const endpoint=new URL(url).pathname;
    requests.push({endpoint, method:options.method||'GET', body:options.body&&JSON.parse(options.body)});
    let value;
    if(endpoint==='/entry/whoami') value=store.cookie||registered?{principal_id:'guest',assurance:registered?2:0}:{};
    else if(endpoint==='/entry/anon') { if(cookieAccepted)store.cookie=true; value={token:'must-not-be-stored'}; }
    else if(endpoint==='/research/sberindex/preview' && options.method!=='POST') value={preview_remaining:store.used?0:1};
    else if(endpoint==='/research/sberindex/preview') {
      if(store.used)value={reply:'Регистрация',registration_required:true};
      else {store.used=true;store.paid++;value={reply:'Проверенный результат [1].',guest_preview:true,preview_remaining:0};}
    } else if(endpoint==='/research/sberindex/chat') {store.paid++;value={reply:'Продолжение [1].'};}
    else throw new Error('Unexpected endpoint '+endpoint);
    return {ok:true,status:200,json:async()=>value};
  };
  const context={window:{FixarCore:{config:{apiOrigin:'https://api.agrigate.pro'}},addEventListener(){}},
    document:{querySelector:()=>root,createElement:()=>new Element(),createTextNode:text=>({textContent:text}),addEventListener(){}},
    navigator:{locks:{request:async(_name,fn)=>fn()}},localStorage:{getItem:()=>staleLegacy?'expired-token':null,setItem:()=>{throw new Error('Token storage forbidden');}},
    fetch,AbortSignal,URL,setTimeout,FileReader:class {constructor(){throw new Error('Guest file must not be read');}}};
  vm.runInNewContext(source,context);
  await tick();
  return {selectors,requests,root,submit:async question=>{
    selectors['[data-chat-input]'].value=question;
    await selectors.form.listeners.submit({preventDefault(){}});
  }};
}
test('new visitor gets cookie, one paid reply, then registration without another POST',async()=>{
  const store={paid:0}; const page=await browser(store);
  assert.equal(page.requests.filter(x=>x.endpoint==='/entry/anon').length,1);
  assert.match(page.root.selectors.form.beforeItem.textContent,/cookie/);
  await page.submit('Что изменилось?');
  assert.equal(store.paid,1);
  await page.submit('Сравни территории и объясни прогноз');
  assert.equal(store.paid,1);
  assert.equal(page.requests.filter(x=>x.method==='POST'&&x.endpoint.includes('/research/')).length,1);
  assert.match(page.selectors['[data-chat-status]'].textContent,/заявка на доступ/);
  assert.match(page.selectors['[data-chat-log]'].children.at(-1).children.map(x=>x.textContent||'').join(''),/материалам дел/);
});
test('reload and other landing retain spent guest quota',async()=>{
  const store={cookie:true,used:true,paid:0};
  for(const project of ['atlas','radar']) {
    const page=await browser(store,{project}); await page.submit('Следующий сложный вопрос');
    assert.equal(page.requests.filter(x=>x.method==='POST').length,0);
  }
  assert.equal(store.paid,0);
});
test('blocked cookie never starts paid request',async()=>{
  const store={paid:0};const page=await browser(store,{cookieAccepted:false});
  await page.submit('Первый вопрос');
  assert.equal(store.paid,0);
  assert.match(page.selectors['[data-chat-error]'].textContent,/cookie/);
});
test('guest file is not read or uploaded',async()=>{
  const store={cookie:true,paid:0};const page=await browser(store);
  page.selectors['[data-chat-file]'].files=[{name:'private.csv',size:100}];
  await page.submit('Посчитай файл');
  assert.equal(store.paid,0);
  assert.equal(page.requests.filter(x=>x.method==='POST').length,0);
});
test('registered visitor keeps deeper authenticated chat',async()=>{
  const store={cookie:true,paid:0};const page=await browser(store,{registered:true});
  await page.submit('Вопрос');await page.submit('Уточнение');
  assert.equal(store.paid,2);
  assert.equal(page.requests.filter(x=>x.endpoint==='/research/sberindex/chat').length,2);
  assert.equal(page.requests.filter(x=>x.endpoint==='/entry/anon').length,0);
});
test('expired legacy token does not replace an existing authenticated cookie with a guest',async()=>{
  const store={cookie:true,paid:0};const page=await browser(store,{registered:true,staleLegacy:true});
  await page.submit('Продолжить');
  assert.equal(page.requests.filter(x=>x.endpoint==='/entry/anon').length,0);
  assert.equal(page.requests.filter(x=>x.endpoint==='/research/sberindex/chat').length,1);
});
