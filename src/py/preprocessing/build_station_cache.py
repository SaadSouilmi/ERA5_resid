"""Save every raw station observation to data2/station_data.parquet using Polars."""

import argparse

import polars as pl

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import RawDataDirectory as RAW_DIRECTORY


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    station_files = sorted((RAW_DIRECTORY / "ECA_blend_tx").glob("TX_STAID*.txt"))
    station_schema = {
        "STAID": pl.Int32,
        "SOUID": pl.Int32,
        "DATE": pl.Int32,
        "TX": pl.Int16,
        "Q_TX": pl.Int8,
    }
    station_data = pl.scan_csv(station_files, skip_rows=20, schema=station_schema)

    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    output = DATA_DIRECTORY / "station_data.parquet"
    print(f"Saving all observations from {len(station_files):,} station files...", flush=True)
    station_data.sink_parquet(output, compression="zstd")

    print(f"Saved {output}")
    print(f"Parquet size: {output.stat().st_size / 1024**2:.1f} MiB")


if __name__ == "__main__":
    main()
