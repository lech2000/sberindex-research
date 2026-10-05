"""Save the authorized consumer study; full KB text and case bytes readback."""
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import zipfile

REPO = Path(__file__).resolve().parents[2]
RUN = REPO/'economic-atlas/runs/Consumption_restructuring_forecast_20261005_v2'
SITE = REPO/'economic-atlas/site/consumption-restructuring-20261005'
REPORT = RUN/'README.md'
spec = importlib.util.spec_from_file_location('atlas_api', REPO/'integrations/fixar/sync_atlas_release.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


def package(out):
    files = list(p for p in RUN.iterdir() if p.is_file())
    files += list(p for p in SITE.iterdir() if p.is_file())
    files += [REPO/p for p in [
        'economic-atlas/src/consumption_restructuring.py',
        'economic-atlas/src/consumption_restructuring_audit.py',
        'economic-atlas/src/consumption_restructuring_site.py',
        'economic-atlas/src/atlas_radar_joint.py',
        'shock-radar/src/r9_strong_baselines.py',
        'economic-atlas/site/consumption-restructuring-template.html',
        'economic-atlas/consumption_restructuring_protocol_20261005.json',
        'economic-atlas/data/panel_v1.parquet',
        'tests/test_consumption_restructuring.py',
        'tests/test_atlas_radar_joint.py',
        'repository-tools/requirements-science.txt',
        'README.md']]
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in files:
            z.write(path, path.relative_to(REPO))
    return {'path': str(out), 'files': len(files), 'bytes': out.stat().st_size,
            'sha256': api.sha(out.read_bytes()), 'external_raw_inputs_included': False}


def publish(args):
    args.receipts.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip()
    rel = str(REPORT.relative_to(REPO))
    url = 'https://github.com/lech2000/sberindex-research/blob/'+commit+'/'+rel
    if api.SECRET.search(REPORT.read_text()):
        raise ValueError('Secret pattern in report')
    if args.kb:
        live = {int(c['id']): c for c in api.request('GET', args.kb_base+'/api/corpora')}
        jobs = {75: 'research:sberindex-2026:economic-atlas:'+api.OWNER,
                76: 'research:sberindex-2026:shock-radar:'+api.OWNER}
        receipt = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
                   'method': 'integrate, full text readback', 'source_commit': commit,
                   'source_url': url, 'documents': []}
        text = REPORT.read_text().strip()
        for cid, expected in jobs.items():
            if live.get(cid, {}).get('name') != expected:
                raise ValueError('Wrong corpus identity '+str(cid))
            result = api.request('POST', f'{args.kb_base}/api/corpora/{cid}/documents/integrate', {
                'title': 'Потребительская перестройка муниципалитетов и проверка прогноза 6 октября 2026',
                'url': url, 'text': text,
                'meta': {'checked_on': '2026-10-06', 'source_sha256': api.sha(REPORT.read_bytes()),
                         'scientific_status': 'EXPLORATORY_NEGATIVE_FORECAST_RESULT',
                         'limits': 'Already viewed 2024; no historical asof, no crisis forecast validation',
                         'source_file': rel}})
            did = result.get('document_id') or result.get('id')
            if did is None:
                raise ValueError('Missing document receipt ID')
            stored = api.request('GET', f'{args.kb_base}/api/corpora/{cid}/documents/{did}/text')
            if stored.get('truncated') or stored.get('text') != text:
                raise ValueError('KB readback mismatch')
            receipt['documents'].append({'corpus_id': cid, 'document_id': did,
                'full_text_readback': True, 'sha256': api.sha(text.encode()), 'result': result})
            api.save(args.receipts/'kb.json', receipt)
            print(json.dumps(receipt['documents'][-1], ensure_ascii=False), flush=True)
        receipt['status'] = 'VERIFIED'
        api.save(args.receipts/'kb.json', receipt)
    if args.case:
        archive = args.receipts/'CONSUMER_RESTRUCTURING_STUDY_20261006.zip'
        info = package(archive)
        api.save(args.receipts/'archive.json', info)
        payload = {'owner': api.OWNER, 'case': api.CASE, 'files': []}
        for path, mime, title in [
            (REPORT, 'text/markdown', 'Потребительская перестройка — результаты и отрицательная проверка прогноза'),
            (SITE/'index.html', 'text/html', 'Потребительская перестройка — автономная карта и шесть историй'),
            (archive, 'application/zip', 'Потребительская перестройка — код, протокол, результаты и карта')]:
            raw = path.read_bytes()
            payload['files'].append({'file': path.name, 'title': title, 'mime': mime,
                'content_b64': base64.b64encode(raw).decode(), 'sha256': api.sha(raw)})
        remote = api.REMOTE.replace('atlas-release-20261005:', 'consumer-study-20261006:')
        program = 'PAYLOAD='+repr(base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode())+'\n'+remote
        cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'joe', 'incus', 'exec', 'aios2', '--',
               'docker', 'exec', '-i', 'ai_os2-case-service-1', 'python', '-']
        receipt = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'case_id': api.CASE,
                   'source_commit': commit, 'method': 'vault/material upload and downloaded bytes SHA-256', 'materials': []}
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            proc.stdin.write(program)
            proc.stdin.close()
            for line in proc.stdout:
                record = json.loads(line)
                receipt['materials'].append(record)
                api.save(args.receipts/'case.json', receipt)
                print(json.dumps(record, ensure_ascii=False), flush=True)
            error = proc.stderr.read()
            if proc.wait():
                raise RuntimeError('Remote save failed: '+error[-1000:])
        if len(receipt['materials']) != 3:
            raise ValueError('Missing material receipts')
        receipt['status'] = 'VERIFIED'
        api.save(args.receipts/'case.json', receipt)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kb', action='store_true')
    parser.add_argument('--case', action='store_true')
    parser.add_argument('--kb-base', default='http://10.189.141.165:8300')
    parser.add_argument('--receipts', type=Path, required=True)
    publish(parser.parse_args())
