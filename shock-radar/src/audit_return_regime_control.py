"""Independent scoring and null replay for the frozen return-regime experiment."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from d02_d03_detectors import d01_alarms, d02_alarms, d03_alarms, apply_cooldown, truncate_budget_monthly

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def worlds(seed, family, amplitude, protocol):
    # Separate construction; replicate the documented random draw order, not saved labels.
    random = np.random.default_rng(seed)
    n = protocol['series_per_seed']
    values = random.normal(size=(n, 24))
    if family == 'student5':
        values = random.standard_t(df=5, size=(n, 24)) * np.sqrt(3 / 5)
    values *= protocol['noise_std']
    selected = random.choice(n, size=protocol['modified_per_seed'], replace=False)
    signs = random.choice([-1., 1.], size=len(selected))
    altered = values.copy()
    for index, sign in zip(selected, signs):
        altered[index, 18:21] += amplitude * protocol['noise_std'] * sign
    months = [f'{2023 + i // 12}-{i % 12 + 1:02d}' for i in range(24)]
    def frame(array):
        return pd.DataFrame([{'tid': f'synthetic_{i:03d}', 'cat': 'synthetic_signal',
                              'ym': month, 'rel': array[i, j]}
                             for i in range(n) for j, month in enumerate(months)])
    return frame(values), frame(altered), {f'synthetic_{i:03d}' for i in selected}

def selected_bank(data, params):
    raw = {
        'D01': d01_alarms(data, 'rel', params['D01']['k'], train_end='2024-03'),
        'D02': d02_alarms(data, 'rel', params['D02']['delta'], params['D02']['lambda']),
        'D03': d03_alarms(data, 'rel', params['D03']['tau'], hazard=.02, n0=10.,
                         rmax=24, train_end='2024-03', strict_log_support=True),
    }
    result = {}
    for method, rows in raw.items():
        cooled = apply_cooldown(rows, 3)
        result[method] = truncate_budget_monthly(cooled[cooled.ym.between('2024-07', '2024-12')], 24)
    return result

def month_number(value):
    year, month = map(int, value.split('-'))
    return year * 12 + month

def verify(protocol_path, calculation, destination, frozen_r7, frozen_commit='1aa5962'):
    root = Path(__file__).resolve().parents[2]
    protocol_path = protocol_path.resolve()
    frozen_r7 = frozen_r7.resolve()
    protocol = json.loads(protocol_path.read_text())
    metrics = json.loads((calculation / 'metrics.json').read_text())
    rows = json.loads((calculation / 'by-seed.json').read_text())
    alerts = pd.read_parquet(calculation / 'alerts.parquet')
    assert sha(protocol_path) == metrics['protocol_sha256']
    assert sha(frozen_r7) == protocol['r7_manifest_sha256']
    assert protocol['parameters'] == json.loads(frozen_r7.read_text())['fitted_on_validation_only']
    assert sha(Path(__file__).with_name('d02_d03_detectors.py')) == protocol['detector_code_sha256'] == metrics['detector_code_sha256']
    assert sha(Path(__file__).with_name('return_regime_control.py')) == metrics['code_sha256']
    assert sha(calculation / 'alerts.parquet') == metrics['alerts_sha256']
    for path in [protocol_path, Path(__file__).with_name('return_regime_control.py')]:
        archived = subprocess.check_output(['git', '-C', str(root), 'show', f'{frozen_commit}:{path.relative_to(root)}'])
        assert archived == path.read_bytes(), 'Frozen protocol/code changed after the run'
    dimensions = ['family', 'seed', 'amplitude', 'method', 'window_after_onset']
    expected = {(f, s, a, m, w) for f in protocol['families'] for s in protocol['seeds']
                for a in protocol['amplitudes'] for m in ['D01', 'D02', 'D03'] for w in [1, 2]}
    assert len(rows) == len(expected) == 720
    assert {tuple(row[k] for k in dimensions) for row in rows} == expected
    assert not alerts.duplicated(['family', 'seed', 'amplitude', 'method', 'tid', 'cat', 'ym']).any()
    assert alerts.ym.between('2024-07', '2024-12').all()
    assert alerts.groupby(['family', 'seed', 'amplitude', 'method', 'ym']).size().le(24).all()
    worlds_by_key, null_counts = {}, {}
    for family in protocol['families']:
        for seed in protocol['seeds']:
            null, shifted, ids = worlds(seed, family, 4, protocol)
            worlds_by_key[family, seed] = (shifted, ids)
            null_counts[family, seed] = {k: len(v) for k, v in selected_bank(null, protocol['parameters']).items()}
    scored = {}
    event_checks = 0
    for row in rows:
        key = tuple(row[k] for k in dimensions)
        family, seed, amplitude, method, window = key
        ids = worlds_by_key[family, seed][1]
        subset = alerts[(alerts.family == family) & (alerts.seed == seed) &
                        (alerts.amplitude == amplitude) & (alerts.method == method)]
        assert subset.is_changed.to_numpy().tolist() == subset.tid.isin(ids).to_numpy().tolist()
        assert row['events_per_transition'] == len(ids) == 10
        result = {}
        hit_sets = []
        for name, onset in [('enter', '2024-07'), ('return', '2024-10')]:
            start = month_number(onset)
            delays = {tid: [] for tid in ids}
            for alarm in subset.itertuples():
                delay = month_number(alarm.ym) - start
                if alarm.tid in ids and 0 <= delay <= window:
                    delays[alarm.tid].append(delay)
            actual_delays = sorted(min(ds) for ds in delays.values() if ds)
            saved_delays = sorted(v for v in row[name + '_delays'] if v is not None)
            assert saved_delays == actual_delays
            hits = {tid for tid, ds in delays.items() if ds}
            hit_sets.append(hits)
            result[name + '_hits'] = len(hits)
            assert row[name + '_hits'] == len(hits)
            event_checks += len(ids)
        result['both_hits'] = len(hit_sets[0] & hit_sets[1])
        assert result['both_hits'] == row['both_hits']
        assert row['selected_alarms'] == len(subset)
        assert row['alarms_on_unchanged_series'] == int((~subset.tid.isin(ids)).sum())
        assert row['null_alarms'] == null_counts[family, seed][method] and row['null_cells'] == 600
        scored[key] = result
    for summary in metrics['summary']:
        group = [row for row in rows if all(row[k] == summary[k] for k in ['family', 'amplitude', 'method', 'window_after_onset'])]
        assert len(group) == 20 and summary['transition_events'] == 200
        for name in ['enter', 'return', 'both']:
            hits = np.array([row[name + '_hits'] for row in group])
            assert summary[name + '_hits'] == int(hits.sum())
            assert summary[name + '_recall'] == hits.sum() / 200
            draws = np.random.default_rng(20261007).integers(0, 20, (10000, 20))
            ci = np.quantile(hits[draws].sum(axis=1) / 200, [.025, .975])
            np.testing.assert_allclose(ci, summary[name + '_descriptive_seed_ci95'], atol=1e-12)
            if name != 'both':
                delays = [v for row in group for v in row[name + '_delays'] if v is not None]
                actual = float(np.median(delays)) if delays else None
                assert actual == summary[name + '_median_delay_among_hits']
        null_total = sum(null_counts[summary['family'], row['seed']][summary['method']] for row in group)
        assert summary['null_alerts'] == null_total and summary['null_cells'] == 12000
        assert summary['null_alert_cell_rate'] == null_total / 12000
    prefix_checks = []
    for family in protocol['families']:
        seed = protocol['seeds'][0]
        full, ids = worlds_by_key[family, seed]
        prefix = full[full.ym <= '2024-08'].copy()
        changed = full.copy()
        changed.loc[changed.ym > '2024-08', 'rel'] = 1e6
        for variant in [prefix, changed]:
            replay = selected_bank(variant, protocol['parameters'])
            for method, result in replay.items():
                columns = ['method', 'tid', 'cat', 'ym', 'score']
                saved = alerts[(alerts.family == family) & (alerts.seed == seed) & (alerts.amplitude == 4) & (alerts.method == method) & (alerts.ym <= '2024-08')]
                saved = saved[columns].sort_values(columns[:4]).reset_index(drop=True)
                actual = result[result.ym <= '2024-08'][columns].sort_values(columns[:4]).reset_index(drop=True)
                pd.testing.assert_frame_equal(saved, actual, check_dtype=False)
                prefix_checks.append({'family': family, 'method': method, 'variant': 'prefix' if len(variant) < len(full) else 'future_mutation', 'alerts_verified': len(saved)})
    receipt = {
        'status': 'INDEPENDENT_RETURN_REGIME_NUMERICAL_AUDIT_PASS',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'checked_where': 'Mac; separate scorer, regenerated IDs/noise and original frozen R7 detector helpers',
        'frozen_commit': frozen_commit, 'by_seed_rows_verified': len(rows),
        'transition_series_checks': event_checks, 'summary_cells_verified': len(metrics['summary']),
        'descriptive_seed_intervals_recomputed': 108, 'null_detector_runs_replayed': 120,
        'prefix_or_future_detector_runs_replayed': len(prefix_checks), 'prefix_checks': prefix_checks,
        'protocol_sha256': sha(protocol_path), 'metrics_sha256': sha(calculation / 'metrics.json'),
        'auditor_sha256': sha(__file__), 'scientific_pass': False,
        'independence_limit': 'Numerical reimplementation and null/prefix replay, not external scientific review or new data',
        'limits': metrics['limits'],
    }
    assert not destination.exists(), 'Do not overwrite audit receipt'
    destination.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: receipt[k] for k in ['status', 'by_seed_rows_verified', 'transition_series_checks', 'summary_cells_verified', 'null_detector_runs_replayed']}))

def main():
    parser = argparse.ArgumentParser()
    for key in ['protocol', 'calculation', 'destination', 'frozen-r7']:
        parser.add_argument('--' + key, required=True, type=Path)
    args = parser.parse_args()
    verify(args.protocol, args.calculation, args.destination, args.frozen_r7)

if __name__ == '__main__':
    main()
