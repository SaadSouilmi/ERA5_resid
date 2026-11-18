"""Extract hourly ERA5 maxima over UTC windows including both endpoints."""

import numpy as np
import pandas as pd
import polars as pl
import xarray as xr


def read_month_cells(path, cells, lat, lon):
    month = pd.Period(path.name[:7], freq="M")
    expected = pd.date_range(month.start_time, (month + 1).start_time, freq="h", inclusive="left")
    with xr.open_dataset(path) as data:
        if (
            not np.array_equal(data.latitude.values, lat)
            or not np.array_equal(data.longitude.values, lon)
            or not np.array_equal(data.valid_time.values, expected.values)
        ):
            raise ValueError(f"Unexpected grid or hourly timestamps: {path}")
        if data.t2m.attrs.get("units") != "K" or data.t2m.attrs.get("GRIB_stepType") != "instant":
            raise ValueError(f"Expected instantaneous temperature in Kelvin: {path}")
        temperature = data.t2m.transpose("valid_time", "latitude", "longitude")
        chunk_hours = data.t2m.encoding["chunksizes"][data.t2m.get_axis_num("valid_time")]
        values = np.empty((len(expected), cells.height), dtype=np.float32)
        y, x = cells["latitude_index"].to_numpy(), cells["longitude_index"].to_numpy()
        for start in range(0, len(expected), chunk_hours):
            end = min(start + chunk_hours, len(expected))
            block = temperature.isel(valid_time=slice(start, end)).values
            values[start:end] = block[:, y, x]
    return values


def inclusive_maxima(values, starts, ends, columns, batch_size=100_000):
    if (
        np.any(starts < 0)
        or np.any(ends >= values.shape[0])
        or np.any(ends < starts)
        or np.any(columns < 0)
        or np.any(columns >= values.shape[1])
    ):
        raise ValueError("Window or grid column outside the loaded hourly array")
    lengths = ends - starts + 1
    maxima = np.full(len(starts), np.nan, dtype=np.float64)
    available = np.zeros(len(starts), dtype=np.int32)
    for length in np.unique(lengths):
        positions = np.flatnonzero(lengths == length)
        offsets = np.arange(length)
        for start in range(0, len(positions), batch_size):
            rows = positions[start : start + batch_size]
            samples = values[starts[rows, None] + offsets, columns[rows, None]]
            counts = np.isfinite(samples).sum(axis=1)
            maxima[rows] = np.where(counts == length, samples.max(axis=1), np.nan)
            available[rows] = counts
    return maxima, available


def outside_download(first_hour, last_hour):
    return (
        (pl.col("window_start_utc") < pl.lit(first_hour))
        | (pl.col("window_end_utc") > pl.lit(last_hour))
    ).fill_null(False)


def match_month(observations, load_month):
    eligible = observations.filter(
        (pl.col("window_status") == "mapped") & pl.col("_grid_column").is_not_null()
    )
    maxima = np.empty(0, dtype=np.float64)
    available = np.empty(0, dtype=np.int32)
    if eligible.height:
        first = eligible["window_start_utc"].min().replace(tzinfo=None)
        last = eligible["window_end_utc"].max().replace(tzinfo=None)
        months = pd.period_range(first, last, freq="M")
        values = np.concatenate([load_month(str(month)) for month in months])
        origin = np.datetime64(months[0].start_time, "h")
        starts = (eligible["window_start_utc"].to_numpy().astype("datetime64[h]") - origin).astype(
            np.int64
        )
        ends = (eligible["window_end_utc"].to_numpy().astype("datetime64[h]") - origin).astype(
            np.int64
        )
        maxima, available = inclusive_maxima(
            values, starts, ends, eligible["_grid_column"].to_numpy()
        )
    results = pl.DataFrame(
        {
            "observation_id": eligible["observation_id"],
            "era5_tmax_celsius": maxima - 273.15,
            "era5_available_samples": available,
        }
    ).with_columns(pl.col("era5_tmax_celsius").fill_nan(None))
    return (
        observations.join(results, on="observation_id", how="left", validate="1:1")
        .with_columns(
            pl.when(pl.col("window_status") == "mapped")
            .then((pl.col("window_end_utc") - pl.col("window_start_utc")).dt.total_hours() + 1)
            .otherwise(None)
            .cast(pl.Int32)
            .alias("era5_expected_samples"),
            pl.lit("both").cast(pl.Categorical).alias("era5_window_closure"),
        )
        .with_columns(
            pl.when(pl.col("window_status") != "mapped")
            .then(pl.lit("unknown_window"))
            .when(pl.col("grid_match_status") == "outside_grid")
            .then(pl.lit("outside_grid"))
            .when(pl.col("era5_tmax_celsius").is_not_null())
            .then(pl.lit("matched"))
            .when(pl.col("era5_cell_masked") & (pl.col("era5_available_samples") == 0))
            .then(pl.lit("masked_cell"))
            .otherwise(pl.lit("incomplete_era5_hours"))
            .cast(pl.Categorical)
            .alias("era5_match_status"),
            (pl.col("station_celsius") - pl.col("era5_tmax_celsius")).alias("residual_celsius"),
        )
        .drop("_grid_column")
        .sort("observation_id")
    )
