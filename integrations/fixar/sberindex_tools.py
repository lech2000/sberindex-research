"""Read-only analytical tools for the two SberIndex research cases.

The model never supplies a path or SQL string. It selects a named immutable
dataset, declared fields, filters and a published statistic. The service
validates the request and returns the formula with computed evidence.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import pyarrow.parquet as pq


DATA_ROOT = Path(os.getenv("SBERINDEX_DATA_DIR", "/research-data")).resolve()
DATASETS = {
    "historical_spending": "raw/sberindex-data-sense-2025/8_consumption.parquet",
    "population": "raw/sberindex-data-sense-2025/2_bdmo_population.parquet",
    "migration": "raw/sberindex-data-sense-2025/3_bdmo_migration.parquet",
    "salary": "raw/sberindex-data-sense-2025/4_bdmo_salary.parquet",
    "market_access": "raw/sberindex-data-sense-2025/1_market_access.parquet",
    "distance": "raw/sberindex-data-sense-2025/5_connection.parquet",
    "dashboard_spending": "raw/sberindex-dashboard-current/municipal-consumer-spending.parquet",
    "dashboard_mobility": "raw/sberindex-dashboard-current/mobility-index.parquet",
    "municipal_dictionary": "raw/sberindex-data-sense-2025/municipal_dictionary.parquet",
}
FILTER_FIELDS = {
    "territory_id", "territory_id_x", "territory_id_y", "date", "year",
    "period", "category", "category_15", "mo", "ref_area", "gender",
    "age", "okved_letter", "okved_name", "indicator_id", "kpi_id",
    "obs_status", "freq", "unit_measure",
}
METRICS = {
    "gini", "hhi", "coefficient_of_variation", "theil_t", "trend_slope",
    "acf", "seasonal_naive_mae", "robust_outlier_share",
}
NORMALIZERS = {"zscore", "robust_z", "minmax", "log1p", "mean_index_100"}


def sberindex_public_channel_record(
    label: str,
    platform: str,
    public_url: str,
    channel_kind: str,
    officiality: str,
    source_ref: str,
    checked_at: str,
    oktmo: str,
    latitude: float,
    longitude: float,
    geocode_precision: str,
    municipality_label: str,
    valid_from: str = "",
) -> dict[str, Any]:
    """Build one normalized public-channel graph fragment without writing it."""
    platform = platform.strip().lower()
    if platform not in {"telegram", "max"}:
        raise ValueError("platform must be telegram or max")
    parsed = urlparse(public_url.strip())
    allowed_hosts = {"telegram": {"t.me", "telegram.me"}, "max": {"max.ru"}}
    if parsed.scheme != "https" or parsed.hostname not in allowed_hosts[platform]:
        raise ValueError("public_url does not match platform")
    handle = parsed.path.strip("/")
    if not handle or "/" in handle or not re.fullmatch(r"[A-Za-z0-9_.-]+", handle):
        raise ValueError("public_url must identify one public channel or chat")
    if channel_kind not in {"channel", "chat"}:
        raise ValueError("channel_kind must be channel or chat")
    if officiality not in {"confirmed", "candidate", "unverified"}:
        raise ValueError("unsupported officiality")
    source = urlparse(source_ref.strip())
    if source.scheme != "https" or not source.hostname:
        raise ValueError("source_ref must be a public HTTPS URL")
    if officiality == "confirmed" and source.hostname in allowed_hosts[platform]:
        raise ValueError("confirmed requires an independent official source_ref")
    try:
        checked = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("checked_at must be ISO 8601") from exc
    if checked.tzinfo is None:
        raise ValueError("checked_at must include timezone")
    if not re.fullmatch(r"[0-9]{8}(?:[0-9]{3})?", oktmo):
        raise ValueError("oktmo must contain 8 or 11 digits")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError("coordinates are outside WGS84 bounds")
    if geocode_precision not in {"building", "street", "settlement", "municipality_centroid"}:
        raise ValueError("unsupported geocode_precision")
    if not label.strip() or not municipality_label.strip():
        raise ValueError("labels must not be empty")
    if valid_from:
        try:
            datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("valid_from must be ISO 8601") from exc

    channel_id = f"public_channel:{platform}:{handle.lower()}"
    municipality_id = f"municipality:oktmo:{oktmo}"
    canonical_url = f"https://{parsed.hostname}/{handle}"
    channel = {
        "entity_id": channel_id,
        "entity_type": "public_channel",
        "label": label.strip(),
        "platform": platform,
        "public_url": canonical_url,
        "channel_kind": channel_kind,
        "officiality": officiality,
        "source_ref": source_ref.strip(),
        "checked_at": checked.isoformat(),
        "oktmo": oktmo,
        "latitude": float(latitude),
        "longitude": float(longitude),
        "geocode_precision": geocode_precision,
        "provenance_class": "observed",
        "valid_from": valid_from or None,
        "valid_to": None,
    }
    municipality = {
        "entity_id": municipality_id,
        "entity_type": "municipality",
        "label": municipality_label.strip(),
        "provenance_class": "observed",
        "valid_from": None,
        "valid_to": None,
        "source_ref": source_ref.strip(),
    }
    relation = {
        "source_entity_id": channel_id,
        "target_entity_id": municipality_id,
        "relation_type": "SERVES_TERRITORY",
        "provenance_class": "observed",
        "confidence": 1.0 if officiality == "confirmed" else 0.7,
        "evidence_url": source_ref.strip(),
        "valid_from": valid_from or None,
        "valid_to": None,
    }
    return {"entities": [municipality, channel], "relations": [relation]}


def _path(dataset: str) -> Path:
    relative = DATASETS.get(dataset)
    if not relative:
        raise ValueError(f"unknown dataset {dataset!r}; allowed: {sorted(DATASETS)}")
    path = (DATA_ROOT / relative).resolve()
    if DATA_ROOT not in path.parents or not path.is_file():
        raise ValueError(f"dataset {dataset!r} is unavailable")
    return path


@lru_cache(maxsize=len(DATASETS))
def _metadata(dataset: str) -> dict[str, Any]:
    path = _path(dataset)
    parquet = pq.ParquetFile(path)
    columns = [
        field.name for field in parquet.schema_arrow
        if not field.name.startswith("__index_level_")
    ]
    return {
        "dataset": dataset,
        "rows": parquet.metadata.num_rows,
        "columns": columns,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "storage": "immutable parquet mounted read-only",
    }


def _validate_columns(dataset: str, columns: list[str] | None) -> list[str]:
    available = _metadata(dataset)["columns"]
    selected = columns or available
    unknown = set(selected) - set(available)
    if unknown:
        raise ValueError(f"unknown columns for {dataset}: {sorted(unknown)}")
    if len(selected) > 16:
        raise ValueError("at most 16 columns may be returned")
    return list(dict.fromkeys(selected))


def _validate_filters(dataset: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    clean = dict(filters or {})
    available = set(_metadata(dataset)["columns"])
    unknown = set(clean) - FILTER_FIELDS
    absent = set(clean) - available
    if unknown:
        raise ValueError(f"unsupported filters: {sorted(unknown)}")
    if absent:
        raise ValueError(f"filters absent from {dataset}: {sorted(absent)}")
    if dataset == "distance" and not ({"territory_id_x", "territory_id_y"} & set(clean)):
        raise ValueError("distance queries require territory_id_x or territory_id_y")
    for key, value in clean.items():
        if isinstance(value, list) and not (1 <= len(value) <= 200):
            raise ValueError(f"filter {key} list must contain 1..200 values")
        if isinstance(value, (dict, tuple, set)):
            raise ValueError(f"filter {key} must be a scalar or list")
    return clean


def _read_dataset(dataset: str, columns: list[str] | None = None,
                  filters: dict[str, Any] | None = None) -> pd.DataFrame:
    selected = _validate_columns(dataset, columns)
    clean = _validate_filters(dataset, filters)
    needed = list(dict.fromkeys(selected + list(clean)))
    frame = pd.read_parquet(_path(dataset), columns=needed)
    for field, expected in clean.items():
        frame = frame[frame[field].isin(expected)] if isinstance(expected, list) \
            else frame[frame[field] == expected]
    return frame[selected]


def _json_rows(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    safe = frame.head(limit).replace({np.nan: None})
    return safe.to_dict(orient="records")


def sberindex_data_catalog(dataset: str = "") -> dict[str, Any]:
    names = [dataset] if dataset else sorted(DATASETS)
    return {"datasets": [_metadata(name) for name in names]}


def sberindex_query_data(dataset: str, columns: list[str] | None = None,
                         filters: dict[str, Any] | None = None,
                         limit: int = 50) -> dict[str, Any]:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    frame = _read_dataset(dataset, columns, filters)
    return {
        "dataset": dataset, "filters": filters or {},
        "matched_rows": len(frame), "returned_rows": min(len(frame), limit),
        "truncated": len(frame) > limit, "rows": _json_rows(frame, limit),
    }


def _normalize_array(values: pd.Series, method: str) -> pd.Series:
    x = pd.to_numeric(values, errors="coerce").astype(float)
    if method == "zscore":
        sigma = x.std(ddof=0)
        return (x - x.mean()) / sigma if sigma and math.isfinite(sigma) else x * 0
    if method == "robust_z":
        median = x.median()
        mad = (x - median).abs().median()
        return 0.67448975 * (x - median) / mad if mad else x * 0
    if method == "minmax":
        width = x.max() - x.min()
        return (x - x.min()) / width if width else x * 0
    if method == "log1p":
        if (x.dropna() <= -1).any():
            raise ValueError("log1p requires every finite value to be greater than -1")
        return np.log1p(x)
    if method == "mean_index_100":
        mean = x.mean()
        return x / mean * 100 if mean else x * 0
    raise ValueError(f"unknown method {method!r}; allowed: {sorted(NORMALIZERS)}")


def sberindex_normalize(dataset: str, value_column: str = "value",
                        method: str = "zscore", group_by: list[str] | None = None,
                        filters: dict[str, Any] | None = None,
                        limit: int = 100) -> dict[str, Any]:
    if method not in NORMALIZERS:
        raise ValueError(f"unknown method {method!r}; allowed: {sorted(NORMALIZERS)}")
    groups = group_by or []
    frame = _read_dataset(dataset, list(dict.fromkeys(groups + [value_column])), filters)
    if len(frame) > 750_000:
        raise ValueError("selection exceeds 750000 rows; narrow it with filters")
    if groups:
        frame["normalized_value"] = frame.groupby(groups, dropna=False)[value_column].transform(
            lambda series: _normalize_array(series, method))
    else:
        frame["normalized_value"] = _normalize_array(frame[value_column], method)
    formulas = {
        "zscore": "z=(x-mean(x))/population_sd(x)",
        "robust_z": "z_r=0.67448975*(x-median(x))/MAD(x)",
        "minmax": "x'=(x-min(x))/(max(x)-min(x))",
        "log1p": "x'=ln(1+x)",
        "mean_index_100": "index=100*x/mean(x)",
    }
    numeric = pd.to_numeric(frame[value_column], errors="coerce")
    return {
        "dataset": dataset, "method": method, "formula": formulas[method],
        "group_by": groups, "matched_rows": len(frame),
        "source_summary": {"count": int(numeric.count()),
                           "mean": float(numeric.mean()),
                           "std_population": float(numeric.std(ddof=0))},
        "rows": _json_rows(frame, min(max(limit, 1), 200)),
    }


def _metric(values: np.ndarray, metric: str, lag: int,
            threshold: float) -> tuple[float | None, str]:
    x = values[np.isfinite(values)].astype(float)
    if x.size == 0:
        return None, "no finite observations"
    if metric == "gini":
        if (x < 0).any() or x.sum() == 0:
            raise ValueError("gini requires nonnegative values with positive sum")
        ordered, n = np.sort(x), x.size
        value = 2 * np.dot(np.arange(1, n + 1), ordered) / (n * ordered.sum()) - (n + 1) / n
        return float(value), "G=(2*sum(i*x_i))/(n*sum(x))-(n+1)/n"
    if metric == "hhi":
        if (x < 0).any() or x.sum() == 0:
            raise ValueError("hhi requires nonnegative values with positive sum")
        return float(np.square(x / x.sum()).sum()), "HHI=sum((x_i/sum(x))^2)"
    if metric == "coefficient_of_variation":
        if x.mean() == 0:
            raise ValueError("coefficient of variation is undefined at zero mean")
        return float(x.std(ddof=0) / abs(x.mean())), "CV=population_sd(x)/abs(mean(x))"
    if metric == "theil_t":
        if (x <= 0).any():
            raise ValueError("Theil T requires strictly positive values")
        ratio = x / x.mean()
        return float(np.mean(ratio * np.log(ratio))), "T=mean((x/mean(x))*ln(x/mean(x)))"
    if metric == "trend_slope":
        return ((float(np.polyfit(np.arange(x.size), x, 1)[0]), "OLS slope of x_t on integer t")
                if x.size >= 2 else (None, "at least two observations required"))
    if metric == "acf":
        if not 1 <= lag < x.size:
            return None, "lag must be smaller than the observation count"
        left, right = x[:-lag] - x.mean(), x[lag:] - x.mean()
        denom = float(np.dot(x - x.mean(), x - x.mean()))
        return (float(np.dot(left, right) / denom) if denom else None,
                "ACF(k)=sum((x_t-mean)*(x_t-k-mean))/sum((x_t-mean)^2)")
    if metric == "seasonal_naive_mae":
        if not 1 <= lag < x.size:
            return None, "seasonal lag must be smaller than the observation count"
        return float(np.mean(np.abs(x[lag:] - x[:-lag]))), "MAE_s=mean(abs(x_t-x_t-s))"
    if metric == "robust_outlier_share":
        median, mad = np.median(x), np.median(np.abs(x - np.median(x)))
        score = np.zeros_like(x) if mad == 0 else 0.67448975 * (x - median) / mad
        return float(np.mean(np.abs(score) > threshold)), "mean(abs(0.67448975*(x-median)/MAD)>threshold)"
    raise ValueError(f"unknown metric {metric!r}; allowed: {sorted(METRICS)}")


def sberindex_scientific_metric(dataset: str, metric: str,
                                value_column: str = "value",
                                group_by: list[str] | None = None,
                                time_column: str = "",
                                filters: dict[str, Any] | None = None,
                                lag: int = 12, threshold: float = 3.5) -> dict[str, Any]:
    if metric not in METRICS:
        raise ValueError(f"unknown metric {metric!r}; allowed: {sorted(METRICS)}")
    groups = group_by or []
    columns = list(dict.fromkeys(groups + ([time_column] if time_column else []) + [value_column]))
    frame = _read_dataset(dataset, columns, filters)
    if len(frame) > 750_000:
        raise ValueError("selection exceeds 750000 rows; narrow it with filters")
    if time_column:
        frame = frame.sort_values(groups + [time_column])
    grouped = [((), frame)] if not groups else frame.groupby(groups, dropna=False, sort=True)
    results, formula = [], ""
    for key, part in grouped:
        value, formula = _metric(pd.to_numeric(part[value_column], errors="coerce").to_numpy(),
                                 metric, lag, threshold)
        key_tuple = key if isinstance(key, tuple) else (key,)
        results.append({"group": dict(zip(groups, key_tuple)),
                        "observations": int(part[value_column].notna().sum()),
                        "value": value})
        if len(results) >= 200:
            break
    return {"dataset": dataset, "metric": metric, "formula": formula,
            "lag": lag, "threshold": threshold, "group_by": groups,
            "groups_returned": len(results), "results": results}


def sberindex_spatial_moran(dataset: str, value_column: str = "value",
                            filters: dict[str, Any] | None = None,
                            k_neighbors: int = 8,
                            permutations: int = 99) -> dict[str, Any]:
    if dataset not in {"historical_spending", "population", "migration", "salary", "market_access"}:
        raise ValueError("dataset has no historical territory_id namespace")
    if not 2 <= k_neighbors <= 20 or not 0 <= permutations <= 199:
        raise ValueError("k_neighbors=2..20 and permutations=0..199 are required")
    values = _read_dataset(dataset, ["territory_id", value_column], filters)
    values[value_column] = pd.to_numeric(values[value_column], errors="coerce")
    series = values.groupby("territory_id")[value_column].mean().dropna()
    if not 10 <= len(series) <= 3000:
        raise ValueError("Moran I requires 10..3000 territories after filtering")
    edges = pd.read_parquet(_path("distance"), columns=["territory_id_x", "territory_id_y", "distance"])
    ids = set(int(i) for i in series.index)
    edges = edges[(edges.territory_id_x.isin(ids)) & (edges.territory_id_y.isin(ids)) & (edges.distance > 0)]
    reverse = edges.rename(columns={"territory_id_x": "territory_id_y", "territory_id_y": "territory_id_x"})
    edges = pd.concat([edges, reverse], ignore_index=True)
    edges = edges.sort_values(["territory_id_x", "distance"]).groupby("territory_id_x", sort=False).head(k_neighbors)
    id_list = sorted(ids)
    pos = {value: idx for idx, value in enumerate(id_list)}
    # Arrow-backed pandas frames may expose a read-only NumPy view in the
    # production image. Moran centering is intentionally local and mutable.
    z = series.reindex(id_list).to_numpy(dtype=float, copy=True)
    z -= z.mean()
    by_source = {int(key): part for key, part in edges.groupby("territory_id_x")}
    neighbors = []
    for source in id_list:
        part = by_source.get(source)
        if part is None or part.empty:
            neighbors.append((np.array([], dtype=int), np.array([], dtype=float)))
            continue
        targets = np.array([pos[int(v)] for v in part.territory_id_y], dtype=int)
        weights = 1.0 / part.distance.to_numpy(float)
        neighbors.append((targets, weights / weights.sum()))

    def moran(vector: np.ndarray) -> float:
        numerator = sum(vector[i] * float(np.dot(w, vector[target]))
                        for i, (target, w) in enumerate(neighbors) if len(target))
        s0 = sum(float(w.sum()) for target, w in neighbors if len(target))
        return float(len(vector) / s0 * numerator / np.dot(vector, vector))

    observed, p_value = moran(z), None
    if permutations:
        rng = np.random.default_rng(20260920)
        simulated = np.array([moran(rng.permutation(z)) for _ in range(permutations)])
        p_value = float((1 + np.sum(np.abs(simulated) >= abs(observed))) / (permutations + 1))
    return {
        "dataset": dataset, "territories": len(id_list), "k_neighbors": k_neighbors,
        "weight": "row-normalized inverse distance",
        "formula": "I=(n/S0)*sum_i(sum_j(w_ij*z_i*z_j))/sum_i(z_i^2)",
        "moran_i": observed, "expected_under_randomization": -1 / (len(id_list) - 1),
        "permutations": permutations, "two_sided_permutation_p": p_value,
        "aggregation": "mean per territory after filters",
    }


_DATASET_ENUM = sorted(DATASETS)
_FILTER_SCHEMA = {"type": "object", "additionalProperties": {"anyOf": [
    {"type": ["string", "number", "integer", "boolean"]},
    {"type": "array", "minItems": 1, "maxItems": 200,
     "items": {"type": ["string", "number", "integer", "boolean"]}},
]}}

_CLUSTER_METHODS = {"agglomerative", "kmeans"}
_CLUSTER_FEATURES = {"shares", "shares_log_volume", "volume"}


def _spending_panel(filters: dict[str, Any] | None = None) -> pd.DataFrame:
    """МО × категория за 2023–2024 из historical_spending.

    Возвращает длинную таблицу [territory_id, date, category, value].
    Только historical_spending: у него есть territory_id и date, в отличие
    от dashboard-копии (mo/period без устойчивого ключа).
    """
    frame = _read_dataset(
        "historical_spending",
        ["territory_id", "date", "category", "value"], filters)
    frame = frame.copy()
    frame["territory_id"] = pd.to_numeric(
        frame["territory_id"], errors="coerce").astype("Int64")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["territory_id", "date", "category", "value"])
    frame = frame[frame["value"] >= 0]
    return frame


def _cluster_features(panel: pd.DataFrame,
                       feature_set: str) -> tuple[list[int], list[str], np.ndarray]:
    """Построить матрицу признаков МО × признаки.

    shares: доля каждой категории в среднем чеке МО (структура без масштаба).
    shares_log_volume: shares + log1p среднего объёма (структура + масштаб).
    volume: только log1p среднего объёма (масштаб без структуры).
    Возвращает (territory_ids, feature_names, X).
    """
    pivot = panel.pivot_table(index="territory_id", columns="category",
                              values="value", aggfunc="mean").fillna(0.0)
    categories = sorted(str(c) for c in pivot.columns)
    pivot = pivot[categories]
    totals = pivot.to_numpy(dtype=float).sum(axis=1, keepdims=True)
    totals[totals == 0] = 1.0
    shares = pivot.to_numpy(dtype=float) / totals
    mean_volume = pivot.to_numpy(dtype=float).mean(axis=1)
    log_volume = np.log1p(np.maximum(mean_volume, 0.0)).reshape(-1, 1)
    if feature_set == "shares":
        names = [f"share:{c}" for c in categories]
        return ([int(i) for i in pivot.index], names, shares)
    if feature_set == "shares_log_volume":
        names = [f"share:{c}" for c in categories] + ["log_volume"]
        return ([int(i) for i in pivot.index], names,
                np.hstack([shares, log_volume]))
    names = ["log_volume"]
    return ([int(i) for i in pivot.index], names, log_volume)


def _kmeans_plus_plus(rng: np.random.Generator, x: np.ndarray,
                      k: int) -> np.ndarray:
    """Инициализация k-means++: первый центр случайно, остальные —
    пропорционально квадрату расстояния до ближайшего центра."""
    n = x.shape[0]
    first = int(rng.integers(n))
    centers = [x[first].copy()]
    nearest_sq = ((x - centers[0]) ** 2).sum(axis=1)
    for _ in range(1, k):
        total = float(nearest_sq.sum())
        if total <= 0:
            centers.append(x[int(rng.integers(n))].copy())
            continue
        probs = nearest_sq / total
        choice = int(rng.choice(n, p=probs))
        centers.append(x[choice].copy())
        dist_sq = ((x - centers[-1]) ** 2).sum(axis=1)
        nearest_sq = np.minimum(nearest_sq, dist_sq)
    return np.array(centers)


def _kmeans(x: np.ndarray, k: int, seed: int,
            max_iter: int = 100) -> tuple[np.ndarray, np.ndarray, float]:
    """Lloyd k-means на евклидовой метрике. Возвращает (labels, centers, wcss)."""
    rng = np.random.default_rng(seed)
    centers = _kmeans_plus_plus(rng, x, k)
    labels = np.zeros(x.shape[0], dtype=int)
    for _ in range(max_iter):
        dist = ((x[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new_labels = dist.argmin(axis=1)
        new_centers = centers.copy()
        for c in range(k):
            members = x[new_labels == c]
            if len(members):
                new_centers[c] = members.mean(axis=0)
            else:
                new_centers[c] = x[int(rng.integers(x.shape[0]))]
        if bool((new_labels == labels).all()) and bool(
                np.allclose(new_centers, centers)):
            labels = new_labels
            centers = new_centers
            break
        labels, centers = new_labels, new_centers
    wcss = float(((x - centers[labels]) ** 2).sum())
    return labels, centers, wcss


def _agglomerative_ward(x: np.ndarray, k: int,
                        seed: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Иерархическая кластеризация Ward на евклидовой метрике.

    Та же z-scored матрица, что у kmeans. Детерминирована: seed входит
    в контракт и возвращается в отчёте, tie-break фиксирован порядком
    linkage/fcluster. Возвращает (labels, centers, wcss) в той же схеме.
    """
    from scipy.cluster.hierarchy import fcluster, linkage
    _ = seed
    height = linkage(x, method="ward")
    flat = fcluster(height, t=int(k), criterion="maxclust")
    labels = (np.asarray(flat, dtype=int) - 1).copy()
    centers = np.array([x[labels == c].mean(axis=0) if bool((labels == c).any())
                        else x.mean(axis=0) for c in range(int(k))])
    wcss = float(((x - centers[labels]) ** 2).sum())
    return labels, centers, wcss


