# R9: ограниченный пилот Prophet на парной маске

Проверено 01.10.2026 на Mac по тому же `8_consumption.parquet` (SHA-256 `9833ddaaee7b2a182ed4cceeed16469031700ea87d508bd976150c6770ef8a61`), что и [базовый расчёт R9](../R9_baseline_20261001/README.md). Исполнитель — [`r9_prophet_feasibility.py`](../../src/r9_prophet_feasibility.py), [машинная квитанция](metrics.json), [прогнозы с ключами](predictions.parquet). Prophet 1.4.0: linear growth, 3 changepoints, сезонности выключены, без интервалов. Вход каждой подгонки ограничен месяцем `origin`; дата цели равна `origin+h`.

До вычисления ошибок взяты первые 10 рядов в каждой из шести категорий по SHA-256 от `(territory_id, category)`. Из 60 выбранных рядов 56 территорий дали 340 полных пар на каждом горизонте; на горизонтах сравниваются те же строки, что у last value, seasonal naive и train mean. Выполнено 966 подгонок Prophet без зарегистрированных ошибок; получено 1360 прогнозов.

| Горизонт | Пар | MAE Prophet | MAE last value | MAE seasonal naive | MAE train mean |
|---:|---:|---:|---:|---:|---:|
| 1 | 340 | 622.06 | 608.41 | 1237.17 | 1265.87 |
| 3 | 340 | 695.94 | 843.85 | 1237.17 | 1361.00 |
| 6 | 340 | 690.08 | 1090.46 | 1237.17 | 1513.91 |
| 12 | 340 | 980.34 | 1237.17 | 1237.17 | 1779.22 |

На этой выборке Prophet проиграл last value при `h=1` и показал меньшую MAE при `h=3/6/12`. Выборка нужна лишь для проверки реализации и затрат. Она не представляет весь массив; интервалы и независимый holdout отсутствуют. Единица поля `value` не подтверждена. **R9 остаётся OPEN / NO SCIENTIFIC PASS**. Следующая вычислительная задача — полный paired Prophet на всех строках маски R9 с checkpoint/resume и учётом времени; затем нужен новый датированный выпуск и заранее замороженный независимый тест.

Повтор: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python shock-radar/src/r9_prophet_feasibility.py --raw <8_consumption.parquet> --output-dir shock-radar/runs/R9_prophet_pilot_20261001 --per-category 10`. Сырые данные не публикуются.
