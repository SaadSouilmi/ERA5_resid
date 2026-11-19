"""Hot-day counts, source-bootstrap ratios, recall and precision at 25–40°C."""

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from py import analysis_common as common


def run():
    data = common.load_sample(weather=True)
    subsets = {
        "all": data,
        "semi_dense_urban_22": data.filter(pl.col("degurba") == 22),
        "urban_22_23_30": data.filter(pl.col("degurba").is_in([22, 23, 30])),
        "wind_at_most_0.5034484": data.filter(pl.col("wind") <= 0.5034484),
        "utc_midnight": data.filter("utc_day_aligned"),
    }
    rows = []
    for name, frame in subsets.items():
        for threshold in [25, 30, 35, 40]:
            station, era5 = (
                pl.col("station_celsius") > threshold,
                pl.col("era5_celsius") > threshold,
            )
            counts = (
                frame.group_by("SOUID")
                .agg(
                    station.sum().alias("station_days"),
                    era5.sum().alias("era5_days"),
                    (station & era5).sum().alias("both_days"),
                )
                .sort("SOUID")
            )
            s, e, both = (
                int(counts[name].sum()) for name in ["station_days", "era5_days", "both_days"]
            )
            rows.append(
                {
                    "sample": name,
                    "threshold_celsius": threshold,
                    "observations": frame.height,
                    "sources": counts.height,
                    "station_days": s,
                    "era5_days": e,
                    "both_days": both,
                    "station_percent": 100 * s / frame.height,
                    "era5_percent": 100 * e / frame.height,
                    "false_negative_days": s - both,
                    "false_positive_days": e - both,
                    "recall_percent": 100 * both / s if s else None,
                    "precision_percent": 100 * both / e if e else None,
                    "count_shortfall_percent": 100 * (s - e) / s if s else None,
                    **common.bootstrap_ratio(
                        counts["station_days"], counts["era5_days"], seed=1337 + threshold
                    ),
                }
            )
    table = pl.DataFrame(rows)
    common.setup_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    full = table.filter(pl.col("sample") == "all")
    for column, label, color in [
        ("station_percent", "Stations", common.COLORS[1]),
        ("era5_percent", "ERA5-Land", common.COLORS[2]),
    ]:
        axes[0].plot(full["threshold_celsius"], full[column], "o-", label=label, color=color)
    axes[0].set(xlabel="Maximum temperature threshold (°C)", ylabel="Exceeding source-days (%)")
    for index, name in enumerate(subsets):
        part = table.filter(pl.col("sample") == name)
        x = part["threshold_celsius"].to_numpy() + (index - 2) * 0.2
        y, low, high = (part[column].to_numpy() for column in ["estimate", "ci_low", "ci_high"])
        axes[1].errorbar(
            x,
            y,
            yerr=np.array([y - low, high - y]),
            fmt="o-",
            capsize=2,
            color=common.COLORS[index],
            label=name.replace("_", " "),
        )
    axes[1].axhline(1, color="#687370", linestyle=":", linewidth=0.8)
    axes[1].set(
        xlabel="Maximum temperature threshold (°C)", ylabel="Station / ERA5 exceedance count"
    )
    for ax in axes:
        ax.grid(True)
        ax.legend(fontsize=8)
    common.save_plot(fig, "exceedances", "threshold_exceedances")
    common.finish(
        "exceedances",
        data,
        {"exceedances": table},
        {"low_wind_cutoff_mps": 0.5034484},
        "Strict >25, >30, >35 and >40°C; archive's fixed low-wind cutoff retained for comparability. Ratios use 1,000 SOUID bootstrap draws. Count shortfall is a net count difference, distinct from false negatives. Unbounded or undefined ratio intervals are flagged.",
        weather=True,
    )


if __name__ == "__main__":
    run()
