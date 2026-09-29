"""Assemble the R8 ablation ledger from verified saved run artifacts.

This script never converts a completed computation into a scientific PASS.
It records unavailable news and unverified historical release timestamps as
limits, not as zero effects or prospective forecast evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def assemble(root: Path, out: Path) -> dict:
    radar = root / "shock-radar"
    paths = {
        "paired": radar / "runs/R8_v2/metrics.json",
        "paired_audit": radar / "runs/R8_v2/audit.json",
        "prophet": radar / "runs/R8_prophet_full_20260927/metrics.json",
        "tsfm": radar / "runs/R8_tsfm_deterministic_20260928/metrics.json",
        "tsfm_audit": radar / "runs/R8_tsfm_deterministic_20260928/audit.json",
        "monthblock": out / "monthblock/metrics.json",
        "monthblock_manifest": out / "monthblock/manifest.json",
        "lag": out / "lag_sensitivity.json",
        "news": radar / "runs/R8/news_audit.json",
    }
    d = {key: read(path) for key, path in paths.items()}
    n = 171150
    assert d["monthblock"]["panel_mae"]["n_rows"] == n
    assert d["tsfm"]["counts"]["n_tsfm_forecasts"] == n
    assert d["tsfm"]["counts"]["n_failures_recorded"] == 0
    assert d["prophet"]["counts"]["n_prophet_forecasts"] == n
    assert d["lag"]["archived_lag2_exact_match_rows"] == n
    assert d["news"]["coverage"]["n_events_total"] == 64
    assert d["news"]["coverage"]["n_eligible"] == 0
    assert d["paired_audit"]["leak_controls"]["prefix_invariance_probe"]["max_abs_prediction_diff"] == 0
    assert d["tsfm_audit"]["leak_controls"]["future_mutation_probe"]["passed"] is True
    assert d["tsfm_audit"]["leak_controls"]["future_mutation_probe"]["max_abs_forecast_diff_repeat_fit"] == 0
    m = d["monthblock"]["panel_mae"]
    assert abs(m["prophet"] - d["prophet"]["common_mask_mae"]["prophet"]) < 1e-9
    assert abs(m["tsfm"] - d["tsfm"]["common_mask_mae"]["tsfm"]) < 1e-9
    assert abs(m["lastavailable"] - d["paired"]["panel_mae"]["lastavailable"]) < 1e-9
    assert d["monthblock_manifest"]["input"]["prophet_predictions_sha256"] == digest(
        radar / "runs/R8_prophet_full_20260927/predictions.parquet"
    )
    assert d["monthblock_manifest"]["input"]["tsfm_predictions_sha256"] == digest(
        radar / "runs/R8_tsfm_deterministic_20260928/predictions.parquet"
    )
    assert d["tsfm"]["provenance"]["code_sha256"] == digest(radar / "src/r8_tsfm_paired.py")
    assert d["tsfm"]["provenance"]["seed"] == 20260928
    assert d["tsfm"]["provenance"]["model_revision_actual"] == (
        "29d808298f1a62493e7b9a5e08529d0d930fa189"
    )

    rows = []
    def add(experiment: str, model: str, mask_n: int | None, mae: float | None,
            status: str, source: str, limit: str = "") -> None:
        rows.append({"experiment": experiment, "model": model, "mask_n": mask_n,
                     "mae": mae, "status": status, "evidence": source, "limit": limit})

    for model, key in (("lastavailable", "lastavailable"), ("seasonal_naive", "seasonal_naive"),
                       ("Prophet", "prophet"), ("Chronos-T5-tiny", "tsfm")):
        add("paired_forecast_assumed_lag2", model, n, m[key], "OBSERVED_RETROSPECTIVE",
            "R8_closeout_20260929/monthblock/metrics.json",
            "Historical available_at and revisions unverified; six target months only")
    for model, key in (("boost_no_news", "nonews_boost"), ("boost_calendar", "calendar_boost")):
        add("calendar_ablation_assumed_lag2", model, n, d["paired"]["panel_mae"][key],
            "OBSERVED_EXPLORATORY", "R8_v2/metrics.json",
            "Validation was used earlier; no fresh unopened test")
    for model in ("news_only", "news_enabled"):
        add("news_ablation", model, None, None, "NA_NO_ELIGIBLE_HISTORICAL_EVENTS",
            "R8/news_audit.json", "64 events, 0 provably available by 2024-12-31")
    for lag in (1, 2, 3):
        add("baseline_release_lag_sensitivity_common_mask", f"lastavailable_lag{lag}",
            d["lag"]["common_mask"]["n"], d["lag"]["common_mask"]["mae"][str(lag)],
            "OBSERVED_DIAGNOSTIC", "R8_closeout_20260929/lag_sensitivity.json",
            "Only baseline was recalculated; no model refit or historical release timestamps")
    add("target_permutation", "boost_no_news_shuffled_labels", n,
        d["paired"]["permutation_control_panel_mae"], "NEGATIVE_CONTROL_EXPLORATORY",
        "R8_v2/metrics.json", "Shuffled booster outperforming unshuffled booster forbids a booster-win claim")
    add("future_mutation", "boost_and_Chronos", None, None, "PASS_LOCAL_PROBES",
        "R8_v2/audit.json; R8_tsfm_deterministic_20260928/audit.json",
        "Two local probes, not exhaustive proof over all origins")
    add("future_news_shift", "news", None, None, "NA_UNINFORMATIVE_ZERO_ELIGIBLE",
        "R8_v2/audit.json", "Synthetic filter self-check passes; no real news-effect test")
    add("future_target_oracle", "oracle", n, 0.0, "INVALID_LEAKAGE_QUARANTINED",
        "R8_v2/audit.json", "Never considered a forecasting model")

    out.mkdir(parents=True, exist_ok=True)
    with (out / "ablations.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    ledger = radar / "runs/R8/ablations.csv"
    if ledger.exists() and ledger.read_bytes() != (out / "ablations.csv").read_bytes():
        raise ValueError("existing R8 ablation ledger differs; refusing overwrite")
    if not ledger.exists():
        ledger.write_bytes((out / "ablations.csv").read_bytes())
    b = d["monthblock"]["bootstrap"]["month_block"]
    months = [
        (record["n_rows"], record["mae_lastavailable"] - record["mae_prophet"])
        for _, record in sorted(d["monthblock"]["per_target_month"].items())
    ]
    assert len(months) == 6
    exact_draws = []
    for selected in itertools.product(range(len(months)), repeat=len(months)):
        denominator = sum(months[i][0] for i in selected)
        exact_draws.append(sum(months[i][0] * months[i][1] for i in selected) / denominator)
    exact_draws.sort()
    prophet_benefit = m["lastavailable"] - m["prophet"]
    prophet_time_interval = {
        "point": prophet_benefit,
        "lo": exact_draws[int(0.025 * (len(exact_draws) - 1))],
        "hi": exact_draws[int(0.975 * (len(exact_draws) - 1))],
        "method": "all_6_to_the_6_target_month_block_resamples_nearest_rank",
    }
    assert prophet_time_interval["lo"] < 0 < prophet_time_interval["hi"]
    verdict = {
        "gate": "R8",
        "disposition": "RESEARCH_COMPLETED_INCONCLUSIVE_NO_SCIENTIFIC_PASS",
        "gate_pass": False,
        "source_action": "act_70e2fe4a16ac4e3d",
        "paired_rows": n,
        "target_month_blocks": d["monthblock"]["n_distinct_target_months"],
        "mae": {k: m[k] for k in ("lastavailable", "seasonal_naive", "prophet", "tsfm")},
        "month_block_benefit_95pct": {
            "prophet_vs_lastavailable": prophet_time_interval,
            "tsfm_vs_prophet": {k: b["tsfm_vs_prophet"][k] for k in ("point", "lo", "hi")},
            "tsfm_vs_lastavailable": {k: b["tsfm_vs_lastavailable"][k] for k in ("point", "lo", "hi")},
        },
        "news_effect": "NA_0_OF_64_HISTORICALLY_ELIGIBLE",
        "prospective_forecast_benefit": "NOT_ESTABLISHED",
        "early_warning": "NOT_ESTABLISHED",
        "historical_asof": "NOT_ESTABLISHED_NO_VERIFIED_AVAILABLE_AT_OR_VINTAGE",
        "limitations": [
            "The two-month release lag is an assumption, not an observed historical publication time.",
            "Only six 2024 target months are evaluated and their interval includes zero.",
            "Validation/test material was inspected before this comparison; it is exploratory, not an unopened final test.",
            "Lag 1/3 sensitivity was measured for the last-observation baseline only; Prophet/Chronos were not refit.",
            "News effect and false-event forecast response are NA because no historical events pass the as-of filter.",
        ],
        "next_stage": "R9_ONLY_AFTER_NEW_INDEPENDENT_TIME_HOLDOUT_AND_VERIFIED_VINTAGE",
        "generation_command": "python3 shock-radar/src/r8_closeout.py --out shock-radar/runs/R8_closeout_20260929",
        "generation_code_sha256": digest(Path(__file__)),
        "evidence_sha256": {key: digest(path) for key, path in paths.items()},
        "predictions_sha256": {
            "prophet": d["monthblock_manifest"]["input"]["prophet_predictions_sha256"],
            "tsfm": d["monthblock_manifest"]["input"]["tsfm_predictions_sha256"],
        },
        "ablation_ledger_sha256": digest(out / "ablations.csv"),
    }
    (out / "decision.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n")
    return verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.root, args.out)
    print(json.dumps({k: result[k] for k in ("disposition", "gate_pass", "paired_rows")}))


if __name__ == "__main__":
    main()
