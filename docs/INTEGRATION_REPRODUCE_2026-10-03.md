# Воспроизведение интеграции миграции, ЦБ и мобильности

Проверено 3 октября 2026 года: полные расчёты на Mac, Python 3.13.0,
NumPy 2.5.3, pandas 3.0.6, PyArrow 25.0.1. Для мобильности дополнительно
SciPy 1.18.1 и scikit-learn 1.9.1. Это отдельная среда от исторических
прогонов A6/R8. Установленные версии перечислены в `requirements-integration.txt`.

```sh
uv venv --python 3.13.0 .venv-integration
uv pip install --python .venv-integration/bin/python -r requirements-integration.txt
```

Все команды ниже запускаются из корня репозитория. Каждый расчёт требует
новый каталог `--out`; существующие результаты не перезаписываются. Сырые
и детальные данные не включены в публичный репозиторий.

## Входы

Пакет организаторов скачивается существующим `data/download_sberindex_2025.sh`.
Актуальные панели СберИндекса получает `data/download_sberindex_current.py`.
Для повторения именно этого опыта нужны сохранённые срезы, а не сегодняшняя
замена прежних данных. Разложите исходный пакет в
`data/raw/sberindex-data-sense-2025/`, мобильность — в
`data/raw/sberindex-dashboard-current/mobility-index.parquet`.

Производные входы отдельно сохраняются как:

- `economic-atlas/data/panel_v1.parquet` — замороженная панель A6;
- `output/frozen/A6-assignments.parquet` — сохранённые назначения A6_v2;
- `output/frozen/r9-paired-predictions.parquet` — аудитированные парные
  прогнозы R9, задающие исходную маску сопоставления;
- `data/curated/cbr-macro-monthly.csv` — восемь подготовленных рядов ЦБ.

Проверяйте SHA256 байтов входов по таблице ниже и `sha256` в сохранённых
`metrics.json`. Другой источник или замена frozen input означает новый опыт.
Пересохранение Parquet другим writer тоже может изменить SHA; численные
выводы тогда требуют отдельной сверки, а не объявления точного повторения.

| Вход | SHA256 |
|---|---|
| `3_bdmo_migration.parquet` | `a7bff6bbf0dbd0cc0a8c83283ddf4b4fd0a13bbff5773ea167e6b79f590c67db` |
| `municipal_dictionary.parquet` | `f25088539a896cdc834d77c8792d0e6ac909d8649b06d65f69215ce12a8eaf4a` |
| `2_bdmo_population.parquet` | `4b69d43dd113591c12cee61df39d318200ff42b83e52a28593930e7ee0b34dbf` |
| `panel_v1.parquet` | `8716a802fb6e25ef4103406cca927de80ce3693a7ff243411cda765b732bcd93` |
| Назначения A6_v2 | `7f4d3a69a2b1449f6ac793494603951b767c737475b4f2b4ccece01e54b1116b` |
| `8_consumption.parquet` | `9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61` |
| `cbr-macro-monthly.csv` | `b9c734d72eb14d911514cc243d9f3413c3ee79f6279f8291e2a3aa2f229097cd` |
| Парные прогнозы R9 | `b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44` |
| `mobility-index.parquet` | `f7af1aa73e6a8b52909abaf130c26e2cdc4e697d1ac65d5548daa1a7d30ba837` |
| Выбранные метаданные мобильности | `b1d959944f426efc5b67b72477cdd97780fcd044648a284b80e058971271ef54` |
| Reference миграции 2023 | `bc30fd0bfb1a718667bbf897cf5d6973dea98d58515ada7ef9ba40eec20915da` |

Метаданные мобильности повторно скачаны переносимым скриптом: SHA совпал
с использованным снимком. Позднее каталог может измениться; это текущая
привязка source code, а не свидетельство исторических юридических границ.

## 1. Миграция

Нормализация сохраняет пропуски и проверяет конфликты естественного ключа.
Возрастные интервалы не складываются: некоторые пересекаются.

```sh
.venv-integration/bin/python economic-atlas/src/supplementary_audit.py \
  --stage migration --root data \
  --assignments output/frozen/A6-assignments.parquet \
  --out output/migration-intake

.venv-integration/bin/python data/download_migration_reference.py \
  --out output/migration-reference

.venv-integration/bin/python economic-atlas/src/migration_verified_analysis.py \
  --root data \
  --reference output/migration-reference/net-migration-2023.parquet \
  --normalized output/migration-intake/migration-normalized.parquet \
  --assignments output/frozen/A6-assignments.parquet \
  --panel economic-atlas/data/panel_v1.parquet \
  --out output/migration-verified
```