def _self_check_cluster_methods() -> dict[str, Any]:
    """Детерминированная самопроверка двух семейств A4 на крошечной X."""
    rng = np.random.default_rng(20260921)
    group_a = rng.normal(loc=-3.0, scale=0.2, size=(4, 2))
    group_b = rng.normal(loc=3.0, scale=0.2, size=(4, 2))
    raw = np.vstack([group_a, group_b])
    means, stds = raw.mean(axis=0), raw.std(axis=0)
    stds[stds == 0] = 1.0
    x = (raw - means) / stds
    report: dict[str, Any] = {"n": int(x.shape[0]), "methods": {}}
    kmeans_labels, kmeans_centers, kmeans_wcss = _kmeans(x, 2, 20260921)
    sil_mean, sil_clusters = _silhouette_sample(x, kmeans_labels, 2)
    report["methods"]["kmeans"] = {
        "labels": [int(v) for v in kmeans_labels],
        "wcss": kmeans_wcss, "silhouette_mean": sil_mean,
        "silhouette_per_cluster": sil_clusters,
        "centers": [list(map(float, row)) for row in kmeans_centers],
    }
    assert len(set(int(v) for v in kmeans_labels)) == 2
    assert kmeans_centers.shape == (2, 2) and math.isfinite(kmeans_wcss)
    try:
        from scipy.cluster.hierarchy import fcluster, linkage  # noqa: F401
    except ImportError:
        report["methods"]["agglomerative"] = "skipped: scipy unavailable"
        return report
    agg_labels, agg_centers, agg_wcss = _agglomerative_ward(x, 2, 20260921)
    agg_sil, agg_sil_clusters = _silhouette_sample(x, agg_labels, 2)
    report["methods"]["agglomerative"] = {
        "labels": [int(v) for v in agg_labels],
        "wcss": agg_wcss, "silhouette_mean": agg_sil,
        "silhouette_per_cluster": agg_sil_clusters,
        "centers": [list(map(float, row)) for row in agg_centers],
    }
    assert len(set(int(v) for v in agg_labels)) == 2
    assert agg_centers.shape == (2, 2) and math.isfinite(agg_wcss)
    assert -1.0 <= agg_sil <= 1.0
    repeat = _agglomerative_ward(x, 2, 20260921)[0]
    assert [int(v) for v in repeat] == [int(v) for v in agg_labels]
    return report


