# repository-tools — standalone reproduction kit

This directory is the only thing added for the autonomous GitHub repo whose
root is `deliverables/sberindex-2026` itself. No existing module was changed.
All commands below run from the repository root:

```bash
cd deliverables/sberindex-2026
```

## Files

| File | Purpose |
|---|---|
| `reproduce.py` | Drives stages `a4/a5/a6/r7/r8/all` via checked subprocess calls of the existing CLIs. No hidden platform calls, no downloads, no network, no LLM, no credentials. |
| `validate_repository.py` | Stdlib-only validator: `ast` parse of Python (except archived/external), JSON validation, SHA-manifest field checks (recompute opt-in), actions shapes, progress A6/R8 mentions, closed-source flags for atlas-05 / radar-07, project config seeds, evidence paths. |
| `requirements-science.txt` | Pins copied verbatim from `shock-radar/runs/R7_v2/requirements.txt` (numpy, pandas, scipy, pyarrow, scikit-learn, networkx, …). |
| `requirements-tsfm.txt` | Optional TSFM runtime kept separate and intentionally unpinned (no pinned TSFM versions exist in the archived R4 run). Not needed for a4/a5/a6/r7/r8. |
| `selftest.sh` | Wrapper: `--help` probes plus compile checks; runs code `--self-check` only when the scientific runtime is present, otherwise compile-only. Never installs or alters the environment. |
| `README-tools.md` | This file. |

## Self-checks (no data, no downloads, no LLM)

```bash
python3 repository-tools/reproduce.py --self-check
python3 repository-tools/reproduce.py --self-check --stage a5
python3 economic-atlas/src/a4_metrics.py --self-check
python3 economic-atlas/src/a5_graph.py --self-check
python3 economic-atlas/src/a6_temporal.py --self-check
python3 shock-radar/src/r7_causal_signal.py --self-check
python3 shock-radar/src/d02_d03_detectors.py --self-check
python3 shock-radar/src/r8_news_audit.py --self-check
```

`--self-check` in `reproduce.py` runs, in order: `a4_metrics.py`,
`a5_graph.py`, `a6_temporal.py`, `r7_causal_signal.py`,
`d02_d03_detectors.py`, `r8_news_audit.py`, each with `--self-check`.
`--stage a5|a6|r7|r8` restricts the wrapper to that stage's module(s).

## Actual runs (explicit paths, read-only archived runs)

Default outputs go to the independent directory `output/reproduced`
(never inside `economic-atlas/runs` or `shock-radar/runs`, which are
read-only; the driver refuses an `--output-root` inside them).
A `reproduce_manifest.json` with the exact commands is written there.

```bash
# everything (needs: panel_v1, 5_connection, 8_consumption, registry, news files)
python3 repository-tools/reproduce.py --stage all --output-root output/reproduced

# A5: frozen panel + distance table
python3 repository-tools/reproduce.py --stage a5 \
  --panel economic-atlas/data/panel_v1.parquet \
  --distance data/raw/sberindex-data-sense-2025/5_connection.parquet \
  --output-root output/reproduced

# A6: frozen panel from this repo (no distance input)
python3 repository-tools/reproduce.py --stage a6 \
  --panel economic-atlas/data/panel_v1.parquet \
  --output-root output/reproduced

# R7: raw8 panel + registry -> signal, then eligible registry, then detectors
# (budget-mode monthly_causal, budget 24, cooldown 3, matching the R7_v2 operator run)
python3 repository-tools/reproduce.py --stage r7 \
  --panel-raw8 data/raw/sberindex-data-sense-2025/8_consumption.parquet \
  --registry shock-radar/events/registry.parquet \
  --output-root output/reproduced

# R8: news audit on explicit events + features (cutoff 2024-12-31)
python3 repository-tools/reproduce.py --stage r8 \
  --news-events shock-radar/events/news_events.json \
  --news-features shock-radar/events/news_features.parquet \
  --output-root output/reproduced

# A4: kmeans vs agglomerative agreement from archived JSONs
python3 repository-tools/reproduce.py --stage a4 \
  --kmeans economic-atlas/runs/A4/kmeans.json \
  --agglomerative economic-atlas/runs/A4/agglomerative.json \
  --output-root output/reproduced
```

R7 detail: `r7_causal_signal.py` writes `signal/` (signal.parquet +
manifest.json); the driver then filters `events/registry.parquet` down to
`manifest.json: registry.eligible_ids` into `registry_eligible.parquet`
(same rule as `runs/R7_v2/operator_run_manifest.json`), and finally runs
`d02_d03_detectors.py --cus <signal.parquet> --registry
<registry_eligible.parquet> --budget-mode monthly_causal --budget 24
--cooldown 3`. R8 is an as-of audit (never a gate PASS) with explicit
`--news-events` / `--news-features`.

## Validation (stdlib only)

```bash
python3 repository-tools/validate_repository.py
python3 repository-tools/validate_repository.py --check-hashes
python3 repository-tools/validate_repository.py --report validation-report.json
bash repository-tools/selftest.sh
```

## Limitations (verified 2026-09-26, not assumed)

- `economic-atlas/runs/A3/` does not exist in this snapshot, so there is no
  `runs/A3/panel_frozen.parquet`. A5/A6 default to the frozen
  `economic-atlas/data/panel_v1.parquet` included in the repo.
- `data/raw/sberindex-data-sense-2025/` in this checkout contains only
  `municipal_dictionary.parquet`. `5_connection.parquet` (A5 distance) and
  `8_consumption.parquet` (R7 panel) are gitignored downloads and are
  absent: the validator lists them as missing-optional, and actual A5/R7
  runs need them placed at the paths above (no downloading is performed).
- Archived `runs/` directories are inputs only; reproduced outputs always
  land under `--output-root` (default `output/reproduced`).
- The validator checks shapes and presence only: it never asserts how many
  experiments ran, how many actions exist, which status enum value an entry
  has, or any scientific result. Reported numbers (ARI/NMI targets, budgets,
  counts) are read from the archived manifests at run time, never invented.
- No network, no credentials, no GitHub calls, no commits, no deploys.
  If the scientific runtime (numpy/pandas/…) is unavailable,
  `selftest.sh` falls back to `--help` + byte-compile checks and reports
  `SKIP` instead of failing.

## A7.S1 — воспроизведение S_Dbw, 04.10.2026

[Протокол и команды](../economic-atlas/runs/A7_SDbw_20261004/README.md): сохранённые A5 features/assignments, без переобучения; семь fixtures и независимый scalar audit. Три конечных значения/два NA; AVI/AVU/MQ SPEC_UNRESOLVED. Запускайте в новый `output/reproduced/A7_SDbw`; входы/SHA не менять.

## Competitive experiments, 2026-10-04

Original scientific CLIs and independent audits, with explicit new output directories:

- [D04 signed/unsigned/covariance comparisons](../shock-radar/runs/D04_multicategory_20261004/README.md).
- [Strong growth/SES forecasts and equal-information pilot](../shock-radar/runs/R9_strong_baselines_20261004/README.md).
- [Three budget/migration/consumption stories and frozen threshold sensitivity](../economic-atlas/runs/Municipal_stories_20261004/README.md).

The historical Prophet cache is an input to the comparison, not another fit.
All full-mask exclusions are published; independent holdout and economic truth remain unverified.
