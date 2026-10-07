#!/usr/bin/env python3
"""Fetch or verify frozen official acts. Never infer a municipal crosswalk."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=("fetch", "verify"))
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--http", action="store_true", help="Explicit public HTTP transport; never sends credentials")
    args = p.parse_args()
    manifest = json.loads(args.manifest.read_text())
    rows = manifest["inputs"]
    if len({x["id"] for x in rows}) != len(rows):
        raise ValueError("Duplicate official publication IDs")
    args.out.mkdir(parents=True, exist_ok=True)
    receipts = []
    for row in rows:
        ident = row["id"]
        if not re.fullmatch(r"\d{16}", ident):
            raise ValueError("Invalid official publication ID")
        parsed = urllib.parse.urlparse(row["pdf_url"])
        if parsed.hostname != "publication.pravo.gov.ru" or parsed.path != "/file/pdf" or urllib.parse.parse_qs(parsed.query) != {"eoNumber": [ident]}:
            raise ValueError("Source must be the observed official PDF endpoint")
        dest = args.out / (ident + ".pdf")
        reused = dest.exists()
        if reused:
            data = dest.read_bytes()
        elif args.mode == "verify":
            raise FileNotFoundError(dest)
        else:
            url = urllib.parse.urlunparse(parsed._replace(scheme="http" if args.http else "https"))
            with urllib.request.urlopen(url, timeout=45) as response:
                if urllib.parse.urlparse(response.url).hostname != parsed.hostname:
                    raise ValueError("Unexpected source redirect")
                data = response.read(10_000_001)
        sha = hashlib.sha256(data).hexdigest()
        if not data.startswith(b"%PDF") or len(data) != row["pdf_bytes"] or sha != row["pdf_sha256"]:
            raise ValueError(f"Changed or invalid original act: {ident}; preserve frozen input")
        if not reused:
            with dest.open("xb") as f:
                f.write(data)
        receipts.append({"id": ident, "sha256": sha, "bytes": len(data), "reused": reused})
    print(json.dumps({"status": "ORIGINAL_ACT_HASHES_VERIFIED", "files": receipts, "crosswalk_approved": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
