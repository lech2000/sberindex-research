# Один `make radar`

Проверено 05.10.2026 на Mac в отдельном scientific worktree. Команда повторяет
R9 strong baselines, D01-MV-v2 (замороженный D04), сравнение при одинаковых
реализованных null тревогах и независимые численные проверки. Интернет,
LLM и доступ к платформе не нужны. Полное обучение Prophet не повторяется:
его сохранённые прогнозы используются как проверяемый вход.

## Подготовка

```sh
uv venv --python 3.13 .venv
uv pip install --python .venv/bin/python -r repository-tools/requirements-science.txt
make radar PYTHON=.venv/bin/python
```

До запуска нужны пять точных входов из `data/frozen/radar/manifest.json`:
raw в `data/raw/sberindex-data-sense-2025/8_consumption.parquet`, три cache
Parquet в `data/frozen/radar/` и национальный snapshot в
`data/raw/sberindex-national-20261005/consumer-spending.parquet`. Скачивание исходного конкурсного raw:
`bash data/download_sberindex_2025.sh`; оно не входит в offline-команду.
Прогнозные cache и словарь локальны и не опубликованы этим изменением.
Значит, чистый clone без подготовки входов пока не является полным
самодостаточным воспроизведением. Любой отсутствующий вход или иной SHA
останавливает запуск до вычислений. Пути можно передать через
`RADAR_RAW`, `RADAR_R9`, `RADAR_PILOT`, `RADAR_DICTIONARY`, `RADAR_NATIONAL`.

## Квитанция

Каждый запуск создаёт отдельный `output/radar/<UTC>-<UUID>`; прежние runs
не меняются. Точные входы копируются туда, SHA сверяются, файлы становятся
read-only. Снимок среды, исходников и эталонов лежит в `snapshot.json`.
`artifact-manifest.json` содержит SHA всех новых артефактов, `result.json` —
итог и ограничения; три stage-log сохраняют полные stdout/stderr.

Проверяются эталонные метрики R9, семь таблиц D04, 2340 скалярных прогнозов
и их инвариантность к изменению будущих значений, 120 скалярных оценок
детекторов и изменение будущего raw для всех каналов. Эталоны сами
защищены SHA. Допуск чисел: rtol=1e-10, atol=1e-8.

```sh
make radar-selfcheck PYTHON=.venv/bin/python
.venv/bin/python shock-radar/src/detector_bank.py --self-check
```

D01-MV-v2 содержит Stouffer lower-tail/two-sided, trailing-window GLR,
max, energy, Mahalanobis на одном многомерном сигнале. Legacy одномерные
D01/D02/D03 не переписываются. Одинаковые **реализованные**3% pooled TEST
null тревог — ретроспективная ROC-сверка, не независимая калибровка.
Отдельный synthetic run показывает пороги из другого calibration sample.
Реальные24 выбранные тревоги/месяц не называются ложными тревогами.

Technical PASS не закрывает научный шлюз. Когорта выбрана ретроспективно
по полноте24месяцев; проверка future-value invariance не доказывает
историческую доступность данных и не проверяет все варианты пропусков.
Holdout отсутствует. h12 старой сезонной модели остаётся UNSUPPORTED;
новый национальный benchmark имеет отдельный протокол.

## Новые external checks

Команда также повторяет зафиксированные R10 national H12 и Flood legal
cohort с полной сверкой новых метрик с эталонами.220824 national прогнозов
проверяются на скалярное совпадение и изменение будущих raw/national
значений. Flood ожидаемо PARTIAL:1 точная идентичность и6 blocked,
не полная научная проверка. Сохраняются оба отдельных stage-log.

Загрузка **нового текущего** national snapshot:
`python data/download_sberindex_national.py --out <NEW-directory>`.
API может измениться; иной SHA требует нового протокола, а не замены
старого эталона ради зелёного PASS. Паспорт опубликован в R10 run.

D05 дополнительно сравнивает base и extended **совместные** банки при
ровно3% общего реализованного TESTnull FA и отдельно при независимых
calibration thresholds. Расширение помогает coherent/ramp шокам и
ухудшает sparse/opposed. Это не универсальный новый default.

## Снимки в деле Радара

В дело владельца приложен приватный ZIP пяти точных входов. После
скачивания архива и подготовки scientific venv одна команда сама
проверяет/раскладывает snapshots, затем повторяет все ключевые прогоны:

```sh
make radar RADAR_BUNDLE=/path/to/radar-frozen-inputs-20261005.zip
```

SHA ZIP и каждого файла опубликованы в
`data/frozen/radar/bundle-manifest.json`. `radar_prepare.py` не ходит в
сеть: принимает локальный архив, разрешает только пять имён, проверяет
размеры, отказывает на изменённый вход и не перезаписывает существующий
иной файл. Сервис Фиксара может получить архив через штатный доступ к
материалу дела; credentials в репозитории отсутствуют. Публичный clone
всё ещё требует получения owner-archive или самостоятельного cache refit.
