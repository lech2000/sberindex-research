# R8 Science Review — TSFM Paired Evaluation

## Статус

Код подготовлен; реальные веса и данные недоступны в этом окружении.
Полный прогон требует `chronos-forecasting`, `torch` и доступ к
`8_consumption.parquet`.

Mac smoke (измерено локально 2026-09-28): 3/73524 tasks, 8 finite
predictions, MPS, pinned revision `29d808298f1a62493e7b9a5e08529d0d930fa189`.
No scientific gate pass.

## Важно: первый полный прогон был exploratory

Первый полный прогон TSFM на Mac (171150 прогнозных точек, 0 ошибок)
**не имел фиксированного RNG seed**. Chronos-T5-tiny использует
стохастическое сэмплирование (Monte Carlo), поэтому без `torch.manual_seed`
перед каждым батчем инференса разные прогоны на одних и тех же данных дают
различные прогнозы. MAE TSFM на том прогоне составил **938.9** — хуже,
чем Prophet (731.4) и lastavailable (880.2). Это не подтверждённый
научный результат, а exploratory замер, полученный при нефиксированном
стохастическом сэмплировании.

Независимый эксперимент с Chronos на MPS показал:
- `torch.manual_seed(20260928)` перед каждым предсказанием → идентичные
  выходы (max diff 0).
- Другой seed → diff 2058.576.

Это **стохастическая вариация инференса**, а не доказанная утечка данных.
Код до этого патча не фиксировал seed в fingerprint и не использовал
стабильную партизацию батчей, поэтому `--resume` мог дать другие прогнозы.

## Deterministic inference (F7b repair)

Начиная с этого патча, инференс детерминирован:

1. **CLI `--seed`** (default 20260928): записывается в fingerprint, manifest
   и metrics. Смена seed при `--resume` отклоняется проверкой fingerprint.

2. **Стабильная партизация батчей**: полный список задач (`tasks`)
   разбивается на фиксированные чанки по `batch_size` без фильтрации
   завершённых чекпоинтов и без ограничения `max_series` на членство
   в батче. Каждый чанк получает детерминированный seed от
   `sha256(global_seed + batch_index)` → 32-bit. Перед вызовом
   predictor/Chronos seed-ятся `random`, `numpy` (если доступен) и
   `torch.manual_seed` (если доступен). Батч, в котором все чекпоинты
   уже существуют, пропускается целиком.

3. **`--max-series` ограничивает сохранённые чекпоинты**, а не членство
   в батче или область инференса. Весь батч инферится; сохраняются
   только отсутствующие чекпоинты до достижения лимита. При `--resume`
   текущий батч переинфится с тем же seed, недостающие чекпоинты
   сохраняются, затем обработка продолжается.

4. **Эквивалентность resume**: если чанк частично содержит чекпоинты,
   переинференс всего чанка выполняется с тем же batch seed и тем же
   порядком контекстов. Сохраняются только недостающие чекпоинты;
   существующие проверяются на совпадение (или критический сбой).

5. **Future-mutation probe с re-seeding**: перед baseline, mutated и
   repeat вызовами seed-ятся `random`, `numpy` (если доступен) и
   `torch` (если доступен) фиксированным `probe_seed=42`.
   Проверяется равенство causal context до/после мутации и равенство
   выходов в пределах tolerance. Неудачный или отсутствующий probe
   блокирует `status=PASS` и `confirmatory=true`.

## Запуск

```bash
python shock-radar/src/r8_tsfm_paired.py \
    --raw <8_consumption.parquet> \
    --paired-run shock-radar/runs/R8_prophet_full_20260927 \
    --outdir shock-radar/runs/R8_science_review \
    --model-revision <40-hex-commit-sha> \
    --device cpu \
    --batch-size 64 \
    --seed 20260928 \
    --max-series 0
```

`--model-revision` **обязательно** 40-hex commit SHA (default `main` запрещён).
Требуется и при `--resume`, т.к. fingerprint хэширует raw, paired, revision и seed.

`--seed` (default 20260928) записывается в fingerprint; смена seed при
`--resume` отклоняется. Для воспроизводимости используйте одинаковый seed.

Возобновление:
```bash
python shock-radar/src/r8_tsfm_paired.py \
    --resume \
    --raw <8_consumption.parquet> \
    --paired-run shock-radar/runs/R8_prophet_full_20260927 \
    --outdir shock-radar/runs/R8_science_review \
    --model-revision <40-hex-commit-sha> \
    --seed 20260928
```

Самопроверка (без Chronos): `python shock-radar/src/r8_tsfm_paired.py --self-check`

## Допущения

- Двухмесячный lag — **допущение** до подтверждения источником.
- Zero-shot Chronos-T5-tiny: веса заморожены, fit отсутствует, обучение
  на target/future невозможно по конструкции.
- Результат является ретроспективным на последней версии данных, а не
  подтверждённым историческим as-of прогнозом.
- Стохастический инференс Chronos управляется фиксированным seed;
  без seed результаты невоспроизводимы.

## Контроли

- Future-mutation probe с re-seed: изменение будущих входов не меняет
  прошлый прогноз (probe_seed=42, causal context equality, tolerance).
  Неудачный/отсутствующий probe блокирует PASS и confirmatory.
- Deterministic resume: повторный запуск с тем же fingerprint и seed даёт
  идентичные прогнозы. Эквивалентность проверяется при переинференсе
  частично чекпоинтированных чанков.
- Fixed batch partitioning: стабильные batch_index → batch_seed,
  независимо от resume-точки.
- Failed/missing predictions сохраняются; ни один прогноз не изобретён.
- Full status PASS требует: `len(paired_rows)==171150`, `len(all_results)==171150`,
  `n_tsfm_ok==171150` и ноль failures и probe PASS. Любое отклонение → NOT_PASS.
  Partial subset (все прогнозы finite, но маска < 171150) не может получить PASS.
- R8 gate_pass всегда false (научный gate остаётся открытым).

## Оптимизации

- **Batched inference**: задачи группируются по (series, origin), context
  tensors объединяются в батчи до `--batch-size` и Chronos вызывается
  один раз на батч (не на задачу). Для 73524 задач с `--batch-size 64`
  это ~1149 вызовов вместо 73524.
- **Fixed partition**: батчи формируются из полного списка задач до
  фильтрации чекпоинтов, что обеспечивает стабильные batch_index.
- **Horizon indexing**: прогнозы индексируются по `h-1` (horizon 1 →
  индекс 0, horizon 2 → индекс 1 и т.д.), а не по enumerate-порядку.
  Для непрефиксных горизонтов (например [2,3]) это критично.

## Выходы

- `predictions.parquet` — per-key прогнозы TSFM, Prophet, lastavailable
- `metrics.json` — MAE по общему маске, по горизонтам, partial/full статус,
  seed в provenance
- `audit.json` — журнал ошибок, будущее-мутация контроль с probe_seed
- `manifest.json` — ревизия весов, SHA, версии, устройство, seed, команда
- `checkpoints/` — per-(series, origin) атомарные чекпоинты
- `fingerprint.json` — включает seed