def _silhouette_sample(x: np.ndarray, labels: np.ndarray,
                       k: int) -> tuple[float, list[float]]:
    """Средний силуэт и силуэты кластеров. O(n²): панель МО это тянет."""
    n = x.shape[0]
    if k < 2 or k >= n:
        return 0.0, [0.0] * k
    diff = x[:, None, :] - x[None, :, :]
    dist = np.sqrt((diff ** 2).sum(axis=2))
    silhouettes = np.zeros(n)
    for i in range(n):
        same = (labels == labels[i])
        same[i] = False
        intra = float(dist[i][same].mean()) if same.any() else 0.0
        inter = min(float(dist[i][labels == c].mean())
                    for c in range(k) if c != labels[i]
                    and bool((labels == c).any()))
        denom = max(intra, inter)
        silhouettes[i] = (inter - intra) / denom if denom > 0 else 0.0
    per_cluster = [float(silhouettes[labels == c].mean())
                   if bool((labels == c).any()) else 0.0 for c in range(k)]
    return float(silhouettes.mean()), per_cluster


def sberindex_crosswalk() -> dict[str, Any]:
    """Связка territory_id панели расходов со словарём СберИндекса (A1).

    Прямой join по territory_id: сколько ID панели имеют запись в словаре,
    сколько актуальных записей словаря покрыто панелью. Формула и обе
    стороны фиксированы, без ОКТМО-посредника.
    """
    panel = _read_dataset("historical_spending", ["territory_id"])
    panel_ids = set(int(t) for t in pd.to_numeric(
        panel["territory_id"], errors="coerce").dropna().unique())
    ref = _read_dataset("municipal_dictionary", ["territory_id"])
    ref_ids = set(int(t) for t in pd.to_numeric(
        ref["territory_id"], errors="coerce").dropna().unique())
    matched = panel_ids & ref_ids
    return {
        "formula": "coverage=|panel∩dict|/|panel| по territory_id, прямое равенство",
        "panel_territories": len(panel_ids),
        "dictionary_territories": len(ref_ids),
        "matched": len(matched),
        "coverage": (len(matched) / len(panel_ids)) if panel_ids else None,
        "panel_only": sorted(panel_ids - ref_ids)[:50],
        "dictionary_only_count": len(ref_ids - panel_ids),
        "unmatched_panel": len(panel_ids - matched),
    }


