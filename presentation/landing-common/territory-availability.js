(() => {
  'use strict';
  const root=document.querySelector('[data-territory-availability]');
  const catalog=window.SBER_TERRITORY_COVERAGE;
  if(!root || !catalog || !window.SberTerritorySearch)return;
  const input=root.querySelector('[data-coverage-search]'),region=root.querySelector('[data-coverage-region]');
  const output=root.querySelector('[data-coverage-selection]');
  input.addEventListener('input',()=>output.replaceChildren());
  const reasons={incomplete_spending_history:'Неполная история расходов за период исследования',absent_population:'Нет территориального ID в таблице населения',absent_migration:'Нет территориального ID в таблице миграции',absent_salary:'Нет территориального ID в таблице зарплат',absent_market_access:'Нет территориального ID в таблице доступности рынков',absent_raw:'Территория отсутствует в исходной выборке расходов этого исследования',selection_reason_unresolved:'Причина отбора не установлена в сохранённой проверке'};
  catalog.regions.forEach(item=>{const option=document.createElement('option');option.value=item.name;option.textContent=item.name+' — '+(item.available?item.available+' в Атласе':'не представлена в Атласе');region.append(option);});
  function show(item) {
    output.replaceChildren();
    const title=document.createElement('h3');title.textContent=item.name+' · '+item.region;output.append(title);
    const status=document.createElement('p');status.textContent=item.available?'Доступна в Атласе: расходы за январь 2023 — декабрь 2024 и сравнение территорий.':'Не входит в опубликованную выборку Атласа. Это ограничение данного исследования, а не заявление об отсутствии данных у СберИндекса.';output.append(status);
    if(item.available){const link=document.createElement('a');link.className='release-button';link.href='/sberindex-2026/economic-atlas/demo/?territory='+encodeURIComponent(item.id);link.textContent='Открыть расходы этой территории ↗';output.append(link);}
    else {const p=document.createElement('p');p.textContent='По сохранённой проверке: '+item.reasons.map(reason=>reasons[reason] || 'Причина: '+reason).join('; ')+'.';output.append(p);}
    if(item.yearTo!==9999){const p=document.createElement('p');p.textContent='Историческая единица в словаре: срок действия заканчивается в '+item.yearTo+' году. Название и границы могут отличаться от современных.';output.append(p);}
    const note=document.createElement('p');note.className='territory-search-hint';note.textContent='Запуск на своей таблице доступен и для других территорий, если файл отвечает требованиям формы. Этот поиск не гарантирует наличие территории во всех экспериментах Радара.';output.append(note);
  }
  const search=window.SberTerritorySearch.bind({input,results:root.querySelector('[data-coverage-results]'),status:root.querySelector('[data-coverage-status]'),
    items:catalog.territories,name:item=>item.name,meta:item=>item.region+' · '+(item.available?'есть в Атласе':'нет в выборке Атласа'),id:item=>item.id,
    filter:item=>!region.value || item.region===region.value,allowEmpty:()=>!!region.value,onSelect:show,
    emptyText:'В словаре исследования совпадений нет. Попробуйте часть названия, «е» вместо «ё» или другой регион. Это не полный справочник современных городов и посёлков.'});
  region.addEventListener('change',()=>{input.value='';search.refresh();input.focus();output.replaceChildren();const r=catalog.regions.find(r=>r.name===region.value);if(r){const p=document.createElement('p');p.textContent=r.name+': '+r.available+' территорий в Атласе; '+r.unavailable+' из словаря не вошли в эту выборку. Уточните название города или района.';output.append(p);}});
  const list=root.querySelector('[data-coverage-region-list]');
  catalog.regions.filter(r=>r.available).forEach(r=>{
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=r.name+' — '+r.available+' территорий';details.append(summary);
    details.addEventListener('toggle',()=>{if(!details.open || details.dataset.loaded)return;details.dataset.loaded='true';const cities=document.createElement('div');cities.className='territory-city-list';catalog.territories.filter(item=>item.available && item.region===r.name).sort((a,b)=>a.name.localeCompare(b.name,'ru')).forEach(item=>{const a=document.createElement('a');a.href='/sberindex-2026/economic-atlas/demo/?territory='+encodeURIComponent(item.id);a.textContent=item.name;cities.append(a);});details.append(cities);});list.append(details);
  });
  root.querySelectorAll('[data-coverage-example]').forEach(button=>button.addEventListener('click',()=>{region.value='';input.value=button.textContent;output.replaceChildren();search.refresh();input.focus();}));
})();
