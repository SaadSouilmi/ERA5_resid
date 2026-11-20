import numpy as np
import polars as pl


def cluster_bootstrap_ci(
    frame: pl.DataFrame,
    bin_column: str,
    bins: list,
    n_boot=1000,
    ci=95,
    rng: np.random.Generator = None,
    weight_column: str = None,
):
    """Cluster bootstrap at station level: resample STAIDs, compute (weighted) mean residual per bin."""
    if weight_column is None:
        station_bin = frame.group_by("STAID", bin_column).agg(
            pl.col("residual").sum().alias("sum"), pl.col("residual").count().alias("count")
        )
    else:
        station_bin = frame.group_by("STAID", bin_column).agg(
            (pl.col("residual") * pl.col(weight_column)).sum().alias("sum"),
            pl.col(weight_column).sum().alias("count"),
        )

    station_bin = station_bin.sort(bin_column, "STAID")
    n_bins = len(bins)
    boot_means = np.zeros((n_bins, n_boot))

    for index, bin_label in enumerate(bins):
        sub_frame = station_bin.filter(station_bin[bin_column].eq(bin_label))
        values = np.zeros((sub_frame["STAID"].n_unique(), 2))
        values[:, 0] = sub_frame["sum"]
        values[:, 1] = sub_frame["count"]

        indices = rng.choice(
            np.arange(values.shape[0]), size=(n_boot, values.shape[0]), replace=True
        )
        samples = values[indices, :]
        totals = samples.sum(axis=1)
        boot_means[index] = totals[:, 0] / totals[:, 1]

    lower_percentile = (100 - ci) / 2
    upper_percentile = 100 - lower_percentile
    ci_high = np.percentile(boot_means, upper_percentile, axis=1)
    ci_low = np.percentile(boot_means, lower_percentile, axis=1)

    return boot_means, ci_low, ci_high


def bin_centers(bins, data_min, data_max):
    centers = []
    for bin_label in bins:
        low, high = bin_label.strip("(]").split(", ")
        low = data_min if low == "-inf" else float(low)
        high = data_max if high == "inf" else float(high)
        centers.append((low + high) / 2)

    return centers


def bin_features(frame: pl.DataFrame, feature: str, n_bins: int = 5):
    frame = frame.filter(pl.col(feature).is_finite())
    frame = frame.with_columns(pl.col(feature).qcut(n_bins, allow_duplicates=True).alias("bin"))
    bins = sorted(
        frame["bin"].drop_nulls().unique().to_list(),
        key=lambda bin_label: float(
            bin_label.strip("(]").split(", ")[0].replace("-inf", "-999999")
        ),
    )

    return frame, bins


def pdp_cluster_bootstrap(
    frame,
    bin_column,
    bins,
    n_boot=1000,
    ci=95,
    rng: np.random.Generator = None,
    weight_column: str = None,
):
    """Bin feature into quantiles, compute (weighted) mean residual + cluster bootstrap 95% CI."""
    if weight_column is None:
        means = frame.group_by(bin_column).agg(pl.col("residual").mean())
    else:
        means = frame.group_by(bin_column).agg(
            (
                (pl.col("residual") * pl.col(weight_column)).sum() / pl.col(weight_column).sum()
            ).alias("residual")
        )
    means = means.with_columns(pl.col(bin_column).cast(pl.Enum(bins))).sort(bin_column)
    _, ci_low, ci_high = cluster_bootstrap_ci(
        frame, bin_column, bins, n_boot, ci, rng, weight_column=weight_column
    )

    return means["residual"].to_numpy(), ci_low, ci_high
