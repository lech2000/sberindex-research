# R8 Science Review — TSFM Paired Evaluation

## Статус

Код подготовлен; реальные веса и данные недоступны в этом окружении.
Полный прогон требует `chronos-forecasting`, `torch` и доступ к
`8_consumption.parquet`.

Mac smoke (измерено локально 2026-09-28): 3/73524 tasks, 8 finite
predictions, MPS, pinned revision `29d808298f1a62493e7b9a5e08529d0d930fa189`.
No scientific gate pass.

## Назначение

Парное сравнение Chronos-T5-tiny (zero-shot) с Prophet и lastavailable
на **той же 171150-точечной маске** из `R8_prophet_full_20260927`.

## Запуск

```bash
python shock-radar/src/r8_tsfm_paired.py \
    --raw <8_consumption.parquet> \
    --paired-run shock-radar/runs/R8_prophet_full_20260927 \
    --outdir shock-radar/runs/R8_science_review \
    --model-revision <40-hex-commit-sha> \
    --device cpu \
    --batch-size 64 \
    --max-series 0
```

`--model-revision` **обязательно** 40-hex commit SHA (default `main` запрещён).
Требуется и при `--resume`, т.к. fingerprint хэширует raw, paired и revision.

Возобновление:
```bash
python shock-radar/src/r8_tsfm_paired.py \
    --resume \
    --raw <8_consumption.parquet> \
    --paired-run shock-radar/runs/R8_prophet_full_20260927 \
    --outdir shock-radar/runs/R8_science_review \
    --model-revision <40-hex-commit-sha>
```

Самопроверка (без Chronos): `python shock-radar/src/r8_tsfm_paired.py --self-check`

## Допущения

- Двухмесячный lag — **допущение** до подтверждения источником.
- Zero-shot Chronos-T5-tiny: веса заморожены, fit отсутствует, обучение
  на target/future невозможно по конструкции.
- Результат является ретроспективным на последней версии данных, а не
  подтверждённым историческим as-of прогнозом.

## Контроли

- Future-mutation probe: изменение будущих входов не меняет прошлый прогноз.
- Deterministic resume: повторный запуск с тем же fingerprint даёт
  идентичные прогнозы.
- Failed/missing predictions сохраняются; ни один прогноз не изобретён.
- Full status PASS требует: `len(paired_rows)==171150`, `len(all_results)==171150`,
  `n_tsfm_ok==171150` и ноль failures. Любое отклонение → NOT_PASS.
  Partial subset (все прогнозы finite, но маска < 171150) не может получить PASS.
- R8 gate_pass всегда false (научный gate остаётся открытым).

## Оптимизации

- **Batched inference**: задачи группируются по (series, origin), context
  tensors объединяются в батчи до `--batch-size` и Chronos вызывается
  один раз на батч (не на задачу). Для 73524 задач с `--batch-size 64`
  это ~1149 вызовов вместо 73524.
- **Horizon indexing**: прогнозы индексируются по `h-1` (horizon 1 →
  индекс 0, horizon 2 → индекс 1 и т.д.), а не по enumerate-порядку.
  Для непрефиксных горизонтов (например [2,3]) это критично.

## Выходы

- `predictions.parquet` — per-key прогнозы TSFM, Prophet, lastavailable
- `metrics.json` — MAE по общему маске, по горизонтам, partial/full статус
- `audit.json` — журнал ошибок, будущее-мутация контроль
- `manifest.json` — ревизия весов, SHA, версии, устройство, команда
- `checkpoints/` — per-(series, origin) атомарные чекпоинты