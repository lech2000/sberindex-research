#!/usr/bin/env python3
"""Build a compact SVG-ready preview layer from the HSE 2021 shapefile.

This is a presentation asset, not a SberIndex↔OKTMO crosswalk or a current
municipal boundary register. The source archive is deliberately not vendored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import zipfile

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon


SOURCE_URL = (
    "https://geoportal.hse.ru/portal/sharing/rest/content/items/"
    "12e78b9c3bf04feea944f9d53eb3d079/data"
)
WIDTH = 1600
HEIGHT = 850
PADDING = 32
SIMPLIFICATION_METRES = 4500
MAP_CRS = "+proj=aea +lat_1=50 +lat_2=70 +lat_0=60 +lon_0=100 +datum=WGS84 +units=m +no_defs"


def archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_layer(archive: Path) -> gpd.GeoDataFrame:
    with zipfile.ZipFile(archive) as package, tempfile.TemporaryDirectory(prefix="sberindex-geo-") as temporary:
        names = package.namelist()
        candidates = [name for name in names if name.lower().endswith(".shp") and "_reg" not in name and "_fo" not in name]
        if len(candidates) != 1:
            raise ValueError(f"expected one municipal shapefile, found {candidates}")
        stem = Path(candidates[0]).stem
        companions = [name for name in names if Path(name).stem == stem and Path(name).suffix.lower() in {".shp", ".shx", ".dbf", ".prj", ".cpg"}]
        if not {".shp", ".shx", ".dbf"}.issubset({Path(name).suffix.lower() for name in companions}):
            raise ValueError("municipal shapefile is missing required components")
        for name in companions:
            item = package.getinfo(name)
            if item.file_size > 500 * 1024 * 1024:
                raise ValueError(f"oversized archive member: {name}")
            with package.open(name) as source, (Path(temporary) / Path(name).name).open("wb") as output:
                shutil.copyfileobj(source, output)
        layer = gpd.read_file(Path(temporary) / f"{stem}.shp", engine="pyogrio")
    if layer.crs is None:
        raise ValueError("source CRS is missing")
    required = {"oktmo", "name", "type", "region", "fo", "pop"}
    missing = required - set(layer.columns)
    if missing:
        raise ValueError(f"municipal attributes missing: {sorted(missing)}")
    if len(layer) != 2607:
        raise ValueError(f"HSE 2021 source should have 2607 records; found {len(layer)}")
    return layer.to_crs(MAP_CRS)


def nonempty(value: object) -> str:
    return "" if value is None or str(value).lower() in {"nan", "none"} else str(value).strip()


def coordinate(x: float, y: float, bounds: tuple[float, float, float, float], scale: float, offset: tuple[float, float]) -> tuple[float, float]:
    minx, _, _, maxy = bounds
    return (offset[0] + (x - minx) * scale, offset[1] + (maxy - y) * scale)


def svg_path(geometry: Polygon | MultiPolygon, bounds: tuple[float, float, float, float], scale: float, offset: tuple[float, float]) -> str:
    polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
    parts: list[str] = []
    for polygon in polygons:
        for ring in [polygon.exterior, *polygon.interiors]:
            points = [coordinate(x, y, bounds, scale, offset) for x, y in list(ring.coords)[:-1]]
            if len(points) < 3:
                continue
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in points) + "Z")
    return "".join(parts)


def build(archive: Path, output: Path) -> dict[str, object]:
    layer = load_layer(archive)
    layer["geometry"] = layer.geometry.simplify(SIMPLIFICATION_METRES, preserve_topology=True)
    minx, miny, maxx, maxy = (float(value) for value in layer.total_bounds)
    bounds = (minx, miny, maxx, maxy)
    scale = min((WIDTH - 2 * PADDING) / (maxx - minx), (HEIGHT - 2 * PADDING) / (maxy - miny))
    offset = (
        PADDING + ((WIDTH - 2 * PADDING) - (maxx - minx) * scale) / 2,
        PADDING + ((HEIGHT - 2 * PADDING) - (maxy - miny) * scale) / 2,
    )
    features: list[dict[str, object]] = []
    for _, row in layer.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"missing/unsupported geometry for {row['oktmo']}")
        population = row["pop"]
        feature_bounds = geometry.bounds
        left, top = coordinate(feature_bounds[0], feature_bounds[3], bounds, scale, offset)
        right, bottom = coordinate(feature_bounds[2], feature_bounds[1], bounds, scale, offset)
        path = svg_path(geometry, bounds, scale, offset)
        if not path:
            raise ValueError(f"empty SVG path for {row['oktmo']}")
        features.append({
            "o": nonempty(row["oktmo"]),
            "n": nonempty(row["name"]),
            "t": nonempty(row["type"]),
            "r": nonempty(row["region"]),
            "f": nonempty(row["fo"]),
            "p": int(population) if population is not None and math.isfinite(float(population)) else None,
            "b": [round(left, 1), round(top, 1), round(right - left, 1), round(bottom - top, 1)],
            "d": path,
        })
    payload = {
        "width": WIDTH, "height": HEIGHT,
        "source": SOURCE_URL,
        "source_sha256": archive_sha256(archive),
        "geography_asof": "2021-01-01",
        "simplification_m": SIMPLIFICATION_METRES,
        "features": features,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("window.SBER_MUNICIPAL_2021=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return {"features": len(features), "bytes": output.stat().st_size, "source_sha256": payload["source_sha256"], "output_sha256": archive_sha256(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("municipal-2021.js"))
    args = parser.parse_args()
    print(json.dumps(build(args.archive, args.output), ensure_ascii=False, indent=2))
