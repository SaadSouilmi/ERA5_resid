"""Build the static GitHub Pages report from verified figure tables and notebook exports."""

import argparse as Argparse
import csv as Csv
import hashlib as Hashlib
import html as Html
import json as Json
import math as Math
import shutil as Shutil
import tempfile as Tempfile
import zipfile as Zipfile
from datetime import date as Date
from pathlib import Path
from string import Template
from xml.etree import ElementTree as Et

import vl_convert as Vlc

from py.paths import (
    AnalysisDataDirectory,
    FiguresDirectory,
    NotebookFiguresDirectory,
    ProjectRoot,
    ReportsDirectory,
)
from py.report_style import ReportCss
from py.scripts.build_paper_figures import Bounds
from py.scripts.export_notebooks import NotebookNames


def Digest(File):
    with File.open("rb") as Stream:
        return Hashlib.file_digest(Stream, "sha256").hexdigest()


def ReadTable(File):
    with File.open(newline="") as Stream:
        return list(Csv.DictReader(Stream))


def ReadJson(File):
    return Json.loads(File.read_text())


def WriteJson(File, Value):
    File.parent.mkdir(parents=True, exist_ok=True)
    File.write_text(Json.dumps(Value, indent=2) + "\n")


def Table(Headers, Rows, Numeric=()):
    Head = "".join(f'<th scope="col">{Html.escape(Name)}</th>' for Name in Headers)
    Body = []
    for Row in Rows:
        Cells = "".join(
            f'<td class="{"numeric" if Index in Numeric else "text"}">{Html.escape(str(Value))}</td>'
            for Index, Value in enumerate(Row)
        )
        Body.append(f"<tr>{Cells}</tr>")
    return f'<div class="table-scroll" tabindex="0" role="region" aria-label="Scrollable data table"><table><thead><tr>{Head}</tr></thead><tbody>{"".join(Body)}</tbody></table></div>'


def Figure(Output, Stem, Label, Alt, Caption, Multi=False):
    Svg = Output / f"{Stem}.svg"
    Bounds = [float(Value) for Value in Et.fromstring(Svg.read_text()).attrib["viewBox"].split()]
    Width, Height = round(Bounds[2]), round(Bounds[3])
    Classes = "multi-panel" if Multi else "compact"
    return f"""<figure class="{Classes}">
      <div class="figure-frame" tabindex="0" role="region" aria-label="{Html.escape(Label)}">
        <img src="{Stem}.svg" alt="{Html.escape(Alt)}" width="{Width}" height="{Height}" loading="lazy">
      </div>
      <figcaption><strong>{Html.escape(Label)}.</strong> {Html.escape(Caption)}</figcaption>
      <p class="figure-links"><a href="{Stem}.svg">Open full-size SVG</a><a href="{Stem}.pdf">PDF</a><a href="{Stem}.vl.json">Plotted data and Altair specification</a><span class="mobile-hint">Scroll wide figures horizontally.</span></p>
    </figure>"""


