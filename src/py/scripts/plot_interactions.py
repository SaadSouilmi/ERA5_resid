"""Export the existing joint-bin residual heatmaps for the current clean sample."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import polars as pl
import seaborn as sns

from py import pdp
from py.load_data import load_data
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import NotebookFiguresDirectory as FIGURES_DIRECTORY
from py.preprocessing.land_cover import CLASSES
from py.preprocessing.match_era5_grid import sha256
from py.scripts.plot_partial_dependence import FEATURES
from py.scripts.plot_style import COLORS, paper_style
from py.scripts.scientific_style import save_scientific_figure as save_figure

PAIRS = {
    "station_celsius_by_wind": ("station_celsius", "wind"),
    "elevation_by_dist_to_sea_km": ("elevation", "dist_to_sea_km"),
    "elevation_by_wind": ("elevation", "wind"),
    "distance_by_degurba": ("dist_to_sea_km", "degurba_label"),
}
LAND_CLASSES = [label for code, label in CLASSES.items() if code != 10]


def bounds(labels, minimum, maximum):
    edges = [tuple(float(value) for value in label.strip("(]").split(", ")) for label in labels]
    return np.array([minimum, *[edge[1] for edge in edges[:-1]], maximum], dtype=float)


def prepare(data, x, y, bins):
    numeric = [x] if y == "degurba_label" else [x, y]
    frame = data.filter(pl.all_horizontal(pl.col(name).is_finite() for name in numeric))
    if y == "degurba_label":
        frame = frame.filter(pl.col(y).is_in(LAND_CLASSES))
    frame, labels_x = pdp.BinFeatures(frame, x, NBins=bins)
    frame = frame.rename({"bin": "bin_x"})
    if y == "degurba_label":
        labels_y = LAND_CLASSES
        frame = frame.with_columns(pl.col(y).alias("bin_y"))
        edges_y = np.arange(len(labels_y) + 1, dtype=float)
    else:
        frame, labels_y = pdp.BinFeatures(frame, y, NBins=bins)
        frame = frame.rename({"bin": "bin_y"})
        edges_y = bounds(labels_y, frame[y].min(), frame[y].max())
    edges_x = bounds(labels_x, frame[x].min(), frame[x].max())
    table = (
        frame.group_by("bin_x", "bin_y")
        .agg(
            pl.col("residual_celsius").mean().alias("mean"),
            pl.len().alias("observations"),
            pl.col("SOUID").n_unique().alias("sources"),
        )
        .with_columns(pl.col("bin_x", "bin_y").cast(pl.String))
    )
    lookup_x, lookup_y = (
        {key: i for i, key in enumerate(labels_x)},
        {key: i for i, key in enumerate(labels_y)},
    )
    matrix = np.full((len(labels_y), len(labels_x)), np.nan)
    rows = []
    for row in table.iter_rows(named=True):
        i, j = lookup_x[row["bin_x"]], lookup_y[row["bin_y"]]
        matrix[j, i] = row["mean"]
        rows.append(
            {
                **row,
                "x_low": edges_x[i],
                "x_high": edges_x[i + 1],
                "y_low": edges_y[j],
                "y_high": edges_y[j + 1],
            }
        )
    count_x, hist_x = np.histogram(frame[x].to_numpy(), bins=40)
    if y == "degurba_label":
        counts = dict(frame.group_by(y).len().iter_rows())
        count_y, hist_y = np.array([counts.get(label, 0) for label in labels_y]), edges_y
    else:
        count_y, hist_y = np.histogram(frame[y].to_numpy(), bins=40)
    return {
        "table": pl.DataFrame(rows).sort("x_low", "y_low"),
        "matrix": matrix,
        "edges_x": edges_x,
        "edges_y": edges_y,
        "hist_x": hist_x,
        "count_x": count_x,
        "hist_y": hist_y,
        "count_y": count_y,
        "labels_y": labels_y,
        "observations": frame.height,
        "sources": frame["SOUID"].n_unique(),
    }


def draw(fig, specification, profile, x, y):
    grid = specification.subgridspec(
        2, 2, width_ratios=[5, 1], height_ratios=[1, 4], wspace=0.04, hspace=0.04
    )
    ax = fig.add_subplot(grid[1, 0])
    top = fig.add_subplot(grid[0, 0], sharex=ax)
    side = fig.add_subplot(grid[1, 1], sharey=ax)
    color = sns.blend_palette([COLORS[2], "#FFFFFF", COLORS[1]], as_cmap=True)
    extent = max(float(np.nanmax(np.abs(profile["matrix"]))), 1e-12)
    mesh = ax.pcolormesh(
        profile["edges_x"],
        profile["edges_y"],
        profile["matrix"],
        cmap=color,
        norm=TwoSlopeNorm(vmin=-extent, vcenter=0, vmax=extent),
        shading="flat",
    )
    fig.colorbar(mesh, ax=side, label="Mean residual (°C)", fraction=0.35, pad=0.15)
    ax.set(
        xlabel=FEATURES[x][1], ylabel="DEGURBA class" if y == "degurba_label" else FEATURES[y][1]
    )
    top.bar(
        profile["hist_x"][:-1],
        profile["count_x"] / 1000,
        width=np.diff(profile["hist_x"]),
        align="edge",
        color=FEATURES[x][2],
        alpha=0.55,
    )
    side.barh(
        profile["hist_y"][:-1],
        profile["count_y"] / 1000,
        height=np.diff(profile["hist_y"]),
        align="edge",
        color=COLORS[5] if y == "degurba_label" else FEATURES[y][2],
        alpha=0.55,
    )
    top.set_ylabel("N (10³)")
    side.set_xlabel("N (10³)")
    top.tick_params(labelbottom=False)
    side.tick_params(labelleft=False)
    top.locator_params(axis="y", nbins=3)
    side.locator_params(axis="x", nbins=2)
    if y == "degurba_label":
        ax.set_yticks(np.arange(len(LAND_CLASSES)) + 0.5, labels=LAND_CLASSES)
    for axis in [ax, top, side]:
        axis.grid(True)
    ax.set_xlim(profile["edges_x"][[0, -1]])
    ax.set_ylim(profile["edges_y"][[0, -1]])
    title_y = "Urbanisation" if y == "degurba_label" else FEATURES[y][0]
    top.set_title(f"{FEATURES[x][0]} × {title_y.lower()}")


def from_tables(directory, name, coverage):
    table = pl.read_csv(directory / f"{name}.csv")
    edges_x = np.r_[table["x_low"].unique().sort(), table["x_high"].max()]
    edges_y = (
        np.arange(len(LAND_CLASSES) + 1, dtype=float)
        if PAIRS[name][1] == "degurba_label"
        else np.r_[table["y_low"].unique().sort(), table["y_high"].max()]
    )
    matrix = np.full((len(edges_y) - 1, len(edges_x) - 1), np.nan)
    matrix[np.searchsorted(edges_y, table["y_low"]), np.searchsorted(edges_x, table["x_low"])] = (
        table["mean"]
    )
    profile = dict(table=table, matrix=matrix, edges_x=edges_x, edges_y=edges_y, **coverage)
    for axis in ["x", "y"]:
        histogram = pl.read_csv(directory / f"{name}_hist_{axis}.csv")
        profile[f"hist_{axis}"] = np.r_[histogram["low"], histogram["high"][-1]]
        profile[f"count_{axis}"] = histogram["count"].to_numpy()
    return profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", nargs="+", choices=list(PAIRS), default=list(PAIRS))
    parser.add_argument("--bins", type=int, default=8)
    parser.add_argument("--from-tables", action="store_true")
    args = parser.parse_args()
    plt.switch_backend("Agg")
    include_weather = any("wind" in PAIRS[name] for name in args.pairs)
    directory = FIGURES_DIRECTORY / "interactions"
    tables = directory / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    if args.from_tables:
        manifest = json.loads(manifest_path.read_text())
    else:
        data = load_data(include_weather=include_weather)
    paper_style(palette=COLORS)
    profiles = {}
    for name in args.pairs:
        x, y = PAIRS[name]
        if args.from_tables:
            profile = from_tables(tables, name, manifest["pairs"][name])
        else:
            profile = prepare(data, x, y, args.bins)
            profile["table"].write_csv(tables / f"{name}.csv")
            for axis in ["x", "y"]:
                pl.DataFrame(
                    {
                        "low": profile[f"hist_{axis}"][:-1],
                        "high": profile[f"hist_{axis}"][1:],
                        "count": profile[f"count_{axis}"],
                    }
                ).write_csv(tables / f"{name}_hist_{axis}.csv")
        profiles[name] = profile
        fig = plt.figure(figsize=(8.5, 5.4), layout="constrained")
        draw(fig, fig.add_gridspec(1, 1)[0], profile, x, y)
        save_figure(fig, directory / name)
        plt.close(fig)
        print(f"Saved {name}: {profile['observations']:,} observations", flush=True)
    columns = min(2, len(args.pairs))
    rows = (len(args.pairs) + columns - 1) // columns
    fig = plt.figure(figsize=(9 * columns, 5.8 * rows), layout="constrained")
    grid = fig.add_gridspec(rows, columns)
    for index, name in enumerate(args.pairs):
        draw(fig, grid[index // columns, index % columns], profiles[name], *PAIRS[name])
    save_figure(fig, directory / "interactions")
    plt.close(fig)
    if args.from_tables:
        manifest["restyled_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["render_code_sha256"] = {
            str(path): sha256(path)
            for path in [
                Path(__file__),
                Path(__file__).with_name("scientific_style.py"),
                Path(__file__).with_name("plot_style.py"),
            ]
        }
        manifest["presentation"] = {"style": "Original Seaborn/DejaVu Sans", "grid": "major"}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        return
    files = [
        DATA_DIRECTORY / name
        for name in [
            "station_era5_clean.parquet",
            "station_coastal_distance.parquet",
            "station_land_cover.parquet",
        ]
    ]
    if any("elevation" in PAIRS[name] for name in args.pairs):
        files.append(DATA_DIRECTORY / "station_elevation.parquet")
    if include_weather:
        files.append(DATA_DIRECTORY / "station_hourly_weather.parquet")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "statistic": "Observation-weighted joint-bin residual means; descriptive associations.",
        "bins_per_numeric_axis": args.bins,
        "pairs": {
            name: {"observations": profile["observations"], "sources": profile["sources"]}
            for name, profile in profiles.items()
        },
        "inputs": {str(path): sha256(path) for path in files},
        "code_sha256": {
            str(path): sha256(path)
            for path in [
                Path(__file__),
                Path(__file__).with_name("scientific_style.py"),
                Path(__file__).with_name("plot_style.py"),
                Path(__file__).parents[1] / "load_data.py",
            ]
        },
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
