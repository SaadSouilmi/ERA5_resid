"""Build screened temperature pairs and independently documented covariates."""

import argparse as Argparse
import hashlib as Hashlib
import html as Html
import json as Json
import urllib.request as UrlRequest

import numpy as Np
import polars as Pl
import xarray as Xr

from py.covariates import AddSeasonalNdvi, CoastDistances, SampleRaster
from py.paths import AnalysisDataDirectory, RawDataDirectory, ReportsDirectory
from py.report_style import StyleHtml
from py.scripts.audit_cleaning import VerifyGridValues
from py.temperature_quality import (
    ObservationSources,
    SelectTemperaturePairs,
    SourceTemperatureEvidence,
)


def Digest(File):
    with File.open("rb") as Stream:
        return Hashlib.file_digest(Stream, "sha256").hexdigest()


def HtmlTable(Rows):
    if not Rows:
        return "<p>No rows.</p>"
    Columns = list(Rows[0])
    Header = "<tr>" + "".join(f"<th>{Html.escape(Name)}</th>" for Name in Columns) + "</tr>"
    Body = "".join(
        "<tr>" + "".join(f"<td>{Html.escape(str(Row[Name]))}</td>" for Name in Columns) + "</tr>"
        for Row in Rows
    )
    return "<table>" + Header + Body + "</table>"


def AttachSourceGrid(Frame):
    Sources = Frame.select(
        "STAID", "SOUID", "source_lat", "source_lon", "era5_lat", "era5_lon"
    ).unique()
    File = (
        RawDataDirectory / "derived-era5-land-daily-statistics/2020_2m_temperature_daily_maximum.nc"
    )
    with Xr.open_dataset(File) as Grid:
        Lats, Lons = Sources["source_lat"].to_numpy(), Sources["source_lon"].to_numpy()
        Valid = Np.isfinite(Lats) & Np.isfinite(Lons)
        Y = Grid.indexes["latitude"].get_indexer(Np.where(Valid, Lats, 0), method="nearest")
        X = Grid.indexes["longitude"].get_indexer(Np.where(Valid, Lons, 0), method="nearest")
        Same = (
            Valid
            & (Np.abs(Lats - Grid.latitude.values[Y]) <= 0.050001)
            & (Np.abs(Lons - Grid.longitude.values[X]) <= 0.050001)
        )
        Same &= Np.isclose(
            Grid.latitude.values[Y], Sources["era5_lat"].to_numpy(), atol=1e-7, rtol=0
        ) & Np.isclose(Grid.longitude.values[X], Sources["era5_lon"].to_numpy(), atol=1e-7, rtol=0)
    return Frame.join(
        Sources.select("STAID", "SOUID").with_columns(Pl.Series("source_same_grid_cell", Same)),
        on=["STAID", "SOUID"],
        how="left",
        validate="m:1",
    ).with_columns(
        Pl.col("observation_window")
        .is_in(["TX3", "TX21"])
        .fill_null(False)
        .alias("utc_day_aligned")
    )


