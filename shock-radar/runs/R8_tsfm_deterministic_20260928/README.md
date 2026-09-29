# Детерминированный полный Chronos, 28.09.2026

Компактная копия завершённого Mac MPS прогона. Веса `amazon/chronos-t5-tiny`
закреплены ревизией `29d808298f1a62493e7b9a5e08529d0d930fa189`, seed
`20260928`; код `shock-radar/src/r8_tsfm_paired.py` совпадает с SHA-256 в
`metrics.json`. Все 73 524 задачи дали 171 150 прогнозов без ошибок.
`predictions.parquet` имеет SHA-256
`17ba7ea03f01fb7b67142b6ebb339decd2cb37cc85796dc46be8da1400f2a676`.

Отдельные 73 524 checkpoint JSON (около 287 МБ) остаются в исходном runtime
каталоге Mac `shock-radar/output/R8_tsfm_deterministic_20260928/checkpoints`;
их счёт и статусы проверены при расчёте. В Git сохранены прогнозы, метрики,
аудит, fingerprint, progress и manifest для независимого пересчёта. Исходный
сырой файл расходов проверяется по SHA-256 из манифеста и не копируется сюда.

`metrics.status=PASS` означает завершение вычисления. `gate_pass=false`:
научный результат R8 оценивается отдельно в
[`../R8_closeout_20260929/README.md`](../R8_closeout_20260929/README.md).
