"""Explicit, finite fresh-fit reproduction of the H12 equal-information pilot."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
for name in ['raw', 'r9', 'national', 'out']:
    parser.add_argument('--' + name, type=Path, required=True)
args = parser.parse_args()
if args.out.exists():
    raise FileExistsError('Use a new output directory; frozen results cannot be overwritten')
cli = [sys.executable, str(ROOT / 'shock-radar/src/r10_equal_information_h12.py')]
for name in ['raw', 'r9', 'national', 'out']:
    cli += ['--' + name, str(getattr(args, name).resolve())]
subprocess.run(cli + ['--prepare'], check=True)
frozen_dir = ROOT / 'shock-radar/runs/R10_equal_information_h12_20261006'
expected_protocol = json.loads((frozen_dir / 'protocol.json').read_text())
actual_protocol = json.loads((args.out / 'protocol.json').read_text())
for key in ['input_sha256', 'selection_manifest', 'primary_model', 'primary_reference',
            'primary_prophet_config', 'expected_rows', 'expected_fits', 'target_months',
            'information_contract', 'future_national_path', 'sensitivity', 'seed']:
    assert actual_protocol[key] == expected_protocol[key], key
with (args.out / 'fit.log').open('w') as log:
    subprocess.run(cli, check=True, stdout=log, stderr=subprocess.STDOUT)
subprocess.run([sys.executable, str(ROOT / 'shock-radar/src/audit_h12_equal.py'),
                '--run', str(args.out), '--raw', str(args.raw), '--r9', str(args.r9),
                '--national', str(args.national)], check=True)
expected = json.loads((frozen_dir / 'metrics.json').read_text())
actual = json.loads((args.out / 'metrics.json').read_text())
for key in ['rows', 'n_series', 'municipalities', 'fits_success', 'fits_expected',
            'failures', 'training_months', 'future_mutation_and_conditional_last_checks']:
    assert actual[key] == expected[key], key
for reference, measured in zip(expected['results'], actual['results']):
    assert reference['model'] == measured['model'] and reference['reference'] == measured['reference']
    for key in ['mae_model', 'mae_reference', 'benefit_mae', 'relative_improvement_percent']:
        assert math.isclose(reference[key], measured[key], rel_tol=1e-6, abs_tol=1e-8), (key, reference['reference'])
receipt = {'status': 'TECHNICAL_REPEAT_PASS', 'fresh_fits': 2160, 'rows': 720,
           'comparisons': 5, 'relative_tolerance': 1e-6, 'scientific_pass': False}
(args.out / 'reproduction.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
