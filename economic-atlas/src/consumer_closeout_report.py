"""Build Russian closeout reports and an offline geographic point map."""
from pathlib import Path
import hashlib
import html
import json
import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[2]
RUN = R/'economic-atlas/runs/Consumer_closeout_20261006'
NAT = R/'shock-radar/runs/National_equal_information_20261006'


def dump(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def build():
    d = json.loads((RUN/'metrics.json').read_text())
    null = json.loads((RUN/'synthetic-null.json').read_text())
    n = json.loads((NAT/'metrics.json').read_text())
    cities = pd.read_csv(RUN/'robustness-municipalities.csv')
    den = pd.read_csv(RUN/'denominator-decomposition.csv')
    primary = [x for x in d['results'] if x['category'] in ['Все категории', 'Маркетплейсы']]
    lines = []
    for x in primary:
        m = x['mae']
        lines.append(f"| {x['category']} | {x['horizon']} | {m['profile_ses']:.2f} | {m['one_step_zero_peer']:.2f} | {m['direct_zero_peer']:.2f} |")
    core = cities.loc[cities.descriptive_core80].sort_values('territory_id')
    core_table = '\n'.join(f"| {int(x.territory_id)} | {x['name']} | {x.region_name} | {int(x.configurations_selected)}/45 |" for _, x in core.iterrows())
    text = f"""# Потребительская перестройка: дополнительные проверки перед завершением

Проверено 06.10.2026 на Mac в отдельном Git worktree и новом Python3.13 окружении, установленном из локального кэша. Все расчёты локальные; платные API и CMD не используются. Протокол зафиксирован до новых результатов. 2024 уже изучался, поэтому это дополнительное исследование, не нетронутая контрольная выборка.

## Что было в данных

Рабочая панель содержит 1896 территорий, 24 месяца с января2023 по декабрь2024 и шесть показателей: агрегат «Все категории», маркетплейсы, продовольствие, здоровье, общественное питание и транспорт. Всего273024 записи. Пять отдельных категорий не исчерпывают агрегат; складывать их с агрегатом нельзя. Это номинальные банковские показатели: количества товаров, индивидуальных бюджетов, доходов, долгов и цен в этой таблице нет. Описание единиц и ограничения первичного показателя сохранены в паспорте, а не уточняются предположением.

Для сравнения территорий использованы население2023 по двум полам, тип муниципалитета и девять характеристик2023: пять средних долей, логарифм населения, средний уровень, наклон и изменчивость общих расходов. Списки соседей заморожены по2023. Поддержка есть у1539 МО; у357 её нет. Население здесь помогает подобрать сопоставления, не является новым делителем банковских расходов. Полная панель и современный словарь выбраны ретроспективно; историческая дата публикации исходников неизвестна.

## Прогноз: удаление общей поправки изменило результат

Прежний опыт переносил среднюю прошлую ошибку на все территории. Это уже само по себе сильно ухудшало Profile SES. Новые варианты используют те же пять собственных признаков отклонения и дополнительно пять сравнений с соседями, но могут предсказывать поправку с нулевым средним при среднем наборе признаков. Поправка ограничена логарифмическим диапазоном±0,1; штраф ridge0,1 не подбирался по новым ошибкам.

Проверены все семь заранее записанных вариантов, шесть категорий и горизонты1/3/6. Ниже две основные категории; все варианты, месячные ошибки и интервалы находятся в metrics.json. На каждом сравнении ровно9234 наблюдения:1539МО×6 целевых месяцев. Ошибка MAE в исходных единицах показателя; меньше лучше.

| Категория | Горизонт, месяцев | Profile SES | Одношаговая поправка без среднего, свои+соседи | Поправка для своего горизонта без среднего |
|---|---:|---:|---:|---:|
{chr(10).join(lines)}

Для общих расходов на месяц улучшение модели «свои+соседи без среднего» составляет2,69%; для прямого трёхмесячного варианта3,79%. Одношаговые собственные признаки дают2,56% на месяц, поэтому всю прибавку нельзя приписать соседям. Для маркетплейсов собственная одношаговая поправка на месяц ухудшает прогноз, а добавление соседних отклонений даёт1,22% относительно Profile SES.

**Поправка для шести месяцев не обучена.** В этих точках нет ни одного завершённого шестимесячного исхода, начиная с доступности годовых признаков в январе2024. Прямые модели возвращают исходный прогноз и помечены COLD_START. Столбец одношаговой поправки на h6 переносит уже обученный одномесячный эффект на длинный прогноз; его результат1,96% для общего показателя не равен самостоятельному обучению или раннему предсказанию кризиса.

Для прямого h3 доступно1–6 завершённых месячных блоков; при одном блоке модель возвращает baseline. Тысячи территорий не заменяют длинную временную историю. Интервалы построены по шести целевым месяцам; отдельный анализ по регионам не учитывает одновременно всю временную зависимость. Совпадающие h1 варианты не являются двумя независимыми подтверждениями. Множество просмотренных вариантов и пересекающиеся горизонты сохраняют статус exploratory.

![Прогнозная прибавка и синтетические флаги](closeout-results.png)

## Насколько устойчивы 25 сигналов

Перебраны45 комбинаций:5 вариантов соседств×3 порога абсолютного разрыва×3 порога оценки необычности. Сохранялись тип МО, ограничения размера, использование2023 и требование трёх месяцев подряд во втором полугодии2024. При разных правилах из исходных25 сохраняются от7 до25.

Девять территорий отобраны минимум в80% вариантов. Это удобный список для первоочередного разбора, а не вероятность истинного шока:

| ID | Территория | Регион | Вариантов с сигналом |
|---:|---|---|---:|
{core_table}

Все частоты и новые отборы: robustness-municipalities.csv; правила, охват и Жаккар: robustness-grid.csv. При смене соседства поддержка меняется, поэтому полный список исключений и число сопоставимых МО учитываются отдельно.

## Может ли такое число флагов возникнуть от шума

Проведены100 синтетических повторов. В нулевом случае каждой территории задан одинаковый месячный сдвиг доли в процентных пунктах. Без случайного шума устойчивых флагов0. Шум берётся из изменений2023, совместно по категориям и территориям, с трёхмесячными блоками; за12 месяцев он накапливается. Это конкретная модель шума, а не подтверждённое описание2024.

Одна территория, ID316, не допускает положительную долю при заданном общем сдвиге. Она исключена только из синтетического опыта до первого счёта флагов, без обрезания отрицательных значений. Синтетическая панель1895, поддержка1538; на той же маске в реальных данных остаются25 сигналов.

Среднее число устойчивых нулевых флагов **{null['mean_null_count']:.2f}**, медиана **{null['null_count_quantiles_025_50_975'][1]:.0f}**, интервал между2,5% и97,5% повторов **{null['null_count_quantiles_025_50_975'][0]:.2f}–{null['null_count_quantiles_025_50_975'][2]:.2f}**. Это интервал распределения синтетических счётов, не доверительный интервал реальной доли ошибок. Значение25 само по себе не доказывает редкость локальных перестроек.

В первом зафиксированном шумовом повторе десяти МО добавлено+3п.п. маркетплейсов в июле–декабре; сработали3из10. До добавления уже был флаг у1из10, вне целевых МО после добавления45флагов. Такие десять инъекций не дают точной оценки чувствительности реальных кризисов. Пороги после этого результата не перенастраивались. Сигнал остаётся способом выбрать историю для проверки источников.

## Доля или общие расходы

Для всех25 разобраны отдельно логарифмический рост маркетплейсов и рост агрегата. Разность даёт изменение доли точно. Для этой вспомогательной декомпозиции используется среднее логарифмических изменений соседей: отдельно взятые медианы такую аддитивность не гарантируют. Исходный медианный детектор при этом не изменён.

У22из25 в минимум трёх месяцах второго полугодия есть номинальное отклонение маркетплейсов не менее5логарифмических пунктов в направлении исходного разрыва. У24 отношение маркетплейсов к продовольствию движется относительно соседей в ту же сторону в IVквартале. У3 изменение общего знаменателя по модулю сильнее изменения числителя. Приведены также отношения к остальным расходам; агрегат минус маркетплейсы положителен у всех1896 МО.

Это усиливает или ослабляет отдельные истории, но не является независимым причинным подтверждением. Несколько долей с одним знаменателем могут двигаться совместно без нескольких отдельных событий. Полная таблица: denominator-decomposition.csv.

## Что получилось practically

Карта показывает все1896 территорий,25 исходных сигналов и9 наиболее устойчивых к правилам. Для выбранного МО видны частота отбора, доля и уровень, вклад числителя и знаменателя, факт и разные прогнозы на тех же датах. Для неподдерживаемых территорий отсутствие сопоставления указано явно. География — точки координат словаря, не новые административные полигоны.

Для конкурсной работы сильный тезис: измеренная потребительская перестройка, проверяемые сопоставления и небольшая дополнительная прогнозная прибавка при честной калибровке. Реальная частота ложных тревог, независимая прогнозная победа, причинность и обещание кризиса за полгода не установлены.

## Проверка и повтор

Все204768 исходных прогнозных ключей сохранены; факт и Profile SES побитно совпали с прежним опытом. Замена всех будущих значений сохранила1638144 прогнозных чисел. Новые формулы проверены отдельным augmented least-squares решением, а сырьё и соседства — прежними независимо записанными уравнениями. Квитанция находится в ../Consumer_closeout_independent_audit_20261006/independent-validation.json.

Повтор с новым каталогом вывода:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python economic-atlas/src/consumer_closeout.py \
  --data-dir /path/to/frozen-inputs \
  --protocol economic-atlas/consumer_closeout_protocol_20261006.json \
  --out /path/to/new-run
```

Внешние входы:2_bdmo_population.parquet и municipal_dictionary.parquet, с исходными SHA. Панель, старые производные прогнозы, код baseline и протокол находятся в репозитории; исходные выпуски предоставляются отдельно. Собственная воспроизводимость не устанавливает историческую доступность данных.
"""
    text = text.replace('Что получилось practically', 'Как использовать результат')
    (RUN/'README.md').write_text(text)
    national_table = '\n'.join(f"| {x['category']} | {x['mae']['fresh_plain_prophet']:.2f} | {x['mae']['national_prophet']:.2f} | {x['mae']['national_yoy_lag1']:.2f} |" for x in n['by_category'])
    (NAT/'README.md').write_text(f"""# Национальный фактор и Prophet: одинаковая доступная информация

Проверено06.10.2026 на Mac:120 рядов,20 МО×6 категорий,720 одинаковых прогнозных ключей h12 за июль–декабрь2024. МО выбраны по SHA256(seed,id) из полноты ключей, без выбора по ошибкам. Протокол, полный список IDs, исходные SHA и все прогнозы сохранены.

Заново обучены обычный Prophet и Prophet с национальным регрессором: linear,3changepoints, без сезонностей и uncertainty samples, одинаковая история и seed. Регрессор — логарифм национального агрегата с лагом1месяц; для будущего он экстраполируется последним доступным годовым темпом, реальные будущие национальные значения не используются. Простая модель умножает последнее собственное значение на тот же доступный годовой национальный темп.

| Категория | Свежий Prophet | Prophet+национальный ряд | Простая национальная модель |
|---|---:|---:|---:|
{national_table}

Пул всех категорий: MAE{n['mae']['fresh_plain_prophet']:.2f} / {n['mae']['national_prophet']:.2f} / {n['mae']['national_yoy_lag1']:.2f}. Национальный регрессор даёт Prophet всего0,11%; интервал парной прибавки−45,67…+41,24 включает ноль. Простая национальная модель лучше Prophet с тем же рядом на36,79% в этом пилоте; парный шестимесячный bootstrap прибавки166,50…518,88 исходных единиц.

Общее среднее сильно зависит от масштаба категорий и агрегата, который пересекается с ними. **На маркетплейсах простая национальная модель хуже Prophet с регрессором на53,04%.** Единого победителя по всем категориям нет. Продовольствие также имеет широкий интервал, включающий ноль.

В новом окружении выполнены1452 свежих fit, включая12 повторных проверок после замены будущего; ошибок обучения0. Свежие обычные720 прогнозов в точности совпали с сохранённым Prophet. Небольшая новая выборка и2024 уже просмотрены. Национальный снимок загружен05.10.2026; исторические пересмотры и доступность в2023 не подтверждены. Собственной истории в h12 fit только7–12 наблюдений. Это дополнительная проверка одинаковой информации, не подтверждение на независимом будущем.

Повтор:

```bash
MPLCONFIGDIR=/tmp/prophet-cache OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
python shock-radar/src/national_prophet_closeout.py \
  --raw /path/8_consumption.parquet --r9 /path/predictions-r9.parquet \
  --national /path/national-consumer-spending.parquet \
  --protocol shock-radar/national_prophet_protocol_20261006.json --out /path/new-run
```

Prophet1.4.0, NumPy2.5.3, pandas3.0.6; seed20261006. Никаких платных модельных API. Источник национального ряда: СберИндекс, https://sberindex.ru/ru/dashboards/consumer-spending. Исходные файлы здесь не перепубликуются.
""")
    summary = """# Дополнительные проверки перед завершением проекта · 06.10.2026

Новые вычисления выполнены локально в чистом окружении;2024 уже просмотрен. Протоколы, все варианты и отрицательные исходы сохранены. Исследования из PR11 и PR14 включены в эту рабочую ветку вместе с независимым аудитом PR13; старые научные пакеты сохранены.

| Шаг | Выполнено | Результат и граница |
|---|---|---|
| Прогноз по локальным отклонениям | 7 вариантов,6 категорий,h1/3/6,204768 ключей | После удаления общей средней поправки: общие расходы h1+2,69%, прямой h3+3,79%; exploratory |
| Горизонт6 | Доступные завершённые исходы проверены | Прямое обучение невозможно в этих окнах; перенос одношаговой поправки проверен отдельно |
| Устойчивость локальных сигналов | 45 правил | 9из25 сохраняются≥80%; минимум7 максимум25 исходных |
| Шум и ложные флаги | 100 синтетических повторов и10 инъекций | В среднем50,04 флага без локального шока; реальная точность детектора не установлена |
| Доля и знаменатель | Все25 сигналов, точная лог-декомпозиция |22номинальных подтверждения;24направления marketplace/food;3случая доминирования знаменателя |
| Одинаковая национальная информация | Свежий Prophet120рядов,720пар | Простая модель лучше суммарно36,79%, хуже маркетплейсов53,04%;0,11% от регрессора Prophet неубедительно |
| Новое окружение и проверки | Полные новые расчёты,1452 свежих Prophet fit, независимый регрессионный пересчёт | Технический повтор; не экономический holdout |
| MQ | Сохранено SPEC_UNRESOLVED | По решению владельца «mq не будет»; NewmanQ отдельно, запрос организаторам не нужен |
| Карта, отчёты и пакет | Новая карта и ссылки, исходный код и SHA | Публичная проверка и публикация фиксируются отдельными квитанциями |
| Конкурсная подача | Форма просмотрена, описания и ссылки готовятся | Нужны ФИО, контакты, место работы/учёбы, специализация, команда и решение по обязательным согласиям; отправка не подтверждена |

Подробный разбор данных, прогнозов, девяти территорий и ограничений: [новое исследование](../economic-atlas/runs/Consumer_closeout_20261006/README.md). [Prophet при одинаковой информации](../shock-radar/runs/National_equal_information_20261006/README.md). [Новая карта](../economic-atlas/site/consumer-closeout-20261006/index.html).

Исходные прогнозы прежнего опыта со средней поправкой были хуже Profile SES. Этот результат сохранён; новые варианты улучшают его после конкретного изменения формулы, выбранного уже после просмотра2024. Формулировку «отклонения всегда бесполезны» теперь использовать нельзя, как и формулировку «независимое преимущество доказано».

Для участия доступны интерактивные страницы: PDF по условиям является альтернативой, не обязательным дополнительным файлом. На официальной странице06.10 подтверждён день9октября; точное время и часовой пояс не найдены. Форма требует соглашения с положением и обработки персональных данных. Галочки и отправка не выполнены. Отдельное согласие на рекламные сообщения не выбирается автоматически.

Отдельная задача CMD не равнозначна исследованию. Автоматические вызовы стоят на паузе; владельцем в соседней сессии одобрен ручной Muse. Администраторские права агентного SSH остаются предметом отдельного ограничения. Полный ночной биллинг без выгрузки провайдера недоступен; пять показанных Sonnet строк подтверждают$0,798.
"""
    (R/'docs/RESEARCH_CLOSEOUT_2026-10-06.md').write_text(summary)
    map_build(cities, den)
    for folder in [RUN, NAT]:
        dump(folder/'release-manifest.json', {'files': {
            str(p.relative_to(R)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file() and p.name != 'release-manifest.json'}})
    print(json.dumps({'reports_built': 3, 'map': 'economic-atlas/site/consumer-closeout-20261006/index.html'}))


def map_build(cities, den):
    f = pd.read_parquet(R/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2/pre-2024-features.parquet')
    old = json.loads((R/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2/anomalies.json').read_text())
    p = pd.read_parquet(RUN/'predictions.parquet')
    city = cities.set_index('territory_id').to_dict('index')
    decomposition = den.set_index('territory_id').to_dict('index')
    forecasts = {}
    for (tid, cat, h), g in p.loc[p.category.isin(['Все категории', 'Маркетплейсы'])].groupby(['territory_id', 'category', 'horizon']):
        if not g.supported.all():
            continue
        forecasts.setdefault(int(tid), {})[('all' if cat == 'Все категории' else 'market')+str(h)] = g.sort_values('target')[
            ['actual', 'profile_ses', 'one_step_zero_peer', 'direct_zero_peer']].round(6).to_numpy().tolist()
    data = []
    for r in old:
        tid = r['territory_id']
        z = city.get(tid)
        dec = decomposition.get(tid)
        data.append({'id': tid, 'name': r['name'], 'region': r['region_name'],
            'lat': r['lat'], 'lon': r['lon'], 'supported': r['supported'],
            'signal': bool(r['supported'] and r['Маркетплейсы']['persistent']),
            'selected': int(z['configurations_selected']) if z else 0,
            'core': bool(z and z['descriptive_core80']),
            'market': r['Маркетплейсы'] if r['supported'] else None,
            'denominator': dec, 'forecast': forecasts.get(tid)})
    out = R/'economic-atlas/site/consumer-closeout-20261006'
    out.mkdir(parents=True, exist_ok=True)
    css = """*{box-sizing:border-box}body{margin:0;background:#f5f6f9;color:#17243b;font:16px/1.55 system-ui,sans-serif}main{max-width:1300px;margin:auto;padding:28px}h1{line-height:1.1;font-size:42px;margin:12px 0}h2{line-height:1.25}a{color:#145da0}header p{max-width:1000px}.note{background:#fff1d6;padding:16px;border-left:4px solid #c57a00}.stats{display:flex;gap:20px;flex-wrap:wrap;margin:22px 0}.stats span{background:white;padding:15px 23px;border-radius:10px}.layout{display:grid;grid-template-columns:1.1fr 1fr;gap:24px;align-items:start}.panel{min-width:0;background:white;padding:20px;border-radius:12px}.map{width:100%;background:#eaf2f5;border:1px solid #d4e1e8;border-radius:12px}circle{cursor:pointer}circle:focus{stroke:#000;stroke-width:3}input,select,button{font:inherit;max-width:100%;padding:10px;border:1px solid #bac4d2;border-radius:6px;background:white}input{width:100%}label{display:block;margin-top:12px}button{cursor:pointer;margin:4px 4px 4px 0}.tablewrap{overflow:auto}table{border-collapse:collapse;font-size:14px;width:100%}th,td{padding:8px;border-bottom:1px solid #dbe1e9;text-align:left;white-space:nowrap}.muted{color:#536075;font-size:14px}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:13px}.badge{font-weight:700;color:#13644e}svg.chart{width:100%;height:210px}footer{margin-top:25px}#results button{display:block;width:100%;text-align:left}@media(max-width:800px){main{padding:16px}h1{font-size:30px}.layout{grid-template-columns:1fr}.panel{padding:15px}.stats{gap:8px}.stats span{padding:10px}.chart{height:190px}}"""
    app = r"""
const D=__DATA__;const byId=new Map(D.map(x=>[x.id,x]));const $=id=>document.getElementById(id);
let current=byId.get(2037);const fmt=(v,n=2)=>v===null||v===undefined?'недоступно':Number(v).toLocaleString('ru-RU',{maximumFractionDigits:n});
const NS='http://www.w3.org/2000/svg';function el(tag,attributes){let e=document.createElementNS(NS,tag);Object.entries(attributes).forEach(([k,v])=>e.setAttribute(k,v));return e}
let map=$('map');D.forEach(x=>{if(!Number.isFinite(x.lon)||!Number.isFinite(x.lat))return;let lon=x.lon<0?x.lon+360:x.lon;let e=el('circle',{cx:20+(lon-19)/174*850,cy:20+(82-x.lat)/42*230,r:x.core?5:x.signal?3.8:1.8,fill:x.core?'#078464':x.signal?'#da7900':x.supported?'#6f899e':'#bbb',tabindex:x.signal?0:-1,'aria-label':x.name+', '+x.region});let t=el('title',{});t.textContent=x.name+' · '+x.region;e.appendChild(t);e.addEventListener('click',()=>show(x.id));e.addEventListener('keydown',e=>{if(e.key==='Enter')show(x.id)});map.appendChild(e)});
D.filter(x=>x.core).forEach(x=>{let b=document.createElement('button');b.textContent=x.name;b.addEventListener('click',()=>show(x.id));$('stories').appendChild(b)});
function show(id){current=byId.get(Number(id));$('city').textContent=current.name;$('region').textContent=current.region+' · ID '+current.id;
 $('support').textContent=current.supported?'Соседи зафиксированы по2023. '+(current.signal?'Исходный устойчивый сигнал. Отбор '+current.selected+'/45 правил; '+(current.core?'в числе девяти устойчивых.':'чувствителен к правилам.'):'По исходному правилу устойчивый сигнал не найден.'):'Сопоставление недоступно; поправка не оценивается. Это не доказательство отсутствия изменений.';
 let m=current.market;$('share').textContent=m?'Доля маркетплейсов: средняя2023 '+fmt(m.share_2023)+'%,2024 '+fmt(m.share_2024)+'%. Разрыв с соседями в IVквартале '+fmt(m.q4_peer_gap_pp)+'п.п.':'Нет допустимого сопоставления для интерпретации долей.';
 let d=current.denominator;$('decomposition').textContent=d?'IVквартал, относительно среднего соседей: рост маркетплейсов '+fmt(d.marketplace_numerator_excess_logpoints)+' лог-п.; рост агрегата '+fmt(d.aggregate_denominator_excess_logpoints)+' лог-п.; изменение доли '+fmt(d.share_excess_logpoints_exact)+' лог-п. Номинальное подтверждение: '+(d.nominal_confirmation?'да':'нет')+'. Числитель и знаменатель: разность точная; исходный медианный сигнал использует другую агрегацию.':'Декомпозиция рассчитана для25 исходных сигналов.';
 draw();$('results').replaceChildren();}
function draw(){let key=$('category').value+$('horizon').value;let q=current.forecast?current.forecast[key]:null;let body=$('rows');body.replaceChildren();let svg=$('chart');svg.replaceChildren();if(!q){$('forecast-note').textContent='Сопоставление недоступно; новые поправки не показаны.';return}
 $('forecast-note').textContent=$('horizon').value==='6'?'Прямой h6 не обучен: нет завершённых исходов. Синяя линия переносит одношаговую поправку.':'Прогнозы обучались только на завершённых исходах; весь2024 уже просмотрен. Это дополнительный опыт.';
 let lo=Math.min(...q.flat()),hi=Math.max(...q.flat());let range=hi-lo||1;let colors=['#18243a','#b56a2c','#007b72','#3568bc'];let names=['Факт','Profile SES','Одношаговая, без среднего','Прямой горизонт, без среднего'];
 colors.forEach((color,j)=>{let points=q.map((r,i)=>(30+i*85)+','+(175-(r[j]-lo)/range*135)).join(' ');svg.appendChild(el('polyline',{points,fill:'none',stroke:color,'stroke-width':j===0?3:2}));let t=el('text',{x:8,y:195+0,fill:'#425068','font-size':11});});
 q.forEach((r,i)=>{let t=el('text',{x:24+i*85,y:195,fill:'#425068','font-size':11});t.textContent=['Июл','Авг','Сен','Окт','Ноя','Дек'][i];svg.appendChild(t);let tr=document.createElement('tr');['2024-'+String(i+7).padStart(2,'0'),...r.map(x=>fmt(x))].forEach(x=>{let td=document.createElement('td');td.textContent=x;tr.appendChild(td)});body.appendChild(tr)});
 $('local-error').textContent=names.slice(1).map((name,j)=>name+': MAE '+fmt(q.reduce((s,r)=>s+Math.abs(r[0]-r[j+1]),0)/q.length)).join(' · ');
}
$('query').addEventListener('input',()=>{let q=$('query').value.toLocaleLowerCase('ru-RU');let list=$('results');list.replaceChildren();if(q.length<2)return;D.filter(x=>(x.name+' '+x.region+' '+x.id).toLocaleLowerCase('ru-RU').includes(q)).slice(0,15).forEach(x=>{let b=document.createElement('button');b.textContent=x.name+' · '+x.region;b.addEventListener('click',()=>show(x.id));list.appendChild(b)})});
$('category').addEventListener('change',draw);$('horizon').addEventListener('change',draw);show(current.id);
"""
    encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('</', r'<\/')
    app = app.replace('__DATA__', encoded)
    filename = 'consumer-map-'+hashlib.sha256(app.encode()).hexdigest()[:16]+'.js'
    (out/filename).write_text(app)
    (out/'closeout.css').write_text(css)
    page = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Потребительская перестройка — проверка сигнала и прогноза</title><link rel="stylesheet" href="closeout.css"></head><body><main><header><p>СберИндекс · Дополнительный опыт06.10.2026</p><h1>От необычного изменения к проверяемой истории</h1><p>1896 муниципалитетов,2023–2024. Здесь исходный сигнал, устойчивость к45 правилам, вклад общих расходов и факт против прогноза рассматриваются вместе.</p><p class="note">Девять территорий устойчивы к выбору правил. Реальная частота ложных тревог не установлена: выбранная модель шума даёт в среднем50 флагов при25 наблюдаемых.2024 уже просмотрен; кризис за полгода не предсказывается.</p></header><div class="stats"><span><b>1539</b> МО с сопоставлением</span><span><b>25</b> исходных сигналов</span><span><b>9</b> сохраняются≥80% правил</span><span><b>22/25</b> номинальных подтверждения</span></div><div class="layout"><section class="panel"><h2>Выберите территорию</h2><label for="query">Название, регион или ID</label><input id="query" type="search" placeholder="Например, Шалинский"><div id="results"></div><p class="muted">Точки из координат словаря. Схематическая география; административные границы здесь не показаны.</p><svg id="map" class="map" viewBox="0 0 920 310" role="img" aria-label="Муниципалитеты и устойчивые локальные сигналы"></svg><p class="legend"><span>● зелёный:9 устойчивых</span><span>● оранжевый:остальные16 сигналов</span><span>● синий:есть сопоставление</span><span>● серый:сопоставление недоступно</span></p><div id="stories"></div></section><section class="panel"><h2 id="city"></h2><p id="region" class="muted"></p><p id="support" class="badge"></p><p id="share"></p><p id="decomposition"></p><label for="category">Прогнозируемый показатель</label><select id="category"><option value="all">Все категории</option><option value="market">Маркетплейсы</option></select><label for="horizon">Горизонт, месяцев</label><select id="horizon"><option value="1">1</option><option value="3">3</option><option value="6">6</option></select><p id="forecast-note" class="muted"></p><svg id="chart" class="chart" viewBox="0 0 490 210" aria-label="Факт и три прогноза"></svg><p class="legend">● чёрный:факт · ● коричневый:Profile SES · ● зелёный:одношаговая поправка · ● синий:прямой горизонт</p><p id="local-error" class="muted"></p><div class="tablewrap"><table><thead><tr><th>Месяц</th><th>Факт</th><th>Profile SES</th><th>Одношаговая</th><th>Прямой горизонт</th></tr></thead><tbody id="rows"></tbody></table></div><p class="muted">Номинальные исходные единицы. Поправки используют непрерывные отклонения всех поддерживаемых МО;25флагов не являются единственными обучающими примерами.</p></section></div><footer><p><a href="/sberindex-2026/reports/economic-atlas/runs/Consumer_closeout_20261006/README.html">Полный разбор и все ограничения</a> · <a href="/sberindex-2026/reports/shock-radar/runs/National_equal_information_20261006/README.html">Prophet с той же национальной информацией</a> · <a href="https://agrigate.pro/sberindex-2026/economic-atlas/landing/">Атлас</a></p><p class="muted">Источник:СберИндекс, пакет муниципальных расходов2023–2024; сопоставления по2023; словарь и панель ретроспективные. Числа взяты из сохранённого Consumer_closeout_20261006, округлены до6 знаков; алгоритмы и SHA опубликованы с отчётом. Причинность, историческая дата публикации и независимое прогнозное превосходство не установлены.</p></footer></main><script src="__APP__"></script></body></html>"""
    (out/'index.html').write_text(page.replace('__APP__', filename))
    dump(out/'manifest.json', {'municipalities': len(data), 'supported': sum(x['supported'] for x in data),
        'signals': sum(x['signal'] for x in data), 'core80': sum(x['core'] for x in data),
        'forecast_precision': 6, 'source_prediction_sha256': hashlib.sha256((RUN/'predictions.parquet').read_bytes()).hexdigest(),
        'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file() and p.name!='manifest.json'}})


if __name__ == '__main__':
    build()
