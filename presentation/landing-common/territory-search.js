/* One searchable, keyboard-accessible list for geographic and research pages. */
(() => {
  'use strict';
  const normalize = value => String(value ?? '').normalize('NFKC').toLocaleLowerCase('ru')
    .replace(/ё/g, 'е').replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  function createIndex(items, name, meta, id) {
    return items.map(item => ({item, name:normalize(name(item)), text:normalize(`${name(item)} ${meta(item)} ${id(item)}`), id:normalize(id(item))}));
  }
  function find(index, query, limit = 12, {allowEmpty=false}={}) {
    const term = normalize(query);
    if (!term && !allowEmpty) return {total:0, items:[]};
    const words = term.split(' ');
    const hits = index.filter(row => words.every(word => row.text.includes(word)));
    const rank = row => row.id === term || row.name === term ? 0 : row.name.startsWith(term) ? 1 : words.every(word => row.name.includes(word)) ? 2 : 3;
    hits.sort((a,b) => rank(a)-rank(b) || a.name.localeCompare(b.name,'ru') || a.text.localeCompare(b.text,'ru'));
    return {total:hits.length, items:hits.slice(0,limit).map(row=>row.item)};
  }
  function bind({input, results, status, items, name, meta, id, onSelect, format = name, limit = 12, filter=()=>true, allowEmpty=()=>false, emptyText = 'Территория не найдена. Попробуйте часть названия или регион.'}) {
    const index = createIndex(items,name,meta,id);
    const wrapper = input.parentElement;
    wrapper.classList.add('territory-search');
    results.classList.add('territory-search-results');
    results.id ||= input.id+'-results';
    results.setAttribute('role','listbox');
    results.setAttribute('aria-label','Найденные территории');
    input.setAttribute('role','combobox');
    input.setAttribute('aria-autocomplete','list');
    input.setAttribute('aria-controls',results.id);
    input.setAttribute('aria-expanded','false');
    input.removeAttribute('list');
    const control = document.createElement('div');
    control.className='territory-input-control';
    input.before(control);control.append(input,results);
    const clear = document.createElement('button');
    clear.type='button';clear.className='territory-search-clear';clear.textContent='×';
    clear.setAttribute('aria-label','Очистить поиск территории');clear.hidden=!input.value;
    input.after(clear);
    let hits = [], active = -1, total = 0;
    function close() {results.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');active=-1;}
    function highlight(next) {
      active=next;
      Array.from(results.querySelectorAll('[role="option"]')).forEach((option,i)=>option.setAttribute('aria-selected',String(i===active)));
      if(active>=0){const option=results.querySelectorAll('[role="option"]')[active];input.setAttribute('aria-activedescendant',option.id);option.scrollIntoView({block:'nearest'});}
    }
    function select(item) {input.value=format(item);clear.hidden=false;input.focus();close();onSelect(item);status.textContent=`Выбрано: ${name(item)}, ${meta(item)}.`;}
    function render() {
      clear.hidden=!input.value;
      const found=find(index.filter(row=>filter(row.item)),input.value,limit,{allowEmpty:allowEmpty()});hits=found.items;total=found.total;active=-1;
      results.replaceChildren();input.removeAttribute('aria-activedescendant');
      if(!normalize(input.value) && !allowEmpty()){status.textContent='Введите название города, района или региона.';close();return;}
      results.hidden=false;input.setAttribute('aria-expanded','true');
      if(!hits.length){const p=document.createElement('p');p.textContent=emptyText;results.append(p);status.textContent=emptyText;return;}
      status.textContent=`Найдено: ${total}. `+(total>limit?`Показаны первые ${limit}; уточните запрос. `:'')+'Выберите территорию или используйте стрелки и Enter.';
      hits.forEach((item,i)=>{const option=document.createElement('button');option.type='button';option.tabIndex=-1;option.id=results.id+'-'+i;option.setAttribute('role','option');option.setAttribute('aria-selected','false');const title=document.createElement('b'),small=document.createElement('small');title.textContent=name(item);small.textContent=meta(item);option.append(title,small);option.addEventListener('click',()=>select(item));results.append(option);});
    }
    input.addEventListener('input',render);
    input.addEventListener('focus',()=>{if((input.value || allowEmpty()) && results.hidden)render();});
    input.addEventListener('keydown',event=>{
      if(event.isComposing)return;
      if(event.key==='Escape'){event.preventDefault();close();return;}
      if(event.key==='Tab'){close();return;}
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        if(results.hidden && ['Home','End'].includes(event.key))return;
        if(results.hidden)render();if(!hits.length)return;event.preventDefault();
        highlight(event.key==='Home'?0:event.key==='End'?hits.length-1:event.key==='ArrowDown'?(active+1)%hits.length:active<=0?hits.length-1:active-1);return;
      }
      if(event.key==='Enter'){
        if(results.hidden)render();event.preventDefault();
        if(active>=0)select(hits[active]);else if(total===1)select(hits[0]);
        else if(total>1)status.textContent=`Найдено: ${total}. Выберите нужную территорию стрелками или уточните регион.`;
      }
    });
    clear.addEventListener('click',()=>{input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();});
    document.addEventListener('pointerdown',event=>{if(!wrapper.contains(event.target))close();});
    return {close,refresh:render};
  }
  const api={normalize,createIndex,find,bind};
  if(typeof module!=='undefined' && module.exports)module.exports=api;
  if(typeof window!=='undefined')window.SberTerritorySearch=api;
})();
