"""Sample the existing 2020 DEGURBA raster at observation-source coordinates."""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl

from py.covariates import sample_raster
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.preprocessing.match_era5_grid import sha256

SOURCE_KEYS = ["SOUID", "source_lat", "source_lon"]
CLASSES = {
    10: "Water",
    11: "Very low density rural",
    12: "Low density rural",
    13: "Rural cluster",
    21: "Suburban",
    22: "Semi-dense urban cluster",
    23: "Dense urban cluster",
    30: "Urban centre",
}


def build_land_cover():
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
    raster = (
        DATA_DIRECTORY
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    sources = pl.scan_parquet(input_path).select(SOURCE_KEYS).unique().collect().sort(SOURCE_KEYS)
    coordinates = ["source_lat", "source_lon"]
    locations = sources.select(coordinates).unique().sort(coordinates)
    values = sample_raster(raster, locations.rename({"source_lat": "lat", "source_lon": "lon"}))
    values = np.where(np.isin(values, list(CLASSES)), values, np.nan)
    sampled = locations.with_columns(pl.Series("degurba", values).fill_nan(None).cast(pl.Int16))
    lookup = sources.join(sampled, on=coordinates, validate="m:1").with_columns(
        pl.col("degurba")
        .replace_strict(CLASSES, default=None, return_dtype=pl.String)
        .alias("degurba_label")
    )
    output = DATA_DIRECTORY / "station_land_cover.parquet"
    lookup.write_parquet(output, compression="zstd")
    manifest = {
        "input_sha256": sha256(input_path),
        "raster": str(raster),
        "raster_sha256": sha256(raster),
        "reference_year": 2020,
        "file": str(output),
        "sha256": sha256(output),
        "source_locations": lookup.height,
        "missing": lookup["degurba"].null_count(),
        "join_keys": SOURCE_KEYS,
        "code_sha256": {__file__: sha256(Path(__file__))},
    }
    (DATA_DIRECTORY / "cleaning_audit/station_land_cover.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(f"Saved land-cover classes for {lookup.height:,} source locations", flush=True)


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    build_land_cover()


if __name__ == "__main__":
    main()
