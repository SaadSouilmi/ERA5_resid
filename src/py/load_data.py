"""Load the clean temperature sample with source covariates and optional hourly weather."""

import polars as pl

from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.preprocessing.ndvi import season_key


def load_data(*, include_weather=False) -> pl.DataFrame:
    """Return station–ERA5 pairs and saved covariates in the original row order."""
    observations = pl.scan_parquet(DATA_DIRECTORY / "station_era5_clean.parquet")
    keys = ["SOUID", "source_lat", "source_lon"]
    coastal_distance = pl.scan_parquet(DATA_DIRECTORY / "station_coastal_distance.parquet").select(
        *keys, "dist_to_sea_km"
    )
    ndvi = pl.scan_parquet(DATA_DIRECTORY / "station_ndvi.parquet").drop("observations")
    elevation = pl.scan_parquet(DATA_DIRECTORY / "station_elevation.parquet")
    land_cover = pl.scan_parquet(DATA_DIRECTORY / "station_land_cover.parquet")
    loaded = (
        observations.with_columns(season_key())
        .join(
            coastal_distance,
            on=keys,
            how="left",
            validate="m:1",
            maintain_order="left",
        )
        .join(
            elevation,
            on=["STAID", "source_metadata_id"],
            how="left",
            validate="m:1",
            maintain_order="left",
        )
        .join(land_cover, on=keys, how="left", validate="m:1", maintain_order="left")
        .join(
            ndvi,
            on=[*keys, "ndvi_season"],
            how="left",
            validate="m:1",
            maintain_order="left",
        )
        .with_columns(
            pl.when(pl.col("ndvi").is_not_null())
            .then(
                (pl.col("DATE").cast(pl.String).str.to_date("%Y%m%d") - pl.col("ndvi_source_end"))
                .dt.total_days()
                .add(1)
                .clip(lower_bound=0)
            )
            .otherwise(None)
            .alias("ndvi_lag_days")
        )
    )
    if include_weather:
        from py.preprocessing.hourly_weather import JOIN_KEYS, VALUE_COLUMNS

        loaded = loaded.join(
            pl.scan_parquet(DATA_DIRECTORY / "station_hourly_weather.parquet").select(
                *JOIN_KEYS, *VALUE_COLUMNS
            ),
            on=JOIN_KEYS,
            how="left",
            validate="m:1",
            maintain_order="left",
        )
    return loaded.collect()
