(() => {
  'use strict';
  const input=document.getElementById('search');
  if(!input || !window.SberTerritorySearch)return;
  // Replace native datalist/change handling while retaining the same data/rendering.
  input.addEventListener('change',event=>event.stopImmediatePropagation(),true);
  window.SberTerritorySearch.bind({input,results:document.getElementById('territory-results'),status:document.getElementById('search-status'),
    items:DATA.territories,name:item=>item.name,meta:item=>`${item.region} · ID ${item.id}`,id:item=>item.id,
    format:item=>`${item.name} · ${item.region} · ${item.id}`,onSelect:item=>choose(item.id),
    emptyText:'В выборке из 1896 территорий совпадений нет. Попробуйте часть названия или регион; отсутствие результата не означает отсутствия территории.'});
  const requested=new URL(location.href).searchParams.get('territory');
  if(requested){if(/^\d+$/.test(requested) && byId.has(Number(requested)))choose(Number(requested));else document.getElementById('search-status').textContent='Этой территории нет в рабочей выборке. Найдите другую по названию или региону.';}
})();
