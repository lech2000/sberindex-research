# R8: as-of аудит новостных событий (НЕ прогноз, НЕ гейт)

Scope: F7b only. Рабочая область — `shock-radar`; `r7`/`d02_d03_detectors` не трогаются.
Скрипт: `shock-radar/src/r8_news_audit.py`. Real-data прогон в рамках этой задачи НЕ выполнялся, коммит НЕ делался.

## Входы

- `events/news_events.json` — 64 news events (заявляется задачей; точное число фиксирует `news_audit.json` при прогоне).
- `events/news_features.parquet` — 3380 news_features (заявляется задачей; точное число фиксирует скрипт как `news_features_rows`).
- Прогнозы НЕ строятся и НЕ выдумываются: `forecast_metrics` всегда `null`.

## Запуск (оператор, вне этой задачи)

```bash
cd deliverables/sberindex-2026/shock-radar
python3 src/r8_news_audit.py \
  --news-events events/news_events.json \
  --news-features events/news_features.parquet \
  --cutoff 2024-12-31 \
  --outdir runs/R8
```

Self-check на игрушечных датированных событиях (future/duplicates/wrongtopic/ambiguouscity), без входных файлов:

```bash
python3 src/r8_news_audit.py --self-check
```

## Правила аудита

- `strict_available = max(published_at, first_seen_at)`: отдельного проверенного immutable archive `available_at` в данных НЕТ.
- `updated_at` для исторической целостности НЕ используется; его достоверность — `unknown`.
- Cutoff исключает future (`strict_available > cutoff`) и unknown (нет даты).
- Дедуп по `(url, content_hash)`; дубликаты — в карантин.
- География: `city` с >1 `tid` — ambiguous audit (карантин, без молчаливого выбора); `region` используется явно как регион, precise city из него НЕ выводится.
- Топик: `natural_disaster` на поздравлениях/профилактике/инструктажах/учебных рейдах/тренировках/готовности/рекомендациях — карантин как `suspected_topic_error` БЕЗ silent relabel (исходный топик сохраняется).

## Выходы (`runs/R8/`)

- `news_audit.json` — eligible/excluded, правило availability, coverage counts, checks; `forecast_metrics: null`.
- `quarantined.json` — элементы карантина с причинами, исходные topic/geo сохранены.
- `asof_features.parquet` — только прошлое: колонки `published_at`/`first_seen_at`/`strict_available_at` (+ `url`, `territory_id`, `ym`, `topic_original`, `geography_level`).
- `metrics.json` — общий: `status = PARTIAL_NOT_GATE_PASS`, `gate_pass = false`, `completed_components = [asof_audit, temporal_controls]`, `pending_components = [causal paired forecasting, ablations, calendar, strict lag, shuffle, geography reviewed]`; `news_only_evaluation = NA` (аудит покрывает только as-of availability/coverage новостей, парной прогнозной цели на этом этапе нет).

## Инвариантность и контроли

- Prefix invariance: append будущих статей и правки после cutoff не могут менять прошлые фичи (ассерт внутри скрипта).
- Shuffle-control — только диагностический: возвращает evidence (checksum'ы, seed), НЕ performance claim.
- 0 eligible — валидный аудит, а не PASS R8. PASS запрещён конструктивно при любом исходе.

## Провенанс

Скрипт сохраняет: входы + SHA256, `code_sha256`, `versions` (python/pandas/pyarrow/numpy), `command`, `run_utc` (дата), `git_commit`.
