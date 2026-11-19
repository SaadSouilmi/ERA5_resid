"""Streaming adjusted OLS with source-clustered CR1 standard errors."""

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from scipy import stats

from py import analysis_common as common

CONTINUOUS = ["midpoint", "wind", "dist_to_sea_km", "elevation", "log10_tp", "ndvi"]


def design(frame, means, deviations, months):
    z = [(frame[name].to_numpy() - means[name]) / deviations[name] for name in CONTINUOUS]
    return np.column_stack(
        [
            np.ones(frame.height),
            *z,
            z[0] * z[1],
            frame["degurba"].is_in([22, 23, 30]).to_numpy().astype(float),
            *[(frame["month"].to_numpy() == month).astype(float) for month in months],
        ]
    )


def fit_clustered(frame, chunk_size=500_000):
    means = {name: frame[name].mean() for name in CONTINUOUS}
    deviations = {name: frame[name].std() for name in CONTINUOUS}
    levels = frame["month"].unique().sort().to_list()
    months = levels[1:]
    names = [
        "intercept",
        *[f"z_{name}" for name in CONTINUOUS],
        "z_midpoint_x_z_wind",
        "urban_22_23_30",
        *[f"month_{month}" for month in months],
    ]
    n, k = frame.height, len(names)
    groups = frame["SOUID"].unique().sort().to_numpy()
    g = len(groups)
    xx, xy = np.zeros((k, k)), np.zeros(k)
    for chunk in frame.iter_slices(chunk_size):
        x, y = design(chunk, means, deviations, months), chunk["residual_celsius"].to_numpy()
        xx += x.T @ x
        xy += x.T @ y
    inverse = np.linalg.inv(xx)
    beta = np.linalg.solve(xx, xy)
    scores, rss = np.zeros((g, k)), 0.0
    for chunk in frame.iter_slices(chunk_size):
        x = design(chunk, means, deviations, months)
        error = chunk["residual_celsius"].to_numpy() - x @ beta
        rss += error @ error
        np.add.at(scores, np.searchsorted(groups, chunk["SOUID"].to_numpy()), x * error[:, None])
    covariance = (g / (g - 1)) * ((n - 1) / (n - k)) * inverse @ (scores.T @ scores) @ inverse
    se = np.sqrt(np.diag(covariance))
    critical = stats.t.ppf(0.975, g - 1)
    coefficients = pl.DataFrame(
        {
            "term": names,
            "coefficient": beta,
            "cluster_se": se,
            "ci_low": beta - critical * se,
            "ci_high": beta + critical * se,
            "t_statistic": beta / se,
            "p_value": 2 * stats.t.sf(np.abs(beta / se), g - 1),
        }
    )
    summary = {
        "observations": n,
        "sources": g,
        "parameters": k,
        "r_squared": 1 - rss / ((n - 1) * frame["residual_celsius"].var()),
        "feature_means": means,
        "feature_sd": deviations,
        "reference_month": levels[0],
    }
    return coefficients, summary, covariance


def run():
    data = common.load_sample(weather=True)
    frame = data.filter(pl.col("tp") >= 0).with_columns(
        pl.col("tp").clip(lower_bound=1e-9).log10().alias("log10_tp")
    )
    frame = frame.filter(
        pl.all_horizontal(pl.col(name).is_finite() for name in CONTINUOUS)
        & pl.col("degurba").is_not_null()
        & (pl.col("degurba") != 10)
    )
    coefficients, summary, covariance = fit_clustered(frame)
    summary["excluded_missing_covariates_or_water"] = data.height - frame.height
    common.setup_plotting(whiskers=True)
    fig, ax = plt.subplots(figsize=(7.5, 4), layout="constrained")
    display = coefficients.filter(
        ~pl.col("term").str.starts_with("month_") & (pl.col("term") != "intercept")
    )
    x = display["coefficient"].to_numpy()
    ax.errorbar(
        x,
        np.arange(display.height),
        xerr=np.array([x - display["ci_low"].to_numpy(), display["ci_high"].to_numpy() - x]),
        fmt="o",
        color=common.COLORS[0],
        capsize=3,
    )
    ax.set_yticks(np.arange(display.height), display["term"].to_list())
    ax.set_xlabel("Adjusted coefficient (°C), 95% source-clustered interval")
    ax.grid(True)
    common.save_plot(fig, "multivariate", "adjusted_coefficients", whiskers=True)
    covariance_table = pl.DataFrame(covariance, schema=coefficients["term"].to_list()).with_columns(
        coefficients["term"].alias("term")
    )
    common.finish(
        "multivariate",
        data,
        {"coefficients": coefficients, "covariance": covariance_table},
        summary,
        "Complete-case OLS: standardized temperature midpoint, wind, coastal distance, elevation, log10 precipitation, NDVI; standardized midpoint×wind interaction; urban indicator for classes 22/23/30; calendar-month indicators. SOUID-clustered sandwich CR1 covariance, t intervals with G−1 degrees of freedom. The midpoint contains the station outcome, so this is descriptive adjustment and is not a feasible prediction model.",
        weather=True,
    )


if __name__ == "__main__":
    run()
