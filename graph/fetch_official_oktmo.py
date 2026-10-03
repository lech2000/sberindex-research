#!/usr/bin/env python3
"""Fetch dated Rosstat OKTMO CSVs with a scoped, verified CA chain.

Rosstat omits its 2024 intermediate TLS certificate. Fetch the Russian root
over normally verified HTTPS, fetch the AIA intermediate, verify its signature
against that root, then pass the resulting bundle only to Rosstat requests.
Never disables TLS verification or alters the system trust store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import pandas as pd
import requests


ROOT_CA_URL = "https://gu-st.ru/content/Other/doc/russian_trusted_root_ca.cer"
SUB_CA_URL = "http://nuc-cdp.digital.gov.ru/cdp/subca_ssl_rsa2024.crt"
BASE_URL = "https://rosstat.gov.ru/opendata/7708234640-oktmo/"
STRUCTURE = "structure-20260210T1102.csv"
SNAPSHOTS = (
    "data-20231219T1512-structure-20260210T1102.csv",
    "data-20241227T1412-structure-20260210T1102.csv",
    "data-20261001T1110-structure-20260210T1102.csv",
)


def _download(url: str, verify: bool | str = True) -> bytes:
    response = requests.get(url, timeout=120, verify=verify)
    response.raise_for_status()
    return response.content


def fetch(outdir: Path, snapshots: tuple[str, ...]) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    root = _download(ROOT_CA_URL)
    sub = _download(SUB_CA_URL)
    root_path = outdir / "russian_trusted_root_ca.pem"
    sub_path = outdir / "russian_trusted_sub_ca_2024.pem"
    root_path.write_bytes(root.rstrip() + b"\n")
    sub_path.write_bytes(sub.rstrip() + b"\n")
    if b"-----BEGIN CERTIFICATE-----" not in root or b"-----BEGIN CERTIFICATE-----" not in sub:
        raise ValueError("expected PEM certificates")
    subprocess.run(["openssl", "verify", "-CAfile", str(root_path),
                    str(sub_path)], check=True, capture_output=True)
    bundle_path = outdir / "rosstat_scoped_ca_bundle.pem"
    bundle_path.write_bytes(root.rstrip() + b"\n" + sub.rstrip() + b"\n")

    meta = _download(BASE_URL + "meta.csv", str(bundle_path))
    (outdir / "meta.csv").write_bytes(meta)
    catalog = pd.read_csv(outdir / "meta.csv", encoding="cp1251", dtype=str)
    listed = set(catalog.property)
    names = (STRUCTURE, *snapshots)
    for name in names:
        if name not in listed:
            raise ValueError(f"snapshot absent from Rosstat passport: {name}")
    manifest = {
        "source": BASE_URL.rstrip("/"),
        "verification": "normal HTTPS for root; OpenSSL signature check of AIA sub; scoped requests TLS verification",
        "root_ca_sha256": hashlib.sha256(root).hexdigest(),
        "sub_ca_sha256": hashlib.sha256(sub).hexdigest(),
        "files": {"meta.csv": {"url": BASE_URL + "meta.csv",
                               "sha256": hashlib.sha256(meta).hexdigest(),
                               "bytes": len(meta)}},
    }
    for name in names:
        payload = _download(BASE_URL + name, str(bundle_path))
        (outdir / name).write_bytes(payload)
        manifest["files"][name] = {"url": BASE_URL + name,
                                   "sha256": hashlib.sha256(payload).hexdigest(),
                                   "bytes": len(payload)}
    (outdir / "fetch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--snapshot", action="append",
                        help="official CSV basename; repeat to override defaults")
    args = parser.parse_args()
    snapshots = tuple(args.snapshot) if args.snapshot else SNAPSHOTS
    manifest = fetch(args.outdir, snapshots)
    print(json.dumps({name: item["sha256"] for name, item in
                      manifest["files"].items()}, indent=2))


if __name__ == "__main__":
    main()
