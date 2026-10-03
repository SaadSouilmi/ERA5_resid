"""Build Altair publication figures; use --from-tables to restyle saved results."""

import argparse as Argparse
import hashlib as Hashlib
import json as Json
from pathlib import Path

import numpy as Np
import polars as Pl
from pypdf import PdfWriter

from py import paper_charts as PaperCharts
from py import pdp as Pdp
from py.paper_charts import DegurbaClasses, FeatureLabels, FeaturePairs, MapExtent
from py.paths import AnalysisDataDirectory, ProjectRoot
from py.publication import PaperStyle, SaveFigure

MissingElevation = (-9999, -999)


def AnalysisFrame(Frame):
    Columns = ["station_celsius", "era5_celsius", "residual", "lat", "lon"]
    Frame = Frame.filter(Pl.all_horizontal(Pl.col(Name).is_finite() for Name in Columns))
    if not len(Frame) or not Np.allclose(
        Frame["residual"], Frame["station_celsius"] - Frame["era5_celsius"]
    ):
        raise ValueError("Expected nonempty finite pairs with residual = station minus ERA5.")
    return Frame


def BinFeature(Df, Feature, NBins):
    Frame = Df.with_columns(Pl.col(Feature).qcut(NBins, allow_duplicates=True).alias("bin"))
    Bins = sorted(Frame["bin"].unique().to_list(), key=lambda B: Bounds(B)[0])
    return Frame, Bins


def Bounds(Label):
    return tuple(float(V) for V in Label.strip("(]").split(", "))


def Summarize(Df, Column, Bins, NBoot, Seed):
    """Observation means and pointwise station-cluster percentile intervals."""
    Aggregates = (
        Df.group_by(Column, "STAID")
        .agg(Pl.col("residual").sum().alias("total"), Pl.len().alias("n"))
        .sort(Column, "STAID")
    )
    Rng = Np.random.default_rng(Seed)
    Rows = []
    for Label in Bins:
        Group = Aggregates.filter(Pl.col(Column) == Label)
        Totals, Counts = Group["total"].to_numpy(), Group["n"].to_numpy()
        N = len(Group)
        if not N:
            continue
        Boot = Np.empty(NBoot)
        for Start in range(0, NBoot, 64):
            Indices = Rng.integers(N, size=(min(64, NBoot - Start), N))
            Boot[Start : Start + len(Indices)] = Totals[Indices].sum(axis=1) / Counts[Indices].sum(
                axis=1
            )
        Lo, Hi = Np.percentile(Boot, [2.5, 97.5])
        Rows.append(
            {
                "bin": str(Label),
                "mean": Totals.sum() / Counts.sum(),
                "ci_low": Lo,
                "ci_high": Hi,
                "n_observations": int(Counts.sum()),
                "n_stations": N,
            }
        )
    return Pl.DataFrame(Rows)


def FeatureFrame(Df, Features):
    Frame = Df.filter(Pl.all_horizontal(Pl.col(F).is_finite() for F in Features))
    if "elevation" in Features:
        Frame = Frame.filter(~Pl.col("elevation").is_in(MissingElevation))
    return Frame


def AddBounds(Summary, Frame, Fx, Fy):
    Columns = []
    for Axis, Feature in [("x", Fx), ("y", Fy)]:
        Lo, Hi = float(Frame[Feature].min()), float(Frame[Feature].max())
        Intervals = [Bounds(B) for B in Summary[f"bin_{Axis}"]]
        Columns.extend(
            [
                Pl.Series(f"{Axis}_lo", [max(Lo, B[0]) for B in Intervals]),
                Pl.Series(f"{Axis}_hi", [min(Hi, B[1]) for B in Intervals]),
            ]
        )
    return Summary.with_columns(Columns)


