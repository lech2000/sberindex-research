# R9: полный Prophet на парной маске — вычислительное задание

Начато 01.10.2026 после [пилота](../R9_prophet_pilot_20261001/README.md). Исполнитель: [`r9_prophet_batch.py`](../../src/r9_prophet_batch.py). Он сверяет полный набор eligible-строк со всеми четырьмя горизонтами базового расчёта, обучает Prophet только до соответствующего `origin`, сохраняет атомарную квитанцию на каждый ряд `(МО, категория)` и возобновляется после прерывания. Fingerprint включает SHA-256 исходного parquet, код, параметры и версию Prophet; несовпадение блокирует небезопасный resume.

Запуск на Mac:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python shock-radar/src/r9_prophet_batch.py \
  --raw /Users/sergey/projects/sberindex-research/data/raw/sberindex-data-sense-2025/8_consumption.parquet \
  --outdir /Users/sergey/projects/sberindex-research-jobs/R9_prophet_full_20261001
```

Повтор той же команды продолжает незавершённые ряды. `--max-series N` ограничивает новые ряды за один вызов для проверки. Оперативный статус — `progress.json` в каталоге задания; финальные `metrics.json` и `predictions.parquet` появляются после завершения. Каталог checkpoint не коммитится в Git. Итоговые метрики подлежат независимой проверке и публикации в репозитории.

Даже если весь расчёт завершится без ошибок, он остаётся техническим сравнением на исторической панели 2023–2024. Для научного закрытия R9 требуются датированный новый выпуск, проверенные `published_at/available_at`, заранее замороженный независимый holdout и интервалы. Вычислительный статус `computed` не означает `scientific PASS`.