def LoadEvidence(NotebookDirectory):
    Summary = ReadJson(AnalysisDataDirectory / "clean/summary.json")
    Audit = ReadJson(AnalysisDataDirectory / "cleaning_audit/summary.json")
    Metadata = ReadJson(FiguresDirectory / "metadata.json")
    Exports = ReadJson(NotebookDirectory / "exports.json")
    if Metadata["data_sha256"] != Summary["cleaned_data_sha256"]:
        raise ValueError("Paper figures use a different release; rebuild them first")
    if Summary["input_sha256"] != Audit["cleaned_data_sha256"]:
        raise ValueError("Cleaning releases do not form a consistent chain")
    if (
        Metadata["analysis_rows"] != Summary["cleaned_rows"]
        or Metadata["stations"] != Summary["cleaned_stations"]
    ):
        raise ValueError("Paper figure sample counts differ from the release")
    for Name in NotebookNames:
        Record = Exports[Name]
        if Record["notebook_sha256"] != Digest(ProjectRoot / f"src/py/notebooks/{Name}.py"):
            raise ValueError(f"Notebook export is stale: {Name}")
        if (
            Name != "data_comparison"
            and Record["cleaned_data_sha256"] != Summary["cleaned_data_sha256"]
        ):
            raise ValueError(f"Notebook input is stale: {Name}")
        if not (NotebookDirectory / f"{Name}.html").is_file():
            raise FileNotFoundError(f"Missing notebook HTML: {Name}")
    for Name, Expected in Exports["cleaning_process"]["audit_files"].items():
        if Digest(ProjectRoot / Name) != Expected:
            raise ValueError(f"Cleaning notebook evidence changed: {Name}")
    Tables = {
        Feature: ReadTable(FiguresDirectory / f"tables/covariate_{Feature}.csv")
        for Feature in Metadata["feature_samples"]
    }
    for Feature, Rows in Tables.items():
        if sum(int(Row["n_observations"]) for Row in Rows) != Metadata["feature_samples"][Feature]:
            raise ValueError(f"Figure table sample count differs: {Feature}")
    Stations = ReadTable(FiguresDirectory / "tables/station_means.csv")
    Count = sum(int(Row["n_observations"]) for Row in Stations)
    Mean = sum(float(Row["residual"]) * int(Row["n_observations"]) for Row in Stations) / Count
    if Count != Summary["cleaned_rows"] or not Math.isclose(
        Mean, Summary["mean_residual"], abs_tol=1e-10
    ):
        raise ValueError("Station source table does not reconcile with the headline mean")
    PostDirectory = NotebookFiguresDirectory / "poststrat_analysis"
    PostMetadata = ReadJson(PostDirectory / "metadata.json")
    if (
        PostMetadata["data_sha256"] != Summary["cleaned_data_sha256"]
        or PostMetadata["notebook_sha256"] != Exports["poststrat_analysis"]["notebook_sha256"]
    ):
        raise ValueError("Post-stratification tables are stale; export the notebook first")
    Post = ReadTable(PostDirectory / "estimates.csv")
    return Summary, Audit, Metadata, Exports, Tables, Post


