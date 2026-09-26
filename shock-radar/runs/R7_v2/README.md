# R7_v2: причинный last-value baseline + D01/D02/D03 (exploratory)

Scope: только `shock-radar/src/d02_d03_detectors.py` (note → `len(reg)`) и этот README.
Остальные computation не менялись, legacy-режим сохранён. `runs/R7` не трогается.
Тест уже открыт (R7 primary `runs/R7`, 2026-09-25 считается exploratory); R7_v2 — exploratory-v2.
Детекция, НЕ заявление о раннем предупреждении.

## Конвейер (выполняет оператор, в этой задаче прогон НЕ выполнялся)

```bash
cd deliverables/sberindex-2026/shock-radar
/tmp/sberindex-research-20260926/bin/python src/r7_causal_signal.py \
  --panel <raw8 8_consumption.parquet> \
  --registry events/registry.parquet \
  --outdir runs/R7_v2/signal
/tmp/sberindex-research-20260926/bin/python -c "
import json, pandas as pd
mf = json.load(open('runs/R7_v2/signal/manifest.json'))
ids = set(mf['registry']['eligible_ids'])
reg = pd.read_parquet('events/registry.parquet')
reg[reg['event_id'].astype(str).isin(ids)].reset_index(drop=True).to_parquet('runs/R7_v2/registry_eligible.parquet', index=False)
"
/tmp/sberindex-research-20260926/bin/python src/d02_d03_detectors.py \
  --cus runs/R7_v2/signal/signal.parquet \
  --registry runs/R7_v2/registry_eligible.parquet \
  --outdir runs/R7_v2 \
  --budget-mode monthly_causal
```

`--panel` — исходный raw8, `--registry` — исходные 60 (`events/registry.parquet`).
`registry_eligible.parquet` собирается строго из `signal/manifest.json: registry.eligible_ids`.

Self-checks кода (без данных, syntax-level):

```bash
/tmp/sberindex-research-20260926/bin/python -m py_compile src/d02_d03_detectors.py src/r7_causal_signal.py
/tmp/sberindex-research-20260926/bin/python src/d02_d03_detectors.py --self-check
/tmp/sberindex-research-20260926/bin/python src/r7_causal_signal.py --self-check
```

## Реальные замеры (joe, 26.09, вручную проверены)

- Сигнал: 287268 rows; ряды 12744 included / 396 excluded.
- Реестр: 60 total / 59 eligible; 1 ineligible — причину смотреть в аудите
  (`signal/manifest.json: registry.ineligible` + `signal/pretrain_audit.parquet`),
  недостающая единица здесь не перечисляется.

## Publication lag (assumed 2 months)

Метрики R7 — observation-clock only. Операционально:
`available = observed_month + 2`,
`operational_delay = reported_signed_delay + 2`.
Лаг assumed, не измерен.

## Провенанс

- Предшествующие source jobs: лимит max turns 30, exit 8.
- Code self-checks + реальный сигнал вручную проверены; job fully success НЕ заявляется.
- В этой задаче: computation run НЕ выполнялся, коммит НЕ делался, других файлов не менялось.
