"""Shared input, source-cluster inference and exports for the numerical analyses."""

import json
from datetime import datetime, time, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from scipy import stats

from py.load_data import load_data
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import ANALYSIS_FIGURES_DIRECTORY, ProjectRoot
from py.preprocessing.match_era5_grid import sha256
from py.scripts.plot_style import COLORS as COLORS, paper_style, save_figure
from py.scripts.scientific_style import (
    save_scientific_figure,
    scientific_style,
    top_legend,
    zero_line as zero_line,
)

OUTPUT_DIRECTORY = ANALYSIS_FIGURES_DIRECTORY / "numerical_analysis"
FEATURES = ["station_celsius", "wind", "tp", "ndvi", "dist_to_sea_km", "elevation"]
LABELS = {
    "station_celsius": "Station maximum temperature (°C)",
    "era5_celsius": "ERA5-Land window maximum (°C)",
    "midpoint": "Temperature midpoint (°C)",
    "wind": "Magnitude of mean wind (m/s)",
    "tp": "Window precipitation (log₁₀ m)",
    "ndvi": "NDVI",
    "dist_to_sea_km": "Distance to sea (km)",
    "elevation": "Source elevation (m)",
    "relative_elevation_25km": "Elevation relative to neighbouring sources (m)",
}


def load_sample(weather=False):
    return (
        load_data(include_weather=weather)
        .with_columns(
            pl.col("DATE").cast(pl.String).str.to_date("%Y%m%d").alias("date"),
            pl.col("era5_tmax_celsius").alias("era5_celsius"),
            (
                (pl.col("window_hours") == 24)
                & (pl.col("window_start_utc").dt.time() == time(0))
                & (pl.col("window_end_utc").dt.time() == time(0))
            ).alias("utc_day_aligned"),
        )
        .with_columns(
            pl.col("date").dt.month().alias("month"),
            (0.5 * (pl.col("station_celsius") + pl.col("era5_celsius"))).alias("midpoint"),
        )
    )


def feature_rows(data, feature):
    frame = data.filter(pl.col(feature).is_finite())
    if feature == "tp":
        frame = frame.filter(pl.col(feature) >= 0).with_columns(
            pl.col(feature).clip(lower_bound=1e-9).log10()
        )
    return frame


def bootstrap_ratio_draws(numerator, denominator, bootstrap=1000, seed=1337, rng=None):
    numerator, denominator = np.asarray(numerator, float), np.asarray(denominator, float)
    rng = np.random.default_rng(seed) if rng is None else rng
    draws = np.full(bootstrap, np.nan)
    for first in range(0, bootstrap, 100):
        indices = rng.integers(
            0, len(numerator), size=(min(100, bootstrap - first), len(numerator))
        )
        top, bottom = numerator[indices].sum(axis=1), denominator[indices].sum(axis=1)
        values = np.divide(top, bottom, out=np.full(len(top), np.nan), where=bottom != 0)
        values[(bottom == 0) & (top > 0)] = np.inf
        draws[first : first + len(values)] = values
    return draws


def bootstrap_ratio(numerator, denominator, bootstrap=1000, seed=1337, rng=None):
    numerator, denominator = np.asarray(numerator, float), np.asarray(denominator, float)
    draws = bootstrap_ratio_draws(numerator, denominator, bootstrap, seed, rng)
    defined = draws[~np.isnan(draws)]
    method = "inverted_cdf" if np.isinf(defined).any() else "linear"
    low, high = (
        np.quantile(defined, [0.025, 0.975], method=method) if len(defined) else (np.nan, np.nan)
    )
    return {
        "estimate": float(numerator.sum() / denominator.sum()) if denominator.sum() else None,
        "ci_low": float(low) if np.isfinite(low) else None,
        "ci_high": float(high) if np.isfinite(high) else None,
        "upper_unbounded": bool(np.isposinf(high)),
        "undefined_bootstrap_draws": int(np.isnan(draws).sum()),
    }


def mean_summary(frame, residual="residual_celsius", bootstrap=1000, seed=1337):
    grouped = (
        frame.group_by("SOUID")
        .agg(
            pl.col(residual).sum().alias("total"),
            pl.len().alias("count"),
            pl.col(residual).mean().alias("source_mean"),
        )
        .sort("SOUID")
    )
    interval = bootstrap_ratio(grouped["total"], grouped["count"], bootstrap, seed)
    return {
        "observations": frame.height,
        "sources": grouped.height,
        "mean": interval["estimate"],
        "ci_low": interval["ci_low"],
        "ci_high": interval["ci_high"],
        "sd": frame[residual].std(),
        "source_weighted_mean": grouped["source_mean"].mean(),
        "positive_source_percent": 100 * (grouped["source_mean"] > 0).mean(),
    }


