"""Download hourly ERA5-Land wind components and precipitation for the clean sample."""

import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import xarray as xr

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.preprocessing.download_era5_hourly import expected_times, save_json, unpack
from py.preprocessing.match_era5_grid import sha256

DATASET = "reanalysis-era5-land"
DIRECTORY = DATA_DIRECTORY / "era5_land_hourly_weather"
AUDIT_DIRECTORY = DATA_DIRECTORY / "cleaning_audit"
VARIABLES = {
    "u10": "10m_u_component_of_wind",
    "v10": "10m_v_component_of_wind",
    "tp": "total_precipitation",
}


def prepare():
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
    observations = pl.scan_parquet(input_path)
    bounds = (
        observations.select(
            pl.len().alias("observations"),
            pl.col("window_start_utc").min().alias("start"),
            pl.col("window_end_utc").max().alias("end"),
        )
        .collect()
        .row(0, named=True)
    )
    reference = next((DATA_DIRECTORY / "era5_land_hourly").glob("2020-01_*.nc"))
    with xr.open_dataset(reference) as data:
        lat, lon = data.latitude.values, data.longitude.values
    area = [float(lat.max()), float(lon.min()), float(lat.min()), float(lon.max())]
    first = (bounds["start"] - timedelta(hours=1)).date()
    last = bounds["end"].date()
    requests = []
    for month in pd.period_range(first, last, freq="M"):
        start = max(first, month.start_time.date())
        end = min(last, month.end_time.date())
        for field, variable in VARIABLES.items():
            requests.append(
                {
                    "month": str(month),
                    "field": field,
                    "first_date": start.isoformat(),
                    "last_date": end.isoformat(),
                    "expected_hours": ((end - start).days + 1) * 24,
                    "file": str(DIRECTORY / f"{month}_{field}.nc"),
                    "request": {
                        "variable": [variable],
                        "year": [str(month.year)],
                        "month": [f"{month.month:02d}"],
                        "day": [f"{day:02d}" for day in range(start.day, end.day + 1)],
                        "time": [f"{hour:02d}:00" for hour in range(24)],
                        "area": area,
                        "data_format": "netcdf",
                        "download_format": "unarchived",
                    },
                }
            )
    DIRECTORY.mkdir(exist_ok=True)
    observations.select(
        "grid_cell_id", "latitude_index", "longitude_index", "era5_lat", "era5_lon"
    ).unique().sort("grid_cell_id").collect().write_parquet(DIRECTORY / "cells.parquet")
    plan = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET,
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "observations": bounds["observations"],
        "required_start_utc": bounds["start"].isoformat(),
        "required_end_utc": bounds["end"].isoformat(),
        "download_start_date": first.isoformat(),
        "download_end_date": last.isoformat(),
        "boundary_buffer": "Include the previous UTC day for precipitation de-accumulation at midnight.",
        "reference_grid": str(reference),
        "area_north_west_south_east": area,
        "latitude_count": len(lat),
        "longitude_count": len(lon),
        "variables": VARIABLES,
        "requests": requests,
        "precipitation": "Original ERA5-Land forecast accumulations; convert to hourly amounts before summing station windows.",
        "code_sha256": {__file__: sha256(Path(__file__))},
    }
    save_json(AUDIT_DIRECTORY / "hourly_weather_plan.json", plan)
    print(
        f"Prepared {len(requests)} requests: {first} through {last}; fields {list(VARIABLES)}",
        flush=True,
    )
    return plan


def validate_file(path, row, latitude, longitude):
    with xr.open_dataset(path) as data:
        field = data[row["field"]]
        if field.dims != ("valid_time", "latitude", "longitude"):
            raise ValueError(f"Unexpected hourly dimensions: {path}: {field.dims}")
        if not np.array_equal(data.valid_time.values, expected_times(row)):
            raise ValueError(f"Missing or unexpected UTC timestamps: {path}")
        for axis, expected in [("latitude", latitude), ("longitude", longitude)]:
            if not np.array_equal(data[axis].values, expected):
                raise ValueError(f"Hourly weather {axis} differs from the temperature grid: {path}")
        step_type = "accum" if row["field"] == "tp" else "instant"
        if field.attrs.get("GRIB_stepType") != step_type:
            raise ValueError(f"Unexpected {row['field']} step type in {path}")
        units = field.attrs.get("units")
        expected_units = "m" if row["field"] == "tp" else "m s**-1"
        if units != expected_units:
            raise ValueError(f"Expected {expected_units}, found {units}: {path}")
    return {
        "month": row["month"],
        "field": row["field"],
        "hours": row["expected_hours"],
        "file": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def download_weather(workers=2, config=None):
    import cdsapi

    if config:
        os.environ["CDSAPI_RC"] = str(Path(config).expanduser())
    elif "CDSAPI_RC" not in os.environ and (DATA_DIRECTORY / ".cdsapirc").exists():
        os.environ["CDSAPI_RC"] = str(DATA_DIRECTORY / ".cdsapirc")
    plan = prepare()
    with xr.open_dataset(plan["reference_grid"]) as reference:
        latitude, longitude = reference.latitude.values.copy(), reference.longitude.values.copy()
    progress_path = AUDIT_DIRECTORY / "hourly_weather_progress.json"
    progress = {
        "status": "running",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "requests": len(plan["requests"]),
        "completed": 0,
        "bytes": 0,
        "workers": workers,
    }
    save_json(progress_path, progress)

    def retrieve(row):
        path = Path(row["file"])
        if not path.exists():
            client = cdsapi.Client(timeout=120, retry_max=5, sleep_max=60, progress=False)
            print(
                f"Requesting {row['month']} {row['field']}: {row['expected_hours']} hours",
                flush=True,
            )
            temporary = path.with_suffix(".download")
            client.retrieve(DATASET, row["request"], str(temporary))
            partial = path.with_suffix(".nc.part")
            unpack(temporary, partial)
            return row, partial
        else:
            return row, path

    completed = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(retrieve, row) for row in plan["requests"]]
        for future in as_completed(futures):
            request, ready = future.result()
            path = Path(request["file"])
            row = validate_file(ready, request, latitude, longitude)
            if ready != path:
                ready.replace(path)
            row["file"] = str(path)
            completed.append(row)
            pl.DataFrame(completed).sort("month", "field").write_csv(
                AUDIT_DIRECTORY / "hourly_weather_downloads.csv"
            )
            progress.update(
                completed=len(completed), bytes=sum(item["bytes"] for item in completed)
            )
            save_json(progress_path, progress)
            print(
                f"Verified {row['month']} {row['field']}: {len(completed)}/{len(futures)}",
                flush=True,
            )
    progress.update(status="complete", completed_utc=datetime.now(timezone.utc).isoformat())
    save_json(progress_path, progress)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.prepare_only:
        prepare()
    else:
        download_weather(args.workers, args.config)


if __name__ == "__main__":
    main()
