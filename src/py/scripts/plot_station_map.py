"""Map current source residuals with a clean atlas style or the original street map."""

import argparse
import asyncio
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import plotly.express as px
import polars as pl
from matplotlib.colors import Normalize
from pyproj import Transformer

from py.paths import AnalysisDataDirectory, ANALYSIS_FIGURES_DIRECTORY
from py.preprocessing.match_era5_grid import sha256
from py.publication import export_analysis_plotly_figure
from py.publication import Font as FONT
from py.scripts.plot_style import INK, MUTED, paper_style

BASEMAP_SOURCE = AnalysisDataDirectory / "clean/sources/ne_50m_admin_0_countries.shp"


def source_means(observations):
    return (
        observations.group_by("SOUID", "source_lat", "source_lon")
        .agg(
            pl.col("residual_celsius").mean().alias("residual"),
            pl.col("source_name", "country_code").first(),
            pl.len().alias("n_observations"),
        )
        .rename({"source_lat": "lat", "source_lon": "lon"})
        .sort("SOUID", "lat", "lon")
    )


def station_map(sources):
    west, east = sources["lon"].min(), sources["lon"].max()
    south, north = sources["lat"].min(), sources["lat"].max()
    south_y, north_y = [
        math.asinh(math.tan(math.radians(latitude))) / (2 * math.pi) for latitude in (south, north)
    ]
    width, padding = 800, 24
    longitude_span = (east - west) / 360
    zoom = math.log2((width - 2 * padding) / (512 * max(longitude_span, north_y - south_y)))
    center = {
        "lat": math.degrees(math.atan(math.sinh(math.pi * (south_y + north_y)))),
        "lon": (west + east) / 2,
    }
    figure = px.scatter_map(
        sources,
        lat="lat",
        lon="lon",
        color="residual",
        color_continuous_scale="RdBu_r",
        range_color=[-3, 3],
        zoom=zoom,
        center=center,
        hover_data=["SOUID", "source_name", "country_code", "residual", "n_observations"],
    )
    figure.update_traces(
        lat=sources["lat"].to_list(),
        lon=sources["lon"].to_list(),
        marker={"size": 6, "color": sources["residual"].to_list()},
    )
    figure.update_layout(
        width=width + 120,
        height=width,
        margin={"l": 0, "r": 120, "t": 0, "b": 0, "autoexpand": False},
        template="plotly_white",
        font={"family": FONT, "size": 19},
        map_style="open-street-map",
        coloraxis_colorbar={
            "title": {"text": "Mean<br>residual<br>(°C)"},
            "thickness": 22,
            "len": 0.85,
            "x": 1.01,
            "xanchor": "left",
            "tickvals": [-3, -2, -1, 0, 1, 2, 3],
            "ticktext": ["≤ −3", "−2", "−1", "0", "1", "2", "≥ 3"],
        },
        meta={"export_width_mm": 180, "map_dpi": 900, "station_padding_px": padding},
    )
    return figure