def profile(data, feature, residual="residual_celsius", bins=10, bootstrap=1000, seed=1337):
    frame = feature_rows(data, feature).with_columns(
        pl.col(feature).qcut(bins, allow_duplicates=True).cast(pl.String).alias("bin")
    )
    rows = []
    rng = np.random.default_rng(seed)
    parts = sorted(frame.partition_by("bin"), key=lambda part: part[feature].min())
    for part in parts:
        grouped = (
            part.group_by("SOUID")
            .agg(pl.col(residual).sum().alias("total"), pl.len().alias("count"))
            .sort("SOUID")
        )
        interval = bootstrap_ratio(grouped["total"], grouped["count"], bootstrap, rng=rng)
        rows.append(
            {
                "bin": part["bin"][0],
                "x": part[feature].mean(),
                "x_low": part[feature].min(),
                "x_high": part[feature].max(),
                "mean": interval["estimate"],
                "ci_low": interval["ci_low"],
                "ci_high": interval["ci_high"],
                "observations": part.height,
                "sources": grouped.height,
            }
        )
    return pl.DataFrame(rows).sort("x")


def omnibus_test(data, feature, bins=10):
    frame = feature_rows(data, feature).with_columns(
        pl.col(feature).qcut(bins, allow_duplicates=True).cast(pl.String).alias("bin")
    )
    grouped = frame.group_by("SOUID", "bin").agg(
        pl.col("residual_celsius").sum().alias("total"), pl.len().alias("count")
    )
    sources = grouped["SOUID"].unique().sort().to_numpy()
    categories = sorted(grouped["bin"].unique().to_list())
    g, k, n = len(sources), len(categories), frame.height
    source_index = np.searchsorted(sources, grouped["SOUID"].to_numpy())
    indices = {name: index for index, name in enumerate(categories)}
    bin_index = np.array([indices[name] for name in grouped["bin"]])
    totals, counts = np.zeros((g, k)), np.zeros((g, k))
    np.add.at(totals, (source_index, bin_index), grouped["total"].to_numpy())
    np.add.at(counts, (source_index, bin_index), grouped["count"].to_numpy())
    size = counts.sum(axis=0)
    means = totals.sum(axis=0) / size
    scores = totals - counts * means
    covariance = (g / (g - 1)) * ((n - 1) / (n - k)) * ((scores.T @ scores) / np.outer(size, size))
    contrast = np.column_stack([-np.ones(k - 1), np.eye(k - 1)])
    difference = contrast @ means
    variance = contrast @ covariance @ contrast.T
    rank = np.linalg.matrix_rank(variance)
    statistic = float(difference @ np.linalg.pinv(variance) @ difference / rank) if rank else None
    return {
        "feature": feature,
        "observations": n,
        "sources": g,
        "bins": k,
        "df_numerator": rank,
        "df_denominator": g - 1,
        "wald_f": statistic,
        "p_value": float(stats.f.sf(statistic, rank, g - 1)) if rank else None,
        "range_celsius": float(np.ptp(means)),
    }


def clean_json(value):
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def finish(name, data, tables, summary, method, weather=False, extra_inputs=()):
    directory = OUTPUT_DIRECTORY / name
    table_directory = directory / "tables"
    table_directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for label, table in tables.items():
        path = table_directory / f"{label}.csv"
        table.write_csv(path)
        files[label] = {"file": str(path), "sha256": sha256(path)}
    result = {
        "analysis": name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_observations": data.height,
        "parent_sources": data["SOUID"].n_unique(),
        "summary": summary,
        "method": method,
        "tables": files,
    }
    result_path = directory / "results.json"
    result_path.write_text(json.dumps(clean_json(result), indent=2, allow_nan=False) + "\n")
    inputs = [
        "station_era5_clean",
        "station_ndvi",
        "station_elevation",
        "station_coastal_distance",
        "station_land_cover",
    ]
    if weather:
        inputs.append("station_hourly_weather")
    manifest = {
        "analysis": name,
        "bootstrap_unit": "SOUID (actual observation source)",
        "hourly_weather_included": weather,
        "origin": "ERA5_resid_v3_code.zip: pending_remarks_analysis.py and supplemental_v3_checks.py",
        "inputs": {
            **{
                str(DATA_DIRECTORY / f"{label}.parquet"): sha256(
                    DATA_DIRECTORY / f"{label}.parquet"
                )
                for label in inputs
            },
            **{str(path): sha256(path) for path in extra_inputs},
        },
        "code_sha256": {
            str(path): sha256(path)
            for path in [
                Path(__file__),
                Path(__file__).with_name(f"analysis_{name}.py"),
                Path(__file__).with_name("load_data.py"),
                ProjectRoot / "src/py/scripts/scientific_style.py",
                ProjectRoot / "src/py/scripts/plot_style.py",
            ]
        },
        "results_sha256": sha256(result_path),
        "tables": files,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved {name}: {directory}", flush=True)


def save_plot(fig, name, filename, whiskers=False):
    output = OUTPUT_DIRECTORY / name / filename
    if whiskers:
        top_legend(fig)
        save_scientific_figure(fig, output)
    else:
        save_figure(fig, output)
        if output.with_suffix(".svg").exists():
            fig.savefig(output.with_suffix(".svg"))
    plt.close(fig)


def setup_plotting(whiskers=False):
    plt.switch_backend("Agg")
    if whiskers:
        scientific_style()
    else:
        paper_style(palette=COLORS)


def draw_profile(ax, table, label, color):
    ax.plot(table["x"], table["mean"], "o-", label=label, color=color, markerfacecolor="white")
    ax.fill_between(
        table["x"], table["ci_low"], table["ci_high"], color=color, alpha=0.15, linewidth=0
    )
    ax.grid(True, axis="both")
    ax.margins(y=0.08)