def PrepareTables(Df, Args, Tables):
    for Index, Feature in enumerate(FeatureLabels):
        print(f"  Computing {Feature}...", flush=True)
        Frame = FeatureFrame(Df, [Feature])
        if Feature == "tp":
            Frame = Frame.with_columns(Pl.col(Feature).clip(1e-9).log10())
        Frame, Bins = BinFeature(Frame, Feature, Args.Bins)
        Summary = Summarize(Frame, "bin", Bins, Args.Bootstrap, Args.Seed + Index)
        Centers = Pdp.BinCenters(Bins, Frame[Feature].min(), Frame[Feature].max())
        Summary.with_columns(Pl.Series("x", Centers)).write_csv(Tables / f"covariate_{Feature}.csv")
    Summary = Summarize(Df, "degurba_label", DegurbaClasses, Args.Bootstrap, Args.Seed)
    Order = [Label for Label in DegurbaClasses if Label in Summary["bin"].to_list()]
    Summary.with_columns(Pl.col("bin").cast(Pl.Enum(Order))).sort("bin").write_csv(
        Tables / "urbanization.csv"
    )
    for Fx, Fy in FeaturePairs:
        Frame = FeatureFrame(Df, [Fx, Fy])
        Frame, _ = BinFeature(Frame, Fx, Args.Bins)
        Frame = Frame.rename({"bin": "bin_x"})
        Frame, _ = BinFeature(Frame, Fy, Args.Bins)
        Summary = (
            Frame.group_by("bin_x", "bin")
            .agg(
                Pl.col("residual").mean(),
                Pl.len().alias("n_observations"),
                Pl.col("STAID").n_unique().alias("n_stations"),
            )
            .rename({"bin": "bin_y"})
        )
        AddBounds(Summary, Frame, Fx, Fy).sort("bin_x", "bin_y").write_csv(
            Tables / f"{Fx}_by_{Fy}.csv"
        )
    Df.group_by("STAID").agg(
        Pl.col("residual").mean(),
        Pl.col("lat").first(),
        Pl.col("lon").first(),
        Pl.len().alias("n_observations"),
    ).sort("STAID").write_csv(Tables / "station_means.csv")


def UpgradeBounds(Tables, Source):
    """Enrich older saved tables with finite heatmap edges, without re-estimating."""
    for Fx, Fy in FeaturePairs:
        FilePath = Tables / f"{Fx}_by_{Fy}.csv"
        Summary = Pl.read_csv(FilePath)
        if "x_lo" not in Summary.columns:
            print(
                f"  Adding numeric bounds to {FilePath.name} from the original input...", flush=True
            )
            Frame = FeatureFrame(Pl.scan_parquet(Source), [Fx, Fy])
            Extrema = (
                Frame.select(
                    Pl.col(Fx).min().alias("x_min"),
                    Pl.col(Fx).max().alias("x_max"),
                    Pl.col(Fy).min().alias("y_min"),
                    Pl.col(Fy).max().alias("y_max"),
                )
                .collect()
                .row(0)
            )
            Limits = Pl.DataFrame({Fx: Extrema[:2], Fy: Extrema[2:]})
            AddBounds(Summary, Limits, Fx, Fy).write_csv(FilePath)


