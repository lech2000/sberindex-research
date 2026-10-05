# Муниципальные бюджеты: инкремент локального графа, 04.10.2026

Проверено 04.10.2026 на Mac: SQLite backup исходного GM3, чтение verified
Parquet бюджетного пилота и фактические SQL из [queries.sql](queries.sql).
Квитанция — [coverage.json](coverage.json). Исходный GM3 snapshot не изменён.

В новую локальную копию добавлены **71 наблюдение из семи официальных годовых
отчётов за 2023–2024**: Орск, Курган, Ишим оба года, Тюмень 2023.
312 728 → **312 799 observations**; source releases 5 → 12. Все семь
бюджетных МО×год имеют существующие наблюдения расходов и населения.
Пять недостающих МО×год из фиксированной выборки сохранены явно в coverage,
не превращены в нулевые бюджеты. [Научный пилот](../../../economic-atlas/runs/Municipal_budget_pilot_20261004/README.md).

Таблица fiscal_cell сохраняет INTEGER копейки, source unit, locator, literal,
member SHA, печатную дату решения/публикации и статус геопривязки. Родительский
GM3 observation использует REAL; в текущих 71 суммах диапазон допускает точное
представление, проверено равенство INTEGER/REAL. Новые суммы >2^53 отвергаются.
Индикаторы имеют префикс fiscal_executed_, единица kopeck; региональные
агрегаты 2025 не выданы за бюджеты отдельных МО.

Выполненные проверки: FK violations=0, orphan fiscal lineage=0,
duplicate version naturalkey=0, integer-kopeck mismatch=0, fiscal synthetic=0.
Все 71 available_at неизвестны; eligible asof2024=0. Печатная дата публикации
не перенесена в historical availability. Исторические границы остаются
unverified; новых юридических связей правопреемства нет.

Это локальный исследовательский граф. Production ingest и полные GM3/GM4
не объявлены завершёнными. Наблюдения пригодны для последующего описания
муниципальных историй; forecast input и economic scientific PASS отсутствуют.

## Воспроизведение

```bash
<venv-python> graph/municipal_budget_graph.py   --base <GM3_snapshot_20261003>/graph.sqlite   --base-receipt <GM3_snapshot_20261003>/coverage.json   --pilot economic-atlas/runs/Municipal_budget_pilot_20261004   --out <NEW-graph-run>
```

Сначала восстановить исходный [GM3](../GM3_snapshot_20261003/README.md), если
его локальной БД нет. SHA базы проверяется до и после добавления. Код пишет
только новую БД; исходная открывается mode=ro. SHA полученной копии зависит
от recorded_at, но входные SHA, ключи и SQL results должны совпадать.
Сама БД с исходными организаторскими данными хранится вне Git.
