"""Observation and source coverage behind coastal-distance and elevation deciles."""

import matplotlib.pyplot as plt
import numpy as np

from py import analysis_common as common


def plot(tables):
    common.setup_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.5), layout="constrained")
    for ax, feature in zip(axes, ["dist_to_sea_km", "elevation"]):
        table = tables[feature]
        ax.bar(
            table["decile"],
            table["sources"],
            color=common.COLORS[4 if feature == "dist_to_sea_km" else 5],
            alpha=0.7,
        )
        ax.set(
            title=common.LABELS[feature],
            xlabel="Observation-weighted decile",
            ylabel="Distinct sources",
        )
        ax.set_xticks(np.arange(1, table.height + 1))
        ax.grid(True)
    common.save_plot(fig, "geographic_deciles", "sources_per_decile")


def run():
    data = common.load_sample()
    tables = {
        feature: common.profile(data, feature).with_row_index("decile", offset=1)
        for feature in ["dist_to_sea_km", "elevation"]
    }
    plot(tables)
    common.finish(
        "geographic_deciles",
        data,
        tables,
        {},
        "Ten observation-weighted quantile bins per feature. Tables retain actual bin bounds, mean residuals, source-bootstrap intervals and distinct source counts. These source counts need not be equal across observation deciles.",
    )


if __name__ == "__main__":
    run()
