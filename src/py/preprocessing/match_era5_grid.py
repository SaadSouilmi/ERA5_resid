"""Save a reusable ERA5-Land grid lookup for the selected ECA&D source locations."""

import argparse
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import polars as pl
import xarray as xr

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.preprocessing.era5_grid import match_coordinates

SOURCE_KEYS = ["STAID", "SOUID", "source_lat", "source_lon"]
COORDINATE_KEYS = ["source_lat", "source_lon"]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    input_path = DATA_DIRECTORY / "selected_station_observations.parquet"
    output_path = DATA_DIRECTORY / "selected_station_era5_grid.parquet"
    files = sorted((DATA_DIRECTORY / "era5_land_hourly").glob("????-??_2m_temperature_hourly.nc"))
    with xr.open_dataset(files[0]) as data:
        lat, lon = data.latitude.values.copy(), data.longitude.values.copy()
        dimensions = data.t2m.dims
        available = np.isfinite(
            data.t2m.isel(valid_time=0).transpose("latitude", "longitude").values
        )
        mask_timestamp = str(data.valid_time.values[0])
    for file in files[1:]:
        with xr.open_dataset(file) as data:
            if (
                not np.array_equal(data.latitude.values, lat)
                or not np.array_equal(data.longitude.values, lon)
                or data.t2m.dims != dimensions
            ):
                raise ValueError(f"Grid values, ordering or dimensions differ: {file}")

    observations = pl.scan_parquet(input_path)
    sources = (
        observations.group_by(SOURCE_KEYS)
        .agg(
            pl.len().alias("observation_count"),
            pl.col("DATE").min().alias("first_date"),
            pl.col("DATE").max().alias("last_date"),
        )
        .collect()
    )
    locations = sources.select(COORDINATE_KEYS).unique().sort(COORDINATE_KEYS)
    coordinates = match_coordinates(locations, lat, lon, available)
    mapping = sources.join(coordinates, on=COORDINATE_KEYS, how="left", validate="m:1").sort(
        SOURCE_KEYS
    )
    mapping.write_parquet(output_path, compression="zstd")

    saved = pl.scan_parquet(output_path)
    joined = (
        observations.select(SOURCE_KEYS)
        .join(
            saved.select(*SOURCE_KEYS, "grid_match_status"),
            on=SOURCE_KEYS,
            how="left",
            validate="m:1",
        )
        .select(
            pl.len().alias("observations"),
            pl.col("grid_match_status").null_count().alias("observations_without_lookup"),
        )
        .collect()
        .row(0, named=True)
    )
    if (
        joined["observations_without_lookup"]
        or joined["observations"] != sources["observation_count"].sum()
    ):
        raise ValueError("Saved grid lookup does not preserve all observation matches")

    counts = (
        mapping.group_by("grid_match_status")
        .agg(
            pl.len().alias("source_locations"),
            pl.struct(COORDINATE_KEYS).n_unique().alias("distinct_coordinates"),
            pl.col("grid_cell_id").drop_nulls().n_unique().alias("grid_cells"),
            pl.col("observation_count").sum().alias("observations"),
        )
        .sort("grid_match_status")
    )
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "output": str(output_path),
        "output_sha256": sha256(output_path),
        "output_bytes": output_path.stat().st_size,
        "join_keys": SOURCE_KEYS,
        **joined,
        "station_ids": sources["STAID"].n_unique(),
        "source_locations": sources.height,
        "distinct_coordinates": locations.height,
        "status_counts": counts.to_dicts(),
        "matching_method": "Nearest coordinate independently on each stored grid axis; pandas selects the larger coordinate for exact ties. No land fallback or interpolation.",
        "index_convention": "Zero-based positions in the downloaded axes; grid_cell_id = latitude_index * longitude_count + longitude_index.",
        "grid_reference_file": str(files[0]),
        "grid_dimensions": dimensions,
        "latitude_count": len(lat),
        "longitude_count": len(lon),
        "latitude_sha256": hashlib.sha256(lat.tobytes()).hexdigest(),
        "longitude_sha256": hashlib.sha256(lon.tobytes()).hexdigest(),
        "monthly_files_checked": [file.name for file in files],
        "monthly_grid_axes_identical": True,
        "mask_definition": f"Non-finite t2m at {mask_timestamp} UTC in the reference hourly file; this flag is separate from the full hourly completeness audit.",
        "outside_grid_policy": "Outside the outer half-cell footprint: flag outside_grid and leave grid coordinates, indices and mask null.",
        "time_coverage_policy": "Geographical lookup only. Later maximum extraction will drop observations whose window extends outside the downloaded period.",
    }
    audit_path = DATA_DIRECTORY / "cleaning_audit/selected_station_era5_grid.json"
    audit_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(counts)
    print(f"Saved {mapping.height:,} source-location matches to {output_path}")
    print(f"Verified lookup joins for all {joined['observations']:,} observations")
    print(f"Audit: {audit_path}")


if __name__ == "__main__":
    main()
