# Экономический атлас: A9–A13 (05.10.2026)

Результаты описательные. Новые данные2025 не использовались; четыре основные проверки существующего A8 отрицательны. Наличие индексов и технического воспроизведения не доказывает экономическую валидность типов.

## Что запускается

- A9:12 определений kNN-сети × окна A5/annual2023/annual2024; degree/connected components/geo overlap/temporal Jaccard/ARI sensitivity.
- A10:6 fixed-K методов при K3/5/8,5 seeds,20 common80% subsamples; Louvain natural K отдельно; годовые разбиения для cross-year.
- A11:SW/CH/DB/S_Dbw/AVI/AVU/ANUI/Q,12 graph sensitivity variants,300 label permutations per row,двунаправленная cross-year проверка; MQ:SPEC_UNRESOLVED.
- A12:36 config consensus K5, core tau0.90, sensitivity0.80/0.95, December2023/2024, паспорта только ядер,1000 region bootstrap repetitions.
- A13:проверка входов/протоколов/receipts, независимый от расчётной команды regression baseline, чистое повторное выполнение.

## Окружение и входы

Python>=3.11. Первое измеренное окружение:Python3.14.4; точные версии requirements-atlas.txt. Рекомендуемый отдельный venv:

```sh
uv venv --python 3.14 .venv-atlas
uv pip install --python .venv-atlas/bin/python -r requirements-atlas.txt
export SBERINDEX_DATA_SENSE_DIR=/path/to/existing/sberindex-data-sense-2025
export SBERINDEX_MUNICIPAL_DICTIONARY=/path/to/existing/municipal_dictionary.parquet
make PYTHON=.venv-atlas/bin/python atlas
```

Все7 SHA входов — frozen_inputs.json. Внутренние: A5 features/assignments/geographic edges; panel_v1; features/spec.yaml. Внешние: 2_bdmo_population.parquet (имеющийся набор2023–2024) и municipal_dictionary.parquet. Данные не скачиваются программой автоматически. Лицензии и происхождение — исходный data/manifest.json и frozen_inputs.json; словарь CC BY-SA4.0 по existing manifest, для population/contest data требуется supplied documentation. Эта локальная работа не разрешает дальнейшее распространение raw data.

Необязательная внешняя сверка Pattern задаётся SBERINDEX_PATTERN_REF; отсутствие отмечается pytest skip. Код Pattern/quizzes1 не копируется. Базовые тесты с population env включают ранее пропущенную проверку реальной панели; тесты работают без API/production.

## Команды

make atlas-check; make atlas-a9; make atlas-a10; make atlas-a11; make atlas-a12; make atlas-test; make atlas-verify.
`make atlas` последовательно исполняет check/tests/A9/A10/A11/A12/verify (порядок сохраняется при make -j). Полный повтор перезаписывает только generated artifacts новых A9–A12 run-каталогов, неизменные protocols сохраняются; используйте чистую копию для отдельно сохраняемого воспроизведения. Legacy A5/A7/A8 и исходные receipts не меняются.

`make atlas-freeze-regression` использовался один раз ПОСЛЕ первого расчёта; повторная запись эталона запрещена. expected_metrics.json — regression baseline, не научная предрегистрация. При несовпадении counts/statuses/SHA или чисел за rtol1e-7/atol1e-8 проверка падает.19 исходных разбиений сравниваются с expected_partitions.parquet по ARI=1.

## Ограничения и чтение

Сетка36 не даёт вероятности истинной группы. Ядра условны на K5 и составе сетки; паспорта/CI не моделируют неопределённость выбора разбиения. S_Dbw имеет явную pair-union density convention и возвращает NA для нулевого знаменателя; MQ не подменяется модулярностью Ньюмана. AVI/ANUI могут предпочитать гиганты, K и размеры групп требуют отдельного контроля. Cross-year не заменяет независимый источник экономических исходов.

Точность модели, причинность, прогноз2025 и превосходство над другими участниками не заявляются. Негативные результаты помещены в run README вместе с положительными.

Протоколы: runs/A*_20261005/PROTOCOL.md; code/input/output SHA в provenance.json каждого run. A12 сохраняет исходныйv1 и amendmentv2 до успешного расчёта (точные дубли населения удаляются, конфликты блокируют). Разбор исходного задания: runs/A13_reproduction_20261005/TASK_REVIEW_2026-10-05.md.

Время полной чистой сборки и финальное число passed/skipped записаны в clean_reproduction_receipt.json после завершения проверки. Отчёт завершения: COMPLETION_REPORT_2026-10-05.md.
