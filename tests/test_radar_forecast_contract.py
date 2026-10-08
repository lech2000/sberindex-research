"""Audit scientific contracts against frozen evidence without fitting models."""
import hashlib
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'shock-radar/protocol/forecast_contract.yaml'


def read(path):
    return json.loads((ROOT / path).read_text())


class ForecastContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = yaml.safe_load(CONTRACT.read_text())

    def test_preserves_historical_r0_and_closed_scientific_gate(self):
        c = self.c
        self.assertEqual(c['meta']['status'], 'r0_pass_conservative_lag_2m')
        self.assertEqual(c['horizons']['historical_r0_proposed'], [1, 2, 3])
        self.assertEqual(c['horizons']['official_contest'], [1, 3, 6, 12])
        self.assertEqual(c['target']['unit'], 'unknown_native_value')
        self.assertEqual(c['temporal_split']['test'], 'CLOSED')
        self.assertEqual(c['r9_independent_test']['gate_state'], 'CLOSED')
        for field in ['historical_asof_verified', 'independent_holdout', 'scientific_pass']:
            self.assertIs(c['meta']['current_revision'][field], False)
        self.assertEqual(c['historical_r0_fields']['temporal_split']['train'], '2023-01..origin-1')

    def test_actual_r9_origins_masks_mae_and_intervals_match_artifacts(self):
        c = self.c['r9_paired_prophet']
        self.assertEqual(c['observation_lag_months'], 0)
        audit = read('shock-radar/runs/R9_prophet_full_20261001/audit.json')
        base = read('shock-radar/runs/R9_baseline_20261001/metrics.json')
        intervals = read('shock-radar/runs/R9_intervals_20261003/metrics.json')
        self.assertEqual(c['common_rows'], 294570)
        self.assertEqual(c['expected_paired_rows'] - c['common_rows'], 222)
        self.assertEqual(c['source_panel_sha256'], base['source_sha256'])
        self.assertEqual(c['predictions_sha256'], intervals['provenance']['predictions_sha256'])
        for row, a, b, ci in zip(c['results'], audit['by_horizon'], base['results'], intervals['results']):
            self.assertEqual(row['horizon'], a['horizon'])
            self.assertEqual(row['origins'], b['origins'])
            self.assertEqual(row['n_origins'], 6)
            self.assertEqual(row['mae_common'], a['mae_common'])
            self.assertEqual(row['n_common'], a['n_common'])
            self.assertEqual(row['excluded_insufficient_train'], a['n_baseline_mask'] - a['n_common'])
            self.assertEqual(row['benefit_prophet_vs_last_month_ci95'], [ci['month_block']['lo'], ci['month_block']['hi']])
            for origin, target, train in zip(row['origins'], row['test_targets'], row['train_calendar_months_lag0']):
                oi = (int(origin[:4]) - 2023) * 12 + int(origin[5:]) - 1
                ti = (int(target[:4]) - 2023) * 12 + int(target[5:]) - 1
                self.assertEqual(ti - oi, row['horizon'])
                self.assertEqual(train, oi + 1)
                self.assertLessEqual(ti, 23)
        self.assertEqual([r['excluded_insufficient_train'] for r in c['results']], [0, 6, 0, 216])

    def test_calendar_minimum_history_and_lag_two_are_separate(self):
        results = self.c['calendar_feasibility']['results']
        self.assertEqual([results[h]['min12_lag0']['n_origins'] for h in [1, 3, 6, 12]], [12, 10, 7, 1])
        self.assertEqual([results[h]['min12_lag2']['n_origins'] for h in [1, 3, 6, 12]], [10, 8, 5, 0])
        for h, scenarios in results.items():
            for lag in [0, 2]:
                expected = []
                for i in range(24):
                    if i - lag + 1 >= 12 and i + h <= 23:
                        expected.append(f'{2023 + i // 12:04d}-{1 + i % 12:02d}')
                self.assertEqual(scenarios[f'min12_lag{lag}']['origins'], expected)
        self.assertEqual(results[12]['min12_lag2']['origins'], [])
        self.assertFalse(self.c['r9_technical_baselines']['availability_lag_verified'])

    def test_two_h12_pilots_keep_distinct_masks_models_and_metrics(self):
        pilots = self.c['national_h12_pilots']
        self.assertFalse(pilots['pool_masks_or_metrics'])
        self.assertEqual(len(pilots['runs']), 2)
        first, second = pilots['runs']
        self.assertNotEqual(first['run_id'], second['run_id'])
        self.assertNotEqual(first['series_selection'], second['series_selection'])
        for p in pilots['runs']:
            metric = read(p['metrics']['path'])
            protocol = read(p['protocol']['path'])
            self.assertEqual(p['input_sha256'], protocol['input_sha256'])
            self.assertEqual(p['rows'], 720)
            self.assertEqual(p['n_series'], 120)
            self.assertEqual(p['training_calendar_months'], [7, 12])
            self.assertEqual(p['results'], metric.get('comparisons', metric.get('results')))
            self.assertFalse(p['historical_asof_verified'])
            self.assertFalse(p['independent_holdout'])
            self.assertFalse(p['scientific_pass'])
        self.assertEqual(first['fits'], 1452)
        self.assertEqual(first['fits'], read(first['metrics']['path'])['new_fits'])
        self.assertEqual(second['fits'], read(second['metrics']['path'])['fits_success'])
        self.assertEqual(second['fits'], 2160)
        self.assertAlmostEqual(first['results'][1]['mae_model'], 598.0916651328823)
        self.assertAlmostEqual(second['results'][0]['mae_model'], 679.7461352252822)

    def test_all_evidence_bytes_match_and_unexecuted_methods_remain_unexecuted(self):
        seen = []
        def walk(value):
            if isinstance(value, dict):
                if 'path' in value and 'sha256' in value:
                    actual = hashlib.sha256((ROOT / value['path']).read_bytes()).hexdigest()
                    self.assertEqual(actual, value['sha256'], value['path'])
                    seen.append(value['path'])
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
        walk(self.c)
        self.assertGreaterEqual(len(set(seen)), 14)
        metrics = self.c['baseline_metrics']
        self.assertEqual(metrics['tsfm_chronos2']['status'], 'not_executed')
        self.assertEqual(metrics['timesfm']['status'], 'not_executed_optional_deferred_p2')
        self.assertEqual(metrics['tsfm_chronos_t5_tiny']['model']['model_id'], 'amazon/chronos-t5-tiny')
        self.assertEqual(metrics['tsfm_chronos_t5_tiny']['model']['model_revision_actual'], '29d808298f1a62493e7b9a5e08529d0d930fa189')
        self.assertEqual(self.c['unexecuted_methods']['real_W01']['status'], 'not_executed')
        self.assertNotEqual(self.c['r9_independent_test']['prophet_full_panel'], 'pending')
        self.assertNotEqual(self.c['r9_independent_test']['uncertainty_intervals'], 'pending')

    def test_taxonomy_payload_outside_prose_is_unchanged(self):
        raw = (ROOT / 'shock-radar/protocol/event_taxonomy.yaml').read_text()
        payload = raw.split('principles:\n', 1)[0] + raw.split('\ntopics:', 1)[1]
        self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(), '55662dd79781b3b0045463ebf9132fd7a0ac5edb52a10c79010cf56a161a3138')

    def test_text_artifact_consumers_keep_the_same_path(self):
        for path in ['agents/attach_gate_artifacts.py', 'model-lab/sync_plan_to_kb.py']:
            source = (ROOT / path).read_text()
            self.assertIn('shock-radar/protocol/forecast_contract.yaml', source)
            self.assertNotIn('forecast_contract.json', source)
        taxonomy = yaml.safe_load((ROOT / 'shock-radar/protocol/event_taxonomy.yaml').read_text())
        self.assertEqual(taxonomy['meta']['contract'], 'shock-radar/protocol/forecast_contract.yaml')
        self.assertEqual(len(taxonomy['principles']), 3)
        self.assertTrue(all(isinstance(rule, str) for rule in taxonomy['principles']))
        self.assertEqual(taxonomy['principles'][0].strip(), 'as-of прежде всего: событие используется на origin O, только если его published_at <= последнего дня месяца O-1. Строго прошлое, без исключений.')
        self.assertEqual(taxonomy['principles'][1].strip(), 'Первичная публикация подтверждает: GDELT — только обнаружение и метаданные, в корпус идёт URL первичного источника (официальный сайт, региональное СМИ).')
        self.assertEqual(taxonomy['principles'][2].strip(), 'Одно событие — одна запись с географией; региональная новость маппится на все tid региона, городская — на конкретный tid.')
        self.assertEqual(yaml.safe_load(CONTRACT.read_text()), self.c)


if __name__ == '__main__':
    unittest.main()
