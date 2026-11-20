"""Export binned residual profiles for the station-window-matched temperature sample."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
import seaborn as sns

from py import pdp
from py.load_data import load_data
from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.paths import ANALYSIS_FIGURES_DIRECTORY as FIGURES_DIRECTORY
from py.preprocessing.match_era5_grid import sha256
from py.scripts.plot_style import COLORS, paper_style
from py.scripts.scientific_style import save_scientific_figure as save_figure

FEATURES = {
    "station_celsius": ("Station temperature", "Station maximum temperature (°C)", "#D18A32"),
    "tp": ("Precipitation", "Window precipitation total (log₁₀ m)", "#2A9BA8"),
    "wind": ("Wind", "Magnitude of mean wind (m/s)", COLORS[3]),
    "ndvi": ("Vegetation", "NDVI (with carry-forward)", COLORS[0]),
    "dist_to_sea_km": ("Coastal distance", "Distance to sea (km)", COLORS[2]),
    "elevation": ("Elevation", "Source elevation (m)", COLORS[4]),
}


def summarize(data, feature, bins, bootstrap, seed):
    frame = data.select(
        pl.col("SOUID").alias("STAID"),
        pl.col("residual_celsius").alias("residual"),
        feature,
    ).filter(pl.col(feature).is_finite())
    negative_totals = frame.filter(pl.col(feature) < 0).height if feature == "tp" else 0
    if feature in ("wind", "tp"):
        frame = frame.filter(pl.col(feature) >= 0)
    if feature == "tp":
        frame = frame.with_columns(pl.col("tp").clip(lower_bound=1e-9).log10())
    binned, labels = pdp.bin_features(frame, feature, n_bins=bins)
    mean, low, high = pdp.pdp_cluster_bootstrap(
        binned, "bin", labels, n_boot=bootstrap, rng=np.random.default_rng(seed)
    )
    centers = pdp.bin_centers(labels, frame[feature].min(), frame[feature].max())
    counts = (
        binned.group_by("bin")
        .agg(pl.len().alias("observations"), pl.col("STAID").n_unique().alias("sources"))
        .with_columns(pl.col("bin").cast(pl.Enum(labels)))
        .sort("bin")
    )
    curve = pl.DataFrame(
        {
            "bin": labels,
            "x": centers,
            "mean": mean,
            "ci_low": low,
            "ci_high": high,
            "observations": counts["observations"],
            "sources": counts["sources"],
        }
    )
    heights, edges = np.histogram(frame[feature].to_numpy(), bins=50)
    histogram = pl.DataFrame({"left": edges[:-1], "right": edges[1:], "count": heights})
    coverage = {
        "observations": frame.height,
        "sources": frame["STAID"].n_unique(),
        "missing_or_invalid": data.height - frame.height,
    }
    if feature == "tp":
        coverage["negative_totals_excluded"] = negative_totals
    return curve, histogram, coverage


def draw_profile(ax, histogram_ax, curve, histogram, feature):
    title, label, color = FEATURES[feature]
    sns.lineplot(
        data=curve.to_pandas(),
        x="x",
        y="mean",
        ax=ax,
        color=color,
        estimator=None,
        errorbar=None,
        marker="o",
        markerfacecolor="white",
        markeredgecolor=color,
    )
    ax.fill_between(
        curve["x"], curve["ci_low"], curve["ci_high"], color=color, alpha=0.16, linewidth=0
    )
    ax.set(title=title, xlabel="", ylabel="Mean residual (°C)")
    ax.margins(y=0.08)
    ax.tick_params(labelbottom=False)
    histogram_ax.bar(
        histogram["left"],
        histogram["count"] / 1000,
        width=histogram["right"] - histogram["left"],
        align="edge",
        color=color,
        alpha=0.55,
        linewidth=0,
    )
    histogram_ax.set(xlabel=label, ylabel="N (10³)")
    histogram_ax.set_xlim(histogram["left"].min(), histogram["right"].max())
    histogram_ax.locator_params(axis="y", nbins=3)
    ax.set_xlim(histogram_ax.get_xlim())
    for axis in (ax, histogram_ax):
        axis.grid(True, axis="both", which="major", color="#DDE3E1", linewidth=0.5, alpha=0.8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--features",
        nargs="+",
        choices=list(FEATURES),
        default=["station_celsius", "ndvi", "dist_to_sea_km", "elevation"],
    )
    parser.add_argument("--bins", type=int, default=10)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--from-tables", action="store_true", help="Restyle the saved statistics")
    args = parser.parse_args()
    plt.switch_backend("Agg")
    output_dir = FIGURES_DIRECTORY / "partial_dependence"
    tables = output_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    if args.from_tables:
        manifest = json.loads(manifest_path.read_text())
    else:
        data = load_data(include_weather=any(name in args.features for name in ("wind", "tp")))
    paper_style(palette=COLORS)
    profiles, histograms, coverage = {}, {}, {}
    for feature in args.features:
        if args.from_tables:
            curve = pl.read_csv(tables / f"pdp_{feature}.csv")
            histogram = pl.read_csv(tables / f"histogram_{feature}.csv")
            count = manifest["features"][feature]
        else:
            curve, histogram, count = summarize(data, feature, args.bins, args.bootstrap, args.seed)
            curve.write_csv(tables / f"pdp_{feature}.csv")
            histogram.write_csv(tables / f"histogram_{feature}.csv")
        profiles[feature], histograms[feature], coverage[feature] = curve, histogram, count
        fig, axes = plt.subplots(
            2,
            1,
            figsize=(6.5, 4.5),
            layout="constrained",
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True,
        )
        draw_profile(*axes, curve, histogram, feature)
        save_figure(fig, output_dir / f"pdp_{feature}")
        plt.close(fig)
        print(f"Saved {feature}: {count}", flush=True)
    columns = 3 if len(args.features) > 4 else 2
    rows = (len(args.features) + columns - 1) // columns
    fig = plt.figure(figsize=(6.0 * columns, 4.7 * rows), layout="constrained")
    grid = fig.add_gridspec(rows, columns)
    for index, feature in enumerate(args.features):
        inner = grid[index // columns, index % columns].subgridspec(2, 1, height_ratios=[3, 1])
        ax = fig.add_subplot(inner[0])
        histogram_ax = fig.add_subplot(inner[1], sharex=ax)
        draw_profile(ax, histogram_ax, profiles[feature], histograms[feature], feature)
    save_figure(fig, output_dir / "partial_dependence")
    plt.close(fig)
    render_code = {
        str(path): sha256(path)
        for path in [
            Path(__file__),
            Path(__file__).with_name("scientific_style.py"),
            Path(__file__).with_name("plot_style.py"),
        ]
    }
    if args.from_tables:
        manifest["restyled_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["render_code_sha256"] = render_code
        manifest["presentation"] = {
            "style": "Original Seaborn/DejaVu Sans",
            "feature_colours": {name: FEATURES[name][2] for name in args.features},
            "grid": "major horizontal and vertical",
            "y_limits": "Fit curve and confidence band with 8% padding",
            "zero_reference": False,
            "bottom_caption": False,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return
    input_paths = [
        DATA_DIRECTORY / name
        for name in (
            "station_era5_clean.parquet",
            "station_coastal_distance.parquet",
            "station_ndvi.parquet",
            "station_elevation.parquet",
        )
    ]
    if "wind" in args.features or "tp" in args.features:
        input_paths.append(DATA_DIRECTORY / "station_hourly_weather.parquet")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "input_records": data.height,
        "features": coverage,
        "bins": args.bins,
        "bootstrap": args.bootstrap,
        "seed": args.seed,
        "statistic": "Observation-weighted residual means in quantile bins; descriptive associations, not model-based partial dependence or causal effects.",
        "bootstrap_unit": "SOUID: source IDs resampled within each bin for pointwise percentile intervals.",
        "ndvi_policy": "Original seasonal rasters with last available value carried forward across seasons; missing pixels within existing seasons remain missing.",
        "weather_policy": "Wind and precipitation aggregated over each station's UTC observation window from hourly ERA5-Land; wind is the magnitude of the time-mean vector and tp is total precipitation in metres.",
        "precipitation_plot": "Exclude negative window totals from the log profile only; retain them in the saved covariates. Nonnegative totals use log10(max(tp, 1e-9)).",
        "presentation": {
            "style": "Original Seaborn/DejaVu Sans",
            "feature_colours": {name: FEATURES[name][2] for name in args.features},
            "grid": "major horizontal and vertical",
            "y_limits": "Fit curve and confidence band with 8% padding",
            "zero_reference": False,
            "bottom_caption": False,
        },
        "inputs": {str(path): sha256(path) for path in input_paths},
        "code_sha256": {
            str(path): sha256(path)
            for path in [
                Path(__file__),
                Path(__file__).with_name("scientific_style.py"),
                Path(__file__).with_name("plot_style.py"),
                Path(__file__).parents[1] / "load_data.py",
                Path(__file__).parents[1] / "pdp.py",
            ]
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
