"""Source elevation relative to nearby observation sources, not a DEM-derived TPI."""

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from scipy import stats

from py import analysis_common as common


def plot(tables):
    finite = tables["sources"].filter(pl.col("relative_elevation_25km").is_finite())
    x, y = finite["relative_elevation_25km"].to_numpy(), finite["mean_residual"].to_numpy()
    slope, intercept = np.polyfit(x, y, 1)
    common.setup_plotting()
    fig, ax = plt.subplots(figsize=(6.5, 3.8), layout="constrained")
    ax.scatter(x, y, s=10, alpha=0.20, color=common.COLORS[0], edgecolors="none")
    limits = np.array([x.min(), x.max()])
    ax.plot(limits, intercept + slope * limits, color=common.COLORS[1])
    ax.set(xlabel=common.LABELS["relative_elevation_25km"], ylabel="Source mean residual (°C)")
    ax.grid(True)
    common.save_plot(fig, "relative_elevation", "neighbour_elevation_residual")


def source_topography(data):
    sources = (
        data.group_by("SOUID")
        .agg(
            pl.col("source_lat", "source_lon", "elevation").first(),
            pl.col("residual_celsius").mean().alias("mean_residual"),
            pl.len().alias("observations"),
        )
        .sort("SOUID")
    )
    locations = (
        sources.select("source_lat", "source_lon", "elevation")
        .filter(pl.col("elevation").is_finite())
        .unique()
        .sort("source_lat", "source_lon", "elevation")
    )
    lat, lon, height = (locations[column].to_numpy() for column in locations.columns)
    relative, counts = np.full(len(lat), np.nan), np.zeros(len(lat), dtype=np.int32)
    for index in range(len(lat)):
        distance = 111.32 * np.hypot(
            lat - lat[index], (lon - lon[index]) * np.cos(np.deg2rad(lat[index]))
        )
        neighbours = (distance > 0.1) & (distance <= 25)
        counts[index] = int(neighbours.sum())
        if counts[index] >= 2:
            relative[index] = height[index] - height[neighbours].mean()
    lookup = locations.with_columns(
        pl.Series("relative_elevation_25km", relative).fill_nan(None),
        pl.Series("neighbours_25km", counts),
    )
    return sources.join(
        lookup, on=["source_lat", "source_lon", "elevation"], how="left", validate="m:1"
    )


def run():
    data = common.load_sample()
    sources = source_topography(data)
    directory = common.DATA_DIRECTORY / "numerical_analysis"
    directory.mkdir(exist_ok=True)
    lookup_path = directory / "relative_elevation.parquet"
    sources.write_parquet(lookup_path, compression="zstd")
    finite = sources.filter(pl.col("relative_elevation_25km").is_finite())
    x, y = finite["relative_elevation_25km"].to_numpy(), finite["mean_residual"].to_numpy()
    correlation, p_value = stats.pearsonr(x, y)
    slope, _ = np.polyfit(x, y, 1)
    bands = (
        finite.with_columns(
            pl.when(pl.col("elevation") <= 105)
            .then(pl.lit("<=105m"))
            .when(pl.col("elevation") <= 500)
            .then(pl.lit("105–500m"))
            .when(pl.col("elevation") <= 695)
            .then(pl.lit("500–695m"))
            .when(pl.col("elevation") <= 958)
            .then(pl.lit("695–958m"))
            .otherwise(pl.lit(">958m"))
            .alias("elevation_band")
        )
        .group_by("elevation_band")
        .agg(
            pl.len().alias("sources"),
            pl.col("relative_elevation_25km").mean().alias("mean_relative_elevation_m"),
            pl.col("relative_elevation_25km").median().alias("median_relative_elevation_m"),
            (100 * (pl.col("relative_elevation_25km") < 0).mean()).alias(
                "percent_below_neighbours"
            ),
            pl.col("mean_residual").mean().alias("mean_source_residual"),
        )
    )
    summary = {
        "sources_with_two_neighbours": finite.height,
        "sources_without_proxy": sources.height - finite.height,
        "pearson_r": float(correlation),
        "pearson_p_naive": float(p_value),
        "slope_celsius_per_100m": float(100 * slope),
        "lookup_file": str(lookup_path),
        "lookup_sha256": common.sha256(lookup_path),
    }
    plot({"sources": sources})
    common.finish(
        "relative_elevation",
        data,
        {"sources": sources, "elevation_bands": bands},
        summary,
        "Elevation minus the unweighted mean height of at least two distinct nearby source locations, 0.1–25 km away, using the archive's local equirectangular distance approximation. Duplicate location/height entries count once. This depends on station-network geometry and is not DEM topographic position or station-minus-grid elevation. Correlation gives every source equal weight; its naive Pearson p-value does not account for spatial dependence. Fixed elevation bands reproduce the archive's boundaries.",
    )


if __name__ == "__main__":
    run()
