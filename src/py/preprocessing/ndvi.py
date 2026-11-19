"""Sample the original seasonal NDVI rasters and carry the last value forward."""

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import polars as pl

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import RawDataDirectory as RAW_DIRECTORY

SOURCE_KEYS = ["SOUID", "source_lat", "source_lon"]
COORDINATE_KEYS = ["source_lat", "source_lon"]
VALUE_COLUMNS = ["ndvi", "ndvi_source_start", "ndvi_source_end", "ndvi_source_file"]


def season_key():
    month = (pl.col("DATE") // 100) % 100
    year = pl.col("DATE") // 10000 - (month < 3).cast(pl.Int32)
    season_month = pl.when(month < 3).then(12).otherwise(month // 3 * 3)
    return (year * 10000 + season_month * 100 + 1).cast(pl.Int32).alias("ndvi_season")


def fill_missing_seasons(samples):
    samples = samples.sort(*COORDINATE_KEYS, "ndvi_season").with_columns(
        pl.when(pl.col("ndvi").is_not_null())
        .then(pl.struct(VALUE_COLUMNS))
        .otherwise(None)
        .forward_fill()
        .over(COORDINATE_KEYS)
        .alias("_last_seen")
    )
    return (
        samples.with_columns(
            *[
                pl.when(pl.col("_has_raster"))
                .then(pl.col(name))
                .otherwise(pl.col("_last_seen").struct.field(name))
                .alias(name)
                for name in VALUE_COLUMNS
            ]
        )
        .with_columns(
            (pl.col("ndvi").is_not_null() & ~pl.col("_has_raster")).alias("ndvi_is_extrapolated"),
            pl.when(pl.col("ndvi").is_null())
            .then(pl.lit("missing"))
            .when(pl.col("_has_raster"))
            .then(pl.lit("observed_season"))
            .otherwise(pl.lit("last_observation_carried_forward"))
            .alias("ndvi_method"),
        )
        .drop("_last_seen", "_has_raster")
    )


def main():
    import numpy as np

    from py.covariates import sample_raster
    from py.preprocessing.match_era5_grid import sha256

    argparse.ArgumentParser(description=__doc__).parse_args()
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
    raster_dir = RAW_DIRECTORY / "sentinel2_ndvi"
    output = DATA_DIRECTORY / "station_ndvi.parquet"
    source_seasons = (
        pl.scan_parquet(input_path)
        .with_columns(season_key())
        .group_by(*SOURCE_KEYS, "ndvi_season")
        .agg(pl.len().alias("observations"))
        .collect()
    )
    locations = source_seasons.select(COORDINATE_KEYS).unique().sort(COORDINATE_KEYS)
    seasons = source_seasons.select("ndvi_season").unique()
    rasters = sorted(raster_dir.glob("ndvi_*.tif"))
    samples = []
    for path in rasters:
        start, end = [
            date.fromisoformat(part) for part in path.stem.removeprefix("ndvi_").split("_")
        ]
        raw = sample_raster(path, locations.rename({"source_lat": "lat", "source_lon": "lon"}))
        values = np.where((raw >= 0) & (raw <= 254), raw / 254 * 2 - 1, np.nan)
        samples.append(
            locations.with_columns(
                pl.lit(int(start.strftime("%Y%m%d")), dtype=pl.Int32).alias("ndvi_season"),
                pl.Series("ndvi", values).fill_nan(None),
                pl.lit(start).alias("ndvi_source_start"),
                pl.lit(end).alias("ndvi_source_end"),
                pl.lit(path.name).alias("ndvi_source_file"),
            )
        )
        print(f"NDVI sampled: {path.name}", flush=True)
    observed = pl.concat(samples)
    seasonal = (
        locations.join(seasons, how="cross")
        .join(observed, on=[*COORDINATE_KEYS, "ndvi_season"], how="left", validate="1:1")
        .with_columns(pl.col("ndvi_source_file").is_not_null().alias("_has_raster"))
    )
    filled = fill_missing_seasons(seasonal)
    lookup = source_seasons.join(
        filled, on=[*COORDINATE_KEYS, "ndvi_season"], how="left", validate="m:1"
    ).sort(*SOURCE_KEYS, "ndvi_season")
    lookup.write_parquet(output, compression="zstd")
    coverage = (
        lookup.group_by("ndvi_method")
        .agg(pl.col("observations").sum(), pl.len().alias("source_seasons"))
        .sort("ndvi_method")
    )
    audit_dir = DATA_DIRECTORY / "cleaning_audit"
    coverage.write_csv(audit_dir / "station_ndvi_coverage.csv")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "py.preprocessing.ndvi",
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "file": str(output),
        "sha256": sha256(output),
        "bytes": output.stat().st_size,
        "join_keys": [*SOURCE_KEYS, "ndvi_season"],
        "source_seasons": lookup.height,
        "coverage": coverage.to_dicts(),
        "temporal_policy": "Use the original raster for a covered season. Otherwise carry forward the latest earlier nonmissing value at the same source coordinates, across seasons. Never backfill from a future season.",
        "missing_pixel_policy": "Spatial nodata within a covered raster remains missing. Locations with no earlier valid value remain missing.",
        "encoding": "Valid uint8 values 0..254 map to NDVI = value / 254 * 2 - 1; nodata 255 stays missing.",
        "rasters": [{"file": str(path), "sha256": sha256(path)} for path in rasters],
        "code_sha256": {
            str(path): sha256(path)
            for path in [Path(__file__), Path(__file__).parents[1] / "covariates.py"]
        },
    }
    (audit_dir / "station_ndvi.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(coverage, flush=True)
    print(f"Saved {lookup.height:,} source-seasons: {output}", flush=True)


if __name__ == "__main__":
    main()
