# Радар: четыре шага к завершению —05.10.2026

Проверено05.10.2026 на Mac, изолированная scientific Git-ветка:
полные прогоны, SHA входов/кода/эталонов, official SOWA download,
правовые тексты и publication metadata, строгая identity-сверка.
Технический результат отделён от научной приемки.

| Шаг | Фактическое состояние |
|---|---|
| Один make radar | Готов: R9-baselines,D04-bank,scalar/future audit,R10-H12,Flood partial,D05-joint; cache Prophet, без refit |
| Stouffer+GLR при одном бюджете банка | Реализовано и посчитано: target3% independent calibration + ровно3% pooled TESTnull ROC |
| Независимый паводок | Паспорта трёх актов и readiness-act собраны;1/7 strict legal matches,6 historical identity blocked; original PDF/приложения не получены |
| Национальный ряд и h12 |470 строк,94 месяца,73608 точных H12keys; new fixed growth benchmark COMPUTED_EXPLORATORY |

## Что заявлять

H12 lag1 MAE651,269 против1288,251 last-value и1109,523 cached Prophet;
снижение41,30% к Prophet на всех шести категориях. Без перекрывающегося
агрегата, дополнительная post-hoc диагностика:22,01%. Маркетплейсы
**хуже50,33%**, CI по продовольствию включает0. Шесть временных блоков,
нет unseen holdout; текущий national vintage2026 и unknown publication
lag не дают historicalasof-доказательства. Prophet не видел national
ряд, поэтому одинаковая информация пока не обеспечена.
[Все результаты и паспорт](../shock-radar/runs/R10_national_h12_20261005/README.md).

D05 total-bank FA3%, t5 amplitude4: coherent down recall70,20→94,25%,
ramp44,525→72,40%; opposed91,65→71,30%, sparse95,725→71,70%.
Все формы опубликованы. Подключение Stouffer/GLR даёт понятный компромисс,
а не всеобщее превосходство. Настоящие false alarms неизвестны.
[Совместный банк](../shock-radar/runs/D05_joint_bank_20261005/README.md).

Паводок: дата30марта — readiness в Оренбуржье,4апреля — emergency.
Акт Курганской области,8апреля,задаёт7territories режима ЧС.
Точный валидный городской match Курган1333;6district→okrug требуют
официального lineage. В Кургане апрель к ProfileSES все траты+5,36%,
общепит+23,34%; общего провала не видно. Нельзя именовать residuals
причинным эффектом или считать каждую территорию акта затопленной.
[Паспорта и результаты](../shock-radar/runs/Flood_legal_cohort_20261005/README.md).

## Для агентов и следующей ступени

1. Радар: получить historic national snapshot2022/2023 с verified release
   и дать Prophet тот же national exogenous input. Не подставлять actual
   future national regressor; его forecast должен использовать только cutoff.
2. Graph steward: официальный district2023→okrug2024 crosswalk для шести
   территорий из crosswalk.json, initial acts+appendices трех областей,
   отдельные списки фактического затопления. Соцсети не искать.
3. Куратор: принять этот отчет как завершение технических подшагов,
   не закрывать R8/R9 scientific gates; dispatch из source open_actions.
   Новый holdout/ground-truth остаются научными условиями, не системной ошибкой.
4. Отчет/лендинг: показать tradeoff D05, отрицательные категории H12 и
   partial flood статус. Старую seasonal H12 не объявлять реализованной.

Данные скачаны в разрешённой исследовательской области без отдельного
повторного запроса владельцу. Полные raw/cache локальны; Git содержит
паспорта,SHA,код,aggregate metrics. CC BY-SA именно для national dataset
не подтверждена: официальный footer требует упоминание СберИндекса.
Платформенные пакеты и production службы не менялись, deploy-lock не занят.

Воспроизведение: [инструкция](../repository-tools/RADAR_REPRODUCE.md).
На подготовленных пяти frozeninputs: `make radar PYTHON=.venv/bin/python`.
Это не чистый clone с автоматическим обучением Prophet.

GLR здесь — GLR-подобная trailing-window оценка общего направления;
при коррелированном AR-шуме пороги калибруются эмпирически,
точное iid likelihood-доказательство не заявляется.

[Техническая квитанция make](../shock-radar/runs/Reproduction_20261005/README.md):
exit0, все reference метрики совпали; научные шлюзы остаются открыты.