def NdviDiagnostics(Frame, Output):
    Rows = []
    Observed = (
        Frame.filter(Pl.col("ndvi_method") == "observed_season")
        .select("SOUID", "ndvi_source_start", "ndvi")
        .unique()
        .with_columns(
            Pl.col("ndvi_source_start").dt.year().alias("year"),
            Pl.col("ndvi_source_start").dt.month().alias("season"),
        )
    )
    for Lag in (1, 2):
        Proxy = Observed.select(
            "SOUID", "season", (Pl.col("year") + Lag).alias("year"), Pl.col("ndvi").alias("proxy")
        )
        Held = Observed.join(Proxy, on=["SOUID", "year", "season"], how="inner", validate="1:1")
        Error = Held["ndvi"] - Held["proxy"]
        Rows.append(
            {
                "years_carried": Lag,
                "station_seasons": len(Held),
                "mae": Error.abs().mean(),
                "rmse": float(Np.sqrt((Error**2).mean())) if len(Held) else None,
                "mean_error_observed_minus_proxy": Error.mean(),
            }
        )
    Pl.DataFrame(Rows).write_csv(Output / "ndvi_backtest.csv")
    Comparisons = []
    for Name, Subset in [
        ("observed_only", Frame.filter(~Pl.col("ndvi_is_extrapolated"))),
        ("observed_plus_extrapolated", Frame),
    ]:
        Comparisons.append(
            Subset.filter(Pl.col("ndvi").is_not_null())
            .with_columns(
                (((Pl.col("ndvi") + 1) / 0.2).floor().clip(0, 9) * 0.2 - 1).alias("ndvi_bin_lower")
            )
            .group_by("ndvi_bin_lower")
            .agg(
                Pl.len().alias("observations"),
                Pl.col("STAID").n_unique().alias("stations"),
                Pl.col("residual").mean().alias("mean_residual"),
            )
            .with_columns(Pl.lit(Name).alias("sample"))
        )
    Pl.concat(Comparisons).sort("sample", "ndvi_bin_lower").write_csv(
        Output / "ndvi_sensitivity.csv"
    )
    return Rows


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument(
        "--reuse-checks",
        dest="ReuseChecks",
        action="store_true",
        help="Reuse provenance and full ERA5 checks completed for the current processing-cleaned input",
    )
    Args = Parser.parse_args()
    AuditFile = AnalysisDataDirectory / "cleaning_audit/summary.json"
    RawFile, InputFile = (
        AnalysisDataDirectory / "residuals.parquet",
        AnalysisDataDirectory / "residuals_cleaned.parquet",
    )
    GridMatchesFile = AnalysisDataDirectory / "cleaning_audit/station_grid_matches.csv"
    MissingFiles = [
        File for File in (RawFile, InputFile, AuditFile, GridMatchesFile) if not File.is_file()
    ]
    if MissingFiles:
        Missing = "\n".join(
            f"  {File.relative_to(AnalysisDataDirectory.parent)}" for File in MissingFiles
        )
        Parser.error(
            "required local inputs are missing:\n"
            f"{Missing}\n"
            "These data are not included in a Git clone or installed by uv. Restore the "
            "original data files listed in README.md, including data2/residuals.parquet, "
            "then run `uv run python -m py.scripts.audit_cleaning` before this build."
        )
    Output = AnalysisDataDirectory / "clean"
    Output.mkdir(exist_ok=True)
    Audit = Json.loads(AuditFile.read_text())
    if (
        Digest(RawFile) != Audit["input_sha256"]
        or Digest(InputFile) != Audit["cleaned_data_sha256"]
    ):
        raise ValueError("Inputs changed; rerun the processing audit first")
    Frame = Pl.read_parquet(InputFile)
    Matches = Pl.read_csv(AnalysisDataDirectory / "cleaning_audit/station_grid_matches.csv").filter(
        Pl.col("inside_era5_grid")
    )
    if Args.ReuseChecks:
        Cached = Json.loads((Output / "checks_manifest.json").read_text())
        for Name, Expected in Cached.items():
            if Digest(AnalysisDataDirectory / Name) != Expected:
                raise ValueError(f"Cached checks are stale: {Name}")
        Sources = Pl.read_parquet(Output / "observation_sources.parquet")
        GridChecks = Pl.read_csv(Output / "era5_full_checks.csv")
    else:
        Sources = ObservationSources(Frame, Output)
        Sources.write_parquet(Output / "observation_sources.parquet")
        GridChecks = VerifyGridValues(Frame, Matches, AllDates=True)
        GridChecks.write_csv(Output / "era5_full_checks.csv")
        CheckedFiles = [
            InputFile,
            Output / "observation_sources.parquet",
            Output / "era5_full_checks.csv",
            Output / "station_source_files.csv",
        ]
        (Output / "checks_manifest.json").write_text(
            Json.dumps(
                {
                    str(File.relative_to(AnalysisDataDirectory)): Digest(File)
                    for File in CheckedFiles
                },
                indent=2,
            )
            + "\n"
        )
    if GridChecks["sampled_station_days"].sum() != len(Frame) or any(
        GridChecks[Name].sum() for Name in GridChecks.columns if Name.endswith("mismatches")
    ):
        raise ValueError("Full ERA5 validation failed or has incomplete coverage")
    Frame = AttachSourceGrid(Frame.join(Sources, on=["STAID", "date"], how="left", validate="1:1"))
    if Frame["SOUID"].null_count() or Frame["Q_TX"].null_count():
        raise ValueError("Observation provenance is incomplete")
    print("Screening station temperatures independently of ERA5", flush=True)
    SourceEvidence = SourceTemperatureEvidence(Frame)
    Flags = SourceEvidence.filter(Pl.col("source_review_required"))
    Flags.join(
        Frame.select("STAID", "date", "SOUID", "place", "country"),
        on=["SOUID", "date"],
        validate="1:m",
    ).write_csv(Output / "temperature_review.csv")
    SuspectSources = Flags["SOUID"].unique().to_list()
    Evidence = Frame.select("STAID", "SOUID", "date").join(
        SourceEvidence, on=["SOUID", "date"], how="left", validate="m:1"
    )
    SuspectStations = (
        Frame.filter(Pl.col("SOUID").is_in(SuspectSources))["STAID"].unique().to_list()
    )
    StationQuality = (
        Evidence.group_by("STAID")
        .agg(
            Pl.len().alias("observations"),
            Pl.col("source_range_flag").sum(),
            Pl.col("source_spatial_flag").sum(),
            Pl.col("source_spike_flag").sum(),
            (Pl.col("neighbor_count") < 3).sum().alias("days_without_spatial_check"),
        )
        .with_columns(Pl.col("STAID").is_in(SuspectStations).alias("quarantined"))
    )
    StationQuality.sort("STAID").write_csv(Output / "station_quality.csv")
    Clean, Excluded = SelectTemperaturePairs(Frame, SuspectStations)
    Clean = Clean.with_columns(
        Pl.col("elevation").alias("nominal_station_elevation"),
        Pl.col("source_elevation").alias("elevation"),
    )
    Excluded.select(
        "STAID", "SOUID", "date", "station_celsius", "era5_celsius", "residual", "exclusion_reason"
    ).write_parquet(Output / "excluded_pairs.parquet")
    CoreColumns = [
        "STAID",
        "SOUID",
        "date",
        "country",
        "place",
        "lat",
        "lon",
        "elevation",
        "station_celsius",
        "era5_celsius",
        "residual",
        "Q_TX",
        "source_metadata_id",
        "source_metadata_id_offset",
        "source_lat",
        "source_lon",
        "source_elevation",
        "observation_window",
        "utc_day_aligned",
        "era5_lat",
        "era5_lon",
        "era5_distance_km",
    ]
    Core = Clean.select(CoreColumns)
    Core.write_parquet(Output / "temperature_pairs.parquet")
    Core.filter(Pl.col("utc_day_aligned")).write_parquet(Output / "temperature_pairs_utc.parquet")
    print(f"Screened pairs: {len(Core):,}; {Core['STAID'].n_unique():,} stations", flush=True)
    Clean = AddSeasonalNdvi(Clean, IdColumn="SOUID", Coordinates=("source_lat", "source_lon"))
    Stations = (
        Clean.select(
            Pl.col("SOUID").alias("STAID"),
            Pl.col("source_lat").alias("lat"),
            Pl.col("source_lon").alias("lon"),
        )
        .unique()
        .sort("STAID")
    )
    DegurbaFile = (
        AnalysisDataDirectory
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    Degurba = SampleRaster(DegurbaFile, Stations)
    Codes = {
        10: "Water",
        11: "Very low density rural",
        12: "Low density rural",
        13: "Rural cluster",
        21: "Suburban",
        22: "Semi-dense urban cluster",
        23: "Dense urban cluster",
        30: "Urban centre",
    }
    Degurba = Np.where(Np.isin(Degurba, list(Codes)), Degurba, Np.nan)
    Classes = (
        Stations.select("STAID")
        .with_columns(Pl.Series("degurba", Degurba).fill_nan(None).cast(Pl.Int32))
        .with_columns(Pl.col("degurba").replace_strict(Codes, default=None).alias("degurba_label"))
    )
    CoastFile = Output / "sources/ne_10m_coastline.zip"
    CoastFile.parent.mkdir(exist_ok=True)
    if not CoastFile.exists():
        UrlRequest.urlretrieve(
            "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_coastline.zip", CoastFile
        )
    Coast = CoastDistances(Stations, CoastFile)
    OldStations = Clean.group_by("STAID").agg(
        Pl.col("dist_to_sea_km").first().alias("old_coast_km"),
        Pl.col("degurba").first().alias("old_degurba"),
    )
    Covariates = Classes.join(Coast, on="STAID", validate="1:1").rename({"STAID": "SOUID"})
    Clean.select("STAID", "SOUID").unique().join(OldStations, on="STAID", validate="m:1").join(
        Covariates, on="SOUID", validate="m:1"
    ).write_csv(Output / "station_covariate_comparison.csv")
    Clean = (
        Clean.drop("degurba", "degurba_label", "dist_to_sea_km")
        .join(Covariates, on="SOUID", how="left", validate="m:1")
        .with_columns(
            Pl.col("tp").alias("precipitation_proxy_m"),
            Pl.col("wind").alias("mean_wind_vector_mps"),
            Pl.lit(
                "Natural Earth 1:10 million coastline; EPSG:3035 nearest point, WGS84 distance"
            ).alias("coast_distance_method"),
            Pl.lit(2020).alias("degurba_reference_year"),
        )
        .sort("STAID", "date")
    )
    Clean.write_parquet(Output / "analysis.parquet")
    Backtest = NdviDiagnostics(Clean, Output)
    Counts = Excluded.group_by("exclusion_reason").len().sort("exclusion_reason")
    Counts.write_csv(Output / "exclusion_counts.csv")
    Core.group_by("observation_window", "utc_day_aligned").agg(
        Pl.len().alias("observations"), Pl.col("STAID").n_unique().alias("stations")
    ).write_csv(Output / "observation_windows.csv")
    Core.group_by("country").agg(
        Pl.len().alias("observations"), Pl.col("STAID").n_unique().alias("stations")
    ).sort("country").write_csv(Output / "country_coverage.csv")
    Notes = [
        "The original and processing-cleaned inputs are preserved. This release adds conservative station-only screening, source provenance, and separately recalculated covariates. Quarantine is a reproducible review policy, not a claim that every excluded reading is erroneous.",
        "Station-only review flags use TX outside [-60,50] Celsius, an isolated >20 Celsius jump against both adjacent calendar days, or >20 Celsius disagreement with at least three same-day neighbours. Screening operates on unique source-days, at actual source coordinates. Up to ten distinct locations are selected among the 64 closest, 15–100 km away and within 300 m elevation. Missing neighbours do not imply a passed spatial check. These are provisional thresholds, not a calibrated QC algorithm. All series sharing a flagged observation source are quarantined. ERA5 residuals do not select exclusions.",
        "The conservative table excludes nearest-land substitutions and observations whose source coordinates select another ERA5 grid cell. Repeated (SOUID,date) observations are retained once, choosing the smallest eligible STAID deterministically. Distinct source identifiers can still describe related instruments; this is not proof of independent stations.",
        "The supplied sources.txt uses identifiers 100000 higher than participant-observation files, while synoptic identifiers match directly. This offset was inferred from unique within-station matches across the supplied release; it is recorded explicitly, and ambiguous matches fail. Raw SOUID and matched metadata identifiers are both preserved. Provider confirmation of the identifier convention would strengthen provenance.",
        "All retained input temperatures, precipitation proxies and mean-vector wind magnitudes were compared with the supplied daily ERA5 files on every saved station-day. Station temperatures were checked against original TX and Q_TX=0. This validates extraction and arithmetic, not the original instrument or upstream ERA5 aggregation.",
        "Observation windows are retained per source. temperature_pairs_utc.parquet restricts to documented TX3/TX21 00–00 UTC windows. The broader table has mixed windows; it cannot support a claim of identical daily intervals. ERA5 maxima are maxima of hourly samples, while station sampling frequencies differ.",
        "NDVI uses its actual seasonal raster when present; otherwise it carries forward the latest earlier raster for the same season. Every value records the raster filename, dates, years carried and method. Spatial nodata stays missing. This extrapolates a seasonal vegetation pattern and does not represent measured future vegetation or a guarantee of exact periodicity.",
        "NDVI backtests compare observed station-season values with values one or two years earlier. The binned residual sensitivity table compares observed-only versus observed-plus-extrapolated samples; differences also reflect year and sample composition, not just imputation error.",
        "DEGURBA is resampled in the raster CRS using the 2020 GHS-SMOD classification. Coast distance uses global Natural Earth 1:10 million ocean coastline instead of truncated country boundaries, excluding its Caspian Sea ring. It is an approximate geographic covariate: generalized coastline, omitted small islands and nearest-point projection limit fine coastal interpretation.",
        "NDVI, DEGURBA, elevation and coast distance refer to the observation source location, including borrowed observations. Nominal station coordinates and source coordinates are both retained. A nominal station's source and covariates may change over time, so downstream station-level aggregation needs that distinction.",
        "Wind is sqrt(mean(u10)^2+mean(v10)^2) in m/s. Precipitation retains the supplied daily-mean proxy in metres; a daily total cannot be recovered defensibly without the upstream accumulation recipe. Covariate missingness does not remove otherwise valid temperature pairs.",
        "Notebook and figure manifests record the dataset used for each export. Regenerate exports after rebuilding this dataset and verify the input hashes. Paper claims and post-stratification methods require review on the chosen sample.",
    ]
    Files = [
        Output / Name
        for Name in [
            "temperature_pairs.parquet",
            "temperature_pairs_utc.parquet",
            "analysis.parquet",
            "excluded_pairs.parquet",
            "observation_sources.parquet",
        ]
    ]
    Summary = {
        "input": str(InputFile),
        "input_sha256": Digest(InputFile),
        "raw_input_sha256": Digest(RawFile),
        "output": str(Output / "analysis.parquet"),
        "cleaned_data_sha256": Digest(Output / "analysis.parquet"),
        "input_rows": len(Frame),
        "cleaned_rows": len(Clean),
        "cleaned_stations": Clean["STAID"].n_unique(),
        "quarantined_stations": len(SuspectStations),
        "source_flagged_observations": len(Flags),
        "utc_aligned_rows": Core.filter(Pl.col("utc_day_aligned")).height,
        "utc_aligned_stations": Core.filter(Pl.col("utc_day_aligned"))["STAID"].n_unique(),
        "ndvi_observed_rows": Clean.filter(Pl.col("ndvi_method") == "observed_season").height,
        "ndvi_extrapolated_rows": Clean.filter(Pl.col("ndvi_is_extrapolated")).height,
        "ndvi_missing_rows": Clean["ndvi"].null_count(),
        "mean_residual": Clean["residual"].mean(),
        "status": "Conservative screened release; mixed observation windows remain explicit, with a UTC subset available.",
        "exclusions": Counts.to_dicts(),
        "ndvi_backtest": Backtest,
        "findings": Notes,
        "artifacts": {str(File): Digest(File) for File in Files},
    }
    (Output / "summary.json").write_text(Json.dumps(Summary, indent=2) + "\n")
    CovariateFiles = [
        *sorted((RawDataDirectory / "sentinel2_ndvi").glob("*.tif")),
        DegurbaFile,
        CoastFile,
    ]
    Pl.DataFrame(
        [{"file": str(File), "sha256": Digest(File)} for File in CovariateFiles]
    ).write_csv(Output / "covariate_source_files.csv")
    Era5Files = sorted((RawDataDirectory / "derived-era5-land-daily-statistics").glob("*.nc"))
    Pl.DataFrame([{"file": str(File), "sha256": Digest(File)} for File in Era5Files]).write_csv(
        Output / "era5_source_files.csv"
    )
    Report = '<!doctype html><html><head><meta charset="utf-8"><title>Clean dataset</title></head><body><h1>Conservative temperature dataset and covariates</h1>'
    Report += "<p>Explicit screening, source provenance and seasonal NDVI extrapolation.</p><table>"
    Report += "".join(
        f"<tr><th>{Html.escape(Key)}</th><td>{Html.escape(str(Value))}</td></tr>"
        for Key, Value in Summary.items()
        if not isinstance(Value, (list, dict))
    )
    Report += (
        "</table><h2>Exclusions</h2>"
        + HtmlTable(Summary["exclusions"])
        + "<h2>Seasonal NDVI backtest</h2>"
        + HtmlTable(Backtest)
        + "<h2>Methods and limits</h2><ol>"
        + "".join(f"<li><p>{Html.escape(Note)}</p></li>" for Note in Notes)
        + "</ol>"
    )
    Report += '<p>Source documentation: <a href="https://www.ecad.eu/dailydata/datadictionaryelement.php">ECA&D observation windows</a>, <a href="https://www.ecad.eu/helptext/blending_help.html">blending</a>, <a href="https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/">coastline</a>.</p></body></html>'
    ReportFile = ReportsDirectory / "era5-notebooks/clean_dataset.html"
    ReportFile.parent.mkdir(parents=True, exist_ok=True)
    ReportFile.write_text(StyleHtml(Report))
    IndexFile = ReportFile.parent / "index.html"
    Notice = '<p id="clean-release">A <a href="clean_dataset.html">new screened dataset with documented seasonal NDVI extrapolation</a> is available. Existing notebook exports may use an earlier input; check their manifest before comparing results.</p>'
    if IndexFile.exists() and 'id="clean-release"' not in IndexFile.read_text():
        IndexFile.write_text(
            IndexFile.read_text().replace(
                "<h1>ERA5 notebook exports</h1>", "<h1>ERA5 notebook exports</h1>" + Notice
            )
        )
    print(
        Json.dumps(
            {Key: Value for Key, Value in Summary.items() if not isinstance(Value, (list, dict))},
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    Main()