def sberindex_cluster(dataset: str = "historical_spending",
                       feature_set: str = "shares",
                       method: str = "kmeans",
                       k: int = 5, seed: int = 20260921,
                       filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Кластеризовать МО (E01/E04, ворота A4): два семейства.

    Признаки строятся из historical_spending (средние за 2023–2024);
    метод kmeans или agglomerative (Ward); seed фиксирует k-means++
    и все tie-break, в отчёте возвращается всегда. Без GMM.
    Возвращает метки, центры, размеры, WCSS и средний силуэт.
    """
    if dataset != "historical_spending":
        raise ValueError("кластеризация работает только на historical_spending")
    if feature_set not in _CLUSTER_FEATURES:
        raise ValueError(f"unknown feature_set {feature_set!r}; "
                         f"allowed: {sorted(_CLUSTER_FEATURES)}")
    if method not in _CLUSTER_METHODS:
        raise ValueError(f"unknown method {method!r}; "
                         f"allowed: {sorted(_CLUSTER_METHODS)}")
    if not 2 <= k <= 20:
        raise ValueError("k=2..20")
    panel = _spending_panel(filters)
    if panel["territory_id"].nunique() < k + 1:
        raise ValueError("территорий меньше, чем k+1")
    ids, names, raw = _cluster_features(panel, feature_set)
    means = raw.mean(axis=0)
    stds = raw.std(axis=0)
    stds[stds == 0] = 1.0
    x = (raw - means) / stds
    formulas = {
        "kmeans": "z-scored features, euclidean Lloyd k-means++",
        "agglomerative": "z-scored features, euclidean Ward linkage",
    }
    labels, centers, wcss = (_kmeans(x, k, seed) if method == "kmeans"
                             else _agglomerative_ward(x, k, seed))
    sil_mean, sil_clusters = _silhouette_sample(x, labels, k)
    sizes = [int((labels == c).sum()) for c in range(k)]
    return {
        "dataset": dataset, "method": method, "feature_set": feature_set,
        "formula": formulas[method],
        "k": k, "seed": seed, "territories": len(ids),
        "feature_names": names,
        "sizes": sizes, "wcss": wcss,
        "silhouette_mean": sil_mean, "silhouette_per_cluster": sil_clusters,
        "labels": [{"territory_id": tid, "cluster": int(lab)}
                   for tid, lab in zip(ids, labels, strict=True)],
        "centers": [list(map(float, row)) for row in centers],
        "aggregation": "mean 2023-2024 per territory x category",
        "panel_rows": len(panel),
    }


def sberindex_forecast(dataset: str = "historical_spending",
                        horizon: int = 1,
                        filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """Бейзлайны прогноза расходов МО (R2, ворота Radar): last value,
    seasonal naive (лаг 12) и среднее train. Оценка — expanding origin
    2024-07..2024-12-horizon, метрика MAE micro/macro на общей маске."""
    if dataset != "historical_spending":
        raise ValueError("прогноз работает только на historical_spending")
    if not 1 <= horizon <= 3:
        raise ValueError("horizon=1..3")
    panel = _spending_panel(filters)
    panel["ym"] = panel["date"].dt.to_period("M").astype(str)
    months = sorted(panel["ym"].unique())
    if len(months) < 14:
        raise ValueError("нужно минимум 14 месяцев истории")
    test_months = months[-6:]
    series = {(int(t), str(c), str(m)): float(g["value"].mean())
              for (t, c, m), g in panel.groupby(
                  ["territory_id", "category", "ym"])}
    keys = list(series.keys())
    origins = test_months[:len(test_months) - horizon + 1]
    if not origins:
        raise ValueError("горизонт не влезает в тестовое окно")
    errors: dict[str, list[float]] = {
        "last_value": [], "seasonal_naive": [], "train_mean": []}
    per_mo: dict[int, list[float]] = {}
    for tid, cat, month in keys:
        if month not in test_months:
            continue
        try:
            target_idx = months.index(month)
        except ValueError:
            continue
        history = [series.get((tid, cat, m)) for m in months[:target_idx]]
        history = [h for h in history if h is not None]
        if len(history) < 12:
            continue
        actual = series[(tid, cat, month)]
        preds = {
            "last_value": history[-horizon],
            "seasonal_naive": (history[-12 - horizon + 1]
                               if len(history) >= 12 + horizon - 1 else None),
            "train_mean": sum(history) / len(history),
        }
        for name, pred in preds.items():
            if pred is None:
                continue
            err = abs(actual - pred)
            errors[name].append(err)
            per_mo.setdefault(tid, []).append(err if name == "last_value" else 0.0)
    if not errors["last_value"]:
        raise ValueError("нет сопоставимых наблюдений в тестовом окне")

    def _mae(vals: list[float]) -> float | None:
        return float(sum(vals) / len(vals)) if vals else None

    # macro: средний MAE last_value по территориям
    by_territory: dict[int, list[float]] = {}
    for tid, cat, month in keys:
        if month not in test_months:
            continue
        try:
            target_idx = months.index(month)
        except ValueError:
            continue
        history = [series.get((tid, cat, m)) for m in months[:target_idx]]
        history = [h for h in history if h is not None]
        if len(history) < 12:
            continue
        actual = series[(tid, cat, month)]
        by_territory.setdefault(tid, []).append(abs(actual - history[-horizon]))
    macro_vals = [_mae(v) for v in by_territory.values() if v]
    macro_vals = [v for v in macro_vals if v is not None]
    return {
        "dataset": dataset, "horizon": horizon,
        "formula": "MAE=mean(|y-yhat|) on expanding origins",
        "origins": origins, "test_months": test_months,
        "n_observations": len(errors["last_value"]),
        "n_territories": len(by_territory),
        "mae_micro": {name: _mae(vals) for name, vals in errors.items()},
        "mae_macro_last_value": (float(sum(macro_vals) / len(macro_vals))
                                 if macro_vals else None),
        "aggregation": "mean per territory x category x month",
    }

SBERINDEX_TOOL_SPECS = [
    {"name": "sberindex_public_channel_record", "description": "Детерминированно нормализовать одну проверенную публичную Telegram/MAX-площадку, геотег муниципалитета и связь SERVES_TERRITORY; ничего не записывает", "fn": sberindex_public_channel_record,
     "parameters": {"type": "object", "properties": {
         "label": {"type": "string", "minLength": 1, "maxLength": 500},
         "platform": {"type": "string", "enum": ["telegram", "max"]},
         "public_url": {"type": "string", "maxLength": 2000},
         "channel_kind": {"type": "string", "enum": ["channel", "chat"]},
         "officiality": {"type": "string", "enum": ["confirmed", "candidate", "unverified"]},
         "source_ref": {"type": "string", "maxLength": 2000},
         "checked_at": {"type": "string", "maxLength": 64},
         "oktmo": {"type": "string", "pattern": "^[0-9]{8}([0-9]{3})?$"},
         "latitude": {"type": "number", "minimum": -90, "maximum": 90},
         "longitude": {"type": "number", "minimum": -180, "maximum": 180},
         "geocode_precision": {"type": "string", "enum": ["building", "street", "settlement", "municipality_centroid"]},
         "municipality_label": {"type": "string", "minLength": 1, "maxLength": 500},
         "valid_from": {"type": "string", "maxLength": 64}
     }, "required": ["label", "platform", "public_url", "channel_kind", "officiality", "source_ref", "checked_at", "oktmo", "latitude", "longitude", "geocode_precision", "municipality_label"], "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_data_catalog", "description": "Каталог, схема, число строк и SHA-256 загруженных наборов СберИндекса и дополнений", "fn": sberindex_data_catalog,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": [""] + _DATASET_ENUM}}, "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_query_data", "description": "Безопасный запрос к неизменяемым Parquet: только именованные таблицы, поля и фильтры, без SQL и путей", "fn": sberindex_query_data,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": _DATASET_ENUM}, "columns": {"type": "array", "maxItems": 16, "items": {"type": "string"}}, "filters": _FILTER_SCHEMA, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["dataset"], "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_normalize", "description": "Нормализация показателя: z-score, robust z/MAD, min-max, log1p или индекс к среднему=100", "fn": sberindex_normalize,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": _DATASET_ENUM}, "value_column": {"type": "string"}, "method": {"type": "string", "enum": sorted(NORMALIZERS)}, "group_by": {"type": "array", "maxItems": 4, "items": {"type": "string"}}, "filters": _FILTER_SCHEMA, "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["dataset", "method"], "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_scientific_metric", "description": "Расчёт Gini, HHI, CV, Theil T, тренда, ACF, seasonal-naive MAE или доли MAD-выбросов с формулой", "fn": sberindex_scientific_metric,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": _DATASET_ENUM}, "metric": {"type": "string", "enum": sorted(METRICS)}, "value_column": {"type": "string"}, "group_by": {"type": "array", "maxItems": 4, "items": {"type": "string"}}, "time_column": {"type": "string"}, "filters": _FILTER_SCHEMA, "lag": {"type": "integer", "minimum": 1, "maximum": 60}, "threshold": {"type": "number", "minimum": 1, "maximum": 10}}, "required": ["dataset", "metric"], "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_spatial_moran", "description": "Глобальный Moran I по historical territory_id, k ближайшим соседям и обратному расстоянию; с permutation p-value", "fn": sberindex_spatial_moran,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": ["historical_spending", "population", "migration", "salary", "market_access"]}, "value_column": {"type": "string"}, "filters": _FILTER_SCHEMA, "k_neighbors": {"type": "integer", "minimum": 2, "maximum": 20}, "permutations": {"type": "integer", "minimum": 0, "maximum": 199}}, "required": ["dataset"], "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_cluster", "description": "Кластеризация МО по структуре расходов (E01/A4): kmeans или agglomerative Ward; метки, центры, размеры, WCSS и силуэт", "fn": sberindex_cluster,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": ["historical_spending"]}, "feature_set": {"type": "string", "enum": sorted(_CLUSTER_FEATURES)}, "method": {"type": "string", "enum": sorted(_CLUSTER_METHODS)}, "k": {"type": "integer", "minimum": 2, "maximum": 20}, "seed": {"type": "integer", "minimum": 1}, "filters": _FILTER_SCHEMA}, "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_forecast", "description": "Бейзлайны прогноза расходов МО (R2): last value, seasonal naive, train mean; MAE micro/macro на общей маске", "fn": sberindex_forecast,
     "parameters": {"type": "object", "properties": {"dataset": {"type": "string", "enum": ["historical_spending"]}, "horizon": {"type": "integer", "minimum": 1, "maximum": 3}, "filters": _FILTER_SCHEMA}, "additionalProperties": False}, "category": "kbforge"},
    {"name": "sberindex_crosswalk", "description": "Связка territory_id панели расходов со словарём СберИндекса (A1): покрытие прямого join, без ОКТМО-посредника", "fn": sberindex_crosswalk,
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}, "category": "kbforge"},
]


if __name__ == "__main__":
    import json as _json

    print(_json.dumps(_self_check_cluster_methods(), ensure_ascii=False))
