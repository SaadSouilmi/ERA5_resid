"""Seasonal temperature × wind deciles, including ERA5-conditioned comparisons."""

import matplotlib.pyplot as plt
import polars as pl

from py import analysis_common as common

SEASONS = {"DJF": [12, 1, 2], "MAM": [3, 4, 5], "JJA": [6, 7, 8], "SON": [9, 10, 11]}


def joint_cells(data, temperature):
    frame = data.filter(pl.col("wind").is_finite()).with_columns(
        pl.col(temperature)
        .qcut(10, allow_duplicates=True)
        .cast(pl.String)
        .alias("temperature_bin"),
        pl.col("wind").qcut(10, allow_duplicates=True).cast(pl.String).alias("wind_bin"),
    )
    cells = (
        frame.group_by("temperature_bin", "wind_bin")
        .agg(
            pl.col(temperature).min().alias("temperature_low"),
            pl.col(temperature).max().alias("temperature_high"),
            pl.col("wind").min().alias("wind_low"),
            pl.col("wind").max().alias("wind_high"),
            pl.col("residual_celsius").mean().alias("mean"),
            pl.len().alias("observations"),
            pl.col("SOUID").n_unique().alias("sources"),
        )
        .sort("temperature_low", "wind_low")
    )
    warmest = (
        frame.group_by("temperature_bin")
        .agg(pl.col(temperature).min().alias("low"))
        .sort("low")["temperature_bin"][-1]
    )
    # Preserve seasonal wind-decile membership, rather than re-binning warm days.
    rows = []
    order = (
        frame.group_by("wind_bin").agg(pl.col("wind").min().alias("low")).sort("low")["wind_bin"]
    )
    for wind_bin in order:
        part = frame.filter(
            (pl.col("temperature_bin") == warmest) & (pl.col("wind_bin") == wind_bin)
        )
        if part.height:
            rows.append(
                {"wind_bin": wind_bin, "x": part["wind"].mean(), **common.mean_summary(part)}
            )
    profile = pl.DataFrame(rows).sort("x")
    return cells, profile


def run():
    data = common.load_sample(weather=True)
    tables, rows = {}, []
    common.setup_plotting()
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), layout="constrained")
    for ax, (season, months) in zip(axes.flat, SEASONS.items()):
        frame = data.filter(pl.col("month").is_in(months))
        rows.append({"season": season, **common.mean_summary(frame)})
        for index, temperature in enumerate(["station_celsius", "era5_celsius"]):
            cells, curve = joint_cells(frame, temperature)
            tables[f"{season}_{temperature}_cells"] = cells
            tables[f"{season}_{temperature}_warmest"] = curve
            common.draw_profile(
                ax,
                curve,
                "Station-conditioned" if index == 0 else "ERA5-conditioned",
                common.COLORS[index],
            )
        ax.set(
            title=season, xlabel=common.LABELS["wind"], ylabel="Warmest-decile mean residual (°C)"
        )
    axes.flat[0].legend(fontsize=9)
    common.save_plot(fig, "seasonal", "warmest_temperature_wind")
    tables["seasons"] = pl.DataFrame(rows)
    common.finish(
        "seasonal",
        data,
        tables,
        {},
        "DJF/MAM/JJA/SON, with separate 10×10 temperature and wind quantiles within each season. Curves restrict to the season's warmest temperature decile, retaining the original seasonal wind bins. Station- and ERA5-conditioned curves use their respective warm subsets. Intervals: 1,000 SOUID draws per cell. Daily mean-vector wind is not wind measured at the temperature maximum.",
        weather=True,
    )


if __name__ == "__main__":
    run()
