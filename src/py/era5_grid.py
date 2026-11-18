"""Match source coordinates to positions on the downloaded ERA5-Land grid."""

import numpy as np
import pandas as pd
import polars as pl


def match_coordinates(locations, lat, lon, available):
    source_lat = locations["source_lat"].to_numpy()
    source_lon = locations["source_lon"].to_numpy()
    if not (np.isfinite(source_lat).all() and np.isfinite(source_lon).all()):
        raise ValueError("Source coordinates must be finite decimal degrees")

    y = pd.Index(lat).get_indexer(source_lat, method="nearest")
    x = pd.Index(lon).get_indexer(source_lon, method="nearest")
    half_lat = np.abs(np.diff(lat)).min() / 2
    half_lon = np.abs(np.diff(lon)).min() / 2
    inside = (
        (source_lat >= lat.min() - half_lat)
        & (source_lat <= lat.max() + half_lat)
        & (source_lon >= lon.min() - half_lon)
        & (source_lon <= lon.max() + half_lon)
    )
    matches = locations.with_columns(
        pl.Series("latitude_index", y, dtype=pl.Int32),
        pl.Series("longitude_index", x, dtype=pl.Int32),
        pl.Series("grid_cell_id", y * len(lon) + x, dtype=pl.Int32),
        pl.Series("era5_lat", lat[y]),
        pl.Series("era5_lon", lon[x]),
        pl.Series("era5_cell_masked", ~available[y, x]),
        pl.Series(
            "grid_match_status",
            np.where(inside, np.where(available[y, x], "matched", "masked_cell"), "outside_grid"),
        ).cast(pl.Categorical),
    )
    return matches.with_columns(
        pl.when(pl.col("grid_match_status") != "outside_grid")
        .then(pl.col(name))
        .otherwise(None)
        .alias(name)
        for name in [
            "latitude_index",
            "longitude_index",
            "grid_cell_id",
            "era5_lat",
            "era5_lon",
            "era5_cell_masked",
        ]
    )
