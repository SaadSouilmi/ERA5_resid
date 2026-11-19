"""Current sample, variable availability, geographic and urbanisation tables."""

import argparse

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from py import analysis_common as common


def residual_histogram(values):
    counts, edges = np.histogram(values, bins=80)
    return pl.DataFrame({"left": edges[:-1], "right": edges[1:], "count": counts})


def plot(tables):
    common.setup_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), layout="constrained")
    histogram = tables["residual_histogram"]
    axes[0].bar(
        histogram["left"],
        histogram["count"],
        width=histogram["right"] - histogram["left"],
        align="edge",
        color=common.COLORS[0],
        alpha=0.65,
    )
    axes[0].set(xlabel="Station − ERA5-Land maximum (°C)", ylabel="Source-days")
    year = tables["by_year"]
    axes[1].bar(year["year"], year["observations"] / 1e6, color=common.COLORS[2], alpha=0.65)
    axes[1].set(xlabel="Year", ylabel="Source-days (millions)")
    for ax in axes:
        ax.grid(True)
    common.save_plot(fig, "descriptive", "sample")


def run(weather=True):
    data = common.load_sample(weather)
    features = [
        "station_celsius",
        "era5_celsius",
        "residual_celsius",
        "ndvi",
        "elevation",
        "dist_to_sea_km",
    ]
    if weather:
        features += ["wind", "tp"]
    rows = []
    for feature in features:
        values = data.filter(pl.col(feature).is_finite())[feature]
        rows.append(
            {
                "variable": feature,
                "observations": len(values),
                "missing": data.height - len(values),
                "mean": values.mean(),
                "sd": values.std(),
                **{
                    f"p{int(100 * q):02d}": values.quantile(q, interpolation="linear")
                    for q in [0.05, 0.25, 0.5, 0.75, 0.95]
                },
            }
        )
    tables = {"continuous": pl.DataFrame(rows)}
    for label, keys in [("countries", ["country_code"]), ("degurba", ["degurba", "degurba_label"])]:
        tables[label] = (
            data.group_by(keys)
            .agg(
                pl.len().alias("observations"),
                pl.col("SOUID").n_unique().alias("sources"),
                pl.col("STAID").n_unique().alias("nominal_station_ids"),
                pl.col("residual_celsius").mean().alias("mean_residual"),
            )
            .with_columns((100 * pl.col("observations") / data.height).alias("observation_percent"))
            .sort("observations", descending=True)
        )
    tables["by_year"] = (
        data.group_by(pl.col("date").dt.year().alias("year"))
        .agg(
            pl.len().alias("observations"),
            pl.col("SOUID").n_unique().alias("sources"),
            pl.col("residual_celsius").mean().alias("mean_residual"),
        )
        .sort("year")
    )
    summary = {
        **common.mean_summary(data),
        "nominal_station_ids": data["STAID"].n_unique(),
        "countries": data["country_code"].n_unique(),
        "first_date": str(data["date"].min()),
        "last_date": str(data["date"].max()),
        "hourly_weather_included": weather,
    }
    tables["residual_histogram"] = residual_histogram(data["residual_celsius"].to_numpy())
    plot(tables)
    common.finish(
        "descriptive",
        data,
        tables,
        summary,
        "All retained source-days; no covariate-based temperature exclusions. 2025 ends in August.",
        weather,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-weather", action="store_true")
    run(weather=not parser.parse_args().without_weather)


if __name__ == "__main__":
    main()