def Build(Output, NotebookDirectory, Updated):
    Summary, Audit, Metadata, Exports, Tables, Post = LoadEvidence(NotebookDirectory)
    Output.mkdir(parents=True, exist_ok=True)
    (Output / ".nojekyll").write_text("")
    (Output / ".era5-generated-site").write_text("Generated by py.scripts.build_pages\n")
    Shutil.copytree(
        FiguresDirectory,
        Output / "figures/paper",
        ignore=Shutil.ignore_patterns(".cartopy", "*.png"),
    )
    Shutil.copytree(
        NotebookFiguresDirectory,
        Output / "figures/notebooks",
        ignore=Shutil.ignore_patterns(".cartopy"),
    )
    NotebookOutput = Output / "notebooks"
    NotebookOutput.mkdir()
    for Name in [
        *(f"{Name}.html" for Name in NotebookNames),
        "clean_dataset.html",
        "data_cleaning.html",
        "index.html",
        "all_altair_figures.pdf",
    ]:
        Shutil.copy2(NotebookDirectory / Name, NotebookOutput / Name)
    PublicExports = {
        Name: {
            "html": f"notebooks/{Name}.html",
            "source": f"src/py/notebooks/{Name}.py",
            "source_sha256": Record["notebook_sha256"],
            "data_sha256": Record["cleaned_data_sha256"],
        }
        for Name, Record in Exports.items()
        if Name in NotebookNames
    }
    WriteJson(NotebookOutput / "exports.json", PublicExports)
    PublicMetadata = {**Metadata, "data": "data2/clean/analysis.parquet"}
    WriteJson(Output / "figures/paper/metadata.json", PublicMetadata)
    PublicSummary = {
        **Summary,
        "input": "data2/residuals_cleaned.parquet",
        "output": "data2/clean/analysis.parquet",
        "artifacts": {
            f"data2/clean/{Path(Name).name}": Value for Name, Value in Summary["artifacts"].items()
        },
    }
    WriteJson(Output / "data/clean-summary.json", PublicSummary)
    (Output / "assets").mkdir()
    Shutil.copy2(
        ProjectRoot / "assets/fonts/GUST-FONT-LICENSE.txt", Output / "assets/GUST-FONT-LICENSE.txt"
    )
    for Stem in ["cleaning_process/ndvi_coverage", "poststrat_analysis/estimates"]:
        Spec = ReadJson(Output / f"figures/notebooks/{Stem}.vl.json")
        (Output / f"figures/notebooks/{Stem}.svg").write_text(Vlc.vegalite_to_svg(Spec))
    with Zipfile.ZipFile(
        Output / "data/source-tables.zip", "w", compression=Zipfile.ZIP_DEFLATED
    ) as Archive:
        for File in sorted((FiguresDirectory / "tables").glob("*.csv")):
            Archive.write(File, f"paper/{File.name}")
        for Name in [
            "exclusion_counts.csv",
            "observation_windows.csv",
            "ndvi_backtest.csv",
            "ndvi_sensitivity.csv",
            "country_coverage.csv",
            "era5_full_checks.csv",
        ]:
            Archive.write(AnalysisDataDirectory / "clean" / Name, f"cleaning/{Name}")
        Archive.write(
            NotebookFiguresDirectory / "poststrat_analysis/estimates.csv",
            "poststratification/estimates.csv",
        )
        Archive.writestr("cleaning/summary.json", Json.dumps(PublicSummary, indent=2) + "\n")
    Rows, Stations = Summary["cleaned_rows"], Summary["cleaned_stations"]
    Temperature, Wind, Elevation = Tables["station_celsius"], Tables["wind"], Tables["elevation"]
    Coast, Ndvi = Tables["dist_to_sea_km"], Tables["ndvi"]
    PeakElevation = max(Elevation, key=lambda Row: float(Row["mean"]))
    ColdLimit, HotLimit = Bounds(Temperature[0]["bin"])[1], Bounds(Temperature[-1]["bin"])[0]
    CalmLimit, WindyLimit = Bounds(Wind[0]["bin"])[1], Bounds(Wind[-1]["bin"])[0]
    PeakLow, PeakHigh = Bounds(PeakElevation["bin"])
    HighElevation, InlandLimit = Bounds(Elevation[-1]["bin"])[0], Bounds(Coast[-1]["bin"])[0]
    Urban = ReadTable(FiguresDirectory / "tables/urbanization.csv")
    UrbanByClass = {Row["bin"]: Row for Row in Urban}

    def Mean(Row):
        return float(Row["mean"])

    Data = {
        "Updated": Html.escape(Updated),
        "BootstrapCount": f"{Metadata['bootstrap']:,}",
        "Overview": f"<p>Across <strong>{Rows:,} screened station-day pairs at {Stations:,} nominal station IDs</strong>, ERA5-Land is cooler than the station daily maximum by <strong>{Summary['mean_residual']:+.2f} °C on average</strong>. The comparison covers {Metadata['date_start'][:10]} to {Metadata['date_end'][:10]}.</p>",
        "Findings": f"""<ul>
          <li><strong>Warmer station days have larger residuals.</strong> The coldest temperature bin averages {Mean(Temperature[0]):.2f} °C, rising to {Mean(Temperature[-1]):.2f} °C in the warmest bin.</li>
          <li><strong>Residuals decrease across the wind bins.</strong> The lowest and highest mean-vector wind bins average {Mean(Wind[0]):.2f} and {Mean(Wind[-1]):.2f} °C.</li>
          <li><strong>Geographic profiles are not uniformly monotonic.</strong> The highest elevation bin has a lower mean than the middle-elevation peak; the coast-distance profile also has a secondary inland peak.</li>
        </ul>""",
        "Profiles": f"""<p>The temperature bins run from station maxima ≤{ColdLimit:g} °C to &gt;{HotLimit:g} °C. The wind endpoints compare magnitudes below approximately {CalmLimit:.2f} m/s with values above approximately {WindyLimit:.2f} m/s. The plotted locations are bin midpoints, rather than typical or median observations within the bins.</p>
        <p>Mean residual reaches <strong>{Mean(PeakElevation):.2f} °C in the {PeakLow:g}–{PeakHigh:g} m elevation bin</strong>, then falls to <strong>{Mean(Elevation[-1]):.2f} °C above {HighElevation:g} m</strong>. The nearest-coast bin averages {Mean(Coast[0]):.2f} °C, compared with {Mean(Coast[-1]):.2f} °C beyond approximately {InlandLimit:.0f} km, with a non-monotonic pattern between them. Differences in station mix, terrain and observation coverage can contribute to these profiles.</p>
        <p>NDVI bin means span roughly {min(map(Mean, Ndvi)):.2f}–{max(map(Mean, Ndvi)):.2f} °C in this sample. The precipitation panel retains the supplied proxy on a log scale; it cannot establish a response to daily precipitation totals.</p>""",
        "Urbanization": f"""<p>The very-low-density rural class averages {Mean(UrbanByClass["Very low density rural"]):.2f} °C, and urban centres average {Mean(UrbanByClass["Urban centre"]):.2f} °C. The semi-dense urban cluster class has the largest mean, {Mean(UrbanByClass["Semi-dense urban cluster"]):.2f} °C, with a wider interval and only {int(UrbanByClass["Semi-dense urban cluster"]["n_stations"]):,} nominal station IDs. These associations are not an isolated estimate of the urban heat-island effect.</p>""",
        "UrbanTable": Table(
            ["Land class", "Mean (°C)", "95% interval (°C)", "Observations", "Station IDs"],
            [
                [
                    Row["bin"],
                    f"{Mean(Row):.3f}",
                    f"{float(Row['ci_low']):.3f} to {float(Row['ci_high']):.3f}",
                    f"{int(Row['n_observations']):,}",
                    f"{int(Row['n_stations']):,}",
                ]
                for Row in Urban
            ],
            Numeric=(1, 2, 3, 4),
        ),
        "FeatureTable": Table(
            ["Covariate", "Available observations"],
            [
                [Name.replace("_", " "), f"{Count:,}"]
                for Name, Count in Metadata["feature_samples"].items()
            ],
            Numeric=(1,),
        ),
        "Ndvi": f"""<p><strong>{Summary["ndvi_observed_rows"]:,} values use the observed season; {Summary["ndvi_extrapolated_rows"]:,} are explicitly extrapolated; {Summary["ndvi_missing_rows"]:,} remain missing.</strong> Extrapolations account for {100 * Summary["ndvi_extrapolated_rows"] / Rows:.1f}% of the full temperature sample.</p>
        <p>When a seasonal raster is unavailable, the latest earlier raster from the same seasonal quarter is carried forward. Future rasters are never used, and spatial nodata stays missing. Source filenames, date ranges, year lags and flags distinguish extrapolation from observed vegetation.</p>""",
        "NdviTable": Table(
            ["Years carried", "Source-seasons", "MAE", "RMSE", "Mean observed − proxy"],
            [
                [
                    Row["years_carried"],
                    f"{Row['station_seasons']:,}",
                    f"{Row['mae']:.4f}",
                    f"{Row['rmse']:.4f}",
                    f"{Row['mean_error_observed_minus_proxy']:+.4f}",
                ]
                for Row in Summary["ndvi_backtest"]
            ],
            Numeric=(0, 1, 2, 3, 4),
        ),
        "Poststrat": f"""<p>The unweighted baseline gives equal weight to each of <strong>{int(Post[0]["n_stations"]):,} nominal land-station means</strong>, representing {int(Post[0]["n_observations"]):,} observations. It is therefore different from the observation-weighted headline mean. Reweighting by DEGURBA and the exploratory GREG calibration change the estimate as shown below.</p>""",
        "PoststratTable": Table(
            ["Estimator", "Mean residual (°C)", "95% bootstrap interval (°C)"],
            [
                [
                    Row["estimator"],
                    f"{Mean(Row):+.4f}",
                    f"{float(Row['ci_low']):+.4f} to {float(Row['ci_high']):+.4f}",
                ]
                for Row in Post
            ],
            Numeric=(1, 2),
        ),
        "Provenance": f"<p>Dataset SHA-256: <code>{Summary['cleaned_data_sha256']}</code>.</p><p>Quantile profiles use {Metadata['bootstrap']:,} bootstrap replicates with base seed {Metadata['seed']}. The exploratory station estimates use 1,000 replicates with seed 0. All website means and intervals are read from saved analysis tables.</p>",
    }
    Counts = {Row["exclusion_reason"]: Row["len"] for Row in Summary["exclusions"]}
    Remaining = Audit["input_rows"]
    Selection = [["Supplied station–ERA5 pairs", "0", f"{Remaining:,}"]]
    for Label, Removed in [
        ("Outside supplied ERA5 footprint", Audit["outside_grid_rows"]),
        ("Substituted land cell", Counts.get("era5_land_fallback", 0)),
        ("Quarantined station series", Counts.get("station_series_quarantined", 0)),
        ("Invalid observation source", Counts.get("invalid_observation_source", 0)),
        ("Source location selects another cell", Counts.get("source_location_grid_mismatch", 0)),
        ("Repeated source and date", Counts.get("reused_source_observation", 0)),
    ]:
        Remaining -= Removed
        Selection.append([Label, f"{Removed:,}", f"{Remaining:,}"])
    if Remaining != Rows:
        raise ValueError("Sequential exclusions do not reconcile")
    Data["SelectionTable"] = Table(
        ["Selection step", "Removed at this step", "Retained pairs"], Selection, Numeric=(1, 2)
    )
    Data[
        "Validation"
    ] = f"""<p>Every in-grid input pair was checked against the supplied daily ERA5 files: <strong>{Summary["input_rows"]:,} station-days with zero recorded value mismatches</strong>. Station temperatures were checked against original TX values with Q_TX = 0. This validates extraction and arithmetic against those sources, not the upstream aggregation or the original instruments.</p>
      <p>Station-only rules flagged {Summary["source_flagged_observations"]:,} unique source-days and quarantined {Summary["quarantined_stations"]:,} nominal series. The main sample retains mixed daily observation windows. The separate documented UTC-window subset contains <strong>{Summary["utc_aligned_rows"]:,} pairs at {Summary["utc_aligned_stations"]:,} station IDs</strong>.</p>"""
    Captions = (FiguresDirectory / "captions.txt").read_text().strip().split("\n\n")
    Data["MapFigure"] = Figure(
        Output,
        "figures/paper/04_station_map",
        "Figure 1. Station residuals",
        "European station map with larger positive residuals in several coastal and mountainous regions.",
        "Each point is the mean for a nominal station series at its nominal location. "
        + Captions[4].split(": ", 1)[1],
    )
    Data["CovariatesFigure"] = Figure(
        Output,
        "figures/paper/01_covariates",
        "Figure 2. Covariate profiles",
        "Six binned profiles: residuals rise with station temperature, fall across wind bins and have non-monotonic elevation and coast-distance profiles.",
        Captions[1].split(": ", 1)[1] + " Shading gives pointwise 95% station-bootstrap intervals.",
        Multi=True,
    )
    Data["UrbanFigure"] = Figure(
        Output,
        "figures/paper/02_urbanization",
        "Figure 3. Urbanization",
        "Residual means and uncertainty by seven land urbanization classes.",
        Captions[2].split(": ", 1)[1],
    )
    Data["InteractionsFigure"] = Figure(
        Output,
        "figures/paper/03_interactions",
        "Figure 4. Joint covariate bins",
        "Two heatmaps of residual means by temperature and wind, and by elevation and coast distance.",
        Captions[3].split(": ", 1)[1],
        Multi=True,
    )
    Data["NdviFigure"] = Figure(
        Output,
        "figures/notebooks/cleaning_process/ndvi_coverage",
        "Figure 5. NDVI availability",
        "Counts of observed, seasonally extrapolated and missing NDVI values.",
        "Coverage within the full screened temperature sample. Seasonal carry-forward is explicitly distinguished from observed NDVI.",
    )
    Data["PoststratFigure"] = Figure(
        Output,
        "figures/notebooks/poststrat_analysis/estimates",
        "Figure 6. Exploratory station reweighting",
        "Naive, post-stratified and GREG station estimates with 95 percent bootstrap intervals.",
        "Points and 95% percentile intervals from 1,000 station bootstrap resamples. The reference population is held fixed in these intervals; the methodological limitations above and below remain.",
    )
    TemplateDirectory = ProjectRoot / "assets/site"
    (Output / "index.html").write_text(
        Template((TemplateDirectory / "index.html").read_text()).substitute(Data)
    )
    (Output / "styles.css").write_text(
        ReportCss() + "\n" + (TemplateDirectory / "styles.css").read_text()
    )
    (Output / "report.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="0;url=index.html"><title>ERA5 analysis</title></head><body><p><a href="index.html">Continue to the updated ERA5 analysis</a>.</p></body></html>\n'
    )
    Inputs = [
        AnalysisDataDirectory / "clean/summary.json",
        AnalysisDataDirectory / "cleaning_audit/summary.json",
        FiguresDirectory / "metadata.json",
        ProjectRoot / "src/py/scripts/build_pages.py",
        *sorted((FiguresDirectory / "tables").glob("*.csv")),
        *sorted(TemplateDirectory.iterdir()),
    ]
    Manifest = {
        "updated": Updated,
        "data_sha256": Summary["cleaned_data_sha256"],
        "observations": Rows,
        "station_ids": Stations,
        "notebooks": PublicExports,
        "inputs": {str(File.relative_to(ProjectRoot)): Digest(File) for File in Inputs},
        "files": {
            str(File.relative_to(Output)): Digest(File)
            for File in sorted(Output.rglob("*"))
            if File.is_file()
        },
    }
    WriteJson(Output / "data/site-manifest.json", Manifest)
    return Manifest


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument(
        "--output", dest="Output", type=Path, default=ReportsDirectory / "github-pages"
    )
    Parser.add_argument(
        "--notebooks", dest="Notebooks", type=Path, default=ReportsDirectory / "era5-notebooks"
    )
    Parser.add_argument("--date", dest="Updated", default=Date.today().isoformat())
    Args = Parser.parse_args()
    Output = Args.Output.resolve()
    if Output.exists() and not (Output / ".era5-generated-site").is_file():
        raise ValueError("Use an empty output location or an existing generated site")
    Output.parent.mkdir(parents=True, exist_ok=True)
    with Tempfile.TemporaryDirectory(prefix=".era5-pages-", dir=Output.parent) as Temporary:
        Pending = Path(Temporary) / "site"
        Manifest = Build(Pending, Args.Notebooks, Args.Updated)
        if Output.exists():
            Shutil.rmtree(Output)
        Shutil.move(str(Pending), Output)
    print(
        f"Built {Output / 'index.html'}: {len(Manifest['files'])} files, {Manifest['observations']:,} observations.",
        flush=True,
    )


if __name__ == "__main__":
    Main()
