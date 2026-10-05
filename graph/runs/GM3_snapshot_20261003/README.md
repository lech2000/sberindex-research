# GM3: первый наполненный локальный граф, 03.10.2026

Реальная SQLite БД в research-jobs (вне Git): 2660 внутренних муниципальных ключей, 5 source releases, 312728 observations (303126 расходов + 9602 населения по полу/всему возрасту). 16 source null и 16 нормализованных дублей total-age населения явно учтены. Вместе расходами и населением за 2024 покрыты 2027 ключей. Это наличие данных, не подтверждение юридических границ.

Исполненные SQL в queries.sql и квитанция coverage.json: orphan=0, duplicate version naturalkey=0, FK violations=0. Unknown availability=312728; eligible asof2024=0. Jan/Dec ОКТМО: при явно обозначенном half-open допущении 2165 active; 171 Jan-only и 15 Dec-only, neither=0. 183 строки декабрьского файла действуют с 2025 — не применяются к 2024 автоматически. Правопреемники не придуманы.

Это локальный исследовательский граф со связями по FK, а не выложенная production графовая служба. GM3 source остаётся OPEN: ещё нужны mobility/correct units/зарплаты/занятость, правила прав и version semantics. Graph GM4 проверяется на настоящих данных только в пределах перечисленных queries; полный инкрементальный контур не объявлен готовым.

Код/формат прошли F7b/MiMo Pro review; оператор исправил предложения агента: source_estimate для расходов, canonical dimensions NOT NULL (SQLite UNIQUE с NULL не защищает ключ), отсутствие ложного spending→population derived edge, recorded_at не равно downloaded_at, official dated diff по code_presence, а не расходам. Пример SQL агента с EXCEPT не использован. Уведомления/социальные каналы не собирались.

Воспроизведение: `python graph/gm3_snapshot.py --self-check`, затем `python graph/gm3_snapshot.py --root <data directory> --official <GM2_verified directory> --out <NEW directory>`. SHA всех входов и БД сохраняются. Не перезаписывать готовый run. DB SHA может меняться из-за recorded_at нового повторения; source hashes/keys/queries/coverage должны совпадать. БД/сырые строки/dated-diff хранятся внутренне до проверки прав публикации.
