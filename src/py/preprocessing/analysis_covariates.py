"""Save source elevation from ECA&D metadata; weather uses py.preprocessing.hourly_weather."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.paths import RAW_DATA_DIRECTORY as RAW_DIRECTORY
from py.preprocessing.match_era5_grid import sha256


def build_source_elevation():
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
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
        pl.scan_parquet(input_path)
        .select("STAID", "source_metadata_id")
        .unique()
        .collect()
        .join(metadata, on=["STAID", "source_metadata_id"], how="left", validate="1:1")
        .sort("STAID", "source_metadata_id")
    )
    output = DATA_DIRECTORY / "station_elevation.parquet"
    elevation.write_parquet(output, compression="zstd")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "py.preprocessing.analysis_covariates",
        "inputs": {str(path): sha256(path) for path in [input_path, metadata_path]},
        "file": str(output),
        "sha256": sha256(output),
        "metadata_entries": elevation.height,
        "missing": elevation["elevation"].null_count(),
        "units": "metres",
        "source": "HGHT in ECA&D sources.txt; -999 and -9999 remain missing",
        "join_keys": ["STAID", "source_metadata_id"],
        "code_sha256": {__file__: sha256(Path(__file__))},
    }
    (DATA_DIRECTORY / "cleaning_audit/station_elevation.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    print(f"Source elevation saved: {elevation.height:,} metadata entries", flush=True)
    return elevation


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    build_source_elevation()


if __name__ == "__main__":
    main()
