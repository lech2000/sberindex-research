# F7b request — Radar forecast contract reconciliation

Prepared 2026-10-07 on Mac by reading frozen protocols/metrics, checking SHA and exact calendar arithmetic (audit.json). This is a concrete request for fixar-devops, not an executed platform code change.

Problem: shock-radar/protocol/forecast_contract.yaml still says prophet_full_panel: pending, uncertainty_intervals: pending and baseline_metrics.prophet/global_boosting/tsfm_chronos2 planned. Those legacy fields disagree with audited R9 computation and make completed negative results look unexecuted. The existing proposed1/2/3 block must be retained as historical planning and separated from contest h1/3/6/12.

Requested semantic changes, new dated contract revision:

- Preserve original R0 metadata as historical; create current_revision date2026-10-07 and historical_asof_verified=false, independent_holdout=false, scientific_pass=false.
- Set official contest horizons [1,3,6,12], historical_r0_proposed [1,2,3]. Distinguish actually evaluated lag0 retrospective benchmarks from lag2 assumption; do not change their stored metrics or claim lag2 MAE.
- Replace pending R9 full-panel/interval fields with paths and SHA from audit.json. Status technical_run_complete_with222_insufficient_train_exclusions. Common rows h1=73728,h3=73656,h6=73578,h12=73608; excluded0/6/0/216.
- For actual six origins per horizon, record train months h1=18..23,h3=16..21,h6=13..18,h12=7..12. Targets July–December2024. Separate no-lookahead observation cutoff from unverified availability/vintage.
- Calendar feasibility with minimum12 train observations, complete calendar upper bounds: lag0 origins12/10/7/1, lag2 origins10/8/5/0. Per-series missingness further reduces masks. H12 seasonal with minimum12 history and lag2 is unsupported; do not erase the distinct short-history/national exploratory H12 experiments.
- Track two separate national pilot entries. Regressor pilot 120series/720rows/1452fits: national_yoy598.091665 vs national_prophet946.142795; conditional pilot120series/114MO/720rows/2160fits: national_yoy679.746135 vs conditional_linear1707.224403. Different series selection/masks/configurations, no pooled MAE or percent.
- F04 actual model: amazon/chronos-t5-tiny revision29d808298f1a62493e7b9a5e08529d0d930fa189. Chronos-2 not executed; TimesFM not executed. Legacy R3/R5 invalidated. Bounded F03 and negative controls executed, W01 unexecuted.
- Keep closed independent-test gate with prerequisites: new unseen temporal holdout, proven historical releases/vintage and frozen model choice. Unknown native unit remains unverified.

Acceptance: parse contract; assert four contest horizons, correct origins/exclusions, no pending fields for completed R9, exact distinct pilot IDs/model IDs, false scientific/asof/holdout flags and historical R0 preserved. Review by fixar-devops/F7b; deployment only with approved exact candidate and deployment lock if runtime contract is consumed. No new fits required.

Frozen proposed semantic contract: forecast_contract.proposed.json. Its full bytes/SHA are in artifact-manifest.json; it extends legacy YAML rather than overwriting historical R0. Convert reviewed fields into a new current revision through F7b.
