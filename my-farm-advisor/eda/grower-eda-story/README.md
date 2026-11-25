# Grower EDA Story

This reusable EDA subskill creates analysis-ready static tables, comparison
analyses, and figures for runtime grower datasets. The current use case is the
Assignment 2 comparison of Illinois, Iowa, and Nebraska growers. It is not a
report generator and does not create an interactive dashboard.

## At a glance

- **Skill:** `grower-eda-story`, routed through `my-farm-advisor/eda/INDEX.md`
- **Location:** `my-farm-advisor/eda/grower-eda-story/`
- **Generates:** static per-grower tables, cross-grower comparison CSVs, and
  PNG figures for field boundaries, NASA POWER weather, and USDA CDL crop
  history
- **Runtime outputs:** `${DATA_PIPELINE_DATA_ROOT}/data-pipeline/growers/<grower>/derived/eda-story/`
  and `${DATA_PIPELINE_DATA_ROOT}/data-pipeline/derived/eda-story/`
- **One-time report:** `my-farm-advisor/eda/reports/assignment-2-eda-report.html`

## Runtime command

```bash
export DATA_PIPELINE_DATA_ROOT="$HOME/my-farm-advisor-runtime"
cd "$DATA_PIPELINE_DATA_ROOT/data-pipeline/src"
"$DATA_PIPELINE_DATA_ROOT/data-pipeline/.venv/bin/python" \
  scripts/grower_eda_story.py --all-growers --dry-run
```

Remove `--dry-run` to write the analysis tables, comparison tables, and static
PNG figures. The subskill does not generate Markdown, HTML, or narrative
reports.

Outputs are written outside Git:

```text
data-pipeline/growers/<grower>/derived/eda-story/
  manifest.json
  tables/field_inventory.csv
  tables/weather_cells.csv
  tables/field_weather_seasonal.csv
  tables/field_cdl_history.csv
  tables/field_crop_mix.csv
  tables/field_rotation_summary.csv
data-pipeline/derived/eda-story/
  manifest.json
  tables/cross_grower_fields.csv
  tables/field_shape_metrics.csv
  analysis/boundary_comparison.csv
  analysis/boundary_shape_tests.csv
  analysis/weather_comparison.csv
  analysis/cdl_comparison.csv
  figures/boundary_acreage.png
  figures/boundary_shape.png
  figures/boundary_map.png
  figures/weather_anomaly.png
  figures/weather_climate.png
  figures/cdl_timeline.png
  figures/cdl_crop_mix.png
```

The generated artifact set includes two static visualizations and one
comparison analysis for each category: boundaries, weather, and CDL/cropland.
The boundary category compares acreage and shape; weather compares within-field
seasonal variation and farm-location climate; and CDL compares field-year crop
composition and crop history. A static map shows the three grower field sets.
The one-time Assignment 2 report is a separate consumer of these artifacts and
is intentionally outside this reusable subskill.

For method guidance, use the routed [Compare Guide](../eda-compare/GUIDE.md),
[Time Series Guide](../eda-time-series/GUIDE.md), and
[Visualize Guide](../eda-visualize/GUIDE.md) alongside this artifact
generator. They remain part of the My Farm Advisor EDA route; this directory
does not create unrelated standalone skills.

## Comparison levels and limitations

- Within field: weather summaries compare 2021–2025 years; CDL sequences and
  percentages compare 2019–2023 years. Boundaries have no time series.
- Within grower: acreage, field-year CDL classes and percentages, and weather
  summary dispersion are compared across the ten fields.
- Across growers: Illinois, Iowa, and Nebraska field-size, crop-mix, rotation,
  and farm-location weather patterns are compared descriptively.
- Weather is NASA POWER centroid/grid data, not field sensors. Effective
  weather series are expected to be 2 in Illinois, 2 in Iowa, and 1 in
  Nebraska; field-level weather differences must not be treated as independent
  microclimate observations.
- CDL percentages retain the raw field share and expose the residual caused by
  filtered background/No Data pixels. No silent renormalization is performed.
- The boundary crop is a 2023 CDL snapshot, not a management record. No soil,
  imagery, terrain, yield, irrigation, or causal analysis is performed.
