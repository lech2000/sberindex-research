"""Publish verified Atlas documents through existing KB and case APIs.

No agents, model requests or service deployment. Credentials stay in the running
case-service container. Each document is read back and checked by SHA-256.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
ATLAS = ROOT / "economic-atlas"
OWNER = "prn_fbab9aa00cd46169"
CASE = "case_66cae4a89ba6473f"
CORPORA = {
    74: f"research:sberindex-2026:shared:{OWNER}",
    75: f"research:sberindex-2026:economic-atlas:{OWNER}",
}
SECRET = re.compile(r"\bsk-[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|Bearer [A-Za-z0-9_-]{25,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def request(method, url, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    with urlopen(Request(url, data=data, method=method,
                         headers={"Content-Type": "application/json"}), timeout=240) as res:
        return json.load(res)


def jobs():
    result = [(74, ATLAS / "DATA_PASSPORT_RELEASE_2026-10-05.md")]
    result += [(75, ATLAS / name) for name in [
        "RELEASE_REPORT_2026-10-05.md", "MUNICIPAL_STORIES_RELEASE_2026-10-05.md",
        "RELEASE_README.md", "COMPLETION_REPORT_2026-10-05.md",
        "PUBLICATION_MIGRATION_2026-10-05.md",
    ]]
    for run in ["A9_economic_network_20261005", "A10_method_comparison_20261005",
                "A11_icvi_table_20261005", "A12_stable_cores_20261005"]:
        result += [(75, ATLAS / "runs" / run / name) for name in ["README.md", "PROTOCOL.md"]]
    result += [(75, ATLAS / "README.md"),
               (75, ATLAS / "runs/A13_reproduction_20261005/PROTOCOL.md")]
    result.append((75, ATLAS / "runs/A14_release_20261005/PROTOCOL.md"))
    for _, path in result:
        if not path.is_file():
            raise ValueError(f"Missing publication document: {path.relative_to(ROOT)}")
        if SECRET.search(path.read_text()):
            raise ValueError(f"Potential secret: {path.relative_to(ROOT)}")
    return result


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def publish_kb(base, receipt):
    live = {int(c["id"]): c for c in request("GET", base + "/api/corpora")}
    for cid, name in CORPORA.items():
        if live.get(cid, {}).get("name") != name:
            raise ValueError(f"Corpus identity mismatch: {cid}")
    value = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
             "method": "integrate; full document text readback and SHA-256",
             "documents": []}
    for cid, path in jobs():
        rel = str(path.relative_to(ROOT))
        text = ("Проверено 05.10.2026: расчёты и тесты в изолированной рабочей копии на Mac; "
                "публикация и обратное чтение через kb-forge. Исходный артефакт: " + rel + ".\n\n" + path.read_text()).strip()
        result = request("POST", f"{base}/api/corpora/{cid}/documents/integrate", {
            "title": f"Атлас 05.10.2026 — {rel}",
            "url": "urn:sberindex:atlas-release:20261005:" + rel,
            "text": text,
            "meta": {"checked_on": "2026-10-05", "project": "sberindex-2026",
                     "source_file": rel, "source_sha256": sha(path.read_bytes()),
                     "scientific_status": "descriptive; A14 supplementary exploratory",
                     "limits": "A8 negative; no causal or economic superiority claim; MQ unresolved"}})
        did = result.get("document_id") or result.get("id")
        if did is None:
            raise ValueError("Integration receipt contains no document ID")
        stored = request("GET", f"{base}/api/corpora/{cid}/documents/{did}/text")
        stored_text = stored.get("text") if isinstance(stored, dict) else stored
        if (isinstance(stored, dict) and stored.get("truncated")) or stored_text != text:
            raise ValueError(f"KB text readback mismatch: {cid}/{did}")
        record = {"corpus_id": cid, "document_id": did, "file": rel,
                  "source_sha256": sha(path.read_bytes()), "stored_text_sha256": sha(text.encode()),
                  "verified": True, "result": result}
        value["documents"].append(record)
        save(receipt, value)
        print(json.dumps({"corpus": cid, "document": did, "verified": True}), flush=True)
    value["status"] = "VERIFIED"
    save(receipt, value)


REMOTE = r'''
import base64,hashlib,json,os,urllib.request,urllib.parse
payload=json.loads(base64.b64decode(PAYLOAD))
owner=payload['owner']; case=payload['case']
token=os.environ.get('AIOS_INTERNAL_SERVICE_TOKEN','').strip()
if not token: raise RuntimeError('Runtime service credential absent')
def req(method,url,body=None,binary=False):
    data=None if body is None else json.dumps(body,ensure_ascii=False).encode()
    with urllib.request.urlopen(urllib.request.Request(url,data=data,method=method,headers={'content-type':'application/json','X-AIOS-Service-Token':token}),timeout=240) as res:
        raw=res.read()
        return raw if binary else json.loads(raw)
base='http://127.0.0.1:8013'
live=req('GET',base+'/cases/'+case+'?'+urllib.parse.urlencode({'principal_id':owner}))
if live.get('owner_id')!=owner: raise RuntimeError('Case owner mismatch')
out=[]
for item in payload['files']:
    raw=base64.b64decode(item['content_b64']); digest=hashlib.sha256(raw).hexdigest()
    if digest!=item['sha256']: raise RuntimeError('Transport SHA mismatch')
    text=raw.decode() if item['mime']=='text/markdown' else ''
    doc=req('POST','http://vault-service:8019/vault/documents',{'owner_id':owner,'title':item['title'],'content_b64':item['content_b64'],'text':text,'mime':item['mime'],'kind':'file','sensitivity':'normal','domain':'software','source_case_id':case,'in_knowledge':False})['document']
    material=req('POST',base+'/cases/'+case+'/materials',{'kind':'file','mime':item['mime'],'title':item['title'],'storage_ref':'vault:'+doc['id'],'extracted':text,'sensitivity':'normal','source_channel':'api','uploaded_by':owner,'client_message_id':'atlas-release-20261005:'+digest,'client_request_hash':digest,'part_index':0})
    downloaded=req('GET',base+'/cases/'+case+'/materials/'+material['id']+'/content?'+urllib.parse.urlencode({'principal_id':owner}),binary=True)
    if hashlib.sha256(downloaded).hexdigest()!=digest: raise RuntimeError('Material readback SHA mismatch')
    record={'id':material['id'],'vault_document_id':doc['id'],'file':item['file'],'title':item['title'],'bytes':len(raw),'sha256':digest,'verified':True}
    out.append(record)
    print(json.dumps(record,ensure_ascii=False),flush=True)
'''


def publish_case(host, incus, service, archive, receipt):
    paths = [ATLAS / name for name in ["RELEASE_REPORT_2026-10-05.md",
             "DATA_PASSPORT_RELEASE_2026-10-05.md", "MUNICIPAL_STORIES_RELEASE_2026-10-05.md",
             "RELEASE_README.md", "PUBLICATION_MIGRATION_2026-10-05.md"]]
    if archive:
        paths.append(archive)
    payload = {"owner": OWNER, "case": CASE, "files": []}
    for path in paths:
        raw = path.read_bytes()
        if path.suffix == ".md" and SECRET.search(raw.decode()):
            raise ValueError("Potential secret in case document")
        payload["files"].append({"file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name,
                                 "title": "Атлас A9–A14 — " + path.name,
                                 "sha256": sha(raw), "content_b64": base64.b64encode(raw).decode(),
                                 "mime": "application/zip" if path.suffix == ".zip" else "text/markdown"})
    program = "PAYLOAD=" + repr(base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()) + "\n" + REMOTE
    command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
               "incus", "exec", incus, "--", "docker", "exec", "-i", service, "python", "-"]
    value = {"case_id": CASE, "checked_at_utc": datetime.now(timezone.utc).isoformat(),
             "method": "vault upload, case material attach, byte-for-byte readback SHA-256",
             "materials": []}
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        process.stdin.write(program)
        process.stdin.close()
        for line in process.stdout:
            record = json.loads(line)
            value["materials"].append(record)
            save(receipt, value)
            print(json.dumps({"material": record["id"], "verified": True}), flush=True)
        error = process.stderr.read()
        code = process.wait()
        if code:
            raise RuntimeError(f"Remote upload failed with exit {code}: {error[-1000:]}")
    value["status"] = "VERIFIED"
    save(receipt, value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--kb-url")
    parser.add_argument("--case-ssh")
    parser.add_argument("--incus-container", default="aios2")
    parser.add_argument("--service-container", default="ai_os2-case-service-1")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--receipt-dir", type=Path, default=ROOT / "docs/evidence/atlas-release-20261005")
    args = parser.parse_args()
    checked = jobs()
    print(json.dumps({"documents_checked": len(checked), "secret_scan": "PASS"}), flush=True)
    if args.check:
        return
    if args.kb_url:
        publish_kb(args.kb_url.rstrip("/"), args.receipt_dir / "kb-receipts.json")
    if args.case_ssh:
        publish_case(args.case_ssh, args.incus_container, args.service_container,
                     args.archive, args.receipt_dir / "case-receipts.json")


if __name__ == "__main__":
    main()
