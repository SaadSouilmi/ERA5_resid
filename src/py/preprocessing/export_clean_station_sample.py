"""Save the stricter source-day sample without replacing the existing analysis release."""

import argparse
import json
from datetime import datetime, timezone

import polars as pl

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.paths import PROJECT_ROOT
from py.preprocessing.match_era5_grid import sha256
from py.preprocessing.station_sample import select_clean_sample


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    audit_dir = DATA_DIRECTORY / "cleaning_audit"
    source_manifest = audit_dir / "station_era5_monthly.json"
    manifest = json.loads(source_manifest.read_text())
    if manifest["status"] != "complete":
        raise ValueError("Complete the monthly ERA5 extraction before exporting the clean sample")
    coverage = pl.read_csv(audit_dir / "station_era5_monthly_coverage.csv")
    files = []
    for row in coverage.iter_rows(named=True):
        path = DATA_DIRECTORY / "station_era5_monthly" / f"{row['month']}.parquet"
        if sha256(path) != row["sha256"]:
            raise ValueError(f"Monthly output differs from its audit: {path}")
        files.append(path)
    clean, counts = select_clean_sample(pl.read_parquet(files))
    output = DATA_DIRECTORY / "station_era5_clean.parquet"
    clean.write_parquet(output, compression="zstd")
    result = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "py.preprocessing.export_clean_station_sample",
        "file": str(output),
        "sha256": sha256(output),
        "bytes": output.stat().st_size,
        **counts,
        "filter": "era5_match_status == matched and window_sampling == provider_daily_maximum",
        "deduplication": "One row per (SOUID, DATE); conflicting values are rejected, and the smallest observation_id is retained.",
        "duration_policy": "Retain all resolved durations, including 12-hour windows and 23/25-hour daylight-saving days.",
        "source_manifest": str(source_manifest),
        "source_manifest_sha256": sha256(source_manifest),
        "monthly_inputs": coverage.select("month", "sha256").to_dicts(),
        "code_sha256": {
            str(path): sha256(path)
            for path in [
                PROJECT_ROOT / "src/py/preprocessing/station_sample.py",
                PROJECT_ROOT / "src/py/preprocessing/export_clean_station_sample.py",
            ]
        },
    }
    (audit_dir / "station_era5_clean.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"Saved {clean.height:,} source-days to {output}", flush=True)
    print(json.dumps(counts, indent=2), flush=True)


if __name__ == "__main__":
    main()
