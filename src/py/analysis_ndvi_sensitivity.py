"""Original observed-season NDVI versus the full carry-forward sample."""

import matplotlib.pyplot as plt
import polars as pl

from py import analysis_common as common


def plot(tables):
    common.setup_plotting()
    fig, ax = plt.subplots(figsize=(6.5, 3.8), layout="constrained")
    for index, name in enumerate(["all_available", "observed_only"]):
        common.draw_profile(
            ax, tables[name], name.replace("_", " ").capitalize(), common.COLORS[index]
        )
    ax.set(xlabel="NDVI", ylabel="Mean residual (°C)")
    ax.legend()
    common.save_plot(fig, "ndvi_sensitivity", "observed_vs_carry_forward")


def run():
    data = common.load_sample()
    samples = {
        "all_available": data,
        "observed_only": data.filter(~pl.col("ndvi_is_extrapolated").fill_null(True)),
    }
    tables, tests = {}, []
    for name, frame in samples.items():
        table = common.profile(frame, "ndvi")
        tables[name] = table
        tests.append({"sample": name, **common.omnibus_test(frame, "ndvi")})
    plot(tables)
    tables["wald_tests"] = pl.DataFrame(tests)
    common.finish(
        "ndvi_sensitivity",
        data,
        tables,
        {},
        "Compare all available original-season or carried-forward NDVI with ndvi_is_extrapolated == False. Each sample has its own deciles and 1,000 source-bootstrap intervals. Omnibus equal-bin-mean tests use SOUID-clustered CR1 covariance. Samples differ in date coverage and composition; their difference does not isolate an extrapolation effect.",
    )


if __name__ == "__main__":
    run()
