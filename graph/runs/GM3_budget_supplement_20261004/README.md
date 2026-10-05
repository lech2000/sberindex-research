# GM3: бюджетное дополнение — 04.10.2026

В новую локальную SQLite реально добавлены 77 наблюдений из двух источников:
312 799 → **312 876**. Третья выгрузка (3 суммы без МО) исключена из графа.
Включены 22 H1-факта, 22 снимка плана, 21 годовой бюджетный показатель Тюмени
и 12 социально-экономических значений. Валютных ячеек 71, других 6.

Подробная provenance, точные целые копейки и исходные разрешения хранятся в
budget_supplement_cell; проценты и тыс. м² имеют отдельные единицы. Plan/H1/annual,
функциональная классификация и муниципальные программы разделены явно.
Округлённые числа PDF имеют provenance_class=source_estimate; исходные табличные
факты/задокументированные планы — observed. Синтетических строк не добавлено.

Выполнены SQL из queries.sql: FK/orphans/duplicates/расхождения целых копеек=0.
Исходная SQLite не изменена. Старые 71 fiscal_cell и годовое coverage **7/12**
сохранены. Новый available_at не придуман, asof_2024 допускает 0 новых строк.
URL неизвестен: dataset_release использует urn:sha256, а не выдуманный адрес.
Это не production ingestion и не завершение полного GM3/GM4.

```sh
python graph/budget_supplement_graph.py \
  --base /path/to/prior-municipal-budget/graph.sqlite \
  --base-receipt /path/to/prior-municipal-budget/coverage.json \
  --supplement economic-atlas/runs/Budget_owner_supplement_20261004 \
  --out /path/to/new-graph
```

База, исходники и приватные квитанции находятся вне Git. Здесь опубликованы
код, фактический coverage.json, source checksums и SQL. Проверено 04.10.2026
на Mac, реальным SQLite backup/INSERT/SELECT и SHA исходной БД до/после.
