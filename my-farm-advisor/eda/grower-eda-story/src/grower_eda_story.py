#!/usr/bin/env python3
"""Create static analysis-ready tables for the grower EDA story.

This CP1 entrypoint intentionally stops before figures and report generation.
It validates runtime inputs, summarizes weather and CDL history, and writes
small derived CSV/JSON artifacts under the external runtime root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import contextily as cx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as patheffects
from matplotlib.colors import ListedColormap

VERSION = "0.2.0-figures"
DEFAULT_START = 2021
DEFAULT_END = 2025
CDL_YEARS = range(2019, 2024)
CROP_GROUPS = {
    "Corn": "Corn", "Soybeans": "Soybeans", "Winter Wheat": "Other",
    "Alfalfa": "Other", "Forest": "Other", "Grass/Pasture": "Other",
    "Fallow/Idle": "Other",
}
GROWER_ORDER = ["illinois-grower", "iowa-grower", "nebraska-grower"]


def natural_field_key(value: object) -> tuple[str, int]:
    text = str(value)
    match = re.search(r"(\d+)$", text)
    return text[: match.start()] if match else text, int(match.group(1)) if match else -1


def ordered_growers(values: Any) -> list[str]:
    present = {str(value) for value in values}
    return [value for value in GROWER_ORDER if value in present] + sorted(present - set(GROWER_ORDER))


def strict_alternation(sequence: str) -> bool:
    crops = [part.strip() for part in sequence.split("->")]
    return len(crops) > 1 and all(left != right for left, right in zip(crops, crops[1:])) and set(crops) <= {"Corn", "Soybeans"}


def shape_compactness(frame: pd.DataFrame) -> pd.Series:
    values = []
    for geometry in frame["_geometry"]:
        values.append(4 * np.pi * geometry.area / geometry.length ** 2 if geometry is not None and geometry.length else np.nan)
    return pd.Series(values, index=frame.index, dtype=float)


def runtime_root() -> Path:
    raw = os.environ.get("DATA_PIPELINE_DATA_ROOT")
    if not raw or not Path(raw).is_absolute():
        raise SystemExit("DATA_PIPELINE_DATA_ROOT is required and must be absolute")
    return Path(raw).expanduser().resolve() / "data-pipeline"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_revision() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def selected_growers(root: Path, slugs: list[str] | None) -> list[Path]:
    base = root / "growers"
    if slugs:
        paths = [base / slug for slug in slugs]
        missing = [str(path) for path in paths if not path.is_dir()]
        if missing:
            raise SystemExit(f"Grower not found: {', '.join(missing)}")
        return paths
    return sorted(path for path in base.iterdir() if path.is_dir())


def only_farm(grower: Path, farm_slug: str | None) -> list[Path]:
    farms = sorted(path for path in (grower / "farms").iterdir() if path.is_dir())
    if farm_slug:
        farms = [path for path in farms if path.name == farm_slug]
        if not farms:
            raise SystemExit(f"Farm not found under {grower.name}: {farm_slug}")
    return farms


def weather_path(farm: Path, start: int, end: int) -> Path:
    tables = farm / "derived" / "tables"
    exact = sorted(tables.glob(f"*_weather_{start}_{end}.csv"))
    if exact:
        return exact[0]
    raise FileNotFoundError(f"weather table missing for {farm} ({start}-{end})")


def cdl_paths(farm: Path) -> list[Path]:
    tables = farm / "derived" / "tables"
    paths = []
    for path in sorted(tables.glob("*_????_cdl.csv")):
        if re.search(r"_(19|20)\d{2}_cdl\.csv$", path.name):
            year = int(path.name[-12:-8])
            if year in CDL_YEARS:
                paths.append(path)
    return paths


def validate_fields(farm: Path) -> tuple[gpd.GeoDataFrame, list[str]]:
    boundary_path = farm / "boundary" / "field_boundaries.geojson"
    if not boundary_path.is_file():
        raise FileNotFoundError(f"boundary missing: {boundary_path}")
    boundaries = gpd.read_file(boundary_path)
    required = {"field_id", "area_acres", "area_ha_est", "crop", "county", "state"}
    missing = required - set(boundaries.columns)
    if missing:
        raise ValueError(f"boundary missing columns: {sorted(missing)}")
    if boundaries["field_id"].duplicated().any():
        raise ValueError("duplicate field_id in boundary")
    fields = boundaries["field_id"].astype(str).tolist()
    inventory_path = farm / "manifests" / "field-inventory.csv"
    if inventory_path.is_file():
        inventory = pd.read_csv(inventory_path)
        if "field_id" in inventory and set(inventory.field_id.astype(str)) != set(fields):
            raise ValueError("boundary and field-inventory field sets differ")
    return boundaries, fields


def grid_key(weather: pd.DataFrame) -> pd.Series:
    lat = (weather["lat"] / 0.5).round() * 0.5
    lon = (weather["lon"] / 0.625).round() * 0.625
    return lat.map(lambda x: f"{x:.3f}") + ":" + lon.map(lambda x: f"{x:.3f}")


def seasonal_weather(weather: pd.DataFrame, boundaries: gpd.GeoDataFrame,
                     start_year: int, end_year: int, season_start: int,
                     season_end: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"field_id", "date", "T2M", "T2M_MAX", "T2M_MIN", "PRECTOTCORR",
                "ALLSKY_SFC_SW_DWN", "RH2M", "WS10M", "lat", "lon"}
    missing = required - set(weather.columns)
    if missing:
        raise ValueError(f"weather missing columns: {sorted(missing)}")
    weather = weather.copy()
    weather["field_id"] = weather["field_id"].astype(str)
    weather["date"] = pd.to_datetime(weather["date"], errors="coerce")
    if weather.date.isna().any():
        raise ValueError("weather contains unparseable dates")
    if weather.duplicated(["field_id", "date"]).any():
        raise ValueError("duplicate field-date weather rows")
    weather["year"] = weather.date.dt.year
    weather["in_season"] = weather.date.dt.month.between(season_start, season_end)
    weather = weather[weather.year.between(start_year, end_year) & weather.in_season].copy()
    weather["gdd10"] = (((weather.T2M_MAX.clip(upper=30) + weather.T2M_MIN.clip(lower=10)) / 2) - 10).clip(lower=0)
    weather["hot_30"] = weather.T2M_MAX >= 30
    weather["hot_35"] = weather.T2M_MAX >= 35
    weather["wet_1mm"] = weather.PRECTOTCORR >= 1
    weather["wet_25mm"] = weather.PRECTOTCORR >= 25
    aggregations = {
        "season_precip_mm": ("PRECTOTCORR", "sum"), "gdd10": ("gdd10", "sum"),
        "mean_temp_c": ("T2M", "mean"), "mean_solar_mj_m2_day": ("ALLSKY_SFC_SW_DWN", "mean"),
        "mean_rh_pct": ("RH2M", "mean"), "mean_wind_m_s": ("WS10M", "mean"),
        "hot_days_30": ("hot_30", "sum"), "hot_days_35": ("hot_35", "sum"),
        "wet_days_1mm": ("wet_1mm", "sum"), "wet_days_25mm": ("wet_25mm", "sum"),
    }
    grouped = weather.groupby(["field_id", "year"], as_index=False).agg(**aggregations)
    coords = weather.groupby(["field_id", "year"], as_index=False).agg(lat=("lat", "first"), lon=("lon", "first"))
    grouped = grouped.merge(coords, on=["field_id", "year"])
    grouped = grouped.merge(boundaries[["field_id", "county", "state"]].astype({"field_id": str}), on="field_id", how="left")
    grouped["grid_key"] = (grouped["lat"] / 0.5).round() .map(lambda x: f"{x:.3f}") + ":" + (grouped["lon"] / 0.625).round().map(lambda x: f"{x:.3f}")
    cells = weather[["field_id", "lat", "lon"]].drop_duplicates().copy()
    cells["grid_key"] = grid_key(cells)
    cells = cells.groupby("grid_key", as_index=False).agg(
        field_count=("field_id", "nunique"), fields=("field_id", lambda x: ",".join(sorted(x))),
        lat=("lat", "first"), lon=("lon", "first"),
    )
    return grouped, cells


def cdl_tables(boundaries: gpd.GeoDataFrame, paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frames = []
    for path in paths:
        frame = pd.read_csv(path)
        required = {"field_id", "year", "crop_code", "crop_name", "pixel_count", "pct"}
        if required - set(frame.columns):
            raise ValueError(f"CDL missing columns in {path.name}")
        frame["pct"] = pd.to_numeric(frame["pct"], errors="coerce")
        if frame.pct.isna().any():
            raise ValueError(f"CDL contains nonnumeric pct in {path.name}")
        frame["field_id"] = frame.field_id.astype(str)
        frame["crop_group"] = frame.crop_name.map(CROP_GROUPS).fillna("Other")
        frames.append(frame)
    if not frames:
        raise FileNotFoundError("no 2019-2023 CDL tables")
    history = pd.concat(frames, ignore_index=True)
    valid_fields = set(boundaries.field_id.astype(str))
    if not set(history.field_id).issubset(valid_fields):
        raise ValueError("CDL contains field absent from boundary")
    retained = history.groupby(["field_id", "year"], as_index=False)["pct"].sum().rename(columns={"pct": "retained_pct"})
    history = history.merge(retained, on=["field_id", "year"])
    history["share_of_field"] = history["pct"]
    history["share_of_retained"] = np.where(history.retained_pct > 0, history.pct / history.retained_pct * 100, np.nan)
    history["residual_pct"] = 100 - history.retained_pct
    history = history.merge(boundaries[["field_id", "area_acres", "county", "state"]].astype({"field_id": str}), on="field_id", how="left")
    history["estimated_acres"] = history.area_acres * history.share_of_field / 100
    mix = history.groupby(["field_id", "year", "crop_group"], as_index=False).agg(
        share_of_field=("share_of_field", "sum"), estimated_acres=("estimated_acres", "sum"))
    dominant = history.sort_values(["field_id", "year", "share_of_field"], ascending=[True, True, False]).drop_duplicates(["field_id", "year"])
    rotation = dominant.sort_values(["field_id", "year"]).groupby("field_id").agg(
        history_start_year=("year", "min"), history_end_year=("year", "max"),
        rotation_sequence=("crop_name", lambda x: " -> ".join(x)),
        crop_diversity=("crop_name", "nunique"),
    ).reset_index()
    transitions = dominant.sort_values(["field_id", "year"]).groupby("field_id")["crop_name"].apply(lambda x: int((x != x.shift()).sum() - 1)).rename("transitions").reset_index()
    rotation = rotation.merge(transitions, on="field_id")
    return history, mix, rotation


def write_frame(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.drop(columns=["_geometry"], errors="ignore").to_csv(path, index=False)
    return sha256(path)


def save_figure(fig: plt.Figure, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)
    return sha256(path)


def add_note(fig: plt.Figure, text: str) -> None:
    fig.text(0.01, 0.01, text, fontsize=8, color="#555555")


def build_analysis_and_figures(frames: dict[str, pd.DataFrame], out: Path,
                               start_year: int, end_year: int,
                               season_start: int, season_end: int) -> dict[str, str]:
    """Create the six static category figures, map, and three comparisons."""
    out_tables = out / "tables"
    out_analysis = out / "analysis"
    out_figures = out / "figures"
    artifacts: dict[str, str] = {}
    inventory = frames["inventory"].copy()
    seasonal = frames["seasonal"].copy()
    history = frames["history"].copy()
    mix = frames["mix"].copy()
    rotation = frames["rotation"].copy()

    # Boundary comparison and figures.
    geom_rows = []
    for grower in ordered_growers(inventory.grower_slug):
        group = inventory[inventory.grower_slug.eq(grower)]
        boundary_path = None
        # Geometry is reloaded by the caller and supplied through an internal column.
        acres = group.area_acres.astype(float)
        compact = shape_compactness(group)
        geom_rows.append({"grower_slug": grower, "field_count": len(group),
                          "total_acres": acres.sum(), "median_acres": acres.median(),
                          "min_acres": acres.min(), "max_acres": acres.max(),
                          "acreage_cv": acres.std(ddof=1) / acres.mean(),
                          "top_3_acre_share_pct": acres.nlargest(min(3, len(acres))).sum() / acres.sum() * 100,
                          "median_compactness": compact.median(),
                          "area_compactness_spearman": group.area_acres.corr(compact, method="spearman")})
    boundary_comparison = pd.DataFrame(geom_rows)
    artifacts["analysis/boundary_comparison.csv"] = write_frame(boundary_comparison, out_analysis / "boundary_comparison.csv")

    fig, ax = plt.subplots(figsize=(9, 5.5))
    for i, grower in enumerate(ordered_growers(inventory.grower_slug)):
        group = inventory[inventory.grower_slug.eq(grower)]
        values = group.sort_values("area_acres").area_acres.to_numpy()
        ax.scatter(values, np.full(len(values), i), s=42, label=grower.replace("-", " ").title())
        ax.plot([values.min(), values.max()], [i, i], lw=2, alpha=.35)
        ax.text(values.max() + 8, i, f"median {np.median(values):.0f} ac", va="center", fontsize=8)
    grower_order = ordered_growers(inventory.grower_slug)
    ax.set_yticks(range(len(grower_order)))
    ax.set_yticklabels([x.replace("-", " ").title() for x in grower_order])
    ax.invert_yaxis()
    ax.set_xlim(left=None, right=inventory.area_acres.max() + 90)
    ax.set_xlabel("Field area (acres)"); ax.set_title("Field boundary acreage by grower")
    ax.grid(axis="x", alpha=.25); add_note(fig, "10 fields per grower; dots are fields, not independent weather observations.")
    artifacts["figures/boundary_acreage.png"] = save_figure(fig, out_figures / "boundary_acreage.png")

    # Shape figure uses projected geometries from the canonical boundary files.
    shape = inventory.copy()
    shape["compactness"] = shape_compactness(shape)
    shape_metrics = shape.drop(columns=["_geometry"])
    shape_metrics.to_csv(out_tables / "field_shape_metrics.csv", index=False)
    artifacts["tables/field_shape_metrics.csv"] = sha256(out_tables / "field_shape_metrics.csv")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for grower in ordered_growers(shape.grower_slug):
        group = shape[shape.grower_slug.eq(grower)]
        ax.scatter(group.area_acres, group.compactness, label=grower.replace("-", " ").title(), s=45)
    ax.set_xlabel("Field area (acres)"); ax.set_ylabel("Polsby–Popper compactness")
    ax.set_title("Boundary size and shape (descriptive)"); ax.legend(frameon=False); ax.grid(alpha=.25)
    add_note(fig, "Compactness is calculated in EPSG:5070; it describes polygon geometry, not management quality.")
    artifacts["figures/boundary_shape.png"] = save_figure(fig, out_figures / "boundary_shape.png")

    # Static three-panel boundary map, colored by boundary's 2023 CDL snapshot.
    # Esri World Imagery provides geographic context while translucent crop
    # overlays preserve the 2023 CDL comparison shown by this figure.
    fig, axes = plt.subplots(1, 3, figsize=(14, 5.8))
    colors = {"Corn": "#d99b32", "Soybeans": "#4d86c5"}
    for ax, grower in zip(axes, ordered_growers(inventory.grower_slug)):
        group = inventory[inventory.grower_slug.eq(grower)]
        plot_group = gpd.GeoDataFrame(group, geometry=group["_geometry"], crs="EPSG:5070")
        xmin, ymin, xmax, ymax = plot_group.total_bounds
        xpad = max((xmax - xmin) * 0.08, 2_000)
        ypad = max((ymax - ymin) * 0.08, 2_000)
        ax.set_xlim(xmin - xpad, xmax + xpad)
        ax.set_ylim(ymin - ypad, ymax + ypad)
        cx.add_basemap(
            ax,
            crs="EPSG:5070",
            source=cx.providers.Esri.WorldImagery,
            zoom="auto",
            reset_extent=False,
            attribution=False,
            alpha=0.9,
        )
        for crop, subset in plot_group.groupby("crop"):
            subset.plot(
                ax=ax,
                color=colors.get(crop, "#8a9a93"),
                edgecolor="white",
                linewidth=.8,
                alpha=0.52,
                label=crop,
            )
        for _, row in plot_group.iterrows():
            point = row.geometry.representative_point()
            ax.text(
                point.x,
                point.y,
                str(row.field_id),
                fontsize=7,
                fontweight="bold",
                color="white",
                ha="center",
                va="center",
                path_effects=[patheffects.withStroke(linewidth=2.4, foreground="#222222")],
            )
        ax.set_title(grower.replace("-", " ").title(), y=.91); ax.set_axis_off()
    handles, labels = axes[0].get_legend_handles_labels()
    if handles: fig.legend(handles, labels, loc="lower center", ncol=3, frameon=False)
    fig.suptitle("Field boundaries and 2023 CDL crop snapshot", y=.98)
    fig.text(
        0.01,
        0.01,
        "Basemap: Esri World Imagery — Esri, i-cubed, USDA, USGS, AEX, GeoEye, "
        "Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community.",
        fontsize=6.5,
        color="#444444",
    )
    fig.subplots_adjust(top=.80, bottom=.16, wspace=.08)
    artifacts["figures/boundary_map.png"] = save_figure(fig, out_figures / "boundary_map.png")

    # Weather comparison and figures.
    annual = seasonal.groupby(["grower_slug", "field_id", "year"], as_index=False).agg(
        season_precip_mm=("season_precip_mm", "first"), gdd10=("gdd10", "first"), grid_key=("grid_key", "first"))
    annual["precip_anomaly_mm"] = annual["season_precip_mm"] - annual.groupby(["grower_slug", "field_id"]).season_precip_mm.transform("mean")
    annual["gdd_anomaly"] = annual["gdd10"] - annual.groupby(["grower_slug", "field_id"]).gdd10.transform("mean")
    temporal = annual.groupby(["grower_slug", "field_id"], as_index=False).agg(
        field_temporal_precip_sd=("season_precip_mm", "std"),
        field_temporal_gdd_sd=("gdd10", "std"),
    )
    temporal_summary = temporal.groupby("grower_slug", as_index=False).agg(
        mean_within_field_precip_sd=("field_temporal_precip_sd", "mean"),
        mean_within_field_gdd_sd=("field_temporal_gdd_sd", "mean"),
    )
    rows = []
    for (grower, year), group in annual.groupby(["grower_slug", "year"]):
        temporal_row = temporal_summary[temporal_summary.grower_slug.eq(grower)].iloc[0]
        rows.append({"grower_slug": grower, "year": year, "field_count": group.field_id.nunique(),
                     "unique_weather_cells": group.grid_key.nunique(),
                     "mean_within_field_precip_sd": temporal_row.mean_within_field_precip_sd,
                     "mean_within_field_gdd_sd": temporal_row.mean_within_field_gdd_sd,
                     "across_field_precip_sd": group.season_precip_mm.std(ddof=1),
                     "across_field_gdd_sd": group.gdd10.std(ddof=1),
                     "median_precip_mm": group.season_precip_mm.median(), "median_gdd10": group.gdd10.median()})
    weather_comparison = pd.DataFrame(rows)
    artifacts["analysis/weather_comparison.csv"] = write_frame(weather_comparison, out_analysis / "weather_comparison.csv")
    fig, axes = plt.subplots(3, 2, figsize=(13, 11), sharex=True)
    for ax, grower in zip(axes, ordered_growers(annual.grower_slug)):
        group = annual[annual.grower_slug.eq(grower)]
        for field, field_group in group.groupby("field_id"):
            ax[0].plot(field_group.year, field_group.precip_anomaly_mm, marker="o", alpha=.45, lw=1)
            ax[1].plot(field_group.year, field_group.gdd_anomaly, marker="o", alpha=.45, lw=1)
        ax[0].axhline(0, color="black", lw=.7); ax[1].axhline(0, color="black", lw=.7)
        ax[0].set_ylabel("Precip. anomaly (mm)"); ax[1].set_ylabel("GDD anomaly")
        ax[0].set_title(f"{grower.replace('-', ' ').title()} — precipitation; effective cells: {group.grid_key.nunique()}", loc="left", fontsize=10)
        ax[1].set_title("Growing degree days", loc="left", fontsize=10)
        for panel in ax:
            panel.set_xticks(sorted(group.year.unique())); panel.grid(alpha=.2)
    axes[-1, 0].set_xlabel("Weather year"); axes[-1, 1].set_xlabel("Weather year")
    fig.suptitle("Within-field seasonal weather anomalies", y=.995)
    add_note(fig, "April–September; lines are fields, but shared NASA POWER grid cells produce repeated series.")
    artifacts["figures/weather_anomaly.png"] = save_figure(fig, out_figures / "weather_anomaly.png")
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for grower in ordered_growers(annual.grower_slug):
        group = annual[annual.grower_slug.eq(grower)].groupby("year", as_index=False).median(numeric_only=True)
        axes[0].plot(group.year, group.season_precip_mm, marker="o", label=grower.replace("-", " ").title())
        axes[1].plot(group.year, group.gdd10, marker="o", label=grower.replace("-", " ").title())
    axes[0].set_title("Seasonal precipitation"); axes[0].set_ylabel("mm")
    axes[1].set_title("Growing degree days"); axes[1].set_ylabel("GDD base 10°C")
    for ax in axes: ax.set_xlabel("Year"); ax.set_xticks(sorted(annual.year.unique())); ax.grid(alpha=.25)
    axes[1].legend(frameon=False, fontsize=8); fig.suptitle("Farm-location weather patterns across growers")
    add_note(fig, "April–September; lines summarize field-location series, not independent field sensors.")
    artifacts["figures/weather_climate.png"] = save_figure(fig, out_figures / "weather_climate.png")

    # CDL comparison and figures.
    dominant = history.sort_values(["field_id", "year", "share_of_field"], ascending=[True, True, False]).drop_duplicates(["field_id", "year"])
    cdl_rows = []
    for grower in ordered_growers(history.grower_slug):
        group = history[history.grower_slug.eq(grower)]
        grower_rotation = rotation[rotation.grower_slug.eq(grower)]
        crop_counts = group.assign(crop_group=group.crop_name.map(CROP_GROUPS)).groupby(["field_id", "year", "crop_group"]).size().groupby(level=2).size()
        cdl_rows.append({
            "grower_slug": grower, "field_count": group.field_id.nunique(), "year_count": group.year.nunique(),
            "mean_corn_share_pct": group.loc[group.crop_name.eq("Corn"), "share_of_field"].mean(),
            "mean_soybean_share_pct": group.loc[group.crop_name.eq("Soybeans"), "share_of_field"].mean(),
            "mean_residual_pct": group.groupby(["field_id", "year"]).residual_pct.first().mean(),
            "mean_transitions": grower_rotation.transitions.mean(),
            "strict_alternation_fields": int(grower_rotation.rotation_sequence.map(strict_alternation).sum()),
            "continuous_corn_fields": int(grower_rotation.rotation_sequence.eq("Corn -> Corn -> Corn -> Corn -> Corn").sum()),
            "mean_crop_classes_per_field_year": group.groupby(["field_id", "year"]).crop_name.nunique().mean(),
        })
    cdl_comparison = pd.DataFrame(cdl_rows)
    artifacts["analysis/cdl_comparison.csv"] = write_frame(cdl_comparison, out_analysis / "cdl_comparison.csv")
    growers = ordered_growers(dominant.grower_slug)
    fig, axes = plt.subplots(len(growers), 2, figsize=(12, 3.2 * len(growers)), squeeze=False)
    crop_colors = {"Corn": "#d99b32", "Soybeans": "#4d86c5", "Other": "#94a39b"}
    for r, grower in enumerate(growers):
        group = dominant[dominant.grower_slug.eq(grower)].sort_values("field_id", key=lambda s: s.map(natural_field_key)).pivot(index="field_id", columns="year", values="crop_name")
        codes = group.replace({"Corn": 0, "Soybeans": 1}).fillna(2).astype(float)
        axes[r, 0].imshow(codes, aspect="auto", cmap=ListedColormap([crop_colors["Corn"], crop_colors["Soybeans"], crop_colors["Other"]]), vmin=0, vmax=2)
        axes[r, 0].set_yticks(range(len(group))); axes[r, 0].set_yticklabels(group.index, fontsize=7)
        axes[r, 0].set_xticks(range(len(group.columns))); axes[r, 0].set_xticklabels(group.columns); axes[r, 0].set_title(f"{grower.replace('-', ' ').title()} dominant CDL class")
        corn = history[history.grower_slug.eq(grower) & history.crop_name.eq("Corn")].groupby(["field_id", "year"]).share_of_field.sum().unstack(fill_value=0).sort_index(key=lambda s: s.map(natural_field_key))
        im = axes[r, 1].imshow(corn.reindex(index=group.index), aspect="auto", cmap="YlOrBr", vmin=0, vmax=100)
        axes[r, 1].set_yticks(range(len(corn))); axes[r, 1].set_yticklabels(corn.index, fontsize=7); axes[r, 1].set_xticks(range(len(corn.columns))); axes[r, 1].set_xticklabels(corn.columns); axes[r, 1].set_title("Corn share of field (%)")
    fig.colorbar(im, ax=axes[:, 1].tolist(), shrink=.7, label="Corn share (%)")
    fig.suptitle("CDL crop history by field and year", y=.995)
    add_note(fig, "CDL years 2019–2023; percentages are raw field shares and residual/background is not silently renormalized.")
    artifacts["figures/cdl_timeline.png"] = save_figure(fig, out_figures / "cdl_timeline.png")
    crop_mix = mix.groupby(["grower_slug", "year", "crop_group"], as_index=False).estimated_acres.sum()
    fig, axes = plt.subplots(1, len(growers), figsize=(13, 4.5), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, grower in zip(axes, growers):
        group = crop_mix[crop_mix.grower_slug.eq(grower)].pivot(index="year", columns="crop_group", values="estimated_acres").fillna(0).sort_index()
        bottom = np.zeros(len(group))
        for crop in ["Corn", "Soybeans", "Other"]:
            if crop in group:
                ax.bar(group.index, group[crop], bottom=bottom, color=crop_colors[crop], label=crop); bottom += group[crop].to_numpy()
        ax.set_title(grower.replace("-", " ").title()); ax.set_xlabel("Year"); ax.grid(axis="y", alpha=.2)
    axes[0].set_ylabel("Estimated acres"); axes[-1].legend(frameon=False, fontsize=8)
    fig.suptitle("Estimated CDL crop mix by grower")
    add_note(fig, "Estimated acres = boundary acres × CDL share; 2019–2023; non-corn/soy classes remain grouped as Other.")
    artifacts["figures/cdl_crop_mix.png"] = save_figure(fig, out_figures / "cdl_crop_mix.png")
    return artifacts


def process_farm(grower: Path, farm: Path, args: argparse.Namespace, root: Path) -> dict[str, Any]:
    boundaries, fields = validate_fields(farm)
    weather = pd.read_csv(weather_path(farm, args.start_year, args.end_year))
    seasonal, cells = seasonal_weather(weather, boundaries, args.start_year, args.end_year, args.season_start, args.season_end)
    history, mix, rotation = cdl_tables(boundaries, cdl_paths(farm))
    inventory = boundaries[["field_id", "state", "county", "area_acres", "area_ha_est", "crop", "source", "csb_id"]].copy()
    inventory["field_id"] = inventory.field_id.astype(str)
    inventory["grower_slug"] = grower.name
    inventory["farm_slug"] = farm.name
    projected = boundaries.to_crs(5070)
    inventory["_geometry"] = list(projected.geometry)
    cells["grower_slug"] = grower.name
    cells["farm_slug"] = farm.name
    seasonal["grower_slug"] = grower.name
    seasonal["farm_slug"] = farm.name
    history["grower_slug"] = grower.name
    history["farm_slug"] = farm.name
    mix["grower_slug"] = grower.name
    mix["farm_slug"] = farm.name
    rotation["grower_slug"] = grower.name
    rotation["farm_slug"] = farm.name
    out = grower / "derived" / "eda-story"
    artifacts: dict[str, str] = {}
    if not args.dry_run:
        for name, frame in {
            "field_inventory.csv": inventory, "weather_cells.csv": cells,
            "field_weather_seasonal.csv": seasonal, "field_cdl_history.csv": history,
            "field_crop_mix.csv": mix, "field_rotation_summary.csv": rotation,
        }.items():
            artifacts[f"tables/{name}"] = write_frame(frame, out / "tables" / name)
    return {"grower_slug": grower.name, "farm_slug": farm.name, "field_count": len(fields),
            "field_ids": fields, "weather_rows": int(len(weather)),
            "weather_years": sorted(weather.date.astype(str).str[:4].unique().tolist()) if "date" in weather else [],
            "cdl_years": sorted(history.year.unique().tolist()), "weather_unique_cells": int(cells.grid_key.nunique()),
            "warnings": ([] if len(fields) == 10 else [f"expected 10 fields, found {len(fields)}"]),
            "artifacts": artifacts, "frames": {"inventory": inventory, "cells": cells, "seasonal": seasonal,
            "history": history, "mix": mix, "rotation": rotation}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all-growers", action="store_true")
    scope.add_argument("--grower-slug", action="append")
    parser.add_argument("--farm-slug")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START)
    parser.add_argument("--end-year", type=int, default=DEFAULT_END)
    parser.add_argument("--season-start", type=int, default=4)
    parser.add_argument("--season-end", type=int, default=9)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = runtime_root()
    if args.output_root is not None and not args.output_root.is_absolute():
        raise SystemExit("--output-root must be absolute")
    growers = selected_growers(root, args.grower_slug)
    if not args.all_growers and not args.grower_slug:
        raise SystemExit("choose --all-growers or --grower-slug")
    results = []
    errors = []
    for grower in growers:
        for farm in only_farm(grower, args.farm_slug):
            try:
                results.append(process_farm(grower, farm, args, root))
            except (FileNotFoundError, ValueError, KeyError) as exc:
                errors.append({"grower_slug": grower.name, "farm_slug": farm.name, "error": str(exc)})
    if errors:
        raise SystemExit(json.dumps({"errors": errors}, indent=2))
    frames = {key: pd.concat([result["frames"][key] for result in results], ignore_index=True)
              for key in ["inventory", "cells", "seasonal", "history", "mix", "rotation"]}
    cross_dir = args.output_root or (root / "derived" / "eda-story")
    cross_artifacts = {}
    if not args.dry_run:
        cross_fields = frames["inventory"].drop(columns=["_geometry"], errors="ignore").copy()
        weather_rollup = frames["seasonal"].groupby(["grower_slug", "field_id"], as_index=False).agg(
            median_season_precip_mm=("season_precip_mm", "median"), median_gdd10=("gdd10", "median"),
            weather_cells=("grid_key", "nunique"))
        crop_rollup = frames["mix"].pivot_table(index=["grower_slug", "field_id"], columns="crop_group", values="estimated_acres", aggfunc="sum", fill_value=0).reset_index()
        crop_rollup.columns = [str(column).lower().replace(" ", "_") if isinstance(column, str) else column for column in crop_rollup.columns]
        cross_fields = cross_fields.merge(weather_rollup, on=["grower_slug", "field_id"], how="left").merge(crop_rollup, on=["grower_slug", "field_id"], how="left")
        cross_artifacts["tables/cross_grower_fields.csv"] = write_frame(cross_fields, cross_dir / "tables" / "cross_grower_fields.csv")
        cross_artifacts.update(build_analysis_and_figures(
            frames, cross_dir, args.start_year, args.end_year,
            args.season_start, args.season_end))
    manifest = {
        "generator": "grower_eda_story", "version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(), "git_revision": git_revision(),
        "runtime_root": str(root), "args": vars(args) | {"output_root": str(args.output_root) if args.output_root else None},
        "scope": {"growers": [r["grower_slug"] for r in results], "farm_count": len(results),
                  "field_count": sum(r["field_count"] for r in results)},
        "windows": {"weather": [args.start_year, args.end_year], "cdl": [2019, 2023],
                     "season_months": [args.season_start, args.season_end]},
        "farms": [{k: v for k, v in result.items() if k != "frames"} for result in results],
        "cross_artifacts": cross_artifacts,
        "notes": ["Static figures and comparison tables are generated; report generation remains external.",
                   "Weather is centroid/grid data and effective cell counts must be used when comparing fields.",
                   "No soil, satellite, terrain, yield, management, irrigation, or causal analysis is included."],
    }
    manifest_path = cross_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    for result in results:
        farm_manifest = Path(root / "growers" / result["grower_slug"] / "derived" / "eda-story" / "manifest.json")
        farm_manifest.parent.mkdir(parents=True, exist_ok=True)
        farm_manifest.write_text(json.dumps(manifest | {"scope": result}, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"farms": len(results), "fields": manifest["scope"]["field_count"], "dry_run": args.dry_run, "errors": errors}, indent=2))


if __name__ == "__main__":
    main()
