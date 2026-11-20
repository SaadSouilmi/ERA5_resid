"""Retrieve hourly ERA5-Land temperature on the supplied daily grid for an explicit period."""

import argparse
import datetime
import json
import os
import shutil
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.paths import RAW_DATA_DIRECTORY as RAW_DIRECTORY
from py.preprocessing.match_era5_grid import sha256

DATASET = "reanalysis-era5-land"
DIRECTORY = DATA_DIRECTORY / "era5_land_hourly"
AUDIT_DIRECTORY = DATA_DIRECTORY / "cleaning_audit"
REFERENCE_FILE = (
    RAW_DIRECTORY / "derived-era5-land-daily-statistics/2020_2m_temperature_daily_maximum.nc"
)
PLAN_FILE = AUDIT_DIRECTORY / "era5_temperature_plan.json"


def save_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix(file.suffix + ".part")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(file)


def month_requests(start, end, area):
    requests = []
    for month in pd.period_range(start, end, freq="M"):
        first = max(start, month.start_time.date())
        last = min(end, month.end_time.date())
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


def prepare(start, end):
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    with xr.open_dataset(REFERENCE_FILE) as reference:
        lat, lon = reference.latitude.values, reference.longitude.values
    area = [float(lat.max()), float(lon.min()), float(lat.min()), float(lon.max())]
    requests = month_requests(start, end, area)
    plan = {
        "dataset": DATASET,
        "variable": "2m_temperature",
        "units": "K",
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "first_date": start.isoformat(),
        "last_date": end.isoformat(),
        "area_north_west_south_east": area,
        "reference_grid_file": str(REFERENCE_FILE),
        "reference_grid_sha256": sha256(REFERENCE_FILE),
        "expected_hours": sum(row["expected_hours"] for row in requests),
        "requests": requests,
        "selection": "Explicit study period; independent of earlier residual samples. Station windows extending beyond these hours are excluded by temperature matching.",
    }
    save_json(PLAN_FILE, plan)
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
        if actual.shape != expected.shape or not np.allclose(actual, expected, atol=1e-6, rtol=0):
            raise ValueError(f"{name}: downloaded grid differs from the supplied grid")
    if not np.array_equal(data.valid_time.values, expected_times(row)):
        raise ValueError("Missing, duplicate, unordered or unexpected UTC hours")
    if data.t2m.attrs.get("units", "").lower() not in ["k", "kelvin"]:
        raise ValueError(f"Unexpected t2m units: {data.t2m.attrs.get('units')}")


def unpack(temporary, target):
    if zipfile.is_zipfile(temporary):
        with zipfile.ZipFile(temporary) as archive:
            names = [name for name in archive.namelist() if name.endswith(".nc")]
            if len(names) != 1:
                raise ValueError(f"Expected one NetCDF; archive contains {names}")
            with archive.open(names[0]) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
        temporary.unlink()
    else:
        temporary.replace(target)


def download(plan, config=None, limit=None):
    import cdsapi

    if config:
        os.environ["CDSAPI_RC"] = str(Path(config).expanduser())
    elif "CDSAPI_RC" not in os.environ and (DATA_DIRECTORY / ".cdsapirc").exists():
        os.environ["CDSAPI_RC"] = str(DATA_DIRECTORY / ".cdsapirc")
    client = cdsapi.Client(timeout=90, retry_max=3, sleep_max=30)
    with xr.open_dataset(REFERENCE_FILE) as reference:
        lat, lon = reference.latitude.values, reference.longitude.values
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


def audit(plan):
    with xr.open_dataset(REFERENCE_FILE) as reference:
        lat, lon = reference.latitude.values, reference.longitude.values
    checks = []
    for row in plan["requests"]:
        path = Path(row["file"])
        if not path.exists():
            checks.append({"month": row["month"], "complete": False})
            continue
        with xr.open_dataset(path) as data:
            check_coordinates(data, row, lat, lon)
        checks.append({
            "month": row["month"], "complete": True, "file": str(path),
            "sha256": sha256(path), "expected_hours": row["expected_hours"],
        })
    save_json(AUDIT_DIRECTORY / "era5_temperature_coverage.json", {"months": checks})
    print(f"Verified {sum(row['complete'] for row in checks)}/{len(checks)} months", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "download", "audit"])
    parser.add_argument("--start", type=datetime.date.fromisoformat, default=datetime.date(2020, 1, 1))
    parser.add_argument("--end", type=datetime.date.fromisoformat, default=datetime.date(2025, 8, 31))
    parser.add_argument("--config", help="Local CDS configuration path")
    parser.add_argument("--limit", type=int, help="Retrieve only this many initial months")
    args = parser.parse_args()
    plan = (
        prepare(args.start, args.end)
        if args.mode == "prepare" or not PLAN_FILE.exists()
        else json.loads(PLAN_FILE.read_text())
    )
    if args.mode == "download":
        download(plan, args.config, args.limit)
    elif args.mode == "audit":
        audit(plan)


if __name__ == "__main__":
    main()
