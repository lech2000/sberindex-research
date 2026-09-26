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
публичный OSM preview. Экономические результаты в template ещё не нанесены.
