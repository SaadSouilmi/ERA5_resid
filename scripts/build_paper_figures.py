"""Build Altair publication figures; use --from-tables to restyle saved results."""

import argparse
import json
from pathlib import Path

import numpy as np
import polars as pl
from pypdf import PdfWriter

from era5_analysis import paper_charts, pdp
from era5_analysis.paper_charts import DEGURBA, FEATURES, MAP_EXTENT, PAIRS
from era5_analysis.publication import paper_style, save_figure

ROOT = Path(__file__).resolve().parents[1]
MISSING_ELEVATION = (-9999, -999)


def bin_feature(df, feature, n_bins):
    frame = df.with_columns(
        pl.col(feature).qcut(n_bins, allow_duplicates=True).alias("bin")
    )
    bins = sorted(frame["bin"].unique().to_list(), key=lambda b: bounds(b)[0])
    return frame, bins


def bounds(label):
    return tuple(float(v) for v in label.strip("(]").split(", "))


def summarize(df, column, bins, n_boot, seed):
    """Observation means and pointwise station-cluster percentile intervals."""
    aggregates = df.group_by(column, "STAID").agg(
        pl.col("residual").sum().alias("total"), pl.len().alias("n")
    ).sort(column, "STAID")
    rng = np.random.default_rng(seed)
    rows = []
    for label in bins:
        group = aggregates.filter(pl.col(column) == label)
        totals, counts = group["total"].to_numpy(), group["n"].to_numpy()
        n = len(group)
        if not n:
            continue
        boot = np.empty(n_boot)
        for start in range(0, n_boot, 64):
            indices = rng.integers(n, size=(min(64, n_boot - start), n))
            boot[start:start + len(indices)] = (
                totals[indices].sum(axis=1) / counts[indices].sum(axis=1)
            )
        lo, hi = np.percentile(boot, [2.5, 97.5])
        rows.append({
            "bin": str(label), "mean": totals.sum() / counts.sum(),
            "ci_low": lo, "ci_high": hi,
            "n_observations": int(counts.sum()), "n_stations": n,
        })
    return pl.DataFrame(rows)


def feature_frame(df, features):
    frame = df.filter(pl.all_horizontal(pl.col(f).is_finite() for f in features))
    if "elevation" in features:
        frame = frame.filter(~pl.col("elevation").is_in(MISSING_ELEVATION))
    return frame


def add_bounds(summary, frame, fx, fy):
    columns = []
    for axis, feature in [("x", fx), ("y", fy)]:
        lo, hi = float(frame[feature].min()), float(frame[feature].max())
        intervals = [bounds(b) for b in summary[f"bin_{axis}"]]
        columns.extend([
            pl.Series(f"{axis}_lo", [max(lo, b[0]) for b in intervals]),
            pl.Series(f"{axis}_hi", [min(hi, b[1]) for b in intervals]),
        ])
    return summary.with_columns(columns)


def prepare_tables(df, args, tables):
    for i, feature in enumerate(FEATURES):
        print(f"  Computing {feature}...", flush=True)
        frame = feature_frame(df, [feature])
        if feature == "tp":
            frame = frame.with_columns(pl.col(feature).clip(1e-9).log10())
        frame, bins = bin_feature(frame, feature, args.bins)
        summary = summarize(frame, "bin", bins, args.bootstrap, args.seed + i)
        centers = pdp.bin_centers(bins, frame[feature].min(), frame[feature].max())
        summary.with_columns(pl.Series("x", centers)).write_csv(tables / f"covariate_{feature}.csv")
    summary = summarize(df, "degurba_label", DEGURBA, args.bootstrap, args.seed)
    order = [label for label in DEGURBA if label in summary["bin"].to_list()]
    summary.with_columns(pl.col("bin").cast(pl.Enum(order))).sort("bin").write_csv(
        tables / "urbanization.csv"
    )
    for fx, fy in PAIRS:
        frame = feature_frame(df, [fx, fy])
        frame, _ = bin_feature(frame, fx, args.bins)
        frame = frame.rename({"bin": "bin_x"})
        frame, _ = bin_feature(frame, fy, args.bins)
        summary = frame.group_by("bin_x", "bin").agg(
            pl.col("residual").mean(), pl.len().alias("n_observations"),
            pl.col("STAID").n_unique().alias("n_stations"),
        ).rename({"bin": "bin_y"})
        add_bounds(summary, frame, fx, fy).sort("bin_x", "bin_y").write_csv(
            tables / f"{fx}_by_{fy}.csv"
        )
    df.group_by("STAID").agg(
        pl.col("residual").mean(), pl.col("lat").first(), pl.col("lon").first(),
        pl.len().alias("n_observations"),
    ).sort("STAID").write_csv(tables / "station_means.csv")


