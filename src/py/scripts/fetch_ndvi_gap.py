"""Retrieve observed seasonal NDVI for the selected station sample's missing years."""

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl
import rasterio
from pyproj import Transformer

from py.ndvi_observations import FetchSeason as fetch_season
from py.ndvi_observations import SeasonStart as season_start
from py.ndvi_observations import WriteJson as write_json
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import RawDataDirectory as RAW_DIRECTORY

SOURCE_KEYS = ["SOUID", "source_lat", "source_lon"]
TASK_KEYS = ["cell_id", "season_start"]
RESULT_SCHEMA = {
    "cell_id": pl.String,
    "season_start": pl.Date,
    "ndvi_observed": pl.Float64,
    "status": pl.String,
    "valid_dates": pl.Int32,
    "valid_months": pl.Int32,
    "attempted_scenes": pl.Int32,
    "catalog_scenes": pl.Int32,
    "scene_errors": pl.Int32,
    "error_type": pl.String,
}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare_sources(input_file, start, end, transform):
    sources = (
        pl.scan_parquet(input_file)
        .with_columns(pl.col("DATE").cast(pl.String).str.to_date("%Y%m%d").alias("date"))
        .filter((pl.col("date") >= start) & (pl.col("date") < end))
        .with_columns(
            pl.col("date")
            .dt.offset_by("1mo")
            .dt.truncate("1q")
            .dt.offset_by("-1mo")
            .alias("season_start")
        )
        .group_by(*SOURCE_KEYS, "season_start")
        .agg(pl.len().alias("observations"), pl.col("DATE").n_unique().alias("source_days"))
        .sort(*SOURCE_KEYS, "season_start")
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
    tasks = sources.select(*TASK_KEYS, "cell_row", "cell_column").unique().sort(*TASK_KEYS)
    x, y = rasterio.transform.xy(transform, tasks["cell_row"], tasks["cell_column"])
    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(x, y)
    tasks = tasks.with_columns(pl.Series("source_lat", lat), pl.Series("source_lon", lon))
    return sources, tasks


def retrieve_task(task, directory, transform, retry_failed):
    cache = directory / "seasons" / f"{task['cell_id']}_{task['season_start']}.json"
    if retry_failed and cache.exists():
        previous = json.loads(cache.read_text())
        if previous["errors"] and previous["status"] != "observed_season":
            cache.unlink()
    source = {
        "SOUID": task["cell_id"],
        "source_lat": task["source_lat"],
        "source_lon": task["source_lon"],
    }
    result = fetch_season(source, task["season_start"], directory, transform)
    status = result["status"]
    if result["errors"] and status != "observed_season":
        status = "incomplete_fetch"
    return {
        "cell_id": task["cell_id"],
        "season_start": task["season_start"],
        **{
            key: result[key]
            for key in (
                "ndvi_observed",
                "valid_dates",
                "valid_months",
                "attempted_scenes",
                "catalog_scenes",
            )
        },
        "status": status,
        "scene_errors": len(result["errors"]),
        "error_type": None,
    }


def save_progress(results, sources, tasks, directory, started, finished=False):
    cells = pl.DataFrame(results, schema=RESULT_SCHEMA).sort(*TASK_KEYS)
    values = sources.join(cells, on=TASK_KEYS, how="left", validate="m:1").with_columns(
        pl.col("status").fill_null("pending"),
        pl.col("season_start").dt.offset_by("3mo").alias("season_end"),
    )
    coverage = (
        values.group_by("season_start", "status")
        .agg(
            pl.len().alias("source_seasons"),
            pl.col("cell_id").n_unique().alias("cells"),
            pl.col("observations").sum(),
            pl.col("source_days").sum(),
        )
        .sort("season_start", "status")
    )
    for frame, name in ((cells, "cell_season_ndvi"), (values, "source_season_ndvi")):
        temporary = directory / f"{name}.tmp.parquet"
        frame.write_parquet(temporary, compression="zstd")
        temporary.replace(directory / f"{name}.parquet")
    coverage.write_csv(directory / "coverage.csv")
    failures = cells.filter(pl.col("status").is_in(["incomplete_fetch", "download_failed"]))
    failures.write_csv(directory / "failed_cell_seasons.csv")
    write_json(
        directory / "progress.json",
        {
            "status": "complete_with_fetch_errors"
            if finished and len(failures)
            else ("complete" if finished else "running"),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 1),
            "total_cell_seasons": len(tasks),
            "completed_cell_seasons": len(cells),
            "observed_cell_seasons": cells.filter(pl.col("status") == "observed_season").height,
            "failed_cell_seasons": len(failures),
            "pending_cell_seasons": len(tasks) - len(cells),
            "source_season_counts": values.group_by("status").len().sort("status").to_dicts(),
            "adopted_into_analysis": False,
        },
    )
    if finished:
        values.write_csv(directory / "source_season_ndvi.csv")
    return len(failures)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=DATA_DIRECTORY / "selected_station_observations.parquet"
    )
    parser.add_argument("--start", type=date.fromisoformat, default=date(2023, 12, 1))
    parser.add_argument(
        "--end", type=date.fromisoformat, default=date(2025, 9, 1), help="Exclusive end"
    )
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--label", default="sentinel2_selected_gap_v1")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    if (
        season_start(args.start) != args.start
        or season_start(args.end) != args.end
        or args.end <= args.start
    ):
        parser.error("Dates must be increasing meteorological season boundaries")
    if args.workers < 1 or Path(args.label).name != args.label or args.label in ("", ".", ".."):
        parser.error("Use positive workers and a plain directory label")
    directory = DATA_DIRECTORY / "ndvi_observed" / args.label
    for name in ("catalog", "scene_values", "product_metadata", "seasons"):
        (directory / name).mkdir(parents=True, exist_ok=True)
    raster_file = sorted((RAW_DIRECTORY / "sentinel2_ndvi").glob("*.tif"))[0]
    with rasterio.open(raster_file) as raster:
        if raster.crs.to_epsg() != 3035 or raster.res != (80.0, 80.0):
            raise ValueError("Expected the original 80 m EPSG:3035 NDVI grid")
        transform = raster.transform
    sources, tasks = prepare_sources(args.input, args.start, args.end, transform)
    manifest = {
        "input_file": str(args.input.resolve()),
        "input_sha256": sha256(args.input),
        "start": str(args.start),
        "end_exclusive": str(args.end),
        "collection": "sentinel-2-l2a",
        "provider": "Microsoft Planetary Computer",
        "sources": sources["SOUID"].n_unique(),
        "source_locations": sources.select(SOURCE_KEYS).unique().height,
        "source_seasons": len(sources),
        "cells": tasks["cell_id"].n_unique(),
        "cell_seasons": len(tasks),
        "grid_reference": str(raster_file),
        "grid_transform": list(transform),
        "grid": "Original 80 m EPSG:3035 cells, including cells outside the supplied raster extent",
        "scope": "Source-seasons with selected station observations; shared cells fetched once",
        "quality": "SCL 4/5/6; at least 50 native pixel centres in cell; at least 75% valid nonnegative red/NIR reflectance with positive sum; valid negative NDVI retained",
        "sampling": "Up to two distinct acquisition dates per month ordered by tile cloud percentage; up to 16 scene attempts per month",
        "aggregation": "Mean of valid native-pixel NDVI per acquisition; monthly median; equal-weight mean of all three months; each month required",
        "reflectance": "Product XML quantification and per-band offsets applied",
        "code_sha256": {
            path.name: sha256(path)
            for path in (Path(__file__), Path(__file__).parents[1] / "ndvi_observations.py")
        },
        "status": "Candidate observed estimates; original compositing recipe unknown; not adopted",
    }
    manifest_file = directory / "manifest.json"
    if manifest_file.exists() and json.loads(manifest_file.read_text()) != manifest:
        raise ValueError("Input, scope or method changed; use a new output label")
    write_json(manifest_file, manifest)
    sources.write_parquet(directory / "source_seasons.parquet")
    sources.select(SOURCE_KEYS + ["cell_id", "cell_row", "cell_column"]).unique().sort(
        SOURCE_KEYS
    ).write_csv(directory / "selected_sources.csv")
    tasks.write_parquet(directory / "tasks.parquet")
    print(
        f"Sources: {manifest['sources']}; cells: {manifest['cells']}; source-seasons: {len(sources)}; cell-seasons: {len(tasks)}",
        flush=True,
    )
    if args.plan_only:
        return
    started = time.monotonic()
    results = []
    save_progress(results, sources, tasks, directory, started)
    last_saved = started
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {
            pool.submit(retrieve_task, task, directory, transform, args.retry_failed): task
            for task in tasks.iter_rows(named=True)
        }
        for future in as_completed(pending):
            task = pending[future]
            try:
                result = future.result()
            except Exception as error:
                result = {key: None for key in RESULT_SCHEMA}
                result.update({key: task[key] for key in TASK_KEYS})
                result.update(status="download_failed", error_type=type(error).__name__)
            results.append(result)
            print(
                f"{len(results)}/{len(tasks)} {task['cell_id']} {task['season_start']} {result['status']} ndvi={result['ndvi_observed']} scene_errors={result['scene_errors']} error_type={result['error_type']}",
                flush=True,
            )
            if len(results) % 50 == 0 or time.monotonic() - last_saved >= 60:
                save_progress(results, sources, tasks, directory, started)
                last_saved = time.monotonic()
    failures = save_progress(results, sources, tasks, directory, started, finished=True)
    print(f"Saved {directory}; retrieval errors in {failures} cell-seasons", flush=True)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
