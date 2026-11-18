"""Attach source elevation and the supplied daily wind and precipitation covariates."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
import xarray as xr

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import RawDataDirectory as RAW_DIRECTORY
from py.preprocessing.match_era5_grid import sha256

FIELDS = {
    "u10": "10m_u_component_of_wind_daily_mean",
    "v10": "10m_v_component_of_wind_daily_mean",
    "tp": "total_precipitation_daily_mean",
}


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
    observations = pl.scan_parquet(input_path)
    metadata_path = RAW_DIRECTORY / "ECA_blend_tx/sources.txt"
    metadata = (
        pl.DataFrame({"line": metadata_path.read_text().splitlines()[25:]})
        .select(
            pl.col("line").str.slice(0, 5).str.strip_chars().cast(pl.Int32).alias("STAID"),
            pl.col("line")
            .str.slice(6, 6)
            .str.strip_chars()
            .cast(pl.Int32)
            .alias("source_metadata_id"),
            pl.col("line")
            .str.slice(78, 4)
            .str.strip_chars()
            .cast(pl.Float64)
            .replace([-9999.0, -999.0], None)
            .alias("elevation"),
        )
        .unique()
    )
    elevation = (
        observations.select("STAID", "source_metadata_id")
        .unique()
        .collect()
        .join(metadata, on=["STAID", "source_metadata_id"], how="left", validate="1:1")
        .sort("STAID", "source_metadata_id")
    )
    elevation_path = DATA_DIRECTORY / "station_elevation.parquet"
    elevation.write_parquet(elevation_path, compression="zstd")
    print(f"Source elevation saved: {elevation.height:,} metadata entries", flush=True)

    cells = (
        observations.select("grid_cell_id", "era5_lat", "era5_lon")
        .unique()
        .collect()
        .sort("grid_cell_id")
    )
    requests = observations.select("grid_cell_id", "DATE").unique().collect()
    directory = DATA_DIRECTORY / "station_weather"
    directory.mkdir(exist_ok=True)
    summaries, inputs = [], []
    for year in (requests["DATE"] // 10000).unique().sort():
        requested = requests.filter(pl.col("DATE") // 10000 == year)
        values = {}
        expected_dates = None
        for field, suffix in FIELDS.items():
            path = RAW_DIRECTORY / "derived-era5-land-daily-statistics" / f"{year}_{suffix}.nc"
            with xr.open_dataset(path) as data:
                dates = (
                    pd.DatetimeIndex(data.valid_time.values)
                    .strftime("%Y%m%d")
                    .to_numpy()
                    .astype(np.int32)
                )
                time_shift = data.valid_time.attrs.get("time_shift")
                history = data.attrs.get("history", "")
                length = int(np.searchsorted(dates, requested["DATE"].max(), side="right"))
                if expected_dates is None:
                    expected_dates = dates[:length]
                elif not np.array_equal(dates[:length], expected_dates):
                    raise ValueError(f"Daily covariate dates differ within the study period: {path}")
                y = data.indexes["latitude"].get_indexer(
                    cells["era5_lat"].to_numpy(), method="nearest"
                )
                x = data.indexes["longitude"].get_indexer(
                    cells["era5_lon"].to_numpy(), method="nearest"
                )
                if not (
                    np.allclose(
                        data.latitude.values[y], cells["era5_lat"].to_numpy(), atol=1e-7, rtol=0
                    )
                    and np.allclose(
                        data.longitude.values[x], cells["era5_lon"].to_numpy(), atol=1e-7, rtol=0
                    )
                ):
                    raise ValueError(
                        f"Daily covariate grid differs from the temperature matches: {path}"
                    )
                sampled = np.empty((length, cells.height), dtype=np.float32)
                chunk = data[field].encoding["chunksizes"][data[field].get_axis_num("valid_time")]
                for start in range(0, length, chunk):
                    block = (
                        data[field].isel(valid_time=slice(start, min(start + chunk, length))).values
                    )
                    sampled[start : start + len(block)] = block[:, y, x]
                values[field] = sampled
            inputs.append(
                {
                    "file": str(path),
                    "sha256": sha256(path),
                    "time_shift": time_shift,
                    "history": history,
                }
            )
            print(f"Sampled {year} {field}", flush=True)
        weather = pl.DataFrame(
            {
                "grid_cell_id": np.tile(cells["grid_cell_id"].to_numpy(), length),
                "DATE": np.repeat(dates[:length], cells.height),
                "wind": np.sqrt(
                    values["u10"].astype(float) ** 2 + values["v10"].astype(float) ** 2
                ).ravel(),
                "tp": values["tp"].ravel().astype(float),
            }
        ).with_columns(pl.col("wind", "tp").fill_nan(None))
        weather = requested.join(weather, on=["grid_cell_id", "DATE"], how="left", validate="1:1")
        output = directory / f"{year}.parquet"
        weather.write_parquet(output, compression="zstd")
        summaries.append(
            {
                "year": int(year),
                "rows": weather.height,
                "missing_wind": weather["wind"].null_count(),
                "missing_tp": weather["tp"].null_count(),
                "file": str(output),
                "sha256": sha256(output),
            }
        )
        print(f"Saved {year}: {weather.height:,} grid-days", flush=True)
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "py.preprocessing.analysis_covariates",
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "elevation": {
            "file": str(elevation_path),
            "sha256": sha256(elevation_path),
            "missing": elevation["elevation"].null_count(),
            "units": "metres",
            "source": "HGHT in ECA&D sources.txt",
        },
        "source_metadata": str(metadata_path),
        "source_metadata_sha256": sha256(metadata_path),
        "weather": summaries,
        "weather_inputs": inputs,
        "wind": "sqrt(daily_mean_u10 ** 2 + daily_mean_v10 ** 2), metres per second",
        "precipitation": "Supplied total_precipitation_daily_mean proxy in metres; no claim of verified daily totals.",
        "temporal_matching": "Use the supplied daily covariate row labelled by ECA&D DATE. These are calendar-date covariates, not aggregates over station-specific temperature windows.",
        "wind_time_window": "All supplied wind components record zero-shift UTC calendar-day means.",
        "precipitation_time_window": "Unverified: no daily averaging or date-shift history is retained. Unshifted ERA5-Land midnight accumulations refer to the preceding day; no shift is applied to this review lookup.",
        "spatial_matching": "Sample each temperature pair's ERA5 cell; no land fallback or interpolation.",
        "code_sha256": {__file__: sha256(Path(__file__))},
    }
    (DATA_DIRECTORY / "cleaning_audit/station_analysis_covariates.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
