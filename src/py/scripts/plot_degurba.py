"""Plot DEGURBA residual means for the current station-window-matched sample."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
import seaborn as sns
from matplotlib.ticker import FormatStrFormatter, MultipleLocator

from py import pdp
from py.covariates import sample_raster
from py.load_data import load_data
from py.paths import ANALYSIS_DATA_DIRECTORY as DATA_DIRECTORY
from py.paths import ANALYSIS_FIGURES_DIRECTORY as FIGURES_DIRECTORY
from py.paths import PROJECT_ROOT
from py.preprocessing.match_era5_grid import sha256
from py.publication import save_figure as save_altair_figure
from py.scripts.plot_style import paper_style, save_figure

DEGURBA_LABELS = {
    10: "Water",
    11: "Very low density rural",
    12: "Low density rural",
    13: "Rural cluster",
    21: "Suburban",
    22: "Semi-dense urban cluster",
    23: "Dense urban cluster",
    30: "Urban centre",
}
LAND_CLASSES = list(DEGURBA_LABELS.values())[1:]
PAPER_SPEC = PROJECT_ROOT / "paper/tables/degurba.vl.json"
SOURCE_KEYS = ["SOUID", "source_lat", "source_lon"]
RASTER_FILE = (
    DATA_DIRECTORY
    / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0"
    / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
)


def summarize(data, bootstrap, seed):
    sources = data.select(SOURCE_KEYS).unique().sort(SOURCE_KEYS)
    values = sample_raster(RASTER_FILE, sources.rename({"source_lat": "lat", "source_lon": "lon"}))
    values = np.where(np.isin(values, list(DEGURBA_LABELS)), values, np.nan)
    sources = sources.with_columns(
        pl.Series("degurba", values).fill_nan(None).cast(pl.Int32)
    ).with_columns(
        pl.col("degurba").replace_strict(DEGURBA_LABELS, default=None).alias("degurba_label")
    )
    frame = data.join(sources, on=SOURCE_KEYS, how="left", validate="m:1")
    coverage = (
        frame.group_by("degurba", "degurba_label")
        .agg(pl.len().alias("observations"), pl.col("SOUID").n_unique().alias("sources"))
        .with_columns((pl.col("observations") / frame.height).alias("observation_share"))
        .sort("degurba")
    )
    land = frame.filter(pl.col("degurba_label").is_in(LAND_CLASSES)).select(
        pl.col("SOUID").alias("STAID"),
        pl.col("residual_celsius").alias("residual"),
        "degurba_label",
    )
    present = [label for label in LAND_CLASSES if label in land["degurba_label"].unique()]
    mean, low, high = pdp.pdp_cluster_bootstrap(
        land, "degurba_label", present, n_boot=bootstrap, rng=np.random.default_rng(seed)
    )
    summary = (
        pl.DataFrame({"degurba_label": present, "mean": mean, "ci_low": low, "ci_high": high})
        .join(coverage, on="degurba_label", how="left", validate="1:1")
        .sort("degurba")
    )
    return summary, sources, coverage


def draw_altair(summary, output):
    spec = json.loads(PAPER_SPEC.read_text())
    bars = spec["vconcat"][0]["layer"][1]
    shares = spec["vconcat"][1]
    means_name = bars["data"]["name"]
    shares_name = shares["data"]["name"]
    rows = {row["degurba_label"]: row for row in summary.iter_rows(named=True)}
    colors = {row["label"]: row["color"] for row in spec["datasets"][means_name]}
    spec["datasets"][means_name] = [
        {
            **row,
            "mean": rows[row["label"]]["mean"],
            "ci_lo": rows[row["label"]]["ci_low"],
            "ci_hi": rows[row["label"]]["ci_high"],
        }
        for row in spec["datasets"][means_name]
        if row["label"] in rows
    ]
    spec["datasets"][shares_name] = [
        {
            **row,
            "count": rows[row["degurba_label"]]["observations"],
            "share": rows[row["degurba_label"]]["observation_share"],
        }
        for row in spec["datasets"][shares_name]
        if row["degurba_label"] in rows
    ]
    chart = alt.VConcatChart.from_dict(spec)
    dimensions = save_altair_figure(chart, output, formats=("png", "pdf"))
    return {
        "outputs": [str(output.with_suffix(suffix)) for suffix in (".png", ".pdf", ".vl.json")],
        # The paper's shared scale renders alphabetical order, as verified in its PDF.
        "class_order": sorted(colors),
        "spec_declared_class_order": bars["encoding"]["x"]["sort"],
        "colors": colors,
        "presentation": {
            "renderer": "Altair",
            "reference": str(PAPER_SPEC),
            "reference_sha256": sha256(PAPER_SPEC),
            "layout": "Unchanged paper specification; only mean, interval, count and share values replaced",
            "residual_units": "degrees Celsius",
            "share_units": "fraction",
            **dimensions,
        },
    }


def draw_seaborn(summary, output):
    spec = json.loads(PAPER_SPEC.read_text())
    bars = spec["vconcat"][0]["layer"][1]
    shares = spec["vconcat"][1]
    colors = {row["label"]: row["color"] for row in spec["datasets"][bars["data"]["name"]]}
    order = sorted(colors)
    frame = summary.to_pandas().set_index("degurba_label").reindex(order).reset_index()
    paper_style()
    fig, (ax, share_ax) = plt.subplots(
        2,
        1,
        figsize=(8.6, 7.0),
        layout="constrained",
        sharex=True,
        gridspec_kw={"height_ratios": [260, 100]},
    )
    sns.barplot(
        data=frame,
        x="degurba_label",
        y="mean",
        hue="degurba_label",
        order=order,
        hue_order=order,
        palette=colors,
        saturation=1,
        width=0.9,
        dodge=False,
        legend=False,
        errorbar=None,
        linewidth=0,
        alpha=bars["mark"]["opacity"],
        ax=ax,
    )
    positions = np.arange(len(order))
    ax.vlines(positions, frame["ci_low"], frame["ci_high"], color="#23312F", linewidth=0.9)
    for column in ("ci_low", "ci_high"):
        ax.hlines(frame[column], positions - 0.45, positions + 0.45, color="#23312F", linewidth=0.9)
    sns.barplot(
        data=frame,
        x="degurba_label",
        y="observation_share",
        order=order,
        color=shares["mark"]["color"],
        saturation=1,
        width=0.9,
        errorbar=None,
        linewidth=0,
        alpha=shares["mark"]["opacity"],
        ax=share_ax,
    )
    ax.axhline(0, color="#687370", linestyle=":", linewidth=0.8)
    ax.set(
        ylabel="Mean residual (°C)",
        ylim=(
            min(0, np.floor(frame["ci_low"].min() * 2) / 2),
            np.ceil(frame["ci_high"].max() * 2) / 2,
        ),
    )
    ax.yaxis.set_major_locator(MultipleLocator(0.5))
    share_ax.set(ylabel="Obs share", ylim=(0, np.ceil(frame["observation_share"].max() * 10) / 10))
    share_ax.yaxis.set_major_locator(MultipleLocator(0.1))
    for axis in (ax, share_ax):
        axis.grid(axis="y", color="#DDE3E1", linewidth=0.5)
        axis.set_xlabel("DEGURBA class")
        axis.xaxis.label.set_visible(True)
        axis.yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
        axis.set_xlim(-0.5, len(order) - 0.5)
        axis.set_xticks(positions, order, rotation=30, ha="right", rotation_mode="anchor")
        axis.tick_params(axis="x", labelbottom=True)
    paths = save_figure(fig, output)
    plt.close(fig)
    return {
        "outputs": [str(path) for path in paths],
        "class_order": order,
        "colors": colors,
        "presentation": {
            "renderer": "Seaborn / Matplotlib",
            "reference": str(PAPER_SPEC),
            "reference_sha256": sha256(PAPER_SPEC),
            "layout": "Paper category order, colours, opacity, broad bars and interval caps, 260:100 panels and 30-degree labels on both axes",
            "style": "Saved Seaborn typography, regular text with 0.18 pt stroke, thin left/bottom spines and light horizontal grids",
            "residual_units": "degrees Celsius",
            "share_units": "fraction",
            "dpi": 300,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--from-tables", action="store_true")
    parser.add_argument("--renderer", choices=["seaborn", "altair"], default="seaborn")
    args = parser.parse_args()
    plt.switch_backend("Agg")
    output_dir = FIGURES_DIRECTORY / "partial_dependence"
    tables = output_dir / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "degurba_manifest.json"
    render_code = {
        str(path): sha256(path)
        for path in [
            Path(__file__),
            Path(__file__).parents[1] / "publication.py",
            Path(__file__).with_name("plot_style.py"),
        ]
    }
    if args.from_tables:
        summary = pl.read_csv(tables / "degurba.csv")
        manifest = json.loads(manifest_path.read_text())
        manifest.update(
            restyled_utc=datetime.now(timezone.utc).isoformat(), render_code_sha256=render_code
        )
    else:
        data = load_data().select("STAID", "DATE", *SOURCE_KEYS, "residual_celsius")
        if not data["residual_celsius"].is_finite().all():
            raise ValueError("The current clean sample must have finite temperature residuals")
        print(
            f"Loaded {data.height:,} source-days at {data['SOUID'].n_unique():,} sources",
            flush=True,
        )
        summary, sources, coverage = summarize(data, args.bootstrap, args.seed)
        summary.write_csv(tables / "degurba.csv")
        sources.write_csv(tables / "degurba_sources.csv")
        coverage.write_csv(tables / "degurba_coverage.csv")
        manifest = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "input_records": data.height,
            "sources": data["SOUID"].n_unique(),
            "source_locations": sources.height,
            "nominal_stations": data["STAID"].n_unique(),
            "first_date": data["DATE"].min(),
            "last_date": data["DATE"].max(),
            "plotted_observations": summary["observations"].sum(),
            "omitted_observations": data.height - summary["observations"].sum(),
            "statistic": "Observation-weighted mean of station maximum minus the ERA5-Land maximum over the resolved observation window, inclusive of both endpoints",
            "bootstrap_unit": "SOUID: source IDs resampled within each DEGURBA class for pointwise 95% percentile intervals",
            "bootstrap": args.bootstrap,
            "seed": args.seed,
            "classification": "2020 GHS-SMOD raster sampled at actual source coordinates, using the existing raster sampling helper; no interpolation",
            "share_denominator": "All current clean source-days, including water and missing classifications; water and missing classes omitted from both panels",
            "inputs": {
                str(path): sha256(path)
                for path in [DATA_DIRECTORY / "station_era5_clean.parquet", RASTER_FILE]
            },
            "code_sha256": {
                **render_code,
                **{
                    str(path): sha256(path)
                    for path in [
                        Path(__file__).parents[1] / name
                        for name in ("load_data.py", "covariates.py", "pdp.py")
                    ]
                },
            },
        }
    stem = "degurba_seaborn" if args.renderer == "seaborn" else "degurba"
    draw = draw_seaborn if args.renderer == "seaborn" else draw_altair
    manifest.update(draw(summary, output_dir / stem))
    manifest["tables_sha256"] = {path.name: sha256(path) for path in tables.glob("degurba*.csv")}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(summary, flush=True)
    print(f"Saved {output_dir / (stem + '.png')}", flush=True)


if __name__ == "__main__":
    main()
