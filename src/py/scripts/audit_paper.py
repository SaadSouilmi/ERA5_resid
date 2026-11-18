"""Check manuscript tables and notebook point estimates against the saved clean release."""

import argparse as Argparse
import base64 as Base64
import hashlib as Hashlib
import json as Json
import re as Re
import subprocess as Subprocess
from pathlib import Path

import numpy as Np
import polars as Pl

from py.paths import AnalysisDataDirectory, NotebookFiguresDirectory, ProjectRoot

BeforeCal = "04c4e26"


def Digest(File):
    with File.open("rb") as Stream:
        return Hashlib.file_digest(Stream, "sha256").hexdigest()


def Main():
    Argparse.ArgumentParser(description=__doc__).parse_args()
    Tables = ProjectRoot / "paper/tables"
    Summary = Json.loads((AnalysisDataDirectory / "clean/summary.json").read_text())
    Baseline = Json.loads(
        Subprocess.check_output(
            ["git", "show", f"{BeforeCal}:data2/clean/summary.json"],
            cwd=ProjectRoot,
            text=True,
        )
    )
    Checks = []

    def Check(Name, Condition, Details=None):
        Checks.append({"check": Name, "passed": bool(Condition), "details": Details})
        print(f"{'PASS' if Condition else 'FAIL'} {Name}", flush=True)

    for Key, Relative in (
        ("raw_input_sha256", "residuals.parquet"),
        ("input_sha256", "residuals_cleaned.parquet"),
        ("cleaned_data_sha256", "clean/analysis.parquet"),
    ):
        Actual = Digest(AnalysisDataDirectory / Relative)
        Check(f"{Relative} matches the release", Actual == Summary[Key], Actual)
        Check(f"{Relative} is unchanged since before CAL", Actual == Baseline[Key])
    for Name, Expected in Summary["artifacts"].items():
        if Path(Name).name != "analysis.parquet":
            Check(
                f"{Path(Name).name} matches the release",
                Digest(AnalysisDataDirectory / "clean" / Path(Name).name) == Expected,
            )
    CoreFiles = [
        f"src/py/{Name}.py" for Name in ("cleaning", "temperature_quality", "covariates", "pdp")
    ]
    Changed = Subprocess.check_output(
        ["git", "diff", "--name-only", f"{BeforeCal}..HEAD", "--", *CoreFiles],
        cwd=ProjectRoot,
        text=True,
    ).splitlines()
    Check("CAL did not change the core cleaning or estimator modules", not Changed, Changed)
    Frame = Pl.read_parquet(AnalysisDataDirectory / "clean/analysis.parquet")
    Selection = Pl.read_csv(Tables / "cleaning_selection.csv")
    Check(
        "Sequential selection table reconciles",
        Selection["remaining"][-1] == len(Frame)
        and (Selection["remaining"][0] - Selection["removed"].cum_sum()).equals(
            Selection["remaining"]
        ),
    )
    Check(
        "Release row and station counts",
        len(Frame) == Summary["cleaned_rows"]
        and Frame["STAID"].n_unique() == Summary["cleaned_stations"],
    )
    Check(
        "Station-day keys are unique",
        Frame.select(Pl.struct("STAID", "date").n_unique()).item() == len(Frame),
    )
    Check(
        "Source-day keys are unique",
        Frame.select(Pl.struct("SOUID", "date").n_unique()).item() == len(Frame),
    )
    Check(
        "Residual arithmetic",
        Np.allclose(
            Frame["residual"], Frame["station_celsius"] - Frame["era5_celsius"], rtol=0, atol=1e-6
        ),
    )
    Check("Source quality flags", Frame["Q_TX"].null_count() == 0 and (Frame["Q_TX"] == 0).all())
    Check("No substituted land cells", not Frame["era5_land_fallback"].any())
    Check("Source and saved ERA5 cells agree", Frame["source_same_grid_cell"].all())
    Quality = Pl.read_csv(AnalysisDataDirectory / "clean/station_quality.csv")
    Quarantined = Quality.filter(Pl.col("quarantined"))["STAID"]
    Check(
        "Quarantined stations excluded",
        not Frame["STAID"].is_in(Quarantined.implode()).any(),
        len(Quarantined),
    )
    Check(
        "UTC subset definition",
        (Frame["utc_day_aligned"] == Frame["observation_window"].is_in(["TX3", "TX21"])).all(),
    )
    Utc = Frame.filter(Pl.col("utc_day_aligned"))
    Check(
        "UTC subset counts",
        len(Utc) == Summary["utc_aligned_rows"]
        and Utc["STAID"].n_unique() == Summary["utc_aligned_stations"],
    )
    for Method, Key in (
        ("observed_season", "ndvi_observed_rows"),
        ("previous_same_season", "ndvi_extrapolated_rows"),
        ("missing", "ndvi_missing_rows"),
    ):
        Check(f"NDVI {Method} count", (Frame["ndvi_method"] == Method).sum() == Summary[Key])
    Check(
        "NDVI flags agree with methods",
        (Frame["ndvi_is_extrapolated"] == (Frame["ndvi_method"] == "previous_same_season")).all(),
    )
    Ndvi = Frame.filter(Pl.col("ndvi").is_not_null())
    Check(
        "NDVI source dates do not use future rasters",
        (Ndvi["ndvi_source_start"] <= Ndvi["date"].dt.date()).all(),
    )
    Extrapolated = Ndvi.filter(Pl.col("ndvi_is_extrapolated"))
    Months = Extrapolated["date"].dt.month().to_numpy()
    Seasons = Np.where(Np.isin(Months, [1, 2, 12]), 12, Months // 3 * 3)
    Check(
        "NDVI extrapolates the matching season",
        Np.array_equal(Seasons, Extrapolated["ndvi_source_start"].dt.month().to_numpy())
        and (Extrapolated["ndvi_years_extrapolated"] > 0).all(),
    )
    Check(
        "Missing elevations have no retained sentinel codes",
        not Frame["elevation"].is_in([-9999, -999]).any(),
    )
    Grid = Pl.read_csv(AnalysisDataDirectory / "clean/era5_full_checks.csv")
    Check(
        "Saved full ERA5 check covers every intermediate row",
        Grid["sampled_station_days"].sum() == Summary["input_rows"]
        and all(Grid[Name].sum() == 0 for Name in Grid.columns if Name.endswith("mismatches")),
    )

    for Row in Pl.read_csv(Tables / "descriptive_continuous.csv").to_dicts():
        Values = Frame[Row["variable"]].cast(Pl.Float64).to_numpy()
        Values = Values[Np.isfinite(Values)]
        Expected = [
            Values.mean(),
            Values.std(ddof=1),
            *Np.quantile(Values, [0.05, 0.25, 0.5, 0.75, 0.95]),
        ]
        Actual = [Row[Key] for Key in ("mean", "std", "p05", "p25", "p50", "p75", "p95")]
        Check(
            f"Continuous table: {Row['variable']}",
            Row["missing"] == len(Frame) - len(Values)
            and Np.allclose(Expected, Actual, rtol=2e-7, atol=1e-10),
        )
        Cells = [
            Row["variable"].replace("_", r"\_"),
            f"{Row['missing']:,}",
            *(f"{Value:.3g}" for Value in Actual),
        ]
        Check(
            f"LaTeX continuous row: {Row['variable']}",
            " & ".join(Cells) + r" \\" in (Tables / "descriptive_continuous.tex").read_text(),
        )
    for Name, Columns in (
        ("descriptive_degurba", ["degurba", "degurba_label"]),
        ("descriptive_countries", ["country"]),
    ):
        Independent = (
            Frame.select(*Columns, "STAID")
            .to_pandas()
            .groupby(Columns, dropna=False)["STAID"]
            .agg(["size", "nunique"])
        )
        Valid = True
        for Row in Pl.read_csv(Tables / f"{Name}.csv").to_dicts():
            Key = tuple(Row[Name] for Name in Columns) if len(Columns) > 1 else Row[Columns[0]]
            Group = Independent.loc[Key]
            Valid &= (
                int(Group["size"]) == Row["observations"]
                and int(Group["nunique"]) == Row["stations"]
            )
            Valid &= Np.isclose(Row["observation_percent"], 100 * Group["size"] / len(Frame))
            Valid &= Np.isclose(
                Row["station_percent"], 100 * Group["nunique"] / Frame["STAID"].n_unique()
            )
        Check(f"Counts and denominators: {Name}", Valid)
        Display = Pl.read_csv(Tables / f"{Name}.csv")
        if Name == "descriptive_countries":
            Display = Display.head(10)
        Rendered = (Tables / f"{Name}.tex").read_text()
        Check(
            f"LaTeX counts: {Name}",
            all(
                " & ".join(
                    [
                        *(str(Row[Key]).replace("&", r"\&") for Key in Columns),
                        f"{Row['observations']:,}",
                        f"{Row['observation_percent']:.1f}",
                        f"{Row['stations']:,}",
                        f"{Row['station_percent']:.1f}",
                    ]
                )
                + r" \\"
                in Rendered
                for Row in Display.to_dicts()
            ),
        )

    def SavedRows(Name, Key):
        Spec = Json.loads(
            (NotebookFiguresDirectory / "resid_analysis" / f"{Name}.vl.json").read_text()
        )
        return [Row for Rows in Spec["datasets"].values() for Row in Rows if Key in Row]

    BootstrapChanges = []
    for Feature in ("station_celsius", "tp", "wind", "ndvi", "dist_to_sea_km", "elevation"):
        Selected = Frame.filter(Pl.col(Feature).is_finite())
        if Feature == "tp":
            Selected = Selected.with_columns(Pl.col(Feature).clip(1e-9).log10())
        Values = Selected[Feature].to_numpy()
        Edges = Np.unique(Np.quantile(Values, Np.arange(1, 10) / 10))
        Codes = Np.searchsorted(Edges, Values, side="left")
        Counts = Np.bincount(Codes, minlength=len(Edges) + 1)
        Means = Np.bincount(Codes, weights=Selected["residual"], minlength=len(Counts)) / Counts
        Saved = sorted(SavedRows(f"pdp_{Feature}", "mean"), key=lambda Row: Row["x"])
        Previous = Json.loads(
            Subprocess.check_output(
                [
                    "git",
                    "show",
                    f"{BeforeCal}:figures/notebooks/resid_analysis/pdp_{Feature}.vl.json",
                ],
                cwd=ProjectRoot,
                text=True,
            )
        )
        Previous = sorted(
            [Row for Rows in Previous["datasets"].values() for Row in Rows if "mean" in Row],
            key=lambda Row: Row["x"],
        )
        Check(
            f"Pre-CAL point estimates preserved: {Feature}",
            Np.allclose(
                [Row["mean"] for Row in Previous],
                [Row["mean"] for Row in Saved],
                rtol=0,
                atol=1e-10,
            ),
        )
        BootstrapChanges.append(
            {
                "feature": Feature,
                "maximum_interval_endpoint_change_celsius": max(
                    abs(Before[Key] - After[Key])
                    for Before, After in zip(Previous, Saved)
                    for Key in ("ci_lo", "ci_hi")
                ),
            }
        )
        Limits = Np.r_[Values.min(), Edges, Values.max()]
        Check(
            f"Notebook conditional means: {Feature}",
            Np.allclose(Means, [Row["mean"] for Row in Saved], rtol=0, atol=1e-9)
            and Np.allclose(
                (Limits[:-1] + Limits[1:]) / 2, [Row["x"] for Row in Saved], rtol=1e-7, atol=1e-8
            ),
        )
        Check(
            f"Notebook intervals contain the point means: {Feature}",
            all(Row["ci_lo"] <= Row["mean"] <= Row["ci_hi"] for Row in Saved),
        )
    Urban = SavedRows("degurba", "mean")
    Check(
        "Notebook urban-class means",
        all(
            Np.isclose(
                Frame.filter(Pl.col("degurba_label") == Row["label"])["residual"].mean(),
                Row["mean"],
                rtol=0,
                atol=1e-10,
            )
            for Row in Urban
        ),
    )
    Shares = SavedRows("degurba", "share")
    Check(
        "Notebook land-class shares retain the full-sample denominator",
        len(Shares) == len(Urban)
        and {Row["degurba_label"] for Row in Shares} == {Row["label"] for Row in Urban}
        and all(
            Row["count"] == Frame.filter(Pl.col("degurba_label") == Row["degurba_label"]).height
            and Np.isclose(Row["share"], Row["count"] / len(Frame), rtol=0, atol=1e-12)
            for Row in Shares
        ),
    )
    Joint = SavedRows("station_celsius_by_wind", "color_val")
    XEdges, YEdges = [
        Np.quantile(Frame[Feature].to_numpy(), Np.arange(1, 8) / 8)
        for Feature in ("station_celsius", "wind")
    ]
    Code = Np.searchsorted(XEdges, Frame["station_celsius"], side="left") * 8 + Np.searchsorted(
        YEdges, Frame["wind"], side="left"
    )
    Counts = Np.bincount(Code, minlength=64)
    Means = Np.bincount(Code, weights=Frame["residual"], minlength=64) / Counts
    Joint = sorted(Joint, key=lambda Row: (Row["x_hi"], Row["y_hi"]))
    Check(
        "All 64 notebook joint-bin counts and means",
        Np.array_equal(Counts, [Row["n"] for Row in Joint])
        and Np.allclose(Means, [Row["color_val"] for Row in Joint], rtol=0, atol=1e-9),
    )
    SummaryText = (Tables / "data_summary.tex").read_text()
    Check(
        "LaTeX data summary",
        all(
            Value in SummaryText
            for Value in (
                f"{len(Frame):,}",
                f"{Frame['STAID'].n_unique():,}",
                str(Frame["country"].n_unique()),
                f"{Frame['date'].min():%Y-%m-%d} to {Frame['date'].max():%Y-%m-%d}",
                f"{Frame['residual'].mean():.2f} ({Frame['residual'].std():.2f})",
            )
        ),
    )
    Check(
        "LaTeX selection counts",
        all(
            f"{Row['step']} & {Row['removed']:,} & {Row['remaining']:,}" + r" \\"
            in (Tables / "cleaning_selection.tex").read_text()
            for Row in Selection.to_dicts()
        ),
    )
    Results = Pl.read_csv(Tables / "results_summary.csv")
    Check(
        "LaTeX result ranges",
        all(
            f"{Row['variable']} & {Row['pattern']} & {Row['low']:.2f}--{Row['high']:.2f}" + r" \\"
            in (Tables / "results_summary.tex").read_text()
            for Row in Results.to_dicts()
        ),
    )
    MapDirectory = NotebookFiguresDirectory / "resid_analysis"
    MapTable = Pl.read_csv(MapDirectory / "tables/station_means.csv").sort("STAID")
    MapExpected = (
        Frame.select("STAID", "residual", "lat", "lon")
        .to_pandas()
        .groupby("STAID", sort=True)
        .agg(
            residual=("residual", "mean"),
            lat=("lat", "first"),
            lon=("lon", "first"),
            n_observations=("residual", "size"),
        )
    )
    Check(
        "Plotly station map reproduces the cleaned station means and coordinates",
        Np.array_equal(MapTable["STAID"].to_numpy(), MapExpected.index.to_numpy())
        and all(
            Np.allclose(MapTable[Name].to_numpy(), MapExpected[Name].to_numpy(), rtol=0, atol=1e-10)
            for Name in ("residual", "lat", "lon", "n_observations")
        ),
    )
    MapSpec = Json.loads((MapDirectory / "station_map.plotly.json").read_text())
    MapTrace = MapSpec["data"][0]

    def PlotlyArray(Value):
        if isinstance(Value, dict):
            return Np.frombuffer(Base64.b64decode(Value["bdata"]), dtype=Value["dtype"])
        return Np.asarray(Value)

    Check(
        "Plotly specification contains every station with unchanged colours and coordinates",
        MapTrace["type"] == "scattermap"
        and Np.allclose(
            PlotlyArray(MapTrace["marker"]["color"]), MapTable["residual"], rtol=0, atol=1e-10
        )
        and Np.array_equal(PlotlyArray(MapTrace["lat"]), MapTable["lat"])
        and Np.array_equal(PlotlyArray(MapTrace["lon"]), MapTable["lon"])
        and MapSpec["layout"]["coloraxis"]["cmin"] == -3
        and MapSpec["layout"]["coloraxis"]["cmax"] == 3,
    )
    PaperText = (ProjectRoot / "paper/paper.tex").read_text()
    References = Re.findall(r"\\includegraphics\[[^\]]*\]\{figures/([^}]+)\}", PaperText)
    Manifest = Json.loads((Tables / "figure_sources.json").read_text())
    Check(
        "Manuscript contains only its referenced notebook PDFs",
        set(References)
        == set(Manifest)
        == {File.name for File in (ProjectRoot / "paper/figures").iterdir()},
    )
    Check(
        "Manuscript PDFs and plotted data match notebook sources",
        all(
            Digest(ProjectRoot / "paper/figures" / Name)
            == Digest(ProjectRoot / Record["source"])
            == Record["sha256"]
            and Digest(ProjectRoot / "paper" / Record["specification"])
            == Digest(ProjectRoot / Record["source_specification"])
            == Record["specification_sha256"]
            for Name, Record in Manifest.items()
        ),
    )
    Inputs = [
        ProjectRoot / "paper/paper.tex",
        ProjectRoot / "src/py/scripts/audit_paper.py",
        *sorted(Tables.glob("*.csv")),
        *sorted(Tables.glob("*.tex")),
        *sorted((NotebookFiguresDirectory / "resid_analysis").glob("*.vl.json")),
        *sorted((NotebookFiguresDirectory / "resid_analysis").glob("*.plotly.json")),
        NotebookFiguresDirectory / "resid_analysis/tables/station_means.csv",
    ]
    Report = {
        "baseline_commit": BeforeCal,
        "data_sha256": Summary["cleaned_data_sha256"],
        "checks": Checks,
        "bootstrap_order_fix": BootstrapChanges,
        "passed": all(Row["passed"] for Row in Checks),
        "inputs": {str(File.relative_to(ProjectRoot)): Digest(File) for File in Inputs},
        "limits": [
            "Historical full-source checks were reconciled with their saved release; this review does not re-extract every ERA5 value or revalidate instruments.",
            "Mixed observation windows and station sampling frequencies remain; the main figures do not use only the UTC subset.",
            "Station-only screening thresholds and source-ID metadata offsets are provisional; distinct source IDs need not identify independent physical instruments.",
            "NDVI carry-forward is seasonal extrapolation, not contemporaneous vegetation measurement; coastline distance uses generalized geometry.",
            "The precipitation accumulation recipe remains unresolved; mean-vector wind is not mean hourly speed.",
            "Bootstrap clusters are nominal stations, with no correction for dependence across stations, multiplicity or confounding.",
            "The general literature review, authorship and missing downscaling.bib are outside this numerical processing audit.",
        ],
        "documentation": [
            "https://cds.climate.copernicus.eu/datasets/derived-era5-land-daily-statistics?tab=overview",
            "https://www.ecad.eu/dailydata/datadictionary.php",
        ],
    }
    Output = ProjectRoot / "paper/processing_review.json"
    Output.write_text(Json.dumps(Report, indent=2) + "\n")
    print(f"{sum(Row['passed'] for Row in Checks)}/{len(Checks)} checks passed; {Output}")
    if not Report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    Main()
