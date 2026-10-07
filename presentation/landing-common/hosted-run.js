(() => {
  'use strict';
  const root = document.querySelector('[data-hosted-run]');
  if (!root) return;
  const api = window.FixarCore?.config?.apiOrigin;
  const form = root.querySelector('[data-run-form]');
  const status = root.querySelector('[data-run-status]');
  const error = root.querySelector('[data-run-error]');
  const output = root.querySelector('[data-run-result]');
  const method = root.querySelector('[data-run-method]');
  const start = root.querySelector('[data-run-start]');
  const cancel = root.querySelector('[data-run-cancel]');
  let runId = '', owner = '', timer, pending, submitting = false;
  const titles = {queued:'В очереди', running:'Выполняем исследование', completed:'Исследование готово', failed:'Нужны уточнения', cancelled:'Запуск отменён'};
  function headers() {
    const h = {'Content-Type':'application/json', 'X-Fixar-Request':'1'};
    for (const key of ['fixar.token','fixar.start.token','aios_token']) {
      try { const token=localStorage.getItem(key); if(token){h.Authorization='Bearer '+token;break;} } catch (_) {}
    }
    return h;
  }
  async function request(path, payload) {
    if (!api) throw new Error('Адрес Фиксара не загружен. Обновите страницу.');
    const r = await fetch(api+path, {method:payload ? 'POST':'GET',credentials:'include',headers:headers(),
      ...(payload ? {body:JSON.stringify(payload)}:{}),signal:AbortSignal.timeout(30000)});
    const value = await r.json();
    if (!r.ok) throw new Error(typeof value.detail==='string' ? value.detail : 'Не удалось выполнить запрос. Проверьте вход и повторите.');
    return value;
  }
  async function identify() {
    const who = await request('/entry/whoami');
    if (!who.principal_id || Number(who.assurance)<2) throw new Error('Войдите через Фиксар, затем вернитесь к запуску.');
    owner = who.principal_id;
  }
  function savedKey(){ return 'fixar.sberindex.run.'+owner+'.'+location.pathname; }
  function sayError(e){error.hidden=false;error.textContent=e.message || 'Запрос не завершился. Можно вернуться к запуску по ссылке.';}
  function refreshMethod() {
    const forecast = method.value==='forecast';
    root.querySelectorAll('[data-run-forecast]').forEach(el=>el.hidden=!forecast);
    root.querySelectorAll('[data-run-cluster]').forEach(el=>el.hidden=forecast);
    root.querySelector('[data-run-requirements]').textContent=forecast
      ? 'Для обучения: минимум 18 месяцев истории плюс проверочное окно; до 100 рядов территория × категория. Нужна полная месячная история.'
      : 'Для кластеризации: одинаковые категории и месяцы во всех территориях, минимум две категории; до 3000 территорий для K-means и 1500 для Ward. Для смысла долей нужны сопоставимые единицы расходов; индексы в денежные суммы не переводятся.';
  }
  method.value = document.querySelector('[data-research-chat]')?.dataset.project==='atlas' ? 'kmeans':'forecast';
  method.addEventListener('change', refreshMethod); refreshMethod();
  function table(rows, caption) {
    if (!rows?.length) return;
    const heading=document.createElement('h3');heading.textContent=caption;output.append(heading);
    const wrap=document.createElement('div');wrap.className='run-table';
    const element=document.createElement('table'), head=document.createElement('thead'), tr=document.createElement('tr');
    const keys=Object.keys(rows[0]);
    const labels={model:'Модель',observations:'Проверочных точек',mae:'MAE',rmse:'RMSE',bias:'Средняя ошибка',cluster:'Кластер',territories:'Территорий',territory_id:'Территория',category:'Категория',month:'Месяц',prediction:'Прогноз'};
    const names={seasonal_trend:'Сезонность и тренд',ridge_ar:'Ridge с лагами',last_value:'Последнее значение',seasonal_naive:'Тот же месяц год назад'};
    keys.forEach(key=>{const th=document.createElement('th');th.textContent=labels[key] || key;tr.append(th);});head.append(tr);element.append(head);
    const body=document.createElement('tbody');
    rows.slice(0,20).forEach(row=>{const line=document.createElement('tr');keys.forEach(key=>{const td=document.createElement('td');const v=row[key];td.textContent=v==null?'NA':typeof v==='number'?v.toLocaleString('ru-RU',{maximumSignificantDigits:8}):String(names[v] || v);line.append(td);});body.append(line);});
    element.append(body);wrap.append(element);output.append(wrap);
    if(rows.length>20){const note=document.createElement('p');note.textContent='Показаны первые 20 строк из '+rows.length+'. Все строки — в скачиваемом результате.';output.append(note);}
  }
  function render(value) {
    status.textContent=titles[value.status] || value.status;
    cancel.hidden=!['queued','running'].includes(value.status);
    start.disabled=!cancel.hidden;
    output.replaceChildren();
    const link=document.createElement('a'), url=new URL(location.href);
    url.searchParams.set('research_run',value.run_id);url.hash='research-run';
    link.href=url.href;link.textContent='Ссылка на этот запуск — сохраните, чтобы вернуться';output.append(link);
    const methodNames={forecast:'Обучение прогнозных моделей',kmeans:'Кластеризация K-means',ward:'Кластеризация Ward'};
    const note=document.createElement('p');note.textContent='Хранится до '+new Date(value.expires_at).toLocaleString('ru-RU')+'. '+value.dataset.filename+' · '+methodNames[value.parameters.method];output.append(note);
    if(value.error){const p=document.createElement('p');p.textContent=value.error;output.append(p);}
    if (!value.calculation) return;
    const c=value.calculation;
    table(c.table,'Результат');
    if(c.training){const p=document.createElement('p');p.textContent='Обучение: '+c.training.first_month+' — '+c.training.last_month+'. Проверка: '+c.training.holdout_first+' — '+c.training.holdout_last+'. Рядов: '+c.training.series+'. Меньшие MAE и RMSE означают меньшую ошибку на этом окне.';output.append(p);}
    table(c.future_predictions || c.labels,c.future_predictions ? 'Прогноз после конца файла':'Назначения территорий');
    const formula=document.createElement('p');
    formula.textContent=value.parameters.method==='forecast'
      ? 'Для проверки модели обучены на ранней истории и предсказывают всё проверочное окно из одной даты. Для будущего прогноза они обучены заново на всей истории файла. Отрицательные прогнозы ограничены нулём. Эта проверка не подтверждает качество на независимых будущих данных.'
      : 'Территории сгруппированы по долям выбранных категорий расходов за одинаковый период. Силуэт показывает разделимость этих групп; он не подтверждает их экономический смысл.';
    output.append(formula);
    if(c.metrics){const p=document.createElement('p');p.textContent='Средний силуэт: '+Number(c.metrics.silhouette_mean).toFixed(3)+'. Территорий в оценке: '+c.metrics.silhouette_sample_size+'.';output.append(p);}
    const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
    summary.textContent='Проверка, ограничения и версия метода';
    pre.textContent=JSON.stringify({training:c.training,period:c.period,metrics:c.metrics,formula:c.formula,limitations:c.limitations,engine:c.engine,receipt:c.execution_receipt},null,2);
    details.append(summary,pre);output.append(details);
    const button=document.createElement('button');button.type='button';button.textContent='Скачать модели, результаты и квитанцию';
    button.addEventListener('click',()=>{const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),href=URL.createObjectURL(blob),a=document.createElement('a');a.href=href;a.download=value.run_id+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(href),1000);});output.append(button);
  }
  async function poll() {
    clearTimeout(timer);
    if(!runId)return;
    try {
      const value=await request('/research/sberindex/runs/'+encodeURIComponent(runId));
      error.hidden=true;render(value);
      if(['queued','running'].includes(value.status))timer=setTimeout(poll,2500);
    } catch(e){sayError(e);status.textContent='Статус сейчас недоступен. Нажмите «Вернуться к последнему запуску». Не создавайте повторное задание.';}
  }
  async function encode(file) {
    if(!file || !file.size || file.size>8*1024*1024 || !/\.(csv|xlsx|parquet)$/i.test(file.name))throw new Error('Нужен непустой CSV, XLSX или Parquet до 8 МБ.');
    return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Файл не прочитан.'));reader.readAsDataURL(file);});
  }
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(submitting || !cancel.hidden)return;
    submitting=true;error.hidden=true;start.disabled=true;
    try {
      await identify();
      const file=root.querySelector('[data-run-file]').files[0];
      const parameters={method:method.value,k:Number(root.querySelector('[data-run-k]').value),horizon:Number(root.querySelector('[data-run-horizon]').value),holdout:Number(root.querySelector('[data-run-holdout]').value),seed:Number(root.querySelector('[data-run-seed]').value),ridge_alpha:Number(root.querySelector('[data-run-alpha]').value)};
      root.querySelectorAll('[data-run-column]').forEach(field=>parameters[field.dataset.runColumn]=field.value.trim());
      const data={filename:file?.name || '',content_b64:await encode(file),parameters};
      const signature=JSON.stringify(data);
      if(!pending || pending.signature!==signature || pending.owner!==owner)pending={signature,owner,body:{...data,request_key:crypto.randomUUID()}};
      status.textContent='Проверяем файл и ставим задание в очередь…';
      const value=await request('/research/sberindex/runs',pending.body);
      runId=value.run_id;pending=null;
      try{localStorage.setItem(savedKey(),runId);}catch(_){}
      render(value);await poll();
    } catch(e){sayError(e);status.textContent='Запрос запуска не подтверждён. Повтор с тем же файлом безопасен: ключ запроса сохраняется.';start.disabled=false;}
    finally{submitting=false;}
  });
  root.querySelector('[data-run-restore]').addEventListener('click',async()=>{
    try{await identify();runId=new URL(location.href).searchParams.get('research_run') || localStorage.getItem(savedKey()) || '';if(!runId)throw new Error('Сохранённого запуска нет. Загрузите файл и выберите метод.');await poll();}catch(e){sayError(e);}
  });
  cancel.addEventListener('click',async()=>{
    if(!runId)return;
    try{await identify();const value=await request('/research/sberindex/runs/'+encodeURIComponent(runId)+'/cancel',{});clearTimeout(timer);render(value);}catch(e){sayError(e);}
  });
  if(new URL(location.href).searchParams.has('research_run'))root.querySelector('[data-run-restore]').click();
})();
