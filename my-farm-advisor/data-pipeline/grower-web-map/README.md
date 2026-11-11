# Grower Web Map

This subskill generates one lightweight interactive HTML map per grower from
the actual field boundary GeoJSON produced by the data pipeline. It renders
all fields, uses Leaflet from a CDN, and uses ESRI World Imagery as an online
satellite basemap. No imagery, rasters, or large data bundles are embedded.

## Runtime command

```bash
export DATA_PIPELINE_DATA_ROOT=/home/coder/my-farm-advisor-runtime
cd "${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src"
"${DATA_PIPELINE_DATA_ROOT}/data-pipeline/.venv/bin/python" \
  scripts/grower_web_map.py --all-growers
```

Generate one grower only with `--grower-slug <slug>`. Outputs are written to:

```text
${DATA_PIPELINE_DATA_ROOT}/data-pipeline/growers/<grower>/derived/web-map/<grower>_web_map.html
```

The output includes zoom controls, fit-to-fields behavior, clickable field
polygons, a field list that zooms to each field, and popup metadata for grower,
farm, field name/slug, area, crop, and county when available. Leaflet and the
basemap are loaded from the internet when the HTML is opened.

## Source boundaries

The generator reads each farm's canonical
`boundary/field_boundaries.geojson`. It does not use generated report images,
raw satellite files, or raster assets.
