# СберИндекс 2026 — исследования муниципальной экономики

Два направления конкурса: **Экономический атлас** (динамическая кластеризация)
и **Радар потребительских сдвигов** (прогнозирование и детекция).
Снимок исследований: **4 октября 2026**. Это рабочий исследовательский
репозиторий; финальная конкурсная работа ещё не готова.

| Направление | Последний подтверждённый переход | Сейчас | Следующая работа |
|---|---|---|---|
| [Атлас](economic-atlas/) | A7.S1 вычислен; A6 остаётся открыт | 1896 МО: SW/CH и S_Dbw (3 конечных / 2 математических NA), 210 синтетических контролей, бюджетный контекст | Итоговый отчёт; AVI/AVU/MQ SPEC_UNRESOLVED |
| [Радар](shock-radar/) | R8 завершён без научного PASS | Два сезонных окна и пилот с общей информацией: 120 рядов / 2640 fits; V3/банк/монитор только на синтетике | Итоговый отчёт и проверка спецификации пилота; новый holdout отдельно |

Статусы подтверждаются [живыми снимками действий](docs/evidence/sberindex-migration-cases/),
[квитанциями исследований](docs/evidence/) и [состоянием агентов](agents/progress.json).
**PASS технического этапа не означает победное качество.** Раннее предупреждение
в R7_v2 не подтверждено. Fixed-K расчёт A6 не доказывает рождения/исчезновения групп.

## Навигация

- [Итог переноса АТФ, допустимые находки и план завершения](docs/ATF_FINDINGS_AND_CLOSEOUT_2026-10-04.md).

- [S_Dbw завершён: полная маска A5, математические NA и независимая проверка](economic-atlas/runs/A7_SDbw_20261004/README.md).
- [Сезонный пилот с равной общей информацией:120рядов/2640fits](shock-radar/runs/R9_equal_information_pilot_20261004/README.md).
- [Аудит утечки, V3/банк/монитор и раннее сезонное окно](docs/findings/ATF_CLOSEOUT_20261004/source-audit.md).
- [Сезонная гипотеза: точная маска, CI и ансамбль](shock-radar/runs/R9_category_seasonal_20261003/README.md).
- [Официальные события, три истории МО и проверенный охват](shock-radar/runs/Official_cases_20261003/README.md).
- [Ускоренный рабочий график](docs/ACCELERATED_SEASONAL_PLAN_2026-10-03.md).

- [A6.3: 210 количественных контролей и исправление tracker](economic-atlas/runs/A6_frozen_controls_20261003/README.md).

- [Миграция, ЦБ и мобильность: результаты 03.10](docs/DATA_INTEGRATION_RESULTS_2026-10-03.md) и [команды воспроизведения](docs/INTEGRATION_REPRODUCE_2026-10-03.md).

- [Следующие задания на GitHub](docs/NEXT_STEPS.md), [состояние и ограничения](docs/STATE.md), [соответствие требованиям конкурса](docs/CONTEST_CHECKLIST.md).
- [Независимая научная проверка A6/R8](docs/SCIENTIFIC_EVIDENCE_REVIEW_2026-09-28.md) и [исполнимые задания исследователям и F7b](docs/SCIENCE_EXECUTION_TASKS_2026-09-28.md).
- [Научное завершение R8 без PASS](shock-radar/runs/R8_closeout_20260929/README.md), [квитанция закрытого пункта в ФиксАРе](docs/evidence/r8-closeout-case-20260929.json).
- [Методология Атласа на русском](economic-atlas/METHODOLOGY_RU.md), [лестница A0–A10](economic-atlas/research-ladder.md).
- [Методология Радара на русском](shock-radar/METHODOLOGY_RU.md), [лестница R0–R10](shock-radar/research-ladder.md).
- [Данные и происхождение](data/DATA_CATALOG.md), [воспроизведение](docs/REPRODUCIBILITY.md).
- [Научные работы](literature/), [перенесённые методы ATF](methods/ATF_METHODS_TRANSFER.md).
- [Граф муниципалитетов](graph/), [архитектура моделей](model-lab/ARCHITECTURE.md).
- [Публичные шаблоны презентации](presentation/), [необходимые ограничения лицензий](THIRD_PARTY_NOTICES.md).
- [Переезд из aiOS2](docs/MIGRATION.md), [интеграция с ФиксАР](integrations/fixar/README.md).

## Запуск

На проверенном научном runtime используется Python 3.14.5. Виртуальная среда:

```sh
uv venv --python 3.14.5
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python repository-tools/validate_repository.py
.venv/bin/python repository-tools/reproduce.py --self-check
```

Новые результаты пишутся в `output/reproduced/`; архивные `runs/` сохраняются.
Для полного расчёта A5/R7 сначала скачайте публичный пакет организаторов:

```sh
bash data/download_sberindex_2025.sh
.venv/bin/python repository-tools/reproduce.py --stage all
```

Подробные команды и пределы повторяемости — [REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md).
Ни GitHub, ни ФиксАР, ни LLM не нужны для научных самопроверок и расчётов.
Дополнительные TSFM-модели требуют собственных зависимостей и весов.

Лендинги с проверенными результатами и отдельной картой географического контекста можно открыть локально:

```sh
python3 -m http.server 8765
```

[Атлас](http://localhost:8765/presentation/economic-atlas/landing/),
[Радар](http://localhost:8765/presentation/shock-radar/landing/).
Карта показывает географический фон OSM 2021, а не результаты кластеризации или прогнозов.

## Конкурс

[Официальные условия](https://sber.ru/sberindex/konkurs_sberindex) проверены прямой
HTTPS-загрузкой 03.10.2026 (sources/contest-verification-20261003.json). Приём работ: 14.09–09.10.2026, результаты: 30.10.2026.
Подача владельцем через форму конкурса пока не выполнена. Наличие репозитория
не означает, что остальные требования уже закрыты. Организационные вопросы о
составе команды и подаче двух направлений отмечены отдельно в checklist.
