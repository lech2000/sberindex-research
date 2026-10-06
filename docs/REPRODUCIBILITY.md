# Повторить результаты Атласа и Радара

Проверено 06.10.2026 на Mac: свежий локальный клон commit4658266, два новых окружения, make atlas/radar/atlas-radar завершены успешно. [Полные журналы и SHA](evidence/findings-closeout-20261006/README.md). Это технический повтор тем же оператором; новый holdout и внешняя научная рецензия отдельно не заявляются.

## Подготовить входы

Репозиторий PRIVATE: сначала получить разрешённый доступ. Исходные расходы и private forecast cache предоставляются отдельно, публичная страница отчёта не является полным входным комплектом. Для Радара нужен owner ZIP из дела либо точные пять файлов data/frozen/radar/manifest.json; для Атласа также население и словарь, проверяемые economic-atlas/frozen_inputs.json. Raw не скачивается и не заменяется скрыто во время повтора. Иной SHA останавливает запуск.

## Создать отдельные окружения

~~~sh
uv venv --python 3.14.4 .venv-atlas
uv pip install --python .venv-atlas/bin/python -r economic-atlas/requirements-atlas.txt
uv venv --python 3.13.0 .venv-radar
uv pip install --python .venv-radar/bin/python -r repository-tools/requirements-science.txt
~~~

Новые среды06.10: Atlas pandas2.3.3/networkx3.6.1; Radar pandas3.0.6/networkx3.7. Общие numpy2.5.3/pyarrow25.0.1; полные версии в журналах. Все вычисления выполняйте в новой копии: make atlas перезаписывает только свои генерируемые A9–A13 выходы. Эталон freeze-regression повторно не выполняется.

## Три команды

~~~sh
export SBERINDEX_DATA_SENSE_DIR=/path/to/existing/sberindex-data-sense-2025
export SBERINDEX_MUNICIPAL_DICTIONARY=/path/to/existing/municipal_dictionary.parquet
make -C economic-atlas atlas PYTHON="$PWD/.venv-atlas/bin/python"
make radar PYTHON="$PWD/.venv-radar/bin/python" RADAR_OUT=/path/to/new-radar-output
make atlas-radar PYTHON="$PWD/.venv-radar/bin/python" JOINT_DATA_SENSE="$SBERINDEX_DATA_SENSE_DIR" JOINT_OUT=/path/to/new-joint-output
~~~

При необходимости передайте RADAR_RAW/R9/PILOT/DICTIONARY/NATIONAL как описано в [одном make radar](../repository-tools/RADAR_REPRODUCE.md). Полные входы/SHA, новые результаты и stage-logs сохраняются отдельно. Atlas сравнивает 19 разбиений с ARI=1 и эталонные значения; Radar — MAE, семь таблиц и тесты будущего; совместный опыт — 36 строк. SHA исходников и замороженных входов проверяются отдельно от численных допусков.

## Дополнительная сезонная сверка R8

~~~sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv-atlas/bin/python shock-radar/src/r8_seasonal_followup.py --repo "$PWD" --out output/r8-new-repeat --protocol shock-radar/runs/R8_seasonal_followup_20261006/protocol.json
~~~

Нужны исходный raw и два сохранённых R8 forecast cache по SHA протокола. Скрипт переносит фиксированные сезонные формулы, проверяет точные ключи и доступность истории; архивный decision.json не меняет. Все маски и пропуски публикуются; h3 неопределён.

## Что повторяется и что остаётся фиксированным

Простые модели, детекторы и совместные формулы пересчитываются. Prophet/Chronos используются из frozen cache; полного повторного обучения нет. Путь установки Prophet дополнительно проверен в третьей новой Python3.13 среде: Prophet1.4.0/cmdstanpy1.3.0, одно реальное обучение через существующую функцию, три конечных прогноза. Это проверка установки/исполнения, не замена бенчмарка.

Тест изменения будущих значений проверяет формулы, а не реальный historical available_at. Повтор просмотренного окна не превращает результаты в независимое научное доказательство. Практические выводы и области применения — [общий итог](RESEARCH_FINDINGS_2026-10-06.md). Ранние инструкции сохранены в датированном архиве; они не являются текущим порядком приёмки.
