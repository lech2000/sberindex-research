#!/usr/bin/env python3
"""Build the publicly distributable ODbL preview, separate from the HSE research layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from urllib.request import urlopen

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, shape

from build_map import MAP_CRS, PADDING, WIDTH, HEIGHT, coordinate, svg_path


ROOT = Path(__file__).resolve().parents[1]
SITE = Path(__file__).resolve().parents[3] / "infrastructure/agrigate-pro/site/sberindex-2026"
SOURCE_URL = "https://gist.githubusercontent.com/heaviss/7432d4fcb5e920324551cab143ec986a/raw/d247d8911f2f9b4d7f3f2bbd71b583e432f5959a/OSM_russian_boundaries.geojson"
SOURCE_SHA256 = "20fdbdc7234a0670dba73fc40f87ae703b84e05ee09d53f16c0d909bc81cd33e"


def source_data() -> dict:
    with urlopen(SOURCE_URL, timeout=30) as response:
        raw = response.read(3_000_001)
    if len(raw) > 3_000_000 or hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("pinned OSM source changed or exceeded the size limit")
    data = json.loads(raw)
    if data.get("type") != "FeatureCollection" or len(data.get("features", [])) != 2487:
        raise ValueError("unexpected OSM source structure")
    return data


def build_geometry(data: dict) -> dict:
    records = data["features"]
    by_id = {str(record["properties"]["osm_id"]): record["properties"] for record in records}
    districts = {key: value["local_name"] for key, value in by_id.items() if value["admin_level"] == 3}
    regions = {key: value["local_name"] for key, value in by_id.items() if value["admin_level"] == 4}
    municipal = [record for record in records if record["properties"]["admin_level"] == 6]
    geometry = gpd.GeoSeries([shape(record["geometry"]) for record in municipal], crs="EPSG:4326").to_crs(MAP_CRS)
    geometry = geometry.simplify(4500, preserve_topology=True)
    bounds = tuple(float(value) for value in geometry.total_bounds)
    minx, miny, maxx, maxy = bounds
    scale = min((WIDTH - 2 * PADDING) / (maxx - minx), (HEIGHT - 2 * PADDING) / (maxy - miny))
    offset = (
        PADDING + ((WIDTH - 2 * PADDING) - (maxx - minx) * scale) / 2,
        PADDING + ((HEIGHT - 2 * PADDING) - (maxy - miny) * scale) / 2,
    )
    features = []
    for record, polygon in zip(municipal, geometry, strict=True):
        properties = record["properties"]
        parents = properties.get("parents", "").split(",")
        if polygon.is_empty or not isinstance(polygon, (Polygon, MultiPolygon)):
            continue
        left, top = coordinate(polygon.bounds[0], polygon.bounds[3], bounds, scale, offset)
        right, bottom = coordinate(polygon.bounds[2], polygon.bounds[1], bounds, scale, offset)
        path = svg_path(polygon, bounds, scale, offset)
        if not path:
            continue
        features.append({
            "o": str(abs(properties["osm_id"])),
            "n": properties.get("local_name") or properties.get("name") or "Без названия",
            "r": next((regions[parent] for parent in parents if parent in regions), "Субъект не указан"),
            "f": next((districts[parent] for parent in parents if parent in districts), "Округ не указан"),
            "b": [round(left, 1), round(top, 1), round(right - left, 1), round(bottom - top, 1)],
            "d": path,
        })
    if len(features) < 2300:
        raise ValueError(f"too few municipal geometries: {len(features)}")
    return {
        "width": WIDTH, "height": HEIGHT, "source_kind": "osm-boundaries",
        "source": SOURCE_URL, "source_sha256": SOURCE_SHA256,
        "geography_asof": "2021-11-01", "simplification_m": 4500,
        "features": features,
    }


def public_html(source: Path) -> str:
    html = source.read_text(encoding="utf-8")
    html = html.replace('data-default-channel="type"', 'data-default-channel="district"')
    html = html.replace('data-default-channel="population"', 'data-default-channel="district"')
    html = re.sub(
        r'<div class="channel-set" role="group" aria-label="Цветовой канал">.*?</div>',
        '<div class="channel-set" role="group" aria-label="Цветовой канал"><button type="button" data-channel="district" aria-pressed="true">Федеральный округ</button></div>',
        html, flags=re.S,
    )
    html = html.replace('муниципалитеты верхнего уровня на 01.01.2021', 'границы OSM уровня 6, экспорт 2021')
    html = html.replace('по геослою на 1 января 2021 года', 'по экспорту OpenStreetMap 2021 года')
    html = html.replace('Найти муниципалитет или ОКТМО', 'Найти территорию по названию')
    html = html.replace('Цветовые слои показывают только проверенные географические атрибуты. Они не являются результатом экономической кластеризации.', 'Цвет показывает федеральный округ по экспорту OpenStreetMap 2021 года, а не результат экономической кластеризации.')
    html = html.replace('Слой населения помогает ориентироваться в масштабе муниципалитета. Это сведения 2021 года, а не оценка потребления или вероятности шока.', 'Цвет показывает федеральный округ по экспорту OpenStreetMap 2021 года, а не потребление или вероятность шока.')
    html = html.replace('География уже настоящая;', 'Границы взяты из открытого экспорта OpenStreetMap 2021 года;')
    html = html.replace('География относится к 2021 году и ещё не совмещена с экономическими рядами СберИндекса. Публичная выкладка требует отдельной проверки условий повторного использования геослоя.', 'Границы относятся к экспорту OpenStreetMap 2021 года и ещё не совмещены с экономическими рядами СберИндекса. Актуальный реестр муниципалитетов и ОКТМО здесь не представлены.')
    html = html.replace('География относится к 2021 году и ещё не совмещена с рядами СберИндекса. Публичная выкладка требует отдельной проверки условий повторного использования геослоя.', 'Границы относятся к экспорту OpenStreetMap 2021 года и ещё не совмещены с рядами СберИндекса. Актуальный реестр муниципалитетов и ОКТМО здесь не представлены.')
    html = html.replace('Геометрия: <a href="https://geoportal.hse.ru/portal/home/item.html?id=12e78b9c3bf04feea944f9d53eb3d079">НИУ ВШЭ</a> / <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a> · 2021', 'Границы: <a href="https://www.openstreetmap.org/copyright">© OpenStreetMap</a> / <a href="https://osm-boundaries.com/about/documentation">OSM-Boundaries</a> · ODbL · экспорт 2021')
    html = html.replace('<a href="../research-plan.md">План исследования</a>', '<a href="../../landing-common/DATA_LICENSE.txt">Данные и лицензия</a>')
    html = html.replace('Это сведения 2021 года', 'Это экспорт 2021 года')
    if 'НИУ ВШЭ' in html or 'data-channel="type"' in html or 'data-channel="population"' in html:
        raise ValueError(f"public page retained source-only content: {source}")
    return html


def main() -> None:
    payload = build_geometry(source_data())
    shared = SITE / "landing-common"
    shared.mkdir(parents=True, exist_ok=True)
    (shared / "municipal-2021.js").write_text("window.SBER_MUNICIPAL_2021=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    (shared / "map.js").write_bytes((ROOT / "landing-common/map.js").read_bytes())
    css = (ROOT / "landing-common/landing.css").read_text(encoding="utf-8")
    css = css.replace('../../../infrastructure/agrigate-pro/site/v2/fonts/InterVariable.woff2', '/v2/fonts/InterVariable.woff2')
    (shared / "landing.css").write_text(css, encoding="utf-8")
    (shared / "DATA_LICENSE.txt").write_text(
        "SberIndex 2026 public research previews — geographic layer\n"
        "Built 2026-09-24 from an OSM-Boundaries export dated 2021-11-01, shared by heaviss.\n"
        f"Source: {SOURCE_URL}\nSHA-256: {SOURCE_SHA256}\n"
        "Geographic data: © OpenStreetMap contributors, Open Database License 1.0 (ODbL).\n"
        "OSM-Boundaries: https://osm-boundaries.com/about/documentation\n"
        "OpenStreetMap copyright: https://www.openstreetmap.org/copyright\n"
        "The transformed database is available as municipal-2021.js in this directory under ODbL.\n"
        "Simplified 4.5 km; for visual research previews only, not an official or current boundary register.\n",
        encoding="utf-8",
    )
    for name in ("economic-atlas", "shock-radar"):
        output = SITE / name / "landing/index.html"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(public_html(ROOT / name / "landing/index.html"), encoding="utf-8")
    print(json.dumps({"features": len(payload["features"]), "site": str(SITE), "bytes": (shared / "municipal-2021.js").stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