def upgrade_bounds(tables, source):
    """Enrich older saved tables with finite heatmap edges, without re-estimating."""
    for fx, fy in PAIRS:
        path = tables / f"{fx}_by_{fy}.csv"
        summary = pl.read_csv(path)
        if "x_lo" not in summary.columns:
            print(f"  Adding numeric bounds to {path.name} from the original input...", flush=True)
            frame = feature_frame(pl.scan_parquet(source).drop_nulls(), [fx, fy])
            extrema = frame.select(
                pl.col(fx).min().alias("x_min"), pl.col(fx).max().alias("x_max"),
                pl.col(fy).min().alias("y_min"), pl.col(fy).max().alias("y_max"),
            ).collect().row(0)
            limits = pl.DataFrame({fx: extrema[:2], fy: extrema[2:]})
            add_bounds(summary, limits, fx, fy).write_csv(path)


def captions(metadata):
    return [
        "All figures: residual = station minus ERA5 (°C); positive values mean ERA5 is cooler. "
        f"Complete cases from resid_analysis.py: {metadata['complete_rows']:,} observations, "
        f"{metadata['stations']:,} stations; {metadata['date_start'][:10]} to "
        f"{metadata['date_end'][:10]}. Means weight observations equally. "
        f"Intervals are pointwise 95% percentile intervals from {metadata['bootstrap']:,} station "
        "bootstrap resamples within each bin, retaining all observations from sampled stations. "
        "They do not account for dependence between different stations.",
        "01_covariates: Binned mean residuals, with quantile bins and shaded confidence intervals. "
        "Points use bin midpoints, bounded by observed extrema; connecting lines guide the eye. "
        "These are descriptive conditional means, not model-based partial dependence. "
        "Precipitation uses log10(max(tp, 1e-9)) in metres. Elevation excludes −9999 "
        "(the documented missing-value code) and treats −999 as missing too "
        f"({metadata['elevation_missing_rows']:,} observations in total). "
        "Duplicate quantile boundaries are merged.",
        "02_urbanization: Observation-weighted mean residuals and station-bootstrap confidence "
        "intervals by land urbanization class. Water is excluded. Numbers give distinct stations.",
        "03_interactions: Mean residuals in joint quantile bins, drawn at their numeric boundaries. "
        "Both panels share a symmetric colour scale centred on zero. "
        f"Grey cells have fewer than {metadata['heatmap_min_stations']} stations or no data. "
        "Elevation excludes −9999 and −999. The panels describe associations, not causal interactions.",
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "data2/residuals.parquet")
    parser.add_argument("--output", type=Path, default=ROOT / "figures/paper")
    parser.add_argument("--from-tables", action="store_true", help="Render saved tables without rerunning statistics.")
    parser.add_argument("--bootstrap", type=int)
    parser.add_argument("--bins", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dpi", type=int, default=600)
    parser.add_argument("--width-mm", type=float, default=180)
    parser.add_argument("--min-stations", type=int)
    parser.add_argument("--skip-map", action="store_true")
    args = parser.parse_args()
    if args.from_tables and any(v is not None for v in [args.bootstrap, args.bins, args.seed]):
        parser.error("--from-tables uses the saved bootstrap, bin and seed settings.")
    args.bootstrap = 1000 if args.bootstrap is None else args.bootstrap
    args.bins = 10 if args.bins is None else args.bins
    args.seed = 1337 if args.seed is None else args.seed
    if min(args.bootstrap, args.bins, args.dpi, args.width_mm) <= 0 or args.seed < 0:
        parser.error("Counts and width must be positive; seed must be nonnegative.")
    args.output = args.output.resolve()
    tables = args.output / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    if args.from_tables:
        metadata = json.loads((args.output / "metadata.json").read_text())
        upgrade_bounds(tables, Path(metadata["data"]))
    else:
        print("Loading complete cases, matching notebooks/resid_analysis.py...", flush=True)
        raw = pl.read_parquet(args.data)
        df = raw.drop_nulls()
        if not len(df) or df.filter(~pl.col("residual").is_finite()).height:
            raise ValueError("Expected nonempty data with finite residuals.")
        if not np.allclose(df["residual"], df["station_celsius"] - df["era5_celsius"]):
            raise ValueError("Expected residual = station temperature minus ERA5.")
        prepare_tables(df, args, tables)
        metadata = {
            "data": str(args.data.resolve()), "input_rows": len(raw), "complete_rows": len(df),
            "stations": df["STAID"].n_unique(),
            "date_start": str(df["date"].min()), "date_end": str(df["date"].max()),
            "residual_definition": "station minus ERA5 (degrees Celsius)",
            "elevation_missing_rows": df.filter(pl.col("elevation").is_in(MISSING_ELEVATION)).height,
            "elevation_excluded_codes": list(MISSING_ELEVATION),
            "bootstrap": args.bootstrap, "seed": args.seed, "quantile_bins": args.bins,
        }
    min_stations = (args.min_stations if args.min_stations is not None
                    else metadata.get("heatmap_min_stations", 10))
    if min_stations < 1:
        parser.error("--min-stations must be positive.")
    metadata.update(renderer="Altair / Vega-Lite / vl-convert", dpi=args.dpi,
                    figure_width_mm=args.width_mm, heatmap_min_stations=min_stations)
    figure_captions = captions(metadata)
    figures = [
        ("01_covariates", lambda: paper_charts.covariates(tables)),
        ("02_urbanization", lambda: paper_charts.urbanization(tables)),
        ("03_interactions", lambda: paper_charts.interactions(tables, min_stations)),
    ]
    if not args.skip_map:
        paper_charts.map_geometry(tables, args.output / ".cartopy")
        figures.append(("04_station_map", lambda: paper_charts.station_map(tables)))
        stations = pl.read_csv(tables / "station_means.csv")
        shown = stations.filter(pl.col("lon").is_between(*MAP_EXTENT[:2]) &
                                pl.col("lat").is_between(*MAP_EXTENT[2:])).height
        metadata["map_stations_shown"] = shown
        figure_captions.append(
            f"04_station_map: Mean residual at each station. European window: {shown:,} of "
            f"{len(stations):,} stations, 25°W–45°E and 34–72°N. Stations outside the window "
            "are omitted from this map only. Lambert conformal projection; Natural Earth "
            "1:50m land, coastline and national boundaries. Colours saturate beyond ±3°C; "
            "the endpoint labels indicate saturation."
        )
    with PdfWriter() as book:
        metadata["exports"] = {}
        for name, draw in figures:
            print(f"Rendering {name} with Altair...", flush=True)
            chart = paper_style(draw())
            metadata["exports"][name] = save_figure(chart, args.output / name, args.dpi, args.width_mm)
            book.append(args.output / f"{name}.pdf")
        book.write(args.output / "all_figures.pdf")
    (args.output / "captions.txt").write_text("\n\n".join(figure_captions) + "\n")
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Saved figures, specifications and source tables to {args.output}", flush=True)


if __name__ == "__main__":
    main()
