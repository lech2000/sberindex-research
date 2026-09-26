"""A4 cross-method baseline agreement metrics (deterministic, stdlib only).

Reads two full sberindex_cluster result JSONs (kmeans + agglomerative),
verifies they share the identical territory_id mask (2190 territories) and
the same feature_names / k / seed / dataset / feature_set, then computes
label agreement from the contingency table:

- Adjusted Rand Index (Hubert-Arabie, combination counting)
- Normalized Mutual Information, arithmetic normalization
  NMI = 2 * MI / (H(U) + H(V)), natural log

No sklearn / numpy / scipy: pure Python stdlib so the gate is reproducible.

A4 is an INTERNAL baseline gate (compactness/separation/cluster sizes plus
cross-method agreement). External economic validity (do the clusters mean
anything economically) is a later A9 criterion, NOT an A4 criterion.

Current measured target on the A4 pair (2190 territories):
  ARI 0.5076373866, NMI 0.5445703145

Usage:
  python a4_metrics.py --kmeans runs/A4/kmeans.json \
      --agglomerative runs/A4/agglomerative.json --out metrics.json
  python a4_metrics.py --self-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys

EXPECTED_ARI = 0.5076373866
EXPECTED_NMI = 0.5445703145
EXPECTED_N = 2190

NOTE_A9 = (
    "A4 is an internal baseline gate (WCSS/silhouette/sizes plus "
    "cross-method ARI/NMI agreement). External economic validity of the "
    "clusters is evaluated later at A9 and is NOT an A4 criterion."
)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_result(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    for key in ("labels", "feature_names", "k", "seed", "dataset", "feature_set"):
        if key not in obj:
            raise ValueError(f"{path}: missing required key {key!r}")
    return obj


def label_map(result: dict, path: str) -> dict:
    mapping = {}
    for entry in result["labels"]:
        tid = entry["territory_id"]
        if tid in mapping:
            raise ValueError(f"{path}: duplicate territory_id {tid}")
        mapping[tid] = entry["cluster"]
    return mapping


def contingency(u: list, v: list) -> tuple[list[list[int]], list[int], list[int]]:
    cu = sorted(set(u))
    cv = sorted(set(v))
    iu = {c: i for i, c in enumerate(cu)}
    iv = {c: i for i, c in enumerate(cv)}
    table = [[0] * len(cv) for _ in cu]
    for a, b in zip(u, v):
        table[iu[a]][iv[b]] += 1
    row = [sum(r) for r in table]
    col = [sum(table[i][j] for i in range(len(cu))) for j in range(len(cv))]
    return table, row, col


def _c2(x: int) -> int:
    return x * (x - 1) // 2


def adjusted_rand_index(u: list, v: list) -> float:
    n = len(u)
    if n != len(v) or n < 2:
        raise ValueError("label vectors must have equal length >= 2")
    table, row, col = contingency(u, v)
    index = sum(_c2(c) for r in table for c in r)
    sum_row = sum(_c2(c) for c in row)
    sum_col = sum(_c2(c) for c in col)
    total = _c2(n)
    expected = sum_row * sum_col / total if total else 0.0
    maximum = (sum_row + sum_col) / 2.0
    if maximum == expected:
        return 1.0 if index == expected else 0.0
    return (index - expected) / (maximum - expected)


def normalized_mutual_info(u: list, v: list) -> float:
    n = len(u)
    if n != len(v) or n == 0:
        raise ValueError("label vectors must have equal non-zero length")
    table, row, col = contingency(u, v)
    mi = 0.0
    for i in range(len(row)):
        for j in range(len(col)):
            c = table[i][j]
            if c:
                mi += (c / n) * math.log((c * n) / (row[i] * col[j]))
    hu = -sum((c / n) * math.log(c / n) for c in row if c > 0)
    hv = -sum((c / n) * math.log(c / n) for c in col if c > 0)
    if hu + hv == 0.0:
        return 1.0 if len(set(u)) == 1 and len(set(v)) == 1 else 0.0
    return 2.0 * mi / (hu + hv)


def method_block(result: dict, file_sha256: str) -> dict:
    return {
        "method": result.get("method"),
        "wcss": result.get("wcss"),
        "silhouette_mean": result.get("silhouette_mean"),
        "silhouette_per_cluster": result.get("silhouette_per_cluster"),
        "sizes": result.get("sizes"),
        "centers": result.get("centers"),
        "territories": result.get("territories"),
        "k": result.get("k"),
        "seed": result.get("seed"),
        "dataset": result.get("dataset"),
        "feature_set": result.get("feature_set"),
        "feature_names": result.get("feature_names"),
        "file_sha256": file_sha256,
    }


def self_check() -> int:
    cases = [
        ("identical", [0, 0, 1, 1, 2, 2], [0, 0, 1, 1, 2, 2], 1.0, 1.0),
        ("permuted", [0, 0, 1, 1, 2, 2], [1, 1, 2, 2, 0, 0], 1.0, 1.0),
        (
            "partial",
            [0, 0, 0, 1, 1, 1],
            [0, 0, 1, 1, 2, 2],
            0.24242424242424246,
            0.5158037429793888,
        ),
        ("independent", [0, 0, 1, 1], [0, 1, 0, 1], -0.5, 0.0),
    ]
    ok = True
    for name, u, v, want_ari, want_nmi in cases:
        got_ari = adjusted_rand_index(u, v)
        got_nmi = normalized_mutual_info(u, v)
        ari_ok = abs(got_ari - want_ari) < 1e-9
        nmi_ok = abs(got_nmi - want_nmi) < 1e-9
        status = "PASS" if (ari_ok and nmi_ok) else "FAIL"
        if status == "FAIL":
            ok = False
        print(
            f"self-check {name}: ARI={got_ari:.10f} (want {want_ari:.10f}) "
            f"NMI={got_nmi:.10f} (want {want_nmi:.10f}) {status}"
        )
    print("self-check: ALL PASS" if ok else "self-check: FAILURES")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kmeans", default=None, help="kmeans result JSON")
    parser.add_argument(
        "--agglomerative", default=None, help="agglomerative result JSON"
    )
    parser.add_argument("--out", default=None, help="output metrics JSON path")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run tiny-label ARI/NMI checks and exit",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()

    if not args.kmeans or not args.agglomerative or not args.out:
        parser.error("--kmeans, --agglomerative and --out are required")
        return 2

    k_res = load_result(args.kmeans)
    a_res = load_result(args.agglomerative)

    for key in ("feature_names", "k", "seed", "dataset", "feature_set"):
        if k_res[key] != a_res[key]:
            raise SystemExit(
                f"consistency error: {key} differs "
                f"({k_res[key]!r} vs {a_res[key]!r})"
            )

    k_map = label_map(k_res, args.kmeans)
    a_map = label_map(a_res, args.agglomerative)
    if set(k_map) != set(a_map):
        only_k = len(set(k_map) - set(a_map))
        only_a = len(set(a_map) - set(k_map))
        raise SystemExit(
            "consistency error: territory_id mask differs "
            f"(only in kmeans: {only_k}, only in agglomerative: {only_a})"
        )
    n = len(k_map)
    if n != EXPECTED_N:
        raise SystemExit(
            f"consistency error: territory mask size {n} != expected {EXPECTED_N}"
        )
    if len(k_res["labels"]) != n or len(a_res["labels"]) != n:
        raise SystemExit("consistency error: labels length != mask size")

    ids = sorted(k_map)
    u = [k_map[i] for i in ids]
    v = [a_map[i] for i in ids]
    ari = adjusted_rand_index(u, v)
    nmi = normalized_mutual_info(u, v)

    metrics = {
        "gate": "A4",
        "status": "baseline_complete",
        "note": NOTE_A9,
        "n_territories": n,
        "consistency": {
            "territory_mask_identical": True,
            "feature_names": k_res["feature_names"],
            "k": k_res["k"],
            "seed": k_res["seed"],
            "dataset": k_res["dataset"],
            "feature_set": k_res["feature_set"],
        },
        "kmeans": method_block(k_res, sha256_file(args.kmeans)),
        "agglomerative": method_block(a_res, sha256_file(args.agglomerative)),
        "agreement": {
            "ari": ari,
            "nmi_arithmetic": nmi,
            "expected_ari": EXPECTED_ARI,
            "expected_nmi": EXPECTED_NMI,
            "ari_match": abs(ari - EXPECTED_ARI) < 1e-6,
            "nmi_match": abs(nmi - EXPECTED_NMI) < 1e-6,
        },
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")

    print(f"A4 baseline_complete: n={n} ARI={ari:.10f} NMI={nmi:.10f}")
    print(NOTE_A9)
    return 0


if __name__ == "__main__":
    sys.exit(main())
