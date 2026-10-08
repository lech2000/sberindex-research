# F7b: M2/M3 promised geometry — geometry-v3.1

Source actions: `act_b6659ef0c8e049b1`, `act_a1e77e09fb854cca`; A6.3 `act_63eabe3fd8aa4770` is related but its missing historical prior budget is not repaired retroactively. Scientific repository base: `3bc0f36c4fdae32980ad49fdf307c9b9aafde805`. This is a scientific code patch; it does not change production agent instructions or packs.

Apply only the new files in the supplied patch after checking the exact base and SHA. Keep `a6_identities.py`, `a6_frozen_controls.py` and all previous run artifacts byte-identical. Do not redirect current registry/case evidence to new method results until review and acceptance. No secret, paid model, Muse, n8n, background service, KB or live-case change is part of this patch.

## Changed meaning

For member count ≥10 use sample covariance with all off-diagonal terms; covariance eigenvalues are floored by the predeclared absolute/relative floor, and every repaired spectrum is audited. This is an ellipsoid, not a sphere with another name. For <10 members use a documented isotropic sphere. Full Gaussian Bhattacharyya overlap uses the covariance matrices, stable determinants and solves. RMS remains a diagnostic, never the M3 cutoff.

M3 tests member Mahalanobis distance **strictly <2.5**, geometric containment **strictly >0.60** and member composition **strictly >0.60**. Current children are tested in previous parent geometry; previous parents are tested in current child geometry. Split still requires no recognised single continuation and ≥2 children; merge requires ≥2 parents. Sensitivity grid remains 1.5/2/2.5 ×0.60/0.75 using strict inequalities.

Geometry changes also change overlap distributions. Therefore freeze a **new** empirical-2023 calibration; do not apply legacy sphere T/M/Tc. T=q95 cross-overlap, Tc=q50 cross-overlap, M=max(0,q05 paired own-minus-best-competitor overlap). This paired gap is closer to the recognition margin than a difference of separate quantiles, but it still measures a known own cluster versus other clusters, while tracking ranks unknown candidates best-minus-second. It is not economic event validation. Bootstrap remains 200 per eligible monthly cluster, same seed and real 2023-only frozen scaler. 2023 labels/threshold application are retrospective.

The source-scientific promises did not specify an ellipsoid estimator, singular-covariance policy, numerical tolerance or new error budget. These are explicit proposed protocol choices fixed before the new computations; F7b review must evaluate them rather than treating them as an externally agreed scientific standard.

## Files and interface

- `src/a6_geometry_v3.py`: separate tracker/replay CLI; original runner stays intact.
- `src/a6_geometry_controls_v3.py`: anisotropic fresh-seed worlds, frozen evaluator, separate oracle/unsupervised budgets and honest PASS/FAIL/INCONCLUSIVE status.
- `tests/test_geometry_v3.py`: anisotropy, ≥10 threshold, singular/nonfinite covariance, independent Gaussian formula, affine overlap, strict Mahalanobis/60% split and merge boundaries, wrong member composition, birth/status consistency, prefix invariance, calibration future invariance and missing-suite rejection.
- `protocol/geometry-v3-20261007/*`: original source promises, versioned prior protocol and this handoff.

Use the existing Python with numpy/pandas/scipy/sklearn/pyarrow/pytest. No installation is authorised or required here. Set BLAS/OMP threads to1. All output directories below must be new and absent; pre-existing directories cause failure.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 -m pytest -q economic-atlas/tests/test_geometry_v3.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 economic-atlas/src/a6_geometry_controls_v3.py --self-check --atlas-src economic-atlas/src
# Conditional geometry replay: same real panel and archived labels, no new fit.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 economic-atlas/src/a6_geometry_v3.py \
  --panel economic-atlas/data/panel_v1.parquet \
  --archived-assignments economic-atlas/runs/A6_v2/assignments.parquet \
  --outdir output/A6_geometry_v3_replay --seed 20260926
# Fully fresh monthly K selection/fits; same original real panel, no economic holdout.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 economic-atlas/src/a6_geometry_v3.py \
  --panel economic-atlas/data/panel_v1.parquet \
  --outdir output/A6_geometry_v3_fresh --seed 20260926
# 210 new configurations, new real2023 thresholds. Known ontologies, not external holdout.
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 economic-atlas/src/a6_geometry_controls_v3.py \
  --atlas-src economic-atlas/src \
  --calibration output/A6_geometry_v3_replay/calibration.json \
  --out output/A6_geometry_v3_controls
```

## Evidence and remaining acceptance

The component tests must pass; real source hashes and exact archived/full-fit keys must be checked; 2023 calibration must be reproduced independently without any 2024 input; covariance/repair audits must survive output and reload; all 210 configurations must be present; main M×1 budgets must be checked separately for oracle and unsupervised. Pooled empirical error thresholds in protocol.json are proposed engineering acceptance targets for this specified suite, not population error guarantees or independent scientific PASS. Bootstrap confidence intervals are descriptive. M±25% is sensitivity, not a selection grid. Any failed budget remains FAIL; do not alter worlds, M, regularisation or matching until the suite passes. A change would require a new prospectively fixed protocol and run with visible known-results disclosure.

A failed/INCONCLUSIVE suite can still establish a correctly implemented method; it cannot establish accepted detector performance. Keep M2/M3/A6 scientific acceptance open unless every requested component and the new declared acceptance are actually satisfied. The old A6.3 action's request for a budget before its historical run remains unmet; this new protocol belongs to a new experience and does not backdate acceptance. Economic identities, real split/merge, source vintage and historical crosswalk remain unproven regardless of synthetic status. Runtime source revisions, component receipts, exact real replay and synthetic outcomes are listed in the delivery receipt outside the patch.
