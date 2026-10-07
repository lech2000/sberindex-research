"""Metadata/authority tests only: never invoke science, native probe or process."""
import copy
import datetime
import importlib.util
import json
import plistlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[1] / 'economic-atlas/src/atlas_m4_durable.py'
spec = importlib.util.spec_from_file_location('durable_m4', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def result():
    return {'n':1896, 'd':5, 'results':{'10':{'n':1896, 'd':5, 'k':10,
        'fit':{'sig_star':None}, 'calibration':[{'R':1, 'seed':20261008,
        'm':None, 'sig':None, 'raw_gap':None, 'status':'INCONCLUSIVE_GRAPH_ISOLATE'}],
        'held':[{'R':1, 'seed':20261108, 'm':None, 'sig':None, 'raw_gap':None,
        'status':'INCONCLUSIVE_GRAPH_ISOLATE', 'verdict':'INCONCLUSIVE_GRAPH_ISOLATE',
        'shuffle_invalid_seeds':list(range(99)), 'shuffle_raw_gaps':[]}]}}}


class Admission(unittest.TestCase):
    def test_full_allowance_preserved(self):
        now = datetime.datetime(2026,10,8,0,tzinfo=datetime.timezone.utc)
        self.assertEqual(m.admission(now), 93487)
        self.assertEqual(m.admission(now,startup=20),93467)

    def test_too_late_does_not_shrink_bank_or_cap(self):
        with self.assertRaises(ValueError):
            m.admission(datetime.datetime(2026,10,8,8,tzinfo=datetime.timezone.utc))

    def test_historical_time_cannot_reset(self):
        now = datetime.datetime(2026,10,8,0,tzinfo=datetime.timezone.utc)
        for bad in (-1, 0, 82, True, float('nan'), float('inf'), '83'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.admission(now,historical=bad)

    def test_startup_time_cannot_reset(self):
        now = datetime.datetime(2026,10,8,0,tzinfo=datetime.timezone.utc)
        for bad in (-1, True, float('nan'), float('inf')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m.admission(now,startup=bad)

    def test_reserved_key_cannot_restart(self):
        with self.assertRaises(ValueError):
            m.admission(datetime.datetime(2026,10,8,0,tzinfo=datetime.timezone.utc),reserved=True)

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            m.admission(datetime.datetime(2026,10,8))


class Integrity(unittest.TestCase):
    def test_genuine_nulls_preserved(self):
        self.assertEqual(m.validate_scalars(result()),result())

    def test_nan_fit_rejected(self):
        for bad in (True, '1', float('nan'), float('inf')):
            r = result(); r['results']['10']['fit']['sig_star'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):m.validate_scalars(r)

    def test_malformed_rows_rejected(self):
        for field, bad in [('R',True),('seed',1.),('m',True),('m',1897),('sig',float('nan')),('raw_gap',float('inf')),('status','UNKNOWN'),('verdict','UNKNOWN'),('shuffle_invalid_seeds',[True])]:
            r = result(); r['results']['10']['held'][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):m.validate_scalars(r)

    def test_manifest_and_result_binding(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); p = root/'result.json';p.write_text(json.dumps(result()))
            manifest = root/'manifest.json';manifest.write_text(json.dumps({'files_sha256':{'result.json':m.sha(p)}}))
            binding = {'result_sha256':m.sha(p),'manifest_sha256':m.sha(manifest)}
            m.verify_dependency_files(p,binding)
            p.write_text(p.read_text()+' ')
            with self.assertRaises(ValueError):m.verify_dependency_files(p,binding)

    def test_path_escape_rejected_even_with_rehashed_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'result.json';p.write_text(json.dumps(result()))
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'files_sha256':{'../outside.json':'0'*64}}))
            with self.assertRaises(ValueError):m.verify_dependency_files(p,{'result_sha256':m.sha(p),'manifest_sha256':m.sha(manifest)})


