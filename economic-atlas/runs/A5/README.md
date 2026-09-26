# A5 — географический граф + совместная типология (статус: код готов, НЕ ВЫПОЛНЯЛСЯ)

Код: `src/a5_graph.py`. Реальные данные в fixar-devops отсутствуют —
прогон выполняет оператор на joe. Артефакты `runs/A5/` (vertices /
features / edges / assignments `.parquet`, `metrics.json`,
`graph_manifest.json`) появятся только после прогона.

## Запуск на joe

```bash
cd deliverables/sberindex-2026/economic-atlas
python src/a5_graph.py --panel data/panel_v1.parquet \
  --distance ../data/raw/sberindex-data-sense-2025/5_connection.parquet \
  --outdir runs/A5 --seed 20260921 --k 5
```

Deps: numpy, pandas, scipy, networkx, scikit-learn. Seed по умолчанию
`20260921`, `--k 5` (k-means и spectral), гео-kNN `8`, feature-kNN `5`,
Louvain resolution `1.0`.

Самопроверка без данных (toy data: selfloops, дубликаты, нулевые/
отрицательные/NaN расстояния, симметрия, единая маска,
воспроизводимость seed):

```bash
python src/a5_graph.py --self-check
```

## Входы

- `data/panel_v1.parquet` — замороженная панель: полные 24 мес × 6 категорий,
  1896 МО. Колонки распознаются по именам (`territory_id|tid`,
  `date|month|ym`, `category|category_15`, `value`).
- `../data/raw/sberindex-data-sense-2025/5_connection.parquet` —
  `territory_id_x/y`, `distance` (3 303 736 направленных пар по каталогу).

## Признаки (строго A3 `features/spec.yaml` FROZEN v1)

`share(cat,tid,m) = value(cat,tid,m) / value('Все категории',tid,m)` для 5
категорий (Здоровье, Маркетплейсы, Общественное питание, Продовольствие,
Транспорт). «Все категории» — отдельная строка-объём, НЕ сумма пяти
(медиана sum5/total ≈ 0.72): делить на сумму шести запрещено. Без `fillna(0)`:
неполная сетка, NaN, неположительный итог — весь tid исключается и
фиксируется в `feature_audit.excluded_tids`. Доли усредняются по времени,
затем z-score по tid (ddof=0); средние/стд — в аудите.

## Географический граф (только наблюдаемые расстояния)

Только положительные конечные `distance` между выбранными tid; строки x==y
выброшены. Дубликаты неупорядоченных пар схлопываются в MIN (повторы замеров,
не потоки). k=8 ближайших на узел, вес
`w = exp(-distance / median_positive_knn_distance)` (медиана — по отобранным
положительным направленным kNN-дистанциям), симметризация MAX, без selfloops.
Изоляты (нет положительного ребра к выбранным tid) исключаются из маски и
аудируются (`graph_audit.isolated_tids_no_positive_edge`) — искусственных
мостов нет. Компоненты связности — в `graph_audit.components`.

## Эксперименты (ОДНА маска: feature-valid ∩ geo-covered; пересечение явное)

- **E01** — k-means на z-долях, k=5, n_init=10, seed.
- **E02** — Louvain на наблюдаемом гео-графе, resolution=1.0, seed; число
  групп НЕ форсируется.
- **E03** — spectral на `A = 0.5·W_geo + 0.5·F_feat` (feature-kNN k=5,
  гауссово ядро, σ = медиана kNN-дистанций; симметризация max) + абляции
  alpha=0/1 (т.е. F-only / W-only).

Метрики: silhouette / Calinski-Harabasz / Davies-Bouldin — в ОДНОМ feature
space (z-доли); modularity — на гео-графе; попарные ARI/NMI + размеры кластеров
для всех пяти разметок.

## Про A4 (не same-mask comparison)

`runs/A4/*.json` посчитаны на 2190 МО с 6 признаками
(`share:Все категории` + 5) — другая feature definition и другая маска.
Выдавать их за same-mask сравнение с A5 запрещено; новый E01 считается на
маске 1896 с 5-долевым A3-определением (см. `metrics.json → note_A4`).

## Мобильность: исключена

`mobility-index` (594 строки: 297 МО × 2 даты) — подушевой км-индекс, НЕ
OD-матрица, без проверенного кроссволка к tid панели. Статус везде:
`mobility_status=excluded_no_OD_no_verified_crosswalk`. Рёбра из индекса не
выдумываются.

## Выходы `runs/A5/`

`vertices.parquet` (territory_id, in_mask, exclusion_reason),
`features.parquet` (5 share_mean_* + 5 z_*), `edges.parquet` (u<v, distance,
weight), `assignments.parquet` (territory_id + 5 label_*), `metrics.json`
(маска, аудиты, метрики, ARI/NMI, note_A4), `graph_manifest.json` (input/code
SHA256, versions, execution command, seed, формулы, компоненты,
mobility_status).
