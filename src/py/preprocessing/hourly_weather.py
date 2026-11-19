"""Calculate wind and precipitation over each saved station observation window."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import xarray as xr

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.preprocessing.download_hourly_weather import DIRECTORY, VARIABLES
from py.preprocessing.match_era5_grid import sha256

JOIN_KEYS = ["SOUID", "DATE", "grid_cell_id", "window_start_utc", "window_end_utc"]
VALUE_COLUMNS = [
    "wind",
    "tp",
    "u10_mean_mps",
    "v10_mean_mps",
    "wind_mean_speed_mps",
    "wind_available_samples",
    "rain_available_hours",
    "negative_rain_hours",
    "wind_expected_samples",
    "rain_expected_hours",
    "wind_status",
    "precipitation_status",
]


def hourly_precipitation(accumulated, times):
    """ERA5-Land precipitation increments, stamped at the end of each hour."""
    hourly = np.empty_like(accumulated, dtype=np.float64)
    hourly[0] = np.nan
    hourly[1:] = np.diff(accumulated.astype(np.float64), axis=0)
    reset = pd.DatetimeIndex(times).hour == 1
    hourly[reset] = accumulated[reset]
    return hourly


def aggregate_windows(u10, v10, rain, starts, ends, columns, batch_size=100_000):
    """Time-average instantaneous wind; sum precipitation intervals (start, end]."""
    lengths = ends - starts + 1
    result = {
        name: np.full(len(starts), np.nan, dtype=np.float64)
        for name in ["wind", "tp", "u10_mean_mps", "v10_mean_mps", "wind_mean_speed_mps"]
    }
    for name in ["wind_available_samples", "rain_available_hours", "negative_rain_hours"]:
        result[name] = np.zeros(len(starts), dtype=np.int32)
    for length in np.unique(lengths):
        if length < 2:
            raise ValueError("A weather observation window must have positive duration")
        positions = np.flatnonzero(lengths == length)
        for first in range(0, len(positions), batch_size):
            rows = positions[first : first + batch_size]
            indices = starts[rows, None] + np.arange(length)
            grid = columns[rows, None]
            u, v = u10[indices, grid], v10[indices, grid]
            finite_wind = np.isfinite(u) & np.isfinite(v)
            wind_count = finite_wind.sum(axis=1)
            mean_u = np.trapezoid(u, axis=1) / (length - 1)
            mean_v = np.trapezoid(v, axis=1) / (length - 1)
            complete = wind_count == length
            for name, values in [
                ("u10_mean_mps", mean_u),
                ("v10_mean_mps", mean_v),
                ("wind", np.hypot(mean_u, mean_v)),
                ("wind_mean_speed_mps", np.trapezoid(np.hypot(u, v), axis=1) / (length - 1)),
            ]:
                result[name][rows] = np.where(complete, values, np.nan)
            result["wind_available_samples"][rows] = wind_count
            intervals = rain[indices[:, 1:], grid]
            rain_count = np.isfinite(intervals).sum(axis=1)
            result["tp"][rows] = np.where(
                rain_count == length - 1, intervals.sum(axis=1, dtype=np.float64), np.nan
            )
            result["rain_available_hours"][rows] = rain_count
            result["negative_rain_hours"][rows] = (intervals < 0).sum(axis=1)
    return result


def read_cells(path, field, cells, latitude, longitude):
    with xr.open_dataset(path) as data:
        if not (
            np.array_equal(data.latitude.values, latitude)
            and np.array_equal(data.longitude.values, longitude)
        ):
            raise ValueError(f"Hourly weather grid differs from temperature: {path}")
        times = data.valid_time.values.copy()
        values = np.empty((len(times), cells.height), dtype=np.float32)
        chunks = data[field].encoding.get("chunksizes")
        hours = chunks[data[field].get_axis_num("valid_time")] if chunks else 24
        y, x = cells["latitude_index"].to_numpy(), cells["longitude_index"].to_numpy()
        for first in range(0, len(times), hours):
            block = (
                data[field]
                .isel(valid_time=slice(first, first + hours))
                .transpose("valid_time", "latitude", "longitude")
                .values
            )
            values[first : first + len(block)] = block[:, y, x]
    return times, values


def build_weather_covariates():
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
    output = DATA_DIRECTORY / "station_hourly_weather.parquet"
    observations = pl.read_parquet(
        input_path,
        columns=["observation_id", *JOIN_KEYS, "window_hours", "latitude_index", "longitude_index"],
    )
    cells = (
        observations.select("grid_cell_id", "latitude_index", "longitude_index")
        .unique()
        .sort("grid_cell_id")
        .with_row_index("_weather_column")
    )
    observations = observations.join(
        cells.select("grid_cell_id", "_weather_column"), on="grid_cell_id", validate="m:1"
    )
    reference_path = next((DATA_DIRECTORY / "era5_land_hourly").glob("2020-01_*.nc"))
    with xr.open_dataset(reference_path) as reference:
        latitude, longitude = reference.latitude.values.copy(), reference.longitude.values.copy()
    sources = {}

    @lru_cache(maxsize=9)
    def load_month(month, field):
        path = DIRECTORY / f"{month}_{field}.nc"
        loaded = read_cells(path, field, cells, latitude, longitude)
        sources[str(path)] = sha256(path)
        return loaded

    monthly = []
    for month in (observations["DATE"] // 100).unique().sort():
        frame = observations.filter(pl.col("DATE") // 100 == month)
        first = frame["window_start_utc"].min().replace(tzinfo=None) - timedelta(hours=1)
        last = frame["window_end_utc"].max().replace(tzinfo=None)
        periods = pd.period_range(first, last, freq="M")
        arrays, times = {}, None
        for field in VARIABLES:
            parts = [load_month(str(period), field) for period in periods]
            clock = np.concatenate([part[0] for part in parts])
            if times is None:
                times = clock
                if not (np.diff(times) == np.timedelta64(1, "h")).all():
                    raise ValueError("Hourly weather timestamps are not consecutive")
            elif not np.array_equal(clock, times):
                raise ValueError("Wind and precipitation timestamps differ")
            arrays[field] = np.concatenate([part[1] for part in parts])
        origin = times[0].astype("datetime64[h]")
        starts = (frame["window_start_utc"].to_numpy().astype("datetime64[h]") - origin).astype(
            np.int64
        )
        ends = (frame["window_end_utc"].to_numpy().astype("datetime64[h]") - origin).astype(
            np.int64
        )
        values = aggregate_windows(
            arrays["u10"],
            arrays["v10"],
            hourly_precipitation(arrays["tp"], times),
            starts,
            ends,
            frame["_weather_column"].to_numpy(),
        )
        result = (
            frame.select("observation_id", *JOIN_KEYS, "window_hours")
            .hstack(pl.DataFrame(values).with_columns(pl.col(pl.Float64).fill_nan(None)))
            .with_columns(
                (pl.col("window_hours") + 1).cast(pl.Int32).alias("wind_expected_samples"),
                pl.col("window_hours").cast(pl.Int32).alias("rain_expected_hours"),
            )
            .with_columns(
                pl.when(pl.col("wind_available_samples") == pl.col("wind_expected_samples"))
                .then(pl.lit("matched"))
                .otherwise(pl.lit("incomplete_hours"))
                .alias("wind_status"),
                pl.when(pl.col("rain_available_hours") != pl.col("rain_expected_hours"))
                .then(pl.lit("incomplete_hours"))
                .when(pl.col("negative_rain_hours") > 0)
                .then(pl.lit("negative_increment_review"))
                .otherwise(pl.lit("matched"))
                .alias("precipitation_status"),
            )
        )
        monthly.append(result)
        print(f"Aggregated {month}: {result.height:,} station windows", flush=True)
    weather = pl.concat(monthly).sort("observation_id")
    weather.write_parquet(output, compression="zstd")
    if weather.height != observations.height:
        raise ValueError("Weather aggregation changed observation membership")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "py.preprocessing.hourly_weather",
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "file": str(output),
        "sha256": sha256(output),
        "bytes": output.stat().st_size,
        "observations": weather.height,
        "join_keys": JOIN_KEYS,
        "wind": "Trapezoidal time means of instantaneous u10 and v10 on [start,end], followed by vector magnitude. wind_mean_speed_mps separately averages hourly speed with the same weights.",
        "precipitation": "De-accumulate ERA5-Land hourly forecasts, including the 01 UTC reset; tp is the sum of interval amounts on (start,end], in metres. Negative increments are retained and flagged.",
        "completeness": "Require every boundary wind sample and every precipitation interval. Missing covariates stay null; temperature observations remain retained.",
        "coverage": weather.group_by("wind_status", "precipitation_status").len().to_dicts(),
        "negative_window_totals": weather.filter(pl.col("tp") < 0).height,
        "raw_inputs": sources,
        "code_sha256": {__file__: sha256(Path(__file__))},
    }
    (DATA_DIRECTORY / "cleaning_audit/station_hourly_weather.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(f"Saved {weather.height:,} station-window covariates: {output}", flush=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    build_weather_covariates()


if __name__ == "__main__":
    main()
