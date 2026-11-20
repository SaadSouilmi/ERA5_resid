"""UTC-calendar-day versus other resolved station windows and their covariate profiles."""

import argparse

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from py import analysis_common as common
from py.scripts.scientific_style import COLORS as WINDOW_COLORS


def plot(tables):
    summary = tables["summary"]
    common.setup_plotting()
    fig, ax = plt.subplots(figsize=(6.5, 3.6), layout="constrained")
    labels = {
        "full": "All resolved windows",
        "utc_midnight": "00–00 UTC, 24 h",
        "other_resolved": "Other resolved windows",
    }
    positions = np.arange(summary.height)
    mean, low, high = (summary[column].to_numpy() for column in ["mean", "ci_low", "ci_high"])
    ax.bar(
        positions,
        mean,
        width=0.62,
        color=WINDOW_COLORS[:summary.height],
        edgecolor=WINDOW_COLORS[:summary.height],
        linewidth=0.4,
        yerr=np.array([mean - low, high - mean]),
        capsize=2.4,
        error_kw={"ecolor": "#44524F", "elinewidth": 0.9, "capthick": 0.9},
    )
    ax.set_xticks(positions, [labels[name] for name in summary["sample"]])
    ax.set(xlim=(-0.5, summary.height - 0.5), ylabel="Mean residual (°C)")
    ax.margins(y=0.08)
    ax.grid(axis="y", color="#DDE3E1", linewidth=0.5)
    common.save_plot(fig, "utc_windows", "window_means")
    features = [name for name in common.FEATURES if f"full_{name}" in tables]
    common.setup_plotting()
    fig, axes = plt.subplots(2, 3, figsize=(13, 6.5), layout="constrained")
    for ax, feature in zip(axes.flat, features):
        for index, sample in enumerate(["full", "utc_midnight"]):
            common.draw_profile(
                ax, tables[f"{sample}_{feature}"], labels[sample], common.COLORS[index]
            )
        ax.set(xlabel=common.LABELS[feature], ylabel="Mean residual (°C)")
    for ax in list(axes.flat)[len(features) :]:
        ax.set_visible(False)
    axes.flat[0].legend()
    common.save_plot(fig, "utc_windows", "utc_profiles")


def run(weather=True):
    data = common.load_sample(weather)
    subsets = {
        "full": data,
        "utc_midnight": data.filter("utc_day_aligned"),
        "other_resolved": data.filter(~pl.col("utc_day_aligned")),
    }
    summary = pl.DataFrame(
        [{"sample": name, **common.mean_summary(frame)} for name, frame in subsets.items()]
    )
    windows = (
        data.group_by("observation_window", "window_hours", "utc_day_aligned")
        .agg(
            pl.len().alias("observations"),
            pl.col("SOUID").n_unique().alias("sources"),
            pl.col("residual_celsius").mean().alias("mean"),
            pl.col("residual_celsius").std().alias("sd"),
        )
        .sort("observations", descending=True)
    )
    features = (
        common.FEATURES
        if weather
        else [name for name in common.FEATURES if name not in ("wind", "tp")]
    )
    profiles = {}
    for sample in ["full", "utc_midnight"]:
        for feature in features:
            profiles[f"{sample}_{feature}"] = common.profile(subsets[sample], feature)
    tables = {"summary": summary, "windows": windows, **profiles}
    plot(tables)
    if weather:
        from py.analysis_seasonal import joint_cells

        cells, warmest = joint_cells(subsets["utc_midnight"], "station_celsius")
        tables["utc_temperature_wind_cells"] = cells
        tables["utc_warm_calm"] = warmest
    tables["utc_degurba"] = (
        subsets["utc_midnight"]
        .group_by("degurba", "degurba_label")
        .agg(
            pl.col("residual_celsius").mean().alias("mean"),
            pl.len().alias("observations"),
            pl.col("SOUID").n_unique().alias("sources"),
        )
        .sort("degurba")
    )
    common.finish(
        "utc_windows",
        data,
        tables,
        {"utc_observations": subsets["utc_midnight"].height},
        "All pairs already use matched source windows. This comparison tests sample composition across window types, not the former calendar-date matching. Profiles use sample-specific deciles and 1,000 within-bin SOUID bootstrap draws, seed 1337.",
        weather,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-weather", action="store_true")
    run(weather=not parser.parse_args().without_weather)


if __name__ == "__main__":
    main()