def clean_map(sources, directory):
    bounds = (-60, 15, 110, 85)
    land = gpd.read_file(BASEMAP_SOURCE, bbox=bounds)[["ADMIN", "geometry"]].clip(bounds)
    geometry_path = directory / "tables/basemap.geojson"
    geometry_path.write_text(land.to_json(drop_id=True))
    land = land.to_crs("EPSG:3035")
    project = Transformer.from_crs("EPSG:4326", "EPSG:3035", always_xy=True)
    x, y = project.transform(sources["lon"].to_numpy(), sources["lat"].to_numpy())
    span = max(np.ptp(x), np.ptp(y)) * 1.12
    center_x, center_y = (min(x) + max(x)) / 2, (min(y) + max(y)) / 2

    paper_style()
    fig = plt.figure(figsize=(8.6, 10.0), facecolor="white")
    ax = fig.add_axes([0.035, 0.145, 0.93, 0.7998])
    ax.set_facecolor("#F3F7F8")
    land.plot(ax=ax, facecolor="#ECEDE9", edgecolor="#B4BDBB", linewidth=0.35, zorder=1)
    ax.set(
        xlim=(center_x - span / 2, center_x + span / 2),
        ylim=(center_y - span / 2, center_y + span / 2),
        aspect="equal",
    )
    for latitude in [40, 50, 60, 70]:
        longitudes = np.linspace(-45, 65, 250)
        gx, gy = project.transform(longitudes, np.full(len(longitudes), latitude))
        ax.plot(gx, gy, color="#D5DEDC", linewidth=0.4, linestyle=(0, (3, 5)), zorder=0)
    for longitude in [-20, 0, 20, 40]:
        latitudes = np.linspace(25, 80, 250)
        gx, gy = project.transform(np.full(len(latitudes), longitude), latitudes)
        ax.plot(gx, gy, color="#D5DEDC", linewidth=0.4, linestyle=(0, (3, 5)), zorder=0)
    points = ax.scatter(
        x,
        y,
        c=sources["residual"].to_numpy(),
        cmap="RdBu_r",
        norm=Normalize(-3, 3),
        s=9,
        linewidths=0.25,
        edgecolors="white",
        zorder=3,
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.text(0.04, 0.978, "Station–ERA5-Land temperature residuals", fontsize=16, color=INK)
    colorbar_ax = fig.add_axes([0.19, 0.078, 0.62, 0.018])
    colorbar = fig.colorbar(points, cax=colorbar_ax, orientation="horizontal", extend="both")
    colorbar.set_ticks([-3, -2, -1, 0, 1, 2, 3], labels=["≤−3", "−2", "−1", "0", "1", "2", "≥3"])
    colorbar.set_label("Mean station − ERA5-Land residual (°C)", fontsize=10, labelpad=9)
    colorbar.ax.xaxis.set_label_position("top")
    colorbar.outline.set_visible(False)
    colorbar.ax.tick_params(labelsize=9, length=2, width=0.5)
    fig.text(0.19, 0.037, "ERA5-Land warmer", fontsize=9, color="#375E7C")
    fig.text(0.81, 0.037, "ERA5-Land cooler", fontsize=9, color="#934354", ha="right")
    fig.text(0.96, 0.012, "Natural Earth · LAEA Europe", fontsize=7, color=MUTED, ha="right")
    paths = [directory / "station_map.png", directory / "station_map.pdf"]
    for path in paths:
        fig.savefig(path, dpi=900, facecolor="white", bbox_inches=None)
    plt.close(fig)
    return [*paths, geometry_path]


async def export_station_map(style="clean"):
    input_path = AnalysisDataDirectory / "station_era5_clean.parquet"
    observations = pl.read_parquet(input_path)
    sources = source_means(observations)
    directory = ANALYSIS_FIGURES_DIRECTORY / "station_map"
    tables = directory / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    sources.write_csv(tables / "source_means.csv")
    if style == "clean":
        plt.switch_backend("Agg")
        outputs = clean_map(sources, directory)
        presentation = "Clean atlas, EPSG:3035, square panel, cached Natural Earth land/borders, 900 dpi PNG and vector PDF"
    else:
        await export_analysis_plotly_figure(
            station_map(sources), "station_map", "station_map_original", dpi=900
        )
        outputs = [
            directory / "station_map_original.pdf",
            directory / "station_map_original.plotly.json",
        ]
        presentation = "Original Plotly/OpenStreetMap, square panel, 900 dpi, 24 px margin"
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {str(input_path): sha256(input_path)},
        "source_locations": sources.height,
        "observations": sources["n_observations"].sum(),
        "grouping": ["SOUID", "source_lat", "source_lon"],
        "style": presentation,
        "residual": "Source-day mean of station minus ERA5-Land window maximum, in degrees Celsius",
        "colour_limits": [-3, 3],
        "colour_clipping": "Colours saturate outside ±3°C; source values are unchanged",
        "first_date": observations["DATE"].min(),
        "last_date": observations["DATE"].max(),
        "basemap": {
            str(path): sha256(path)
            for path in [
                BASEMAP_SOURCE.with_suffix(suffix)
                for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg")
            ]
        }
        if style == "clean"
        else "OpenStreetMap",
        "code_sha256": {
            str(path): sha256(path)
            for path in [Path(__file__), Path(__file__).with_name("plot_style.py")]
        },
        "outputs": {
            str(path): sha256(path)
            for path in [
                tables / "source_means.csv",
                *outputs,
            ]
        },
    }
    manifest_name = "manifest.json" if style == "clean" else "original_manifest.json"
    (directory / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Saved {style} map: {sources.height:,} source locations, {observations.height:,} source-days",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--style", choices=["clean", "original"], default="clean")
    args = parser.parse_args()
    asyncio.run(export_station_map(args.style))


if __name__ == "__main__":
    main()