def Captions(Metadata):
    SampleRows = Metadata.get("analysis_rows", Metadata.get("complete_rows"))
    SampleDescription = Metadata.get("sample_description", "Saved complete-case sample")
    NdviDescription = (
        f"NDVI includes {Metadata['ndvi_extrapolated_rows']:,} observations with explicitly flagged "
        "carry-forward from the latest available matching season. "
        if "ndvi_extrapolated_rows" in Metadata
        else ""
    )
    return [
        "All figures: residual = station minus ERA5 (°C); positive values mean ERA5 is cooler. "
        f"{SampleDescription}: {SampleRows:,} observations, "
        f"{Metadata['stations']:,} stations; {Metadata['date_start'][:10]} to "
        f"{Metadata['date_end'][:10]}. Each panel uses finite values for its own covariates. "
        "Means weight observations equally. "
        f"Intervals are pointwise 95% percentile intervals from {Metadata['bootstrap']:,} station "
        "bootstrap resamples within each bin, retaining all observations from sampled stations. "
        "They do not account for dependence between different stations. "
        "The main sample retains mixed observation-day windows; it is not restricted to the UTC subset. "
        + NdviDescription,
        "01_covariates: Binned mean residuals, with quantile bins and shaded confidence intervals. "
        "Points use bin midpoints, bounded by observed extrema; connecting lines guide the eye. "
        "These are descriptive conditional means, not model-based partial dependence. "
        "The precipitation proxy uses log10(max(tp, 1e-9)) in metres; it is not a daily total. "
        "Wind is the magnitude of the daily mean vector. "
        f"Elevation excludes {Metadata['elevation_missing_rows']:,} missing, nonfinite or sentinel-coded observations. "
        "Covariates refer to the observation-source location. "
        "Duplicate quantile boundaries are merged.",
        "02_urbanization: Observation-weighted mean residuals and station-bootstrap confidence "
        "intervals by land urbanization class. Water is excluded. Numbers give distinct stations.",
        "03_interactions: Mean residuals in joint quantile bins, drawn at their numeric boundaries. "
        "Both panels share a symmetric colour scale centred on zero. "
        f"Grey cells have fewer than {Metadata['heatmap_min_stations']} stations or no data. "
        "Elevation excludes −9999 and −999. The panels describe associations, not causal interactions.",
    ]


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument(
        "--data", dest="Data", type=Path, default=AnalysisDataDirectory / "clean/analysis.parquet"
    )
    Parser.add_argument("--output", dest="Output", type=Path, default=ProjectRoot / "figures/paper")
    Parser.add_argument(
        "--from-tables",
        dest="FromTables",
        action="store_true",
        help="Render saved tables without rerunning statistics.",
    )
    Parser.add_argument("--bootstrap", dest="Bootstrap", type=int)
    Parser.add_argument("--bins", dest="Bins", type=int)
    Parser.add_argument("--seed", dest="Seed", type=int)
    Parser.add_argument("--dpi", dest="Dpi", type=int, default=600)
    Parser.add_argument("--width-mm", dest="WidthMm", type=float, default=180)
    Parser.add_argument("--min-stations", dest="MinStations", type=int)
    Parser.add_argument("--skip-map", dest="SkipMap", action="store_true")
    Args = Parser.parse_args()
    if Args.FromTables and any(V is not None for V in [Args.Bootstrap, Args.Bins, Args.Seed]):
        Parser.error("--from-tables uses the saved bootstrap, bin and seed settings.")
    Args.Bootstrap = 1000 if Args.Bootstrap is None else Args.Bootstrap
    Args.Bins = 10 if Args.Bins is None else Args.Bins
    Args.Seed = 1337 if Args.Seed is None else Args.Seed
    if min(Args.Bootstrap, Args.Bins, Args.Dpi, Args.WidthMm) <= 0 or Args.Seed < 0:
        Parser.error("Counts and width must be positive; seed must be nonnegative.")
    Args.Output = Args.Output.resolve()
    Tables = Args.Output / "tables"
    Tables.mkdir(parents=True, exist_ok=True)
    if Args.FromTables:
        Metadata = Json.loads((Args.Output / "metadata.json").read_text())
        UpgradeBounds(Tables, Path(Metadata["data"]))
    else:
        print("Loading screened pairs with per-feature covariate availability...", flush=True)
        Raw = Pl.read_parquet(Args.Data)
        Df = AnalysisFrame(Raw)
        DataHash = Hashlib.sha256(Args.Data.read_bytes()).hexdigest()
        if Args.Data.resolve() == (AnalysisDataDirectory / "clean/analysis.parquet").resolve():
            Audit = Json.loads((AnalysisDataDirectory / "clean/summary.json").read_text())
            if DataHash != Audit["cleaned_data_sha256"]:
                raise ValueError("Clean dataset hash differs from its build manifest")
        PrepareTables(Df, Args, Tables)
        Metadata = {
            "data": str(Args.Data.resolve()),
            "data_sha256": DataHash,
            "input_rows": len(Raw),
            "analysis_rows": len(Df),
            "sample_description": "Main screened sample"
            if "source_same_grid_cell" in Df.columns
            else "Finite temperature pairs",
            "feature_samples": {
                Feature: len(FeatureFrame(Df, [Feature])) for Feature in FeatureLabels
            },
            "stations": Df["STAID"].n_unique(),
            "date_start": str(Df["date"].min()),
            "date_end": str(Df["date"].max()),
            "residual_definition": "station minus ERA5 (degrees Celsius)",
            "elevation_missing_rows": len(Df) - len(FeatureFrame(Df, ["elevation"])),
            "elevation_excluded_codes": list(MissingElevation),
            "bootstrap": Args.Bootstrap,
            "seed": Args.Seed,
            "quantile_bins": Args.Bins,
        }
        if "ndvi_is_extrapolated" in Df.columns:
            Metadata["ndvi_extrapolated_rows"] = int(Df["ndvi_is_extrapolated"].sum())
            Metadata["ndvi_policy"] = (
                "latest earlier raster from the same season; spatial nodata remains missing"
            )
    MinStations = (
        Args.MinStations
        if Args.MinStations is not None
        else Metadata.get("heatmap_min_stations", 10)
    )
    if MinStations < 1:
        Parser.error("--min-stations must be positive.")
    Metadata.update(
        renderer="Altair / Vega-Lite / vl-convert",
        dpi=Args.Dpi,
        figure_width_mm=Args.WidthMm,
        heatmap_min_stations=MinStations,
    )
    FigureCaptions = Captions(Metadata)
    Figures = [
        ("01_covariates", lambda: PaperCharts.Covariates(Tables)),
        ("02_urbanization", lambda: PaperCharts.Urbanization(Tables)),
        ("03_interactions", lambda: PaperCharts.Interactions(Tables, MinStations)),
    ]
    if not Args.SkipMap:
        PaperCharts.MapGeometry(Tables, Args.Output / ".cartopy")
        Figures.append(("04_station_map", lambda: PaperCharts.StationMap(Tables)))
        Stations = Pl.read_csv(Tables / "station_means.csv")
        Shown = Stations.filter(
            Pl.col("lon").is_between(*MapExtent[:2]) & Pl.col("lat").is_between(*MapExtent[2:])
        ).height
        Metadata["map_stations_shown"] = Shown
        FigureCaptions.append(
            f"04_station_map: Mean residual at each station. European window: {Shown:,} of "
            f"{len(Stations):,} stations, 25°W–45°E and 34–72°N. Stations outside the window "
            "are omitted from this map only. Lambert conformal projection; Natural Earth "
            "1:50m land, coastline and national boundaries. Colours saturate beyond ±3°C; "
            "the endpoint labels indicate saturation."
        )
    with PdfWriter() as Book:
        Metadata["exports"] = {}
        for Name, Draw in Figures:
            print(f"Rendering {Name} with Altair...", flush=True)
            Chart = PaperStyle(Draw())
            Metadata["exports"][Name] = SaveFigure(
                Chart, Args.Output / Name, Args.Dpi, Args.WidthMm
            )
            Book.append(Args.Output / f"{Name}.pdf")
        Book.write(Args.Output / "all_figures.pdf")
    (Args.Output / "captions.txt").write_text("\n\n".join(Text.strip() for Text in FigureCaptions) + "\n")
    (Args.Output / "metadata.json").write_text(Json.dumps(Metadata, indent=2) + "\n")
    print(f"Saved figures, specifications and source tables to {Args.Output}", flush=True)


if __name__ == "__main__":
    Main()
