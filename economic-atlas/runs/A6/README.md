# A6 — временная устойчивость помесячной типологии (статус: код готов, НЕ ВЫПОЛНЯЛСЯ)

Код: `src/a6_temporal.py`. Реальный полный расчёт выполняет оператор на joe
позднее. Артефакты `runs/A6/` (`transitions.parquet`, `metrics.json`,
`temporal_manifest.json`) появятся только после прогона. `src/a5_graph.py`
НЕ менялся.

## Запуск на joe

```bash
cd deliverables/sberindex-2026/economic-atlas
python src/a6_temporal.py --panel data/panel_v1.parquet \
  --outdir runs/A6 --seed 20260921
```

CLI: `--panel --outdir --seed` (+ `--k 5`, `--lambdas 0,0.5,2`).
Deps: numpy, pandas, scipy, scikit-learn. Seed по умолчанию `20260921`.

Самопроверка без данных (toy + synthetic control, всё в памяти):

```bash
python src/a6_temporal.py --self-check
```

## Входы

- `data/panel_v1.parquet` — замороженная панель: 1896 tid × 24 мес × 6 категорий.
  Ожидаемая форма фиксируется в `metrics.json → frozen_panel`
  (`expected_shape [1896, 24, 6]`, `frozen_shape_ok`). Колонки распознаются
  по именам (`territory_id|tid`, `date|month|ym`, `category|category_15`, `value`).

## Доли (те же, что в A5; zero-impute запрещён)

`share(cat,tid,m) = value(cat,tid,m) / value('Все категории',tid,m)` для 5
категорий (Здоровье, Маркетплейсы, Общественное питание, Продовольствие,
Транспорт). «Все категории» — отдельная строка-объём, НЕ сумма пяти: делить
на сумму шести запрещено. Без `fillna(0)`: неполная сетка, NaN,
неположительный итог — весь tid исключается целиком и фиксируется в
`mask.excluded_tids`. Все категории считаются без исключений из правила.

## Стандартизация (fit только по 2023, frozen transform всех месяцев)

Средние/стд (ddof=0) считаются пулом «маска × месяцы 2023» и замороженными
применяются ко ВСЕМ месяцам. Нулевая дисперсия → std=1.0 (z=0), в аудите
`standardization.zero_variance_features`.

## Кластеризация и выравнивание меток

- Каждый месяц независимо: k-means, k=5, n_init=10,
  `random_state = seed + month_index`. Пер-месячные сиды дают prefix
  invariance: правка будущих месяцев не меняет прошлые выходы.
- Выравнивание ID меток: Hungarian по квадрату центроидного расстояния
  к предыдущим ВЫРОВНЕННЫМ центроидам; месяц 0 хранит raw-ID. Пустые
  raw-кластеры переиспользуют предыдущий выровненный центроид (счётчик
  `empty_raw_clusters_reused_previous_centroid`).

## Временная связка — ЯВНЫЙ post-assignment penalty, НЕ joint dynamic model

С фиксированными центрами, без переобучения:

`post(tid,m) = argmin_c ||z − C(m,c)||² + lambda·[c ≠ post(tid,m−1)]`,

lambda ∈ {0, 0.5, 2}. lambda=0 в точности воспроизводит aligned-метки.
Называть это joint dynamic model запрещено — см. `temporal_linkage.note`
в `metrics.json`.

## Выходы `runs/A6/`

- `transitions.parquet` — колонки строго
  `territory_id / month / independent_label / aligned_label / lambda / post_label`
  (по строке на tid × месяц × lambda).
- `metrics.json` — чувствительность: `switch_rate` (доля смен метки между
  соседними месяцами), `silhouette` (пер-месячный, в том же z-пространстве),
  agreement ARI/NMI пост-меток vs aligned; размеры кластеров; кандидаты
  split/merge; E04; описание synthetic-контроля.
- `temporal_manifest.json` — input/code SHA256, versions, execution command,
  seed, формулы, маска, E04.

## Соседи: только кандидаты split/merge, никаких births/disappearance

Overlap между выровненными соседними кластерами:
`overlap(a@m, b@m+1) = |a ∩ b| / min(|a|, |b|)`, порог ≥ 0.2.
Split-кандидат: кластер месяца m достигает ≥2 кластеров месяца m+1;
merge-кандидат — зеркально. При фиксированном K births/disappearance
неотличимы от переразметки и НЕ выдумываются. E04 помечен incomplete
по построению (`e04` в metrics/manifest): A6 — это чувствительность
временной связки, не биографии кластеров.

## Synthetic abrupt-shift positive control (только self-check, не данные)

2 группы, 60 узлов, 12 месяцев, 20 участников меняют группу в месяц 7;
`labels_truth` живёт только в памяти self-check и НИКОГДА не пишется в
выходы и не касается наблюдаемых данных. Измеренное свидетельство:
recall сдвига + movement delay по lambda; сильная сглаженность МОЖЕТ
скрывать настоящие изменения.

## Self-check: prefix invariance и toy-проверки

- Детерминизм (два прогона побайтово), колонки transitions, полная маска,
  toy без переключений при lambda=0/2, silhouette высокий, lambda=0 ≡ aligned,
  `frozen_shape_ok=false` на toy, отсутствие утечки truth.
- Prefix invariance: панель 18 мес vs её префикс 15 мес (тот же сид генерации)
  — та же маска, тот же 2023-fit, прошлые строки transitions идентичны;
  переименование меток стабильно (majority-vote внутрь вызова).
- Synthetic: lambda=0 находит сдвиг (recall ≥ 0.95, задержка 0), lambda=50
  его прячет (recall падает).
