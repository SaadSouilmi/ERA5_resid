"""Download hourly ERA5-Land on the existing grid and audit UTC coverage.

Run with uv run --with cdsapi python -m py.preprocessing.download_era5_hourly.
"""

import argparse
import calendar
import datetime
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import polars as pl
import xarray as xr
from py.paths import (
    AnalysisDataDirectory as ANALYSIS_DATA_DIRECTORY,
    RawDataDirectory as RAW_DATA_DIRECTORY,
)

DATASET = "reanalysis-era5-land"
DIRECTORY = ANALYSIS_DATA_DIRECTORY / "era5_land_hourly"
AUDIT_DIRECTORY = ANALYSIS_DATA_DIRECTORY / "cleaning_audit"
REFERENCE_FILE = (
    RAW_DATA_DIRECTORY / "derived-era5-land-daily-statistics/2020_2m_temperature_daily_maximum.nc"
)
PLAN_FILE = AUDIT_DIRECTORY / "era5_hourly_plan.json"


def sha256(file):
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix(file.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(file)


def month_requests(start, end, area):
    requests = []
    for month in pd.period_range(start, end, freq="M"):
        first = max(start, month.start_time.date())
        last = min(
            end,
            datetime.date(month.year, month.month, calendar.monthrange(month.year, month.month)[1]),
        )
        requests.append(
            {
                "month": str(month),
                "first_date": first.isoformat(),
                "last_date": last.isoformat(),
                "expected_hours": ((last - first).days + 1) * 24,
                "file": str(DIRECTORY / f"{month}_2m_temperature_hourly.nc"),
                "request": {
                    "variable": ["2m_temperature"],
                    "year": [str(month.year)],
                    "month": [f"{month.month:02d}"],
                    "day": [f"{day:02d}" for day in range(first.day, last.day + 1)],
                    "time": [f"{hour:02d}:00" for hour in range(24)],
                    "area": area,
                    "data_format": "netcdf",
                    "download_format": "unarchived",
                },
            }
        )
    return requests


def nearest_cells(lat, lon, target_lat, target_lon):
    return (
        pd.Index(lat).get_indexer(target_lat, method="nearest"),
        pd.Index(lon).get_indexer(target_lon, method="nearest"),
    )


def prepare():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    frame = pl.scan_parquet(ANALYSIS_DATA_DIRECTORY / "clean/analysis.parquet")
    bounds = (
        frame.select(
            pl.col("date").min().alias("first"),
            pl.col("date").max().alias("last"),
            pl.col("STAID").n_unique().alias("stations"),
        )
        .collect()
        .row(0, named=True)
    )
    start, end = (bounds["first"].date(), bounds["last"].date())
    with xr.open_dataset(REFERENCE_FILE) as reference:
        lat = reference.latitude.values
        lon = reference.longitude.values
    area = [
        round(float(lat.max()), 6),
        round(float(lon.min()), 6),
        round(float(lat.min()), 6),
        round(float(lon.max()), 6),
    ]
    requests = month_requests(start, end, area)
    hours = sum((row["expected_hours"] for row in requests))
    locations = (
        frame.select("STAID", "SOUID", "source_lat", "source_lon", "era5_lat", "era5_lon")
        .unique()
        .collect()
    )
    outside = locations.filter(
        ~pl.col("source_lat").is_between(area[2], area[0])
        | ~pl.col("source_lon").is_between(area[1], area[3])
    )
    half_lat = float(abs(np.diff(lat)).min() / 2)
    half_lon = float(abs(np.diff(lon)).min() / 2)
    beyond_cells = locations.filter(
        ~pl.col("source_lat").is_between(area[2] - half_lat, area[0] + half_lat)
        | ~pl.col("source_lon").is_between(area[1] - half_lon, area[3] + half_lon)
    )
    y, x = nearest_cells(
        lat, lon, locations["source_lat"].to_numpy(), locations["source_lon"].to_numpy()
    )
    same_grid = np.isclose(
        lat[y], locations["era5_lat"].to_numpy(), atol=1e-06, rtol=0
    ) & np.isclose(lon[x], locations["era5_lon"].to_numpy(), atol=1e-06, rtol=0)
    locations = locations.with_columns(
        pl.Series("nearest_grid_lat", lat[y]),
        pl.Series("nearest_grid_lon", lon[x]),
        pl.Series("same_as_retained_grid_cell", same_grid),
    )
    plan = {
        "dataset": DATASET,
        "variable": "2m_temperature",
        "units": "K",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "start_utc": str(start) + "T00:00:00Z",
        "end_utc_inclusive": str(end) + "T23:00:00Z",
        "area_north_west_south_east": area,
        "latitude_count": len(lat),
        "longitude_count": len(lon),
        "expected_hours": hours,
        "expected_grid_cells": len(lat) * len(lon),
        "uncompressed_float32_bytes": hours * len(lat) * len(lon) * 4,
        "retained_station_ids": bounds["stations"],
        "source_locations_outside_grid_centres": outside.height,
        "source_locations_outside_grid_cell_footprint": beyond_cells.height,
        "retained_source_grid_mismatches": int((~same_grid).sum()),
        "reference_grid_file": str(REFERENCE_FILE),
        "reference_grid_sha256": sha256(REFERENCE_FILE),
        "analysis_input_sha256": sha256(ANALYSIS_DATA_DIRECTORY / "clean/analysis.parquet"),
        "coverage_policy": "Full existing geographical grid and all UTC hours in the retained observation date range. Sea cells retain the ERA5-Land mask. No coastal fallback or temporal interpolation.",
        "station_pairing_policy": "Only exact UTC timestamps are paired to station readings. Off-hour station observations remain unmatched.",
        "requests": requests,
    }
    save_json(PLAN_FILE, plan)
    locations.write_csv(AUDIT_DIRECTORY / "era5_hourly_source_locations.csv")
    locations.filter(~pl.col("same_as_retained_grid_cell")).write_csv(
        AUDIT_DIRECTORY / "era5_hourly_source_grid_mismatches.csv"
    )
    outside.write_csv(AUDIT_DIRECTORY / "era5_hourly_source_locations_outside.csv")
    print(
        json.dumps({key: value for key, value in plan.items() if key != "requests"}, indent=2),
        flush=True,
    )
    print(f"Prepared {len(requests)} monthly requests: {PLAN_FILE}", flush=True)
    return plan


def expected_times(row):
    return pd.date_range(
        row["first_date"], pd.Timestamp(row["last_date"]) + pd.Timedelta(hours=23), freq="h"
    ).values


def check_coordinates(data, row, lat, lon):
    if "t2m" not in data or set(data.t2m.dims) != {"valid_time", "latitude", "longitude"}:
        raise ValueError("Expected t2m(valid_time, latitude, longitude)")
    for name, expected in [("latitude", lat), ("longitude", lon)]:
        actual = data[name].values
        if actual.shape != expected.shape or not np.allclose(actual, expected, atol=1e-06, rtol=0):
            raise ValueError(f"{name}: downloaded grid differs from the existing grid")
    if not np.array_equal(data.valid_time.values, expected_times(row)):
        raise ValueError("Missing, duplicate, unordered or unexpected UTC hours")
    if data.t2m.attrs.get("units", "").lower() not in ["k", "kelvin"]:
        raise ValueError(f"Unexpected t2m units: {data.t2m.attrs.get('units')}")


def unpack(temporary, target):
    if zipfile.is_zipfile(temporary):
        with zipfile.ZipFile(temporary) as archive:
            names = [name for name in archive.namelist() if name.endswith(".nc")]
            if len(names) != 1:
                raise ValueError(f"Expected one temperature NetCDF; archive contains {names}")
            with archive.open(names[0]) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        temporary.unlink()
    else:
        temporary.replace(target)


def download(plan, config=None, limit=None):
    if config:
        os.environ["CDSAPI_RC"] = str(Path(config).expanduser())
    import cdsapi

    client = cdsapi.Client(timeout=90, retry_max=3, sleep_max=30)
    with xr.open_dataset(REFERENCE_FILE) as reference:
        lat, lon = (reference.latitude.values, reference.longitude.values)
    requests = plan["requests"][:limit] if limit else plan["requests"]
    for row in requests:
        file = Path(row["file"])
        if not file.exists():
            print(f"Requesting {row['month']}: {row['expected_hours']} hours", flush=True)
            temporary = file.with_suffix(".download")
            client.retrieve(DATASET, row["request"], str(temporary))
            unpacked = file.with_suffix(".nc.part")
            unpack(temporary, unpacked)
            with xr.open_dataset(unpacked) as data:
                check_coordinates(data, row, lat, lon)
            unpacked.replace(file)
        else:
            with xr.open_dataset(file) as data:
                check_coordinates(data, row, lat, lon)
        print(f"Verified grid and timestamps: {row['month']}", flush=True)
    return audit(plan)


def audit(plan):
    with xr.open_dataset(REFERENCE_FILE) as reference:
        lat, lon = (reference.latitude.values, reference.longitude.values)
        land = np.isfinite(reference.t2m.isel(valid_time=0).values)
    stations = pl.read_csv(AUDIT_DIRECTORY / "ghcnh_sample_selection.csv")
    y, x = nearest_cells(
        lat, lon, stations["ghcnh_lat"].to_numpy(), stations["ghcnh_lon"].to_numpy()
    )
    station_map = stations.select(
        "ghcnh_id", "country", "ghcnh_name", "ghcnh_lat", "ghcnh_lon"
    ).with_columns(
        pl.Series("era5_lat", lat[y]),
        pl.Series("era5_lon", lon[x]),
        pl.Series("reference_land_cell", land[y, x]),
    )
    station_map.write_csv(AUDIT_DIRECTORY / "era5_hourly_station_grid.csv")
    rows, series = ([], [])
    for row in plan["requests"]:
        file = Path(row["file"])
        if not file.exists():
            rows.append(
                {
                    "month": row["month"],
                    "status": "missing_file",
                    "expected_hours": row["expected_hours"],
                }
            )
            continue
        with xr.open_dataset(file) as data:
            check_coordinates(data, row, lat, lon)
            missing, new_finite = (0, 0)
            for first in range(0, row["expected_hours"], 24):
                values = (
                    data.t2m.isel(valid_time=slice(first, first + 24))
                    .transpose("valid_time", "latitude", "longitude")
                    .values
                )
                finite = np.isfinite(values)
                missing += int((~finite[:, land]).sum())
                new_finite += int(finite[:, ~land].sum())
            values = (
                data.t2m.isel(
                    latitude=xr.DataArray(y, dims="station"),
                    longitude=xr.DataArray(x, dims="station"),
                )
                .transpose("valid_time", "station")
                .values
            )
            series.append(
                pl.DataFrame(
                    {
                        "timestamp": np.repeat(data.valid_time.values, stations.height),
                        "ghcnh_id": np.tile(
                            stations["ghcnh_id"].to_numpy(), data.sizes["valid_time"]
                        ),
                        "era5_kelvin": values.reshape(-1),
                    }
                ).with_columns(
                    pl.col("timestamp").dt.cast_time_unit("us").dt.replace_time_zone("UTC")
                )
            )
        rows.append(
            {
                "month": row["month"],
                "status": "complete" if missing == 0 else "missing_land_values",
                "expected_hours": row["expected_hours"],
                "missing_reference_land_values": missing,
                "finite_values_outside_reference_land_mask": new_finite,
                "bytes": file.stat().st_size,
                "sha256": sha256(file),
            }
        )
        print(f"Audited {row['month']}: {missing} missing reference-land values", flush=True)
    pl.DataFrame(rows, infer_schema_length=None).write_csv(
        AUDIT_DIRECTORY / "era5_hourly_monthly_coverage.csv"
    )
    complete = all((row["status"] == "complete" for row in rows))
    summary = {
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "complete" if complete else "incomplete",
        "dataset": DATASET,
        "expected_months": len(rows),
        "downloaded_months": sum((row["status"] != "missing_file" for row in rows)),
        "expected_hours": plan["expected_hours"],
        "reference_land_cells": int(land.sum()),
        "grid_and_timestamp_validation": "Exact monthly UTC sequence and complete reference latitude/longitude axes required for each downloaded file.",
        "land_mask_definition": "Finite cells in the first day of the supplied 2020 daily-maximum reference; extra finite cells are reported separately.",
        "station_pairing_policy": plan["station_pairing_policy"],
    }
    if series:
        hourly = pl.concat(series).with_columns(
            (pl.col("era5_kelvin") - 273.15).alias("era5_celsius")
        )
        hourly.write_parquet(DIRECTORY / "ghcnh_sample_grid_hourly.parquet")
        station_coverage = hourly.group_by("ghcnh_id").agg(
            pl.len().alias("downloaded_hours"),
            pl.col("era5_celsius").is_finite().sum().alias("finite_hours"),
        )
        station_map.join(station_coverage, on="ghcnh_id", how="left").with_columns(
            pl.lit(plan["expected_hours"]).alias("expected_hours")
        ).write_csv(AUDIT_DIRECTORY / "era5_hourly_station_coverage.csv")
        observations = pl.read_parquet(ANALYSIS_DATA_DIRECTORY / "ghcnh/sample_temperature.parquet")
        pairs = observations.join(
            hourly, on=["ghcnh_id", "timestamp"], how="left", validate="m:1"
        ).with_columns(
            (
                pl.col("screened_temperature") & pl.col("era5_celsius").is_finite().fill_null(False)
            ).alias("screened_exact_pair")
        )
        pairs.write_parquet(DIRECTORY / "ghcnh_temperature_pairs.parquet")
        screened = pairs.filter(pl.col("screened_temperature"))
        exact = screened.filter(pl.col("timestamp") == pl.col("hour_bin"))
        summary.update(
            screened_station_temperatures=screened.height,
            station_temperatures_on_exact_hours=exact.height,
            station_temperatures_off_hour=screened.height - exact.height,
            matched_screened_station_temperatures=pairs["screened_exact_pair"].sum(),
            exact_hour_station_temperatures_without_finite_era5=exact.filter(
                ~pl.col("screened_exact_pair")
            ).height,
        )
    save_json(AUDIT_DIRECTORY / "era5_hourly_coverage_summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "download", "audit"])
    parser.add_argument(
        "--config", help="Path to a CDS configuration file; credentials are never saved to the plan"
    )
    parser.add_argument(
        "--limit", type=int, help="Retrieve only this many initial months for a pilot"
    )
    arguments = parser.parse_args()
    plan = (
        prepare()
        if arguments.mode == "prepare" or not PLAN_FILE.exists()
        else json.loads(PLAN_FILE.read_text())
    )
    if arguments.mode == "download":
        download(plan, arguments.config, arguments.limit)
    elif arguments.mode == "audit":
        audit(plan)


if __name__ == "__main__":
    main()
