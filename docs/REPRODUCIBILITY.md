# Воспроизведение

Базовая проверенная среда научных расчётов: Python3.14.5, версии библиотек
в requirements.txt. Установите uv, создайте локальную среду; ключи/API не нужны.

```sh
uv venv --python 3.14.5
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python repository-tools/validate_repository.py
.venv/bin/python repository-tools/reproduce.py --self-check
```

Самопроверки запускают A4/A5/A6/R7signal/D02-D03/R8 на синтетических примерах.
Они проверяют формулы и временную причинность, а не достаточность конкурсного результата.

```sh
bash data/download_sberindex_2025.sh
.venv/bin/python repository-tools/reproduce.py --stage all
```

Загрузчик использует публичный Яндекс.Диск организаторов и проверяет каждый SHA.
Текущие дашборды могут меняться, поэтому download_sberindex_current.py не является
способом восстановить исторический vintage. Для A5/A6 используется включённая
замороженная panel_v1.parquet; паспорт и raw sourceSHA рядом. Для R7 нужны
8_consumption.parquet и сохранённый synthetic registry. A5 требует5_connection.parquet.
R8 использует сохранённые events/news_events.json и events/news_features.parquet.

Новые outputs — output/reproduced, архивные runs не перезаписываются.
Некоторые parquet/manifest bytes отличаются из-за даты запуска и версий writer;
сравниваются научные метрики, назначения, покрытия и параметры, а входы — поSHA.
LegacyR7 и R7_v2 не смешиваются. R7_v2 exploratory, тест уже раскрыт.

Прямые воспроизводимые команды дополнительно есть в runs/*/README.md и
R7_v2/operator_run_manifest.json. Стандартные модули имеют --help/--self-check.
TSFM f04 требует собственных весов/dependencies; полная конкурсная оценка R9/R10
и A7–A10 ещё не реализована. Продвинуть partial в PASS одной успешной самопроверкой нельзя.

Локальная презентация:

```sh
python3 -m http.server 8765
```

Откройте presentation/economic-atlas/landing/ или presentation/shock-radar/landing/.
Прежние HSE templates в */landing/ — исторический прототип; здесь для показа применяется
публичный OSM preview. Результаты на 03.10.2026 нанесены на оба presentation/лендинга; цвета карты по-прежнему являются географическим контекстом, не назначениями экономики.


Новые научные модули: `economic-atlas/src/a6_identities.py` и `shock-radar/src/r8_forecast_ablation.py`, оба черезF7b. Прямые команды воспроизведения в runs/A6_v2/README.md и runs/R8_v2/README.md; исходный reproduce.py --stage all воспроизводит прежний снимок, новыеv2 запускаются этими явнымикомандами.


27.09 добавлены `a6_threshold_review.py` и `r8_prophet_pilot.py` (F7b). Явные команды в новых runREADME. Prophet проверен в отдельнойPython3.13 среде с Prophet1.4.0/cmdstanpy1.3.0; его не следует устанавливать в среду базового evaluator без отдельной проверки совместимости. Пилотпо умолчанию32ряда; --max-series0 означает все, требует отдельного бюджета времени. А6 использует основнуюPython3.14.4 среду (точные версии вmanifest). reproduce.py --stage all автоматически эти новыеfollowup не запускает.


03.10: сезонная гипотеза и реальные официальные кейсы воспроизводятся отдельными CLI, не старым `--stage all`: [R9](../shock-radar/runs/R9_category_seasonal_20261003/README.md), [реестр/кейсы/охват](../shock-radar/runs/Official_cases_20261003/README.md). Проверены Python3.13.0 и `requirements-integration.txt`; модели Prophet повторно не обучались. Загрузчик официальных страниц требует системный curl, TLS остаётся включённым. Новые выходные директории обязательны; архивы не перезаписываются.
