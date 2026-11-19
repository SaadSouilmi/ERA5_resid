"""Source-clustered omnibus equality tests for the six descriptive decile profiles."""

import matplotlib.pyplot as plt
import polars as pl

from py import analysis_common as common


def run():
    data = common.load_sample(weather=True)
    table = pl.DataFrame([common.omnibus_test(data, feature) for feature in common.FEATURES])
    common.setup_plotting()
    fig, ax = plt.subplots(figsize=(7, 3.5), layout="constrained")
    ax.barh(table["feature"], table["range_celsius"], color=common.COLORS, alpha=0.75)
    ax.set_xlabel("Largest − smallest decile mean residual (°C)")
    ax.grid(True)
    common.save_plot(fig, "covariate_tests", "decile_effect_ranges")
    common.finish(
        "covariate_tests",
        data,
        {"wald_tests": table},
        {},
        "Equal residual means across observation-weighted deciles, using the source-clustered sandwich covariance with CR1 finite-sample correction. F test degrees of freedom use contrast covariance rank and G−1. P-values are unadjusted for multiple testing; effect ranges are descriptive, not causal effects. Invalid or negative precipitation totals are omitted only from its log profile.",
        weather=True,
    )


if __name__ == "__main__":
    run()
