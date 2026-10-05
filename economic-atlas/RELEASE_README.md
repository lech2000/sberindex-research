# Как открыть и проверить конкурсный пакет

1. Откройте site/atlas-20261005/index.html в браузере. Сервер и интернет не нужны. Начальная карточка — Орск. Переключите2023/2024 и пороги, откройте Тюмень, затем Курган и его соседей.
2. Прочитайте RELEASE_REPORT_2026-10-05.md, DATA_PASSPORT_RELEASE_2026-10-05.md и MUNICIPAL_STORIES_RELEASE_2026-10-05.md.
3. Все дополнительные проверки имеют отдельный каталог runs/A14_release_20261005. Основные A9–A13 не переписаны. browser_qa.json и RELEASE_VERIFICATION.json описывают фактически выполненные проверки.

## Воспроизведение

Используйте Python с версиями requirements-atlas.txt. Полный A9–A13: make atlas; нужны SBERINDEX_DATA_SENSE_DIR и SBERINDEX_MUNICIPAL_DICTIONARY. Предыдущий чистый повтор использовал уже установленные закреплённые версии; установка нового окружения в этом этапе не заявляется.

Полный новый дополнительный анализ:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 python3 src/atlas_release.py --inputs /path/to/existing-data-sense
python3 src/atlas_release_docs.py
python3 -m pytest --noconftest -p no:cacheprovider -q ../tests/test_atlas_release.py
make atlas-verify
```

Параметр --skip-refit только пересобирает демонстрацию и аудит на сохранённых composition_sensitivity.csv. Для воспроизведения исследования с нуля его не используйте. Папка inputs должна содержать2_bdmo_population,1_market_access,3_bdmo_migration,4_bdmo_salary,8_consumption иmunicipal_dictionary в форматеParquet, с SHA из A14 provenance. Эти существующие исходники находятся отдельно от конкурсного архива; контрольные суммы и официальные источники приложены. В репозитории нужны также базовые frozen panel/features/assignments и A7/A8/A12 артефакты; они включены в исследовательскую часть локального пакета.

Полный исправленный A8 (не нужен для доказательства равенства эффективных входов): runs/A14_release_20261005/run_a8_corrected.py с прежними CLI --wages/--employment/--a6v2/--panel/--data-sense-dir и отдельным --outdir. В этот день выполнен аудит влияния дублей, не полный новый A8.

Браузерная проверка: node site/atlas-20261005/qa.cjs с установленным Playwright и Chrome. На текущем Mac используется bundled Playwright; для другой машины задайте ATLAS_PLAYWRIGHT_MODULE. Проверки работают через file://; новых браузеров скрипт не устанавливает.

## Обзор за пять минут

Орск: рост уровня и внешние показатели, но отсутствие паводкового объяснения. Тюмень: ядро2024 и отсутствие ядра2023. Курган: та же пятёрка сопоставимых МО в двух годах. Затем откройте раздел состава: без Москвы переобученное ядро90% пусто. Закончите отрицательной проверкой2025 и воспроизводимостью.

Это локальный пакет для проверки. Веб-публикация и подача формы не выполнены. MQ остаётся содержательным вопросом; проект сообщения в MQ_QUESTION_FOR_OWNER.md.
