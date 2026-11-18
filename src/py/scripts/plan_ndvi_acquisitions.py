"""Plan full-history NDVI coverage at every selected source location."""

import argparse
import json
from datetime import date
from pathlib import Path

import polars as pl
import rasterio
from affine import Affine
from pyproj import Transformer

from py.ndvi_observations import AddMonths as add_months
from py.ndvi_observations import SeasonStart as season_start
from py.ndvi_observations import WriteJson as write_json
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.scripts.fetch_ndvi_acquisitions import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=date(2019, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 9, 1))
    parser.add_argument("--label", default="sentinel2_full_history_plan_v1")
    args = parser.parse_args()
    if Path(args.label).name != args.label or args.label in ("", ".", ".."):
        parser.error("Use a plain directory label")
    if args.start.day != 1 or args.end.day != 1 or args.end <= args.start:
        parser.error("Use increasing month boundaries")
    root = DATA_DIRECTORY / "ndvi_observed"
    directory = root / args.label
    input_file = DATA_DIRECTORY / "selected_station_observations.parquet"
    reference = json.loads((root / "sentinel2_selected_gap_v1/manifest.json").read_text())
    transform = Affine(*reference["grid_transform"][:6])
    sources = (
        pl.scan_parquet(input_file)
        .group_by("SOUID", "source_lat", "source_lon")
        .agg(
            pl.col("DATE").min().alias("first_station_date"),
            pl.col("DATE").max().alias("last_station_date"),
        )
        .sort("SOUID", "source_lat", "source_lon")
        .collect()
    )
    x, y = Transformer.from_crs(4326, 3035, always_xy=True).transform(
        sources["source_lon"].to_numpy(), sources["source_lat"].to_numpy()
    )
    rows, columns = rasterio.transform.rowcol(transform, x, y)
    sources = sources.with_columns(
        pl.Series("cell_row", rows), pl.Series("cell_column", columns)
    ).with_columns(
        pl.concat_str(pl.lit("cell"), "cell_row", "cell_column", separator="_").alias("cell_id")
    )
    cells = sources.select("cell_id", "cell_row", "cell_column").unique().sort("cell_id")
    x, y = rasterio.transform.xy(transform, cells["cell_row"], cells["cell_column"])
    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(x, y)
    cells = cells.with_columns(pl.Series("source_lon", lon), pl.Series("source_lat", lat))
    periods, start = [], args.start
    while start < args.end:
        end = min(add_months(season_start(start), 3), args.end)
        periods.append({"season_start": start, "season_end": end})
        start = end
    periods = pl.DataFrame(periods)
    tasks = (
        cells.join(periods, how="cross")
        .with_columns(
            pl.when(pl.col("season_start") >= date(2023, 12, 1))
            .then(0)
            .when(pl.col("season_end") > date(2020, 1, 1))
            .then(1)
            .otherwise(2)
            .alias("priority"),
            pl.col("cell_id").hash(seed=2026).alias("cell_order"),
        )
        .sort("priority", "season_start", "cell_order")
    )
    source_seasons = sources.join(periods, how="cross")
    manifest = {
        "input_file": str(input_file),
        "input_sha256": sha256(input_file),
        "start": str(args.start),
        "end_exclusive": str(args.end),
        "study_start": "2020-01-01",
        "study_end_exclusive": "2025-09-01",
        "grid_transform": reference["grid_transform"],
        "grid_reference": reference["grid_reference"],
        "sources": sources["SOUID"].n_unique(),
        "source_locations": len(sources),
        "cells": len(cells),
        "periods": len(periods),
        "cell_seasons": len(tasks),
        "scope": "Every selected source location in every period, including periods without station observations; one-year pre-study lookback by default",
        "period_definition": "Meteorological season blocks for catalogue caching only; first and last blocks clipped to requested dates; output remains per acquisition",
        "reuse_catalog_directories": [
            str(root / label / "catalog")
            for label in (
                "sentinel2_selected_gap_v1",
                "sentinel2_selected_overlap_v1",
            )
        ],
        "reuse_metadata_directories": [
            str(root / label / "product_metadata")
            for label in (
                "sentinel2_selected_gap_v1",
                "sentinel2_selected_overlap_v1",
            )
        ],
        "code_sha256": sha256(Path(__file__)),
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError("Plan changed; use a new output label")
    for name in ("catalog", "product_metadata"):
        (directory / name).mkdir(exist_ok=True)
    write_json(path, manifest)
    sources.write_parquet(directory / "source_cells.parquet")
    source_seasons.write_parquet(directory / "source_seasons.parquet")
    tasks.write_parquet(directory / "tasks.parquet")
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
