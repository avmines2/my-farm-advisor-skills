#!/usr/bin/env python3
"""Generate lightweight Leaflet maps from runtime grower field boundaries."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

LEAFLET_VERSION = "1.9.4"
TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"


def runtime_root() -> Path:
    raw = os.environ.get("DATA_PIPELINE_DATA_ROOT")
    if not raw or not Path(raw).is_absolute():
        raise SystemExit("DATA_PIPELINE_DATA_ROOT is required and must be an absolute path")
    return Path(raw).expanduser().resolve() / "data-pipeline"


def js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def discover_growers(root: Path, selected: str | None) -> list[Path]:
    growers = root / "growers"
    if selected:
        path = growers / selected
        if not path.is_dir():
            raise SystemExit(f"Grower not found: {selected}")
        return [path]
    return sorted(path for path in growers.iterdir() if path.is_dir())


def field_feature(source: dict[str, Any], grower: str, farm: str) -> dict[str, Any]:
    props = dict(source.get("properties") or {})
    field = str(props.get("field_id") or props.get("field_slug") or "field")
    metadata = {
        "grower": grower,
        "farm": farm,
        "field": field,
        "area_ha": props.get("area_ha_est") or props.get("area_ha"),
        "crop": props.get("crop"),
        "county": props.get("county"),
    }
    metadata = {key: value for key, value in metadata.items() if value not in (None, "")}
    return {"type": "Feature", "geometry": source.get("geometry"), "properties": metadata}


def collect_features(grower_dir: Path) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    farms_dir = grower_dir / "farms"
    if not farms_dir.is_dir():
        return features
    for farm_dir in sorted(path for path in farms_dir.iterdir() if path.is_dir()):
        boundary = farm_dir / "boundary" / "field_boundaries.geojson"
        if not boundary.is_file():
            continue
        payload = json.loads(boundary.read_text(encoding="utf-8"))
        for feature in payload.get("features", []):
            features.append(field_feature(feature, grower_dir.name, farm_dir.name))
    return features


def render(grower: str, features: list[dict[str, Any]]) -> str:
    data = {"type": "FeatureCollection", "features": features}
    title = html.escape(f"{grower} Grower Web Map")
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css">
<style>html,body,#map{{height:100%;margin:0}}#panel{{position:absolute;z-index:1000;top:10px;right:10px;background:#fff;padding:10px;max-height:80vh;max-width:260px;overflow:auto;box-shadow:0 1px 5px #555;font:14px sans-serif}}#panel h2{{font-size:16px;margin:0 0 8px}}#fields{{padding-left:18px;margin:0}}#fields li{{cursor:pointer;margin:4px 0}}</style></head>
<body><div id="map"></div><aside id="panel"><h2>{title}</h2><div id="count"></div><ol id="fields"></ol></aside>
<script src="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"></script>
<script>
const data={js_json(data)};
const map=L.map('map');
L.tileLayer({js_json(TILE_URL)},{{maxZoom:19,attribution:'Imagery &copy; Esri'}}).addTo(map);
const layer=L.geoJSON(data,{{style:{{color:'#ffdf00',weight:2,fillColor:'#ff9900',fillOpacity:.28}},onEachFeature:(feature,polygon)=>{{
  const p=feature.properties||{{}}; const rows=Object.entries(p).map(([k,v])=>`<b>${{k}}</b>: ${{v}}`).join('<br>'); polygon.bindPopup(rows);
  const item=document.createElement('li'); item.textContent=p.field||'field'; item.onclick=()=>{{map.fitBounds(polygon.getBounds(),{{maxZoom:16}});polygon.openPopup()}}; document.querySelector('#fields').appendChild(item);
}}}}).addTo(map);
if(layer.getBounds().isValid()) map.fitBounds(layer.getBounds(),{{padding:[25,25]}}); else map.setView([39,-98],4);
document.querySelector('#count').textContent=`${{data.features.length}} fields`;
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all-growers", action="store_true")
    group.add_argument("--grower-slug")
    args = parser.parse_args()
    root = runtime_root()
    for grower_dir in discover_growers(root, args.grower_slug):
        features = collect_features(grower_dir)
        if not features:
            print(f"skip {grower_dir.name}: no field boundary GeoJSON found")
            continue
        output_dir = grower_dir / "derived" / "web-map"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{grower_dir.name}_web_map.html"
        output.write_text(render(grower_dir.name, features), encoding="utf-8")
        print(f"wrote {grower_dir.name}: {len(features)} fields -> {output}")


if __name__ == "__main__":
    main()
