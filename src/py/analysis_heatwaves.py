"""Runs of three or more consecutive hot date-labelled maxima, with ratio intervals."""

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from py import analysis_common as common


def plot(tables):
    table = tables["ratios"]
    common.setup_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.6), layout="constrained", sharey=True)
    for index, (ax, measure) in enumerate(zip(axes, ["spells", "days"])):
        part = table.filter(pl.col("measure") == measure).sort("threshold_celsius")
        y, low, high = (part[column].to_numpy() for column in ["estimate", "ci_low", "ci_high"])
        positions = np.arange(part.height)
        ax.bar(
            positions,
            y,
            width=0.62,
            color=common.COLORS[index],
            edgecolor=common.COLORS[index],
            linewidth=0.4,
            yerr=np.array([y - low, high - y]),
            capsize=2.4,
            error_kw={"ecolor": "#44524F", "elinewidth": 0.9, "capthick": 0.9},
        )
        common.zero_line(ax, 1)
        ax.set(
            xlabel="Hot-day threshold (°C)",
            ylabel="Station / ERA5 count ratio" if index == 0 else "",
            title="Hot spells" if measure == "spells" else "Days in hot spells",
            ylim=(0, table["ci_high"].max() * 1.12),
        )
        ax.set_xticks(positions, part["threshold_celsius"].to_list())
        ax.set_xlim(-0.5, part.height - 0.5)
        ax.grid(axis="y", color="#DDE3E1", linewidth=0.5)
    common.save_plot(fig, "heatwaves", "heatwave_ratios")


def count_spells(data, column, threshold):
    frame = (
        data.select("SOUID", "date", column)
        .sort("SOUID", "date")
        .with_columns(
            (pl.col(column) > threshold).alias("hot"),
            (pl.col("date").diff().over("SOUID") == pl.duration(days=1))
            .fill_null(False)
            .alias("consecutive"),
        )
        .with_columns(
            (~(pl.col("hot") & pl.col("consecutive"))).cum_sum().over("SOUID").alias("run")
        )
    )
    return (
        frame.filter("hot")
        .group_by("SOUID", "run")
        .len()
        .filter(pl.col("len") >= 3)
        .group_by("SOUID")
        .agg(pl.len().alias("spells"), pl.col("len").sum().alias("days_in_spells"))
    )


def run():
    data = common.load_sample()
    all_sources = data.select("SOUID").unique().sort("SOUID")
    rows, source_tables = [], []
    for threshold in [30, 35]:
        paired = all_sources
        for prefix, column in [("station", "station_celsius"), ("era5", "era5_celsius")]:
            counts = count_spells(data, column, threshold).rename(
                {"spells": f"{prefix}_spells", "days_in_spells": f"{prefix}_days"}
            )
            paired = paired.join(counts, on="SOUID", how="left", validate="1:1")
        paired = paired.fill_null(0).sort("SOUID")
        source_tables.append(paired.with_columns(pl.lit(threshold).alias("threshold_celsius")))
        for measure, seed in [("spells", 3000), ("days", 4000)]:
            rows.append(
                {
                    "threshold_celsius": threshold,
                    "measure": measure,
                    "station_count": int(paired[f"station_{measure}"].sum()),
                    "era5_count": int(paired[f"era5_{measure}"].sum()),
                    **common.bootstrap_ratio(
                        paired[f"station_{measure}"],
                        paired[f"era5_{measure}"],
                        seed=seed + threshold,
                    ),
                }
            )
    table = pl.DataFrame(rows)
    plot({"ratios": table})
    common.finish(
        "heatwaves",
        data,
        {"ratios": table, "source_counts": pl.concat(source_tables)},
        {},
        "Strict >30°C and >35°C, at least three consecutive calendar dates within SOUID. Missing dates break spells. Counts are conditional on retained observation coverage and mixed provider window durations; they are not a complete climatological heatwave inventory. Ratio intervals use 1,000 source-bootstrap draws, with zero-event sources retained.",
    )


if __name__ == "__main__":
    run()
