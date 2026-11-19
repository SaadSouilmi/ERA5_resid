"""Map current observation sources using the approved Plotly/OpenStreetMap style."""

import argparse
import asyncio
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import plotly.express as px
import polars as pl

from py.paths import AnalysisDataDirectory, NotebookFiguresDirectory
from py.preprocessing.match_era5_grid import sha256
from py.publication import ExportNotebookPlotlyFigure as export_plotly_figure
from py.publication import Font as FONT


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
        math.asinh(math.tan(math.radians(latitude))) / (2 * math.pi)
        for latitude in (south, north)
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


async def export_station_map():
    input_path = AnalysisDataDirectory / "station_era5_clean.parquet"
    sources = source_means(pl.read_parquet(input_path))
    directory = NotebookFiguresDirectory / "station_map"
    tables = directory / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    sources.write_csv(tables / "source_means.csv")
    await export_plotly_figure(station_map(sources), "station_map", "station_map", Dpi=900)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {str(input_path): sha256(input_path)},
        "source_locations": sources.height,
        "observations": sources["n_observations"].sum(),
        "grouping": ["SOUID", "source_lat", "source_lon"],
        "style": "Original Plotly/OpenStreetMap, square panel, 900 dpi, 24 px margin",
        "code_sha256": {__file__: sha256(Path(__file__))},
        "outputs": {
            str(path): sha256(path)
            for path in [
                tables / "source_means.csv",
                directory / "station_map.pdf",
                directory / "station_map.plotly.json",
            ]
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    asyncio.run(export_station_map())


if __name__ == "__main__":
    main()
