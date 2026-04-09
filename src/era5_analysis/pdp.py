import numpy as np
import polars as pl


def cluster_bootstrap_ci(
    df: pl.DataFrame,
    bin_col: str,
    bins: list,
    n_boot=1000,
    ci=95,
    rng: np.random.Generator = None,
):
    """Cluster bootstrap at station level: resample STAIDs, compute mean residual per bin."""
    station_bin = df.group_by("STAID", bin_col).agg(
        pl.col("residual").sum().alias("sum"), pl.col("residual").count().alias("count")
    )

    n_bins = len(bins)
    boot_means = np.zeros((n_bins, n_boot))

    for i, b in enumerate(bins):
        sub_df = station_bin.filter(station_bin[bin_col].eq(b))
        arr = np.zeros((sub_df["STAID"].n_unique(), 2))
        arr[:, 0] = sub_df["sum"]
        arr[:, 1] = sub_df["count"]

        ids = rng.choice(
            np.arange(arr.shape[0]), size=(n_boot, arr.shape[0]), replace=True
        )
        samples = arr[ids, :]
        stats = samples.sum(axis=1)
        boot_means[i] = stats[:, 0] / stats[:, 1]

    pct_lo = (100 - ci) / 2
    pct_hi = 100 - pct_lo
    ci_hi = np.percentile(boot_means, pct_hi, axis=1)
    ci_lo = np.percentile(boot_means, pct_lo, axis=1)

    return boot_means, ci_lo, ci_hi


def bin_centers(bins, data_min, data_max):
    centers = []
    for b in bins:
        lo, hi = b.strip("(]").split(", ")
        lo = data_min if lo == "-inf" else float(lo)
        hi = data_max if hi == "inf" else float(hi)
        centers.append((lo + hi) / 2)

    return centers


def bin_features(df: pl.DataFrame, feature: str, n_bins: int = 5):
    df = df.with_columns(pl.col(feature).qcut(n_bins).alias("bin"))
    bins = sorted(
        df["bin"].drop_nulls().unique().to_list(),
        key=lambda b: float(b.strip("(]").split(", ")[0].replace("-inf", "-999999")),
    )

    return df, bins


def pdp_cluster_bootstrap(
    df, bin_col, bins, n_boot=1000, ci=95, rng: np.random.Generator = None
):
    """Bin feature into quantiles, compute mean residual + cluster bootstrap 95% CI."""
    means = df.group_by(bin_col).agg(pl.col("residual").mean())
    means = means.with_columns(pl.col(bin_col).cast(pl.Enum(bins))).sort(bin_col)
    _, ci_lo, ci_hi = cluster_bootstrap_ci(df, bin_col, bins, n_boot, ci, rng)

    return means["residual"].to_numpy(), ci_lo, ci_hi
