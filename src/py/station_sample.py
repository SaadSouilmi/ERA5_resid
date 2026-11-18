"""Select complete provider maxima and keep one observation per source-day."""

import polars as pl

SOURCE_DAY_KEYS = ["SOUID", "DATE"]
COMPARISON_COLUMNS = [
    "station_celsius",
    "source_lat",
    "source_lon",
    "grid_cell_id",
    "window_start_utc",
    "window_end_utc",
    "era5_tmax_celsius",
]


def select_clean_sample(pairs):
    matched = pairs.filter(
        (pl.col("era5_match_status") == "matched")
        & (pl.col("window_sampling") == "provider_daily_maximum")
    )
    source_days = matched.group_by(SOURCE_DAY_KEYS).agg(
        pl.struct(COMPARISON_COLUMNS).n_unique().alias("versions")
    )
    conflicts = source_days.filter(pl.col("versions") > 1)
    if conflicts.height:
        raise ValueError(
            f"{conflicts.height} source-days have conflicting temperatures, locations or windows"
        )
    clean = matched.sort("observation_id").unique(
        subset=SOURCE_DAY_KEYS, keep="first", maintain_order=True
    )
    return clean, {
        "input_records": pairs.height,
        "matched_provider_records": matched.height,
        "repeated_records_removed": matched.height - clean.height,
        "source_days": clean.height,
        "conflicting_source_days": conflicts.height,
    }
