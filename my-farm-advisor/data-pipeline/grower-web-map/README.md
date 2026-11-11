# Grower Web Map

This subskill generates a new responsive field-intelligence dashboard per
grower from the actual field boundary GeoJSON produced by the data pipeline.
The dashboard combines a satellite map, crop-colored field polygons, search,
crop filters, field cards, summary statistics, selection highlighting, and a
street-map alternative. No imagery, rasters, or large data bundles are
embedded.

## Runtime command

```bash
export DATA_PIPELINE_DATA_ROOT=/home/coder/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/grower_web_map_dashboard.py --all-growers
```

Generate one grower only with `--grower-slug <slug>`. Outputs are written to:

```text
${DATA_PIPELINE_DATA_ROOT}/data-pipeline/growers/<grower>/derived/web-map-v2/<grower>_field_dashboard.html
```

The output includes responsive mobile layout, zoom and fit controls, browser
location support, searchable field cards, crop filters, clickable polygons,
selection highlighting, popup metadata, area/crop summary statistics, and
online Leaflet, Esri World Imagery, and OpenStreetMap resources.

The previous `grower_web_map.py` generator and `derived/web-map/` output are
left intact for backward compatibility; this dashboard is the replacement
map and writes to the separate `web-map-v2/` output family.

## Source boundaries

The generator reads each farm's canonical
`boundary/field_boundaries.geojson`. It does not use generated report images,
raw satellite files, or raster assets.
