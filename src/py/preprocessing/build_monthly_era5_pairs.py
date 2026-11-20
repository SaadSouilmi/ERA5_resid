"""Write one station-observation Parquet per labelled month, with inclusive ERA5 maxima."""

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd
import polars as pl
import xarray as xr

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.preprocessing.era5_windows import match_month, outside_download, read_month_cells
from py.preprocessing.match_era5_grid import SOURCE_KEYS, sha256


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    started = time.monotonic()
    input_path = DATA_DIRECTORY / "selected_station_observations.parquet"
    grid_path = DATA_DIRECTORY / "selected_station_era5_grid.parquet"
    output_dir = DATA_DIRECTORY / "station_era5_monthly"
    audit_dir = DATA_DIRECTORY / "cleaning_audit"
    manifest_path = audit_dir / "station_era5_monthly.json"
    input_hash, grid_hash = sha256(input_path), sha256(grid_path)
    observations = pl.read_parquet(input_path).with_row_index("observation_id")
    grid = pl.read_parquet(grid_path).drop("observation_count", "first_date", "last_date")
    grid_manifest = json.loads((audit_dir / "selected_station_era5_grid.json").read_text())
    if grid_hash != grid_manifest["output_sha256"]:
        raise ValueError("Grid lookup differs from its saved audit")
    files = {
        file.name[:7]: file
        for file in sorted(
            (DATA_DIRECTORY / "era5_land_hourly").glob("????-??_2m_temperature_hourly.nc")
        )
    }
    with xr.open_dataset(files[min(files)]) as data:
        lat, lon = data.latitude.values.copy(), data.longitude.values.copy()
        first_hour = pd.Timestamp(data.valid_time.values[0]).tz_localize("UTC").to_pydatetime()
    with xr.open_dataset(files[max(files)]) as data:
        last_hour = pd.Timestamp(data.valid_time.values[-1]).tz_localize("UTC").to_pydatetime()
    for name, values in [("latitude", lat), ("longitude", lon)]:
        if hashlib.sha256(values.tobytes()).hexdigest() != grid_manifest[f"{name}_sha256"]:
            raise ValueError(f"{name} axis differs from the saved grid lookup")

    mapped = observations.filter(pl.col("window_status") == "mapped")
    for name in ["window_start_utc", "window_end_utc"]:
        if mapped[name].null_count() or (mapped[name].dt.epoch("us") % 3_600_000_000 != 0).any():
            raise ValueError("Mapped observation boundaries must be on full UTC hours")
    if mapped.filter(pl.col("window_end_utc") < pl.col("window_start_utc")).height:
        raise ValueError("Observation window ends before it starts")
    input_count = observations.height
    dropped = observations.filter(outside_download(first_hour, last_hour)).select(
        "observation_id", "STAID", "SOUID", "DATE", "window_start_utc", "window_end_utc"
    )
    dropped.write_csv(audit_dir / "station_era5_monthly_dropped.csv")
    observations = observations.filter(~outside_download(first_hour, last_hour)).with_columns(
        (pl.col("DATE") // 100).alias("_month")
    )
    cells = (
        grid.filter(pl.col("grid_cell_id").is_not_null())
        .select("grid_cell_id", "latitude_index", "longitude_index")
        .unique()
        .sort("grid_cell_id")
        .with_row_index("_grid_column")
    )
    grid = grid.join(
        cells.select("grid_cell_id", "_grid_column"), on="grid_cell_id", how="left", validate="m:1"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "status": "running",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "input_sha256": input_hash,
        "grid_lookup": str(grid_path),
        "grid_lookup_sha256": grid_hash,
        "output_directory": str(output_dir),
        "input_records": input_count,
        "dropped_outside_download": dropped.height,
        "first_available_utc": first_hour.isoformat(),
        "last_available_utc": last_hour.isoformat(),
        "window_convention": "Both endpoints included: start <= valid_time <= end; a 24-hour window requires 25 samples.",
        "month_assignment": "ECA&D DATE, regardless of the UTC months touched by the observation window.",
        "maximum_policy": "Maximum of instantaneous hourly 2m_temperature, converted from Kelvin to Celsius; all required samples must be finite.",
        "unmatched_policy": "Retain unresolved windows and unavailable grid cells with null ERA5 maximum and explicit era5_match_status. Drop windows extending beyond downloaded timestamps.",
        "sampling_policy": "Preserve window_sampling. GSOD sampled reporting days are not guaranteed to use the same sample times as the ERA5 hourly maximum.",
        "observation_id": "Zero-based row position in the hashed input Parquet.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    sources = {}

    @lru_cache(maxsize=3)
    def load_month(month):
        values = read_month_cells(files[month], cells, lat, lon)
        sources[month] = {
            "file": str(files[month]),
            "sha256": sha256(files[month]),
            "hours": len(values),
        }
        print(f"Loaded ERA5 {month}: {len(values)} hours, {cells.height} grid cells", flush=True)
        return values

    monthly = []
    for month_id in observations["_month"].unique().sort():
        month = f"{month_id // 100:04d}-{month_id % 100:02d}"
        frame = (
            observations.filter(pl.col("_month") == month_id)
            .drop("_month")
            .join(grid, on=SOURCE_KEYS, how="left", validate="m:1")
        )
        if frame["grid_match_status"].null_count():
            raise ValueError("Selected observations contain locations absent from the grid lookup")
        result = match_month(frame, load_month)
        output_path = output_dir / f"{month}.parquet"
        result.write_parquet(output_path, compression="zstd")
        saved = pl.scan_parquet(output_path)
        checks = (
            saved.select(
                pl.len().alias("records"),
                pl.col("observation_id").n_unique().alias("unique_observations"),
                ((pl.col("DATE") // 100) != month_id).sum().alias("wrong_month"),
                (
                    (pl.col("era5_match_status") == "matched")
                    & (
                        pl.col("era5_tmax_celsius").is_null()
                        | (pl.col("era5_expected_samples") != pl.col("era5_available_samples"))
                    )
                )
                .sum()
                .alias("incomplete_matches"),
            )
            .collect()
            .row(0, named=True)
        )
        if (
            checks["records"] != frame.height
            or checks["unique_observations"] != frame.height
            or checks["wrong_month"]
            or checks["incomplete_matches"]
        ):
            raise ValueError(f"Saved monthly output failed consistency checks: {checks}")
        counts = dict(result.group_by("era5_match_status").len().iter_rows())
        monthly.append(
            {
                "month": month,
                "records": result.height,
                "matched": counts.get("matched", 0),
                "unknown_window": counts.get("unknown_window", 0),
                "masked_cell": counts.get("masked_cell", 0),
                "outside_grid": counts.get("outside_grid", 0),
                "incomplete_era5_hours": counts.get("incomplete_era5_hours", 0),
                "sampled_station_matches": result.filter(
                    (pl.col("era5_match_status") == "matched")
                    & (pl.col("window_sampling") == "hourly_or_synoptic_samples")
                ).height,
                "bytes": output_path.stat().st_size,
                "sha256": sha256(output_path),
            }
        )
        print(
            f"Saved {month}: {result.height:,} records; {counts.get('matched', 0):,} matched",
            flush=True,
        )

    coverage = pl.DataFrame(monthly)
    coverage.write_csv(audit_dir / "station_era5_monthly_coverage.csv")
    if coverage["records"].sum() + dropped.height != input_count:
        raise ValueError("Output and dropped records do not reconcile with the input")
    if sha256(input_path) != input_hash or sha256(grid_path) != grid_hash:
        raise ValueError("An input changed during extraction")
    manifest.update(
        {
            "status": "complete",
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.monotonic() - started,
            "monthly_files": coverage.height,
            "totals": coverage.select(pl.exclude("month", "sha256").sum()).row(0, named=True),
            "era5_sources": sources,
            "code_sha256": {
                str(path): sha256(path)
                for path in [
                    DATA_DIRECTORY.parent / "src/py/preprocessing/era5_windows.py",
                    DATA_DIRECTORY.parent / "src/py/preprocessing/build_monthly_era5_pairs.py",
                ]
            },
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in [
                    "status",
                    "monthly_files",
                    "dropped_outside_download",
                    "totals",
                    "elapsed_seconds",
                ]
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
