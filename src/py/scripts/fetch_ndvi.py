"""Fetch an observed seasonal NDVI candidate without changing the screened release."""

import argparse as Argparse
import concurrent.futures as Futures
import hashlib as Hashlib
import json as Json
from datetime import date as Date

import polars as Pl
import rasterio as Rasterio

from py.ndvi_observations import AddMonths, FetchSeason, SeasonStart, WriteJson
from py.paths import AnalysisDataDirectory, RawDataDirectory


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument(
        "--sources",
        dest="Sources",
        type=int,
        default=12,
        help="Country-stratified pilot source count; 0 selects all eligible sources",
    )
    Parser.add_argument("--start", dest="Start", type=Date.fromisoformat, default=Date(2023, 3, 1))
    Parser.add_argument("--end", dest="End", type=Date.fromisoformat, default=Date(2023, 9, 1))
    Parser.add_argument("--workers", dest="Workers", type=int, default=12)
    Parser.add_argument("--label", dest="Label", default="sentinel2_pilot_v1")
    Args = Parser.parse_args()
    if (
        SeasonStart(Args.Start) != Args.Start
        or SeasonStart(Args.End) != Args.End
        or Args.End <= Args.Start
    ):
        Parser.error("Start and end must be meteorological season boundaries, with end later")
    if Args.Sources < 0 or Args.Workers < 1:
        Parser.error("Sources must be nonnegative and workers positive")
    if "/" in Args.Label or Args.Label in ("", ".", ".."):
        Parser.error("Label must be a directory name")
    Directory = AnalysisDataDirectory / "ndvi_observed" / Args.Label
    for Name in ["catalog", "scene_values", "product_metadata", "seasons"]:
        (Directory / Name).mkdir(parents=True, exist_ok=True)
    Input = AnalysisDataDirectory / "clean/analysis.parquet"
    with Input.open("rb") as Stream:
        InputHash = Hashlib.file_digest(Stream, "sha256").hexdigest()
    ManifestFile = Directory / "manifest.json"
    if ManifestFile.exists():
        Previous = Json.loads(ManifestFile.read_text())
        if Previous["input_sha256"] != InputHash:
            raise ValueError("Input changed; use a new label to avoid mixing releases")
    Frame = Pl.scan_parquet(Input)
    Reference = (
        Frame.filter(Pl.col("ndvi_method") == "observed_season")
        .group_by("SOUID", "ndvi_source_start")
        .agg(
            Pl.col("source_lat").first(),
            Pl.col("source_lon").first(),
            Pl.col("country").first(),
            Pl.col("degurba").first(),
            Pl.col("ndvi").first(),
        )
        .collect()
    )
    if Args.Sources:
        SourceTable = (
            Reference.group_by("SOUID")
            .agg(
                Pl.col("source_lat").first(),
                Pl.col("source_lon").first(),
                Pl.col("country").first(),
                Pl.col("degurba").first(),
                Pl.len().alias("seasons"),
            )
            .filter(Pl.col("seasons") >= 12)
            .with_columns(Pl.col("SOUID").hash(seed=2026).alias("selection_rank"))
            .sort("selection_rank")
        )
        Countries = (
            SourceTable.group_by("country").len().sort("len", descending=True)["country"].to_list()
        )
        Selected = []
        for Round in range(Args.Sources):
            for Country in Countries:
                Rows = SourceTable.filter(Pl.col("country") == Country)
                if Round < len(Rows):
                    Selected.append(Rows.row(Round, named=True))
                if len(Selected) >= Args.Sources:
                    break
            if len(Selected) >= Args.Sources:
                break
        SourceTable = Pl.DataFrame(Selected)
    else:
        SourceTable = (
            Frame.select("SOUID", "source_lat", "source_lon").unique().sort("SOUID").collect()
        )
    if SourceTable["SOUID"].n_unique() != len(SourceTable):
        raise ValueError("Changing coordinates within a source ID")
    SourceTable.write_csv(Directory / "selected_sources.csv")
    Reference.filter(Pl.col("SOUID").is_in(SourceTable["SOUID"].to_list())).write_parquet(
        Directory / "reference_ndvi.parquet"
    )
    RasterFile = sorted((RawDataDirectory / "sentinel2_ndvi").glob("*.tif"))[0]
    with Rasterio.open(RasterFile) as Raster:
        if Raster.crs.to_epsg() != 3035 or Raster.res != (80.0, 80.0):
            raise ValueError("Expected the documented 80 m EPSG:3035 reference grid")
        Transform = Raster.transform
    Starts = []
    Start = Args.Start
    while Start < Args.End:
        Starts.append(Start)
        Start = AddMonths(Start, 3)
    Manifest = {
        "input_sha256": InputHash,
        "collection": "sentinel-2-l2a",
        "provider": "Microsoft Planetary Computer",
        "season_starts": [Start.isoformat() for Start in Starts],
        "sources": len(SourceTable),
        "grid": "Existing 80 m EPSG:3035 cell; mean of valid native 10 m NDVI pixels with centres inside the cell; at least 50 native pixels",
        "quality": "SCL 4/5/6; nonnegative reflectances with positive sum; at least 75% valid cell coverage",
        "sampling": "Up to two distinct acquisition dates per month, ordered by tile cloud percentage; up to 16 scenes attempted per month",
        "aggregation": "Median within month, equal-weight mean across all three months; require each month",
        "reflectance": "Read quantification and per-band offsets from each product XML before computing NDVI",
        "status": "Candidate observations, not adopted into analysis.parquet",
    }
    WriteJson(ManifestFile, Manifest)
    Tasks = [(Source, Start) for Source in SourceTable.iter_rows(named=True) for Start in Starts]
    print(f"Fetching {len(Tasks)} source-seasons with {Args.Workers} workers", flush=True)
    Results, Failures = [], []
    with Futures.ThreadPoolExecutor(max_workers=Args.Workers) as Pool:
        Pending = {
            Pool.submit(FetchSeason, Source, Start, Directory, Transform): (Source, Start)
            for Source, Start in Tasks
        }
        for Future in Futures.as_completed(Pending):
            Source, Start = Pending[Future]
            try:
                Result = Future.result()
                Results.append(
                    {
                        Key: Result[Key]
                        for Key in [
                            "SOUID",
                            "source_lat",
                            "source_lon",
                            "season_start",
                            "season_end",
                            "ndvi_observed",
                            "status",
                            "valid_dates",
                            "valid_months",
                            "attempted_scenes",
                            "catalog_scenes",
                        ]
                    }
                )
                print(
                    f"{len(Results) + len(Failures)}/{len(Tasks)} source={Source['SOUID']} season={Start} "
                    f"{Result['status']} NDVI={Result['ndvi_observed']} dates={Result['valid_dates']} errors={len(Result['errors'])}",
                    flush=True,
                )
            except Exception as Error:
                Failures.append(
                    {
                        "SOUID": Source["SOUID"],
                        "season_start": str(Start),
                        "error_type": type(Error).__name__,
                    }
                )
                print(
                    f"Failed source={Source['SOUID']} season={Start}: {type(Error).__name__}",
                    flush=True,
                )
    if Results:
        Values = (
            Pl.DataFrame(Results)
            .with_columns(
                Pl.col("season_start").str.to_date(),
                Pl.col("season_end").str.to_date(),
                Pl.col("ndvi_observed").cast(Pl.Float64),
            )
            .sort("SOUID", "season_start")
        )
        Values.write_parquet(Directory / "source_season_ndvi.parquet")
        Values.write_csv(Directory / "source_season_ndvi.csv")
        print(Values.group_by("status").len(), flush=True)
    WriteJson(Directory / "failures.json", Failures)
    print(f"Saved candidate data to {Directory}; failed tasks: {len(Failures)}", flush=True)


if __name__ == "__main__":
    Main()