Загрузчик допускает только точный публичный ZIP указанного показателя.
HTTP Range, Content-Range, ETag, размер и CRC выбранного члена проверяются;
годовой Parquet читается без скачивания всего архива. Receipt содержит
URL, member, SHA и объём передачи. Сверка ячеек использует точные код, год,
возраст и пол; несовпадения и неподтверждённые ячейки исключаются из
подтверждённого слоя. Нормировка на население 1 января — описательная.

## 2. Показатели ЦБ

```sh
.venv-integration/bin/python shock-radar/src/cbr_macro_ablation.py \
  --raw data/raw/sberindex-data-sense-2025/8_consumption.parquet \
  --cbr data/curated/cbr-macro-monthly.csv \
  --r9-predictions output/frozen/r9-paired-predictions.parquet \
  --out output/cbr-macro-ablation
```

Перед вычислением сохраняется `protocol.json`: USD/М2, горизонты 1/3,
основной лаг 2, чувствительность при лаге 3, alpha=1, июль–декабрь 2024,
без подбора. FX — конец предыдущего месяца, М2 — запас на первое число.
Исторические `available_at` и vintage не подтверждены; лаги являются
допущениями, результат — ретроспективным. Собственные лаги и scaler
используют только допустимую обучающую историю. Пересечение с маской R9
проверяет точное совпадение actual/last-available.

В выходе сохраняются прогнозы обеих моделей, канонические временные ключи,
cutoff audit и метрики с 10 000 повторов парного bootstrap по шести целевым
месяцам. Этот bootstrap не устраняет зависимость соседних месяцев.
Ожидаемый вывод исходного опыта: USD/М2 ухудшили MAE; новый Prophet и
независимый holdout здесь не рассчитываются.

## 3. Мобильность

```sh
.venv-integration/bin/python data/download_sberindex_metadata.py \
  --dataset indeks-mobilnosti --out output/mobility-metadata.json

.venv-integration/bin/python economic-atlas/src/supplementary_audit.py \
  --stage mobility --root data \
  --assignments output/frozen/A6-assignments.parquet \
  --metadata output/mobility-metadata.json \
  --out output/mobility-intake

.venv-integration/bin/python economic-atlas/src/mobility_ablation.py \
  --panel economic-atlas/data/panel_v1.parquet \
  --cohort output/mobility-intake/mobility-atlas-candidate-cohort.parquet \
  --assignments output/frozen/A6-assignments.parquet \
  --out output/mobility-ablation
```

Файл с историческим именем `candidate-cohort` содержит строгий core,
отобранный по официальному native code, полному имени/типу и маске времени.
Имя муниципалитета само по себе не служит подтверждённым кроссволком.
Основная когорта — 101 МО; несовпадения типа и строки 2025 не допускаются.
Интервал `[year_from, year_to)` остаётся явно названным допущением.

Scaler расходов обучен на 2023 и заморожен. Для описательной мобильности
используется log1p и scaler на когорте 2024. K=2, n_init=20, пять seed,
основной вес 0,25 и чувствительность 1. Silhouette всех вариантов измеряется
в одном пространстве расходов; устойчивость seed не доказывает
экономическую истинность или национальную репрезентативность.

## Проверки

```sh
.venv-integration/bin/python economic-atlas/src/supplementary_audit.py --self-check
.venv-integration/bin/python economic-atlas/src/migration_verified_analysis.py --self-check
.venv-integration/bin/python shock-radar/src/cbr_macro_ablation.py --self-check
.venv-integration/bin/python economic-atlas/src/mobility_ablation.py --self-check
```

Проверки охватывают конфликтующие ключи, пропуски, точный код,
неоднозначные идентичности, временные смыслы ЦБ, инвариантность к
изменению будущих макроданных и будущего target, общий cohort/пространство
метрик и детерминизм кластеризации. Эти проверки и полные реальные расчёты
прошли. Технический PASS не означает scientific PASS.

Публичные агрегаты: `economic-atlas/runs/Migration_verified_20261003/metrics.json`,
`economic-atlas/runs/Mobility_ablation_20261003/metrics.json`,
`shock-radar/runs/CBR_macro_ablation_20261003/metrics.json`.
Интерпретация и ограничения: [результаты](DATA_INTEGRATION_RESULTS_2026-10-03.md).
