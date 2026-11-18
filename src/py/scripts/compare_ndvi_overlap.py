"""Compare retrieved NDVI with original seasonal rasters in identical 80 m cells."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import rasterio
from affine import Affine

from py.ndvi_observations import AddMonths as add_months
from py.ndvi_observations import WriteJson as write_json
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import RawDataDirectory as RAW_DIRECTORY

TASK_KEYS = ["cell_id", "season_start"]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_reference(directory, tasks, manifest):
    files = [
        RAW_DIRECTORY / "sentinel2_ndvi" / f"ndvi_{start}_{add_months(start, 3)}.tif"
        for start in tasks["season_start"].unique().sort()
    ]
    identity = {
        "tasks_sha256": sha256(directory / "tasks.parquet"),
        "script_sha256": sha256(Path(__file__)),
        "rasters": [
            {"path": str(path), "size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
            for path in files
        ],
    }
    reference_file = directory / "original_cell_season_ndvi.parquet"
    metadata_file = directory / "original_reference_manifest.json"
    if reference_file.exists():
        metadata = json.loads(metadata_file.read_text())
        if metadata["identity"] != identity or metadata["reference_sha256"] != sha256(
            reference_file
        ):
            raise ValueError("Original reference inputs changed; use a fresh comparison directory")
        return pl.read_parquet(reference_file)
    transform = Affine(*manifest["grid_transform"][:6])
    frames, fingerprints = [], []
    for path, start in zip(files, tasks["season_start"].unique().sort()):
        subset = tasks.filter(pl.col("season_start") == start).sort("cell_row", "cell_column")
        rows = subset["cell_row"].to_numpy()
        columns = subset["cell_column"].to_numpy()
        values = np.full(len(subset), np.nan)
        with rasterio.open(path) as raster:
            if raster.crs.to_epsg() != 3035 or raster.transform != transform:
                raise ValueError(f"Original raster grid differs: {path.name}")
            inside = (
                (rows >= 0) & (rows < raster.height) & (columns >= 0) & (columns < raster.width)
            )
            indices = np.flatnonzero(inside)
            x, y = rasterio.transform.xy(transform, rows[indices], columns[indices])
            for index, sample in zip(indices, raster.sample(zip(x, y), indexes=1, masked=True)):
                if not np.ma.is_masked(sample[0]) and 0 <= sample[0] <= 254:
                    values[index] = float(sample[0]) / 254 * 2 - 1
        frames.append(
            subset.select(TASK_KEYS)
            .with_columns(
                pl.Series("ndvi_original", values).fill_nan(None),
                pl.Series("original_in_grid", inside),
                pl.lit(path.name).alias("original_source_file"),
            )
            .with_columns(
                pl.when(~pl.col("original_in_grid"))
                .then(pl.lit("outside_grid"))
                .when(pl.col("ndvi_original").is_null())
                .then(pl.lit("nodata"))
                .otherwise(pl.lit("available"))
                .alias("original_status")
            )
        )
        fingerprints.append({"path": str(path), "sha256": sha256(path)})
        print(f"Original {start}: {len(subset)} cells sampled", flush=True)
    reference = pl.concat(frames).sort(TASK_KEYS)
    reference.write_parquet(reference_file, compression="zstd")
    write_json(
        metadata_file,
        {
            "identity": identity,
            "source_files": fingerprints,
            "reference_sha256": sha256(reference_file),
            "encoding": "Original values 0..254 converted with value / 254 * 2 - 1; nodata excluded",
        },
    )
    return reference


def metric_expressions():
    return [
        pl.len().alias("paired_cell_seasons"),
        pl.col("difference").mean().alias("mean_difference"),
        pl.col("difference").median().alias("median_difference"),
        pl.col("difference").abs().mean().alias("mean_absolute_difference"),
        pl.col("difference").pow(2).mean().sqrt().alias("root_mean_square_difference"),
        pl.corr("ndvi_original", "ndvi_observed").fill_nan(None).alias("pearson_correlation"),
    ]


def compare_snapshot(directory, reference, sources, manifest):
    payload = (directory / "cell_season_ndvi.parquet").read_bytes()
    retrieved = pl.read_parquet(payload)
    comparison = (
        reference.join(retrieved, on=TASK_KEYS, how="left", validate="1:1")
        .with_columns(pl.col("status").fill_null("pending"))
        .with_columns(
            ((pl.col("status") == "observed_season") & pl.col("ndvi_original").is_not_null()).alias(
                "paired"
            ),
        )
        .with_columns(
            pl.when(pl.col("paired"))
            .then(pl.col("ndvi_observed") - pl.col("ndvi_original"))
            .alias("difference")
        )
    )
    paired = comparison.filter(pl.col("paired"))
    values = sources.join(comparison, on=TASK_KEYS, how="left", validate="m:1")
    for frame, name in ((comparison, "comparison_cells"), (values, "comparison_sources")):
        temporary = directory / f"{name}.tmp.parquet"
        frame.write_parquet(temporary, compression="zstd")
        temporary.replace(directory / f"{name}.parquet")
    paired.group_by("season_start").agg(metric_expressions()).sort("season_start").write_csv(
        directory / "comparison_by_season.csv"
    )
    comparison.group_by("season_start", "original_status", "status").agg(
        pl.len().alias("cell_seasons")
    ).sort("season_start", "original_status", "status").write_csv(
        directory / "comparison_coverage.csv"
    )
    summary = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "all_retrievals_processed" if len(retrieved) == len(reference) else "partial",
        "scope_start": manifest["start"],
        "scope_end_exclusive": manifest["end_exclusive"],
        "total_cell_seasons": len(reference),
        "processed_cell_seasons": len(retrieved),
        "original_available_cell_seasons": reference["ndvi_original"].is_not_null().sum(),
        "paired_source_seasons": values["paired"].sum(),
        "retrieval_status_counts": comparison.group_by("status").len().sort("status").to_dicts(),
        "metrics": paired.select(metric_expressions()).to_dicts()[0],
        "difference_definition": "New Sentinel-2-derived NDVI minus original supplied NDVI",
        "weighting": "Each distinct 80 m cell-season equally weighted; repeated station/source/daily records do not add weight",
        "interpretation": "Product agreement, not validation against ground truth. Partial results follow geographic task order and are not representative. Clear-image selection and missing reference values change the paired sample. Original NDVI is quantized in steps of 2/254.",
        "retrieved_snapshot_sha256": hashlib.sha256(payload).hexdigest(),
        "retrieval_manifest_sha256": sha256(directory / "manifest.json"),
        "reference_sha256": sha256(directory / "original_cell_season_ndvi.parquet"),
        "comparison_script_sha256": sha256(Path(__file__)),
        "adopted_into_analysis": False,
    }
    write_json(directory / "comparison_summary.json", summary)
    print(
        f"Comparison: {len(retrieved)}/{len(reference)} retrieved; {len(paired)} paired cells; mean difference={summary['metrics']['mean_difference']}",
        flush=True,
    )
    return len(retrieved) == len(reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="sentinel2_selected_overlap_v1")
    parser.add_argument(
        "--watch", action="store_true", help="Update every minute until the download exits"
    )
    args = parser.parse_args()
    if Path(args.label).name != args.label or args.label in ("", ".", ".."):
        parser.error("Use a plain directory label")
    directory = DATA_DIRECTORY / "ndvi_observed" / args.label
    manifest = json.loads((directory / "manifest.json").read_text())
    tasks = pl.read_parquet(directory / "tasks.parquet")
    sources = pl.read_parquet(directory / "source_seasons.parquet")
    reference = read_reference(directory, tasks, manifest)
    while True:
        exit_status = directory / "download.exit_status"
        finished = exit_status.exists() and exit_status.read_text().strip() != "running"
        complete = compare_snapshot(directory, reference, sources, manifest)
        if not args.watch or finished or complete:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
