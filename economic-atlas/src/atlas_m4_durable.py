"""One-use root launcher for the entire frozen M4 bank, never a resume tool.

Only operational admission changes. The accepted science and its executor are
SHA-pinned. A failed/inconclusive upstream method permits descriptive results.
There is no scheduler, automatic retry, dataset subset or threshold adjustment.
"""
from pathlib import Path
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
import plistlib
import shutil
import signal
import sys
import time

sys.dont_write_bytecode = True
TOTAL_SECONDS = 93600
HISTORICAL_SECONDS = 82.20326720799494
FINALIZATION_SECONDS = 30
SUPERVISORY_OUTPUT_RESERVE = 65536
DEADLINE = datetime.datetime(2026, 10, 9, 9, tzinfo=datetime.timezone.utc)
KEY = 'M4fullbank:6220a61fcaefe60ecc872f5c930023bb6453d0c60059c3f66721199882330969'
LEDGER_ROOT = Path('/private/tmp/sberindex-one-use-ledger')
PINS = {
    'economic-atlas/src/atlas_m4_channels.py': '86553f9d4627fbdccd51ad3f1c6a6335cb1a4b22b6401150ae4a21dd606a1fd9',
    'economic-atlas/src/atlas_m4_executor.py': '76ae66aa2f11ce18060be0173a661d1db1214d38de0ccb95a910a8e6405db3a4',
    'economic-atlas/src/atlas_m1_executor.py': '04b89b778bd3f1f3e5beb83edc0786c39086b249f9b74658219922958c4db93c',
    'economic-atlas/src/atlas_m1_spectral.py': '5ad14f6e2df75ac89d2285e3a09c304e7894ce6c42a363334a1d568115c1758b',
    'economic-atlas/protocols/M4_PROSPECTIVE_V1.json': '6220a61fcaefe60ecc872f5c930023bb6453d0c60059c3f66721199882330969',
    'economic-atlas/protocols/M4_DEPENDENCY_AMENDMENT_V1.json': 'e1c5b21b445c3ef408e9061ae023f706997abe5ebf397ffadeb39a74b0c7f163',
    'economic-atlas/protocols/M4_OPERATIONAL_PREFLIGHT_V1.json': 'eb772e7ff9bbf33048d5ae366024e98e591e05f5a744c04415848088e0863e1b',
    'economic-atlas/protocols/M1_PROSPECTIVE_V1.json': 'fd3133bbda35fb7183908e4c3bd4697f5651962adaf8c0cccf74eb4b15c0dc30',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite numeric ' + label + ' required')
    return value


def admission(now, historical=HISTORICAL_SECONDS, startup=0., reserved=False):
    if now.tzinfo is None:
        raise ValueError('timezone required')
    if finite(historical, 'historical time') < HISTORICAL_SECONDS:
        raise ValueError('historical time cannot reset')
    if finite(startup, 'startup time') < 0:
        raise ValueError('startup time cannot reset')
    if reserved:
        raise ValueError('global one-use key already reserved; no restart')
    remaining = TOTAL_SECONDS - historical - startup
    # Refuse to silently replace the prospectively fixed allowance by a tighter
    # deadline-derived budget. The full bank and fixed deadline stay unchanged.
    if remaining <= FINALIZATION_SECONDS or (DEADLINE - now).total_seconds() < remaining:
        raise ValueError('entire frozen allowance cannot fit fixed deadline')
    return math.floor(remaining - FINALIZATION_SECONDS)


def validate_scalars(result):
    if type(result.get('n')) is not int or type(result.get('d')) is not int:
        raise ValueError('literal n/d integer required')
    for key, c in result['results'].items():
        if any(type(c.get(x)) is not int for x in ('n', 'd', 'k')):
            raise ValueError('literal per-k dimensions required')
        star = c.get('fit', {}).get('sig_star')
        if star is not None:
            finite(star, 'sig_star')
        for field in ('calibration', 'held'):
            for row in c[field]:
                if type(row.get('R')) is not int or type(row.get('seed')) is not int:
                    raise ValueError('literal R/seed integer required')
                m = row.get('m')
                if m is not None and (type(m) is not int or not 1 <= m <= 1896):
                    raise ValueError('malformed m')
                for name in ('sig', 'raw_gap'):
                    if row.get(name) is not None:
                        finite(row[name], name)
                if row['status'] not in ('COMPUTED', 'DEGENERATE_BULK', 'INCONCLUSIVE_GRAPH_ISOLATE', 'INCONCLUSIVE_NO_BULK'):
                    raise ValueError('unknown spectral status')
                if field == 'held':
                    if row['verdict'] not in ('INCONCLUSIVE_GRAPH_ISOLATE', 'ABSTAIN_M1', 'INCONCLUSIVE_CALIBRATION', 'INCONCLUSIVE_DEGENERATE_BULK', 'INCONCLUSIVE_SHUFFLE', 'ABSTAIN_LOW_SIG', 'ABSTAIN_NULL_GAP', 'REAL_GAP'):
                        raise ValueError('unknown held verdict')
                    if any(type(s) is not int for s in row['shuffle_invalid_seeds']):
                        raise ValueError('literal invalid-null seeds required')
    return result


def verify_dependency_files(resultpath, binding):
    resultpath = Path(resultpath)
    manifestpath = resultpath.parent / 'manifest.json'
    if binding.get('result_sha256') != sha(resultpath) or binding.get('manifest_sha256') != sha(manifestpath):
        raise ValueError('actual completed M1 root binding mismatch')
    manifest = json.loads(manifestpath.read_text())
    for name, digest in manifest['files_sha256'].items():
        if Path(name).name != name or name in ('.', '..') or sha(resultpath.parent / name) != digest:
            raise ValueError('M1 completed manifest file mismatch')
    return validate_scalars(json.loads(resultpath.read_text()))


def atomic(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def reserve(path, data):
    """O_EXCL+fsync prevents an alternate output directory resetting the run."""
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alarm(signum, frame):
    raise InterruptedError('full-bank inclusive resource/deadline cap; no retry')


def plist(python, launcher, repo, calibration, binding, binding_sha, receipt_dir, outdir):
    """Return a one-shot user job; caller must validate actual inputs first."""
    return plistlib.dumps({'Label': 'local.sergey.sberindex.m4.fullbank.frozen6220a61f',
        'ProgramArguments': [str(python), str(launcher), '--repo', str(repo),
            '--m1-calibration', str(calibration), '--binding', str(binding),
            '--binding-sha', binding_sha, '--receipt-dir', str(receipt_dir), '--outdir', str(outdir)],
        'RunAtLoad': True, 'KeepAlive': False,
        'StandardOutPath': str(Path(outdir).parent / 'M4-fullbank-launchd.stdout.log'),
        'StandardErrorPath': str(Path(outdir).parent / 'M4-fullbank-launchd.stderr.log'),
        'EnvironmentVariables': {**{k: '1' for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS')}, 'PYTHONDONTWRITEBYTECODE': '1'}})


def main():
    started = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--m1-calibration', type=Path, required=True)
    ap.add_argument('--binding', type=Path, required=True, help='Root-frozen actual complete M1/result/manifest hashes')
    ap.add_argument('--binding-sha', required=True)
    ap.add_argument('--receipt-dir', type=Path, required=True)
    ap.add_argument('--outdir', type=Path, required=True)
    args = ap.parse_args()
    if sha(args.binding) != args.binding_sha:
        raise ValueError('root binding SHA mismatch')
    binding = json.loads(args.binding.read_text())
    if binding.get('one_use_key') != KEY or binding.get('historical_seconds') != HISTORICAL_SECONDS:
        raise ValueError('fixed one-use key/history mismatch')
    if binding.get('source_action') != 'act_a0d924d8af6548e2' or binding.get('launcher_sha256') != sha(__file__):
        raise ValueError('root binding action/launcher mismatch')
    if any(sha(args.repo / p) != digest for p, digest in PINS.items()):
        raise ValueError('accepted full science source/protocol mismatch')
    if args.outdir.exists() or args.receipt_dir.exists():
        raise ValueError('fresh full-bank and supervisory destinations required')
    for destination in (args.outdir.resolve(), args.receipt_dir.resolve()):
        for protected in (args.repo.resolve(), args.m1_calibration.parent.resolve()):
            if destination == protected or protected in destination.parents:
                raise ValueError('output cannot modify frozen source or original calibration')
    # Disk rejection happens before importing numerical methods, native probes,
    # reserving a run or spawning a scientific process.
    if shutil.disk_usage(args.outdir.parent).free < 1073741824:
        raise ValueError('1GiB free required before any probe or science')
    if os.stat(args.outdir.parent).st_dev != os.stat(args.receipt_dir.parent).st_dev:
        raise ValueError('science and supervisory outputs must share resource disk')
    verify_dependency_files(args.m1_calibration, binding)
    admission(utcnow(), startup=time.monotonic() - started)
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        os.environ[key] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    m = load(args.repo / 'economic-atlas/src/atlas_m4_channels.py', 'pinned_m4')
    dependency = m.check_dependency(args.m1_calibration)
    executor = load(args.repo / 'economic-atlas/src/atlas_m4_executor.py', 'pinned_executor')
    # Reserve small supervisory receipts from the same 256MiB total. This wraps
    # only accepted operational-module loading; all scientific bytes are pinned.
    original_load = executor.load
    def operational_load(path, name):
        module = original_load(path, name)
        if name == 'native_executor':
            module.LIMITS = dict(module.LIMITS, output=268435456 - SUPERVISORY_OUTPUT_RESERVE)
        return module
    executor.load = operational_load
    wall = admission(utcnow(), startup=time.monotonic() - started)
    # The fixed UID-scoped path is intentionally not exposed as a CLI override.
    # This is a trusted root launcher, not an authenticated worker endpoint.
    LEDGER_ROOT.mkdir(mode=0o700, exist_ok=True)
    stat = LEDGER_ROOT.lstat()
    if LEDGER_ROOT.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise ValueError('canonical one-use ledger must be private and owned')
    reservation = LEDGER_ROOT / (str(os.getuid()) + '-M4-' + hashlib.sha256(KEY.encode()).hexdigest() + '.json')
    record = {'state': 'STARTED', 'started_at': utcnow().isoformat(), 'uid': os.getuid(),
              'one_use_key': KEY, 'source_action': 'act_a0d924d8af6548e2',
              'launcher_sha256': sha(__file__), 'binding_sha256': args.binding_sha,
              'M1_dependency': dependency, 'science_pins': PINS,
              'total_seconds': TOTAL_SECONDS, 'historical_seconds': HISTORICAL_SECONDS,
              'finalization_reserve_seconds': FINALIZATION_SECONDS,
              'supervisory_output_reserve_bytes': SUPERVISORY_OUTPUT_RESERVE,
              'absolute_deadline_UTC': DEADLINE.isoformat(), 'outdir': str(args.outdir),
              'receipt_dir': str(args.receipt_dir), 'automatic_restart': False,
              'source_actions_closed': 0, 'scientific_pass': False}
    reserve(reservation, record)
    previous_argv = sys.argv
    previous_alarm = signal.getsignal(signal.SIGALRM)
    try:
        args.receipt_dir.mkdir(mode=0o700, exist_ok=False)
        atomic(args.receipt_dir / 'reservation-copy.json', record)
        # Re-check after imports/ledger IO: none of these can reset the budget.
        wall = admission(utcnow(), startup=time.monotonic() - started)
        if shutil.disk_usage(args.outdir.parent).free < 1073741824:
            raise ValueError('disk admission changed before native preflight')
        signal.signal(signal.SIGALRM, alarm)
        signal.setitimer(signal.ITIMER_REAL, wall)
        sys.argv = [str(args.repo / 'economic-atlas/src/atlas_m4_executor.py'),
                    '--repo', str(args.repo), '--m1-calibration', str(args.m1_calibration),
                    '--outdir', str(args.outdir), '--wall-seconds', str(wall)]
        executor.main()
        terminal = json.loads((args.outdir / 'terminal.json').read_text())
        record.update(state=terminal['state'], accepted_executor_terminal_sha256=sha(args.outdir / 'terminal.json'),
                      positive_scientific_qualification=terminal.get('M4_result', {}).get('positive_scientific_qualification', False))
    except BaseException as exc:
        record.update(state='INCONCLUSIVE_DURABLE_STOP_NO_RETRY', error=type(exc).__name__ + ': ' + str(exc))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        sys.argv = previous_argv
        record.update(finalization_started_at=utcnow().isoformat(), inclusive_elapsed_before_finalization_receipts_seconds=HISTORICAL_SECONDS + time.monotonic() - started)
        if record['inclusive_elapsed_before_finalization_receipts_seconds'] > TOTAL_SECONDS or utcnow() > DEADLINE:
            record.update(state='INCONCLUSIVE_FINALIZATION_EXCEEDED_RESOURCE_PROTOCOL', positive_scientific_qualification=False)
        # Canonical terminal also exists if receipt-directory creation failed
        # after the irreversible reservation (e.g. a concurrent path collision).
        canonical_terminal = reservation.with_name(reservation.stem + '-terminal.json')
        atomic(canonical_terminal, record)
        if args.receipt_dir.is_dir():
            atomic(args.receipt_dir / 'terminal.json', record)
        supervisor_size = sum(p.stat().st_size for p in args.receipt_dir.rglob('*') if p.is_file()) if args.receipt_dir.is_dir() else 0
        supervisor_size += reservation.stat().st_size + canonical_terminal.stat().st_size
        for name in ('M4-fullbank-launchd.stdout.log', 'M4-fullbank-launchd.stderr.log'):
            log = args.outdir.parent / name
            if log.is_file():
                supervisor_size += log.stat().st_size
        science_size = sum(p.stat().st_size for p in args.outdir.rglob('*') if p.is_file()) if args.outdir.exists() else 0
        if supervisor_size > SUPERVISORY_OUTPUT_RESERVE or supervisor_size + science_size > 268435456:
            record.update(state='INCONCLUSIVE_COMBINED_OUTPUT_CAP', positive_scientific_qualification=False)
            atomic(canonical_terminal, record)
            if args.receipt_dir.is_dir():
                atomic(args.receipt_dir / 'terminal.json', record)
        # Observe AFTER earlier receipt IO and output scan. A final immutable
        # observation cannot include its own subsequent fsync. Disclose that
        # boundary instead of certifying continuous inclusive-resource PASS.
        record.update(finished_observation_at=utcnow().isoformat(),
                      inclusive_elapsed_observed_seconds=HISTORICAL_SECONDS + time.monotonic() - started,
                      last_verification_receipt_IO_independently_timed=False,
                      continuous_total_resource_pass=False,
                      resource_qualification='SAMPLED_WITH_FINAL_IMMUTABLE_RECEIPT_IO_UNMEASURED',
                      combined_output_bytes_observed=supervisor_size + science_size)
        if record['inclusive_elapsed_observed_seconds'] > TOTAL_SECONDS or utcnow() > DEADLINE:
            record.update(state='INCONCLUSIVE_FINALIZATION_EXCEEDED_RESOURCE_PROTOCOL', positive_scientific_qualification=False)
        atomic(canonical_terminal, record)
        if args.receipt_dir.is_dir():
            atomic(args.receipt_dir / 'terminal.json', record)
        # Reservation remains forever STARTED. Terminal is a separate artifact;
        # neither success nor failure authorizes a second full-bank attempt.
    print(json.dumps({'state': record['state'], 'terminal': str(args.receipt_dir / 'terminal.json'), 'action_closed': False}))
    if record['state'].startswith('INCONCLUSIVE'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
