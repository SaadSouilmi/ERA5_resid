"""Daily-maximum heat excess above 24°C, the archive's cdd24 proxy."""

import matplotlib.pyplot as plt
import polars as pl

from py import analysis_common as common


def plot(tables):
    years = tables["by_year"]
    common.setup_plotting()
    fig, ax = plt.subplots(figsize=(6.5, 3.4), layout="constrained")
    for offset, column, label, color in [
        (-0.18, "station_heat_excess", "Stations", common.COLORS[1]),
        (0.18, "era5_heat_excess", "ERA5-Land", common.COLORS[0]),
    ]:
        ax.bar(years["year"] + offset, years[column] / 1e6, color=color, width=0.36, label=label)
    ax.set(xlabel="Year", ylabel="Maximum-temperature heat excess\n(million °C·days)")
    ax.grid(True)
    ax.legend()
    common.save_plot(fig, "heat_excess", "heat_excess_by_year")


def run():
    data = common.load_sample()
    frame = data.with_columns(
        (pl.col("station_celsius") - 24).clip(lower_bound=0).alias("station_heat_excess"),
        (pl.col("era5_celsius") - 24).clip(lower_bound=0).alias("era5_heat_excess"),
    )
    sources = (
        frame.group_by("SOUID")
        .agg(pl.col("station_heat_excess", "era5_heat_excess").sum())
        .sort("SOUID")
    )
    ratio = common.bootstrap_ratio(
        sources["station_heat_excess"], sources["era5_heat_excess"], seed=2026
    )
    years = (
        frame.group_by(pl.col("date").dt.year().alias("year"))
        .agg(
            pl.col("station_heat_excess", "era5_heat_excess").sum(), pl.len().alias("observations")
        )
        .sort("year")
    )
    summary = {
        "threshold_celsius": 24,
        "station_total_celsius_days": sources["station_heat_excess"].sum(),
        "era5_total_celsius_days": sources["era5_heat_excess"].sum(),
        **ratio,
    }
    plot({"by_year": years})
    common.finish(
        "heat_excess",
        data,
        {"by_year": years, "summary": pl.DataFrame([summary])},
        summary,
        "Sum max(Tmax − 24°C, 0) over retained source-days. This is a daily-maximum heat-excess proxy, not conventional cooling degree-days calculated from daily mean temperature. Ratio CI: 1,000 SOUID bootstrap draws, seed 2026. 2025 ends in August.",
    )


if __name__ == "__main__":
    run()
