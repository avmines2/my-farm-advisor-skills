#!/usr/bin/env python3
"""Build a polished, self-contained field dashboard using runtime boundaries."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any

LEAFLET_VERSION = "1.9.4"
IMAGERY_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
STREET_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"


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


def area_hectares(properties: dict[str, Any]) -> float | None:
    value = properties.get("area_ha_est") or properties.get("area_ha")
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


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
        for source in payload.get("features", []):
            props = dict(source.get("properties") or {})
            field_id = str(props.get("field_id") or props.get("field_slug") or "field")
            area = area_hectares(props)
            metadata = {
                "field_id": field_id,
                "field_label": field_id.replace("-", " ").title(),
                "grower": grower_dir.name,
                "farm": farm_dir.name,
                "crop": str(props.get("crop") or "Unclassified"),
                "county": str(props.get("county") or "—"),
                "state": str(props.get("state") or "—"),
                "area_ha": round(area, 1) if area is not None else None,
                "area_acres": round(float(props["area_acres"]), 1)
                if props.get("area_acres") not in (None, "")
                else None,
            }
            features.append(
                {"type": "Feature", "geometry": source.get("geometry"), "properties": metadata}
            )
    return features


def render(grower: str, features: list[dict[str, Any]]) -> str:
    title = html.escape(grower.replace("-", " ").title())
    data = {"type": "FeatureCollection", "features": features}
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | Field intelligence dashboard</title>
<link rel="preconnect" href="https://unpkg.com"><link rel="stylesheet" href="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.css">
<style>
:root{{--ink:#14231f;--muted:#70807a;--line:#dbe5df;--paper:#f7faf8;--teal:#0c766d;--gold:#e6a93c;--shadow:0 18px 45px rgba(20,45,37,.14)}}
*{{box-sizing:border-box}}html,body{{height:100%;margin:0;background:var(--paper);color:var(--ink);font:14px/1.45 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}body{{overflow:hidden}}button,input{{font:inherit}}button{{cursor:pointer}}#app{{height:100%;display:grid;grid-template-columns:390px 1fr;position:relative}}#map{{height:100%;min-height:420px;z-index:1}}.sidebar{{background:rgba(255,255,255,.96);border-right:1px solid var(--line);display:flex;flex-direction:column;z-index:10;box-shadow:var(--shadow);overflow:hidden}}.brand{{padding:24px 24px 18px;background:linear-gradient(145deg,#123e36,#0b6d64);color:#fff}}.eyebrow{{font-size:11px;letter-spacing:.14em;text-transform:uppercase;opacity:.72;font-weight:700}}h1{{font-size:28px;line-height:1.05;margin:8px 0 5px;letter-spacing:-.04em}}.sub{{margin:0;color:rgba(255,255,255,.72);font-size:13px}}.controls{{padding:16px 18px 12px;border-bottom:1px solid var(--line)}}.search{{display:flex;align-items:center;gap:9px;border:1px solid var(--line);border-radius:12px;padding:10px 12px;background:#fff}}.search input{{border:0;outline:0;width:100%;color:var(--ink);background:transparent}}.search svg{{width:17px;fill:var(--muted)}}.filters{{display:flex;gap:7px;flex-wrap:wrap;margin-top:11px}}.filter{{border:1px solid var(--line);border-radius:999px;padding:6px 10px;background:#fff;color:var(--muted);font-size:12px;font-weight:700}}.filter.active,.filter:hover{{color:#fff;background:var(--teal);border-color:var(--teal)}}.stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:14px 18px;border-bottom:1px solid var(--line)}}.stat{{background:#f0f6f2;border-radius:12px;padding:10px 9px}}.stat strong{{display:block;font-size:20px;letter-spacing:-.04em}}.stat span{{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-top:2px}}.list{{overflow:auto;padding:10px 14px 18px;flex:1}}.field-card{{width:100%;display:block;text-align:left;background:#fff;border:1px solid var(--line);border-radius:14px;padding:13px;margin:0 0 9px;transition:.18s;box-shadow:0 2px 8px rgba(31,65,52,.04)}}.field-card:hover,.field-card.selected{{border-color:var(--teal);box-shadow:0 8px 22px rgba(12,118,109,.15);transform:translateY(-1px)}}.field-top{{display:flex;align-items:center;justify-content:space-between;gap:10px}}.field-name{{font-size:16px;font-weight:800}}.crop{{border-radius:999px;padding:4px 8px;font-size:10px;font-weight:800;background:#e4f2df;color:#2c6a32}}.crop.soybeans{{background:#e4edf8;color:#24558f}}.crop.unclassified{{background:#edf0ee;color:#68746f}}.field-meta{{display:flex;gap:12px;color:var(--muted);font-size:12px;margin-top:7px}}.map-tools{{position:absolute;right:18px;top:18px;z-index:500;display:flex;gap:8px}}.tool{{background:#fff;border:0;border-radius:10px;padding:10px 12px;box-shadow:0 4px 14px rgba(10,35,28,.18);color:var(--ink);font-weight:700}}.tool:hover{{color:var(--teal)}}.leaflet-control-layers{{border:0!important;border-radius:10px!important;box-shadow:0 4px 14px rgba(10,35,28,.18)!important}}.leaflet-popup-content-wrapper,.leaflet-popup-tip{{background:#fff}}.popup h3{{margin:0 0 8px;font-size:17px}}.popup-grid{{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:12px}}.popup-grid b{{color:var(--muted);font-weight:600}}.legend{{position:absolute;left:18px;bottom:18px;z-index:500;background:rgba(255,255,255,.94);border-radius:11px;padding:10px 12px;box-shadow:0 4px 14px rgba(10,35,28,.15);font-size:11px}}.legend-row{{display:flex;gap:7px;align-items:center;margin:3px 0}}.dot{{width:10px;height:10px;border-radius:50%;display:inline-block}}.empty{{color:var(--muted);text-align:center;padding:35px 12px}}@media(max-width:820px){{body{{overflow:auto}}#app{{height:auto;min-height:100%;display:flex;flex-direction:column}}.sidebar{{order:2;border-right:0;border-top:1px solid var(--line);max-height:none;box-shadow:none}}#map{{order:1;height:58vh;min-height:390px}}.brand{{padding:18px 20px}}h1{{font-size:24px}}.map-tools{{top:12px;right:12px}}.legend{{bottom:12px;left:12px}}}}
</style></head><body><main id="app"><aside class="sidebar"><header class="brand"><div class="eyebrow">Field intelligence</div><h1>{title}</h1><p class="sub">A clean view of your operation, boundaries, and crop mix.</p></header><section class="controls"><label class="search"><svg viewBox="0 0 24 24"><path d="m21 19.6-5.1-5.1a7.5 7.5 0 1 0-1.4 1.4l5.1 5.1 1.4-1.4ZM5 10.5a5.5 5.5 0 1 1 11 0 5.5 5.5 0 0 1-11 0Z"/></svg><input id="search" type="search" placeholder="Find a field..."></label><div class="filters" id="filters"></div></section><section class="stats"><div class="stat"><strong id="fieldCount">0</strong><span>fields</span></div><div class="stat"><strong id="areaTotal">—</strong><span>hectares</span></div><div class="stat"><strong id="cropCount">0</strong><span>crops</span></div></section><section class="list" id="fieldList"></section></aside><section id="map"><div class="map-tools"><button class="tool" id="fit">Fit fields</button><button class="tool" id="locate">Locate</button></div><div class="legend"><div><b>Crop layer</b></div><div class="legend-row"><i class="dot" style="background:#e6a93c"></i>Corn</div><div class="legend-row"><i class="dot" style="background:#4d8bd0"></i>Soybeans</div><div class="legend-row"><i class="dot" style="background:#87958f"></i>Other</div></div></section></main><script src="https://unpkg.com/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"></script><script>
const data={js_json(data)}, map=L.map('map',{{zoomControl:false}}), colors={{Corn:'#e6a93c',Soybeans:'#4d8bd0',Unclassified:'#87958f'}}; L.control.zoom({{position:'bottomright'}}).addTo(map);
const imagery=L.tileLayer({js_json(IMAGERY_URL)},{{maxZoom:19,attribution:'Imagery &copy; Esri'}}), streets=L.tileLayer({js_json(STREET_URL)},{{maxZoom:19,subdomains:'abc',attribution:'&copy; OpenStreetMap contributors'}}); imagery.addTo(map); L.control.layers({{'Satellite':imagery,'Streets':streets}},null,{{position:'topright'}}).addTo(map);
const esc=v=>String(v??'—').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[m])); const cropClass=c=>String(c||'Unclassified').toLowerCase();
const style=f=>{{const c=f.properties.crop||'Unclassified';return {{color:colors[c]||colors.Unclassified,weight:2,fillColor:colors[c]||colors.Unclassified,fillOpacity:.3}}}}; const selectedStyle=f=>({{...style(f),weight:4,fillOpacity:.55}});
let active='All', selected=null; const layer=L.geoJSON(data,{{style,onEachFeature:(f,l)=>{{const p=f.properties; l.bindPopup(`<div class="popup"><h3>${{esc(p.field_label)}}</h3><div class="popup-grid"><b>Crop</b><span>${{esc(p.crop)}}</span><b>Area</b><span>${{p.area_ha?esc(p.area_ha+' ha'):'—'}}</span><b>County</b><span>${{esc(p.county)}}</span><b>State</b><span>${{esc(p.state)}}</span></div></div>`); l.on('click',()=>select(p.field_id));}}}}).addTo(map);
function select(id){{selected=id; layer.eachLayer(l=>{{const on=l.feature.properties.field_id===id;l.setStyle(on?selectedStyle(l.feature):style(l.feature));if(on){{map.fitBounds(l.getBounds(),{{maxZoom:16,padding:[30,30]}});l.openPopup()}}}});renderList();}}
function fit(){{const b=layer.getBounds();if(b.isValid())map.fitBounds(b,{{padding:[45,45]}})}} function cropSet(){{return [...new Set(data.features.map(f=>f.properties.crop||'Unclassified'))].sort()}};
function renderFilters(){{const box=document.querySelector('#filters');box.innerHTML=['All',...cropSet()].map(c=>`<button class="filter ${{c===active?'active':''}}" data-crop="${{esc(c)}}">${{esc(c)}}</button>`).join('');box.querySelectorAll('button').forEach(b=>b.onclick=()=>{{active=b.dataset.crop;renderFilters();renderList()}})}}
function renderList(){{const q=document.querySelector('#search').value.toLowerCase();const rows=data.features.filter(f=>{{const p=f.properties;return (active==='All'||(p.crop||'Unclassified')===active)&&(`${{p.field_id}} ${{p.county}} ${{p.crop}}`).toLowerCase().includes(q)}});document.querySelector('#fieldList').innerHTML=rows.length?rows.map(f=>{{const p=f.properties;return `<button class="field-card ${{p.field_id===selected?'selected':''}}" data-id="${{esc(p.field_id)}}"><div class="field-top"><span class="field-name">${{esc(p.field_label)}}</span><span class="crop ${{cropClass(p.crop)}}">${{esc(p.crop)}}</span></div><div class="field-meta"><span>${{p.area_ha?esc(p.area_ha+' ha'):'Area n/a'}}</span><span>${{esc(p.county)}}</span></div></button>`}}).join(''):'<div class="empty">No fields match your filters.</div>';document.querySelectorAll('.field-card').forEach(b=>b.onclick=()=>select(b.dataset.id));layer.eachLayer(l=>l.setStyle((l.feature.properties.field_id===selected)?selectedStyle(l.feature):style(l.feature)))}}
document.querySelector('#search').oninput=renderList;document.querySelector('#fit').onclick=fit;document.querySelector('#locate').onclick=()=>{{if(navigator.geolocation)navigator.geolocation.getCurrentPosition(p=>map.setView([p.coords.latitude,p.coords.longitude],14),()=>alert('Location access was not available.'))}};document.querySelector('#fieldCount').textContent=data.features.length;document.querySelector('#areaTotal').textContent=data.features.reduce((s,f)=>s+(Number(f.properties.area_ha)||0),0).toFixed(1);document.querySelector('#cropCount').textContent=cropSet().length;renderFilters();renderList();fit();
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
        output_dir = grower_dir / "derived" / "web-map-v2"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / f"{grower_dir.name}_field_dashboard.html"
        output.write_text(render(grower_dir.name, features), encoding="utf-8")
        print(f"wrote {grower_dir.name}: {len(features)} fields -> {output}")


if __name__ == "__main__":
    main()
