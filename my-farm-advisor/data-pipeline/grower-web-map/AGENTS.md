# Grower Web Map Local Instructions

- Keep implementation files under this directory and the runtime copy at
  `${DATA_PIPELINE_DATA_ROOT}/data-pipeline/src/scripts/`.
- Require an absolute `DATA_PIPELINE_DATA_ROOT`; never fall back to the
  checkout or a repository-local data directory.
- Read field boundaries only from runtime farm
  `boundary/field_boundaries.geojson` files.
- Generated HTML belongs under each grower's runtime
  `derived/web-map/` directory and must not be committed.
- Keep maps lightweight: vector boundaries and metadata are embedded, while
  Leaflet and satellite tiles remain online resources.