class Authority(unittest.TestCase):
    def test_reservation_immutable_even_after_terminal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'oneuse.json';m.reserve(p,{'state':'STARTED','outdir':'first'})
            (Path(d)/'terminal.json').write_text('{"state":"STOP"}')
            with self.assertRaises(FileExistsError):m.reserve(p,{'state':'STARTED','outdir':'second'})
            self.assertEqual(json.loads(p.read_text())['outdir'],'first')

    def test_launchd_one_shot_and_fixed_arguments(self):
        p=plistlib.loads(m.plist('/absolute/python','/absolute/launcher','/repo','/cal/result.json','/binding','abc','/run/receipts','/run/full'))
        self.assertTrue(p['RunAtLoad']);self.assertFalse(p['KeepAlive'])
        self.assertNotIn('StartInterval',p);self.assertNotIn('StartCalendarInterval',p)
        self.assertEqual(p['ProgramArguments'][0],'/absolute/python')
        self.assertNotIn('--resume',p['ProgramArguments'])
        self.assertNotIn('--wall-seconds',p['ProgramArguments'])
        self.assertEqual(p['EnvironmentVariables']['OMP_NUM_THREADS'],'1')

    def fixture_command(self, root):
        repo=root/'repo';repo.mkdir();cal=root/'cal';cal.mkdir()
        path=cal/'result.json';path.write_text(json.dumps(result()))
        manifest=cal/'manifest.json';manifest.write_text(json.dumps({'files_sha256':{'result.json':m.sha(path)}}))
        binding=root/'binding.json';binding.write_text(json.dumps({'one_use_key':m.KEY,
            'historical_seconds':m.HISTORICAL_SECONDS,'source_action':'act_a0d924d8af6548e2',
            'launcher_sha256':m.sha(SOURCE),'result_sha256':m.sha(path),'manifest_sha256':m.sha(manifest)}))
        return ['launcher','--repo',str(repo),'--m1-calibration',str(path),'--binding',str(binding),
                '--binding-sha',m.sha(binding),'--receipt-dir',str(root/'receipts'),'--outdir',str(root/'full')]

    def test_disk_before_import_probe_or_science(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);argv=self.fixture_command(root)
            with mock.patch.object(m.sys,'argv',argv), mock.patch.object(m,'PINS',{}), \
                 mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=1073741823)), \
                 mock.patch.object(m,'load') as imported:
                with self.assertRaisesRegex(ValueError,'before any probe'):m.main()
                imported.assert_not_called()

    def test_reserved_failure_always_terminal_no_native_calls(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);argv=self.fixture_command(root);ledger=root/'ledger'
            fake_science=SimpleNamespace(check_dependency=lambda _: {'positive_scientific_qualification_allowed':False})
            def fail():raise RuntimeError('synthetic executor failure; no native/model calls')
            fake_executor=SimpleNamespace(load=lambda *a: None,main=fail)
            with mock.patch.object(m.sys,'argv',argv), mock.patch.object(m,'PINS',{}), \
                 mock.patch.object(m,'LEDGER_ROOT',ledger), \
                 mock.patch.object(m.shutil,'disk_usage',return_value=SimpleNamespace(free=3*1073741824)), \
                 mock.patch.object(m,'load',side_effect=[fake_science,fake_executor]), \
                 mock.patch.object(m.signal,'signal'), mock.patch.object(m.signal,'setitimer'):
                with self.assertRaises(SystemExit):m.main()
            reservations=[p for p in ledger.glob('*.json') if not p.name.endswith('-terminal.json')]
            self.assertEqual(len(reservations),1)
            self.assertEqual(json.loads(reservations[0].read_text())['state'],'STARTED')
            terminal=json.loads((root/'receipts/terminal.json').read_text())
            self.assertEqual(terminal['state'],'INCONCLUSIVE_DURABLE_STOP_NO_RETRY')
            self.assertFalse(terminal['scientific_pass'])
            self.assertFalse(terminal['continuous_total_resource_pass'])
            self.assertFalse(terminal['last_verification_receipt_IO_independently_timed'])
            self.assertGreaterEqual(terminal['inclusive_elapsed_observed_seconds'],terminal['inclusive_elapsed_before_finalization_receipts_seconds'])
            self.assertTrue(list(ledger.glob('*-terminal.json')))


if __name__ == '__main__':unittest.main()
