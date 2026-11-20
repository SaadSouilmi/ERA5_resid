"""Select ECA&D observations and attach UTC windows without executing a notebook."""

import argparse
from pathlib import Path

import pandas as pd
import polars as pl
import xarray as xr

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.preprocessing.observation_windows import attach_utc_windows
from py.preprocessing.save_selected_observations import save_selected_observations, save_window_audits
from py.preprocessing.station_metadata import attach_source_locations
from py.preprocessing.station_selection import filter_station_quality, select_station_observations


def study_coverage():
    files = sorted((DATA_DIRECTORY / "era5_land_hourly").glob("????-??_2m_temperature_hourly.nc"))
    if not files:
        raise FileNotFoundError("Download the ERA5-Land hourly files before selecting observations")
    with xr.open_dataset(files[0]) as grid:
        lat, lon = grid.latitude.values, grid.longitude.values
        half_lat, half_lon = abs(float(lat[1] - lat[0])) / 2, abs(float(lon[1] - lon[0])) / 2
        bounds = tuple(
            round(float(value), 6)
            for value in [
                lon.min() - half_lon,
                lat.min() - half_lat,
                lon.max() + half_lon,
                lat.max() + half_lat,
            ]
        )
        first_date = int(pd.Timestamp(grid.valid_time.values[0]).strftime("%Y%m%d"))
    with xr.open_dataset(files[-1]) as grid:
        last_date = int(pd.Timestamp(grid.valid_time.values[-1]).strftime("%Y%m%d"))
    return bounds, first_date, last_date, [files[0], files[-1]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA_DIRECTORY)
    args = parser.parse_args()
    bounds, first_date, last_date, era5_files = study_coverage()
    raw = pl.read_parquet(DATA_DIRECTORY / "station_data.parquet")
    raw_count = raw.height
    valid = filter_station_quality(raw)
    sources = attach_source_locations(valid.group_by("STAID", "SOUID").len(name="observations"))
    print(f"Selecting from {raw_count:,} raw observations", flush=True)
    selected, counts, spikes, range_exclusions = select_station_observations(
        valid, sources, bounds, first_date, last_date
    )
    resolved = attach_utc_windows(selected, sources)
    if resolved.height != selected.height:
        raise ValueError("UTC-window mapping changed observation membership")
    save_window_audits(resolved, sources, args.output_dir, first_date, last_date)
    audit_dir = args.output_dir / "cleaning_audit"
    counts = {"raw": raw_count, **counts}
    pl.DataFrame({"stage": list(counts), "records": list(counts.values())}).write_csv(
        audit_dir / "station_selection_counts.csv"
    )
    spikes.write_csv(audit_dir / "station_selection_spike_days.csv")
    range_exclusions.write_csv(audit_dir / "station_selection_range_exclusions.csv")
    output, manifest = save_selected_observations(
        resolved, sources, output_dir=args.output_dir, era5_files=era5_files
    )
    print(f"Saved {manifest['daily_records']:,} observations: {output}", flush=True)
    print(
        f"UTC windows: {manifest['mapped_records']:,} mapped; {manifest['unresolved_records']:,} unresolved",
        flush=True,
    )


if __name__ == "__main__":
    main()
