"""Source-by-calendar-month demeaned profiles for three temperature references and wind."""

import argparse

import matplotlib.pyplot as plt
import polars as pl

from py import analysis_common as common


def plot(tables):
    features = [
        name
        for name in ["station_celsius", "era5_celsius", "midpoint", "wind"]
        if f"{name}_raw" in tables
    ]
    common.setup_plotting()
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.8), layout="constrained")
    for ax, feature in zip(axes.flat, features):
        common.draw_profile(ax, tables[f"{feature}_raw"], "Raw residual", common.COLORS[0])
        common.draw_profile(
            ax, tables[f"{feature}_within"], "Source × month demeaned residual", common.COLORS[1]
        )
        ax.set(
            xlabel=f"{common.LABELS[feature]}\nwithin-source monthly anomaly",
            ylabel="Mean residual (°C)",
        )
    for ax in list(axes.flat)[len(features) :]:
        ax.set_visible(False)
    axes.flat[0].legend(fontsize=8)
    common.save_plot(fig, "fixed_effects", "within_source_month")


def run(weather=True):
    data = common.load_sample(weather)
    features = ["station_celsius", "era5_celsius", "midpoint"] + (["wind"] if weather else [])
    frame = data.with_columns(
        *[
            (pl.col(feature) - pl.col(feature).mean().over("SOUID", "month")).alias(
                f"{feature}_anomaly"
            )
            for feature in [*features, "residual_celsius"]
        ]
    )
    tables = {}
    for feature in features:
        anomaly = f"{feature}_anomaly"
        raw = common.profile(frame, anomaly)
        within = common.profile(frame, anomaly, residual="residual_celsius_anomaly")
        tables[f"{feature}_raw"] = raw
        tables[f"{feature}_within"] = within
    plot(tables)
    for feature in ["era5_celsius", "midpoint"]:
        tables[f"{feature}_raw_reference"] = common.profile(frame, feature)
        tables[f"{feature}_within_reference"] = common.profile(
            frame, feature, residual="residual_celsius_anomaly"
        )
    common.finish(
        "fixed_effects",
        data,
        tables,
        {},
        "Subtract each source's calendar-month mean across all study years, for both residual and conditioning variables. This removes source-by-month mean differences, not all day-specific confounding. Station temperature and the midpoint both contain a component of the residual; conditioning on ERA5 gives a separate coupling diagnostic. 1,000 SOUID bootstrap draws per bin; demeaning is held fixed during resampling.",
        weather,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--without-weather", action="store_true")
    run(weather=not parser.parse_args().without_weather)


if __name__ == "__main__":
    main()
