# Воспроизведение досрочных расчётов 03.10.2026

Проверенная среда: Python3.13, pandas3.0.6, numpy2.5.3, pyarrow25.0.1, SQLite3.45.3. Для повторного обучения R9 также Prophet1.4.0. Используйте отдельное окружение и requirements-science.txt/requirements-r9.txt. Каждый output — новый run, готовые результаты не перезаписываются.

Исходные файлы Data Sense/словарь должны совпасть с SHA в отчётах. Raw данные и внутренние квитанции здесь не распространяются. Имена файлов: raw/sberindex-data-sense-2025/{8_consumption.parquet,2_bdmo_population.parquet,municipal_dictionary.parquet}; дополнительные internal FNS и market files указаны в параметрах отдельного анализа.

```sh
python shock-radar/src/r9_prophet_batch.py --help
python shock-radar/src/r9_pair_intervals.py --self-check
python shock-radar/src/r9_pair_intervals.py --predictions <audited-R9-predictions.parquet> --out <NEW-metrics.json>
python graph/fetch_official_oktmo.py --help
python graph/gm3_snapshot.py --self-check
python graph/gm3_snapshot.py --root <data-directory> --official <verified-OKTMO-directory> --out <NEW-snapshot-directory>
python economic-atlas/src/a6_external_descriptive.py --root <sberindex-2026-directory> --assignments <frozen-A6-assignments.parquet> --out <NEW-internal-metrics.json>
```

Для R9 итоговые predictions проверяются SHA b9726b7971c55e5c9f32cdfe439694ffc96f66d7b0c180725a7ad2dff68afe44 до расчёта интервалов. Воспроизведение из source с иной библиотекой/версией — другой run и требует отдельного аудита, нельзя отключать SHA guard для получения старого статуса. Публичная сводка опускает private execution paths и необязательный список всех territory bootstrap block labels; научные численные метрики сохранены.

SQLite SHA повторения может измениться из-за recorded_at. Source hashes, природные ключи, counts, missing/duplicate/asof queries должны совпасть. Это локальный исследовательский граф, не production service. Неизвестные доступность/права/единицы сохраняются явными, граф не подставляет юридических правопреемников.
