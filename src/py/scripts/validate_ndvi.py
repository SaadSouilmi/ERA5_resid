"""Compare observed NDVI with carry-forward using held-out acquisition dates."""

import argparse as Argparse
import concurrent.futures as Futures
import hashlib as Hashlib
import json as Json
from datetime import date as Date

import numpy as Np
import polars as Pl

from py.ndvi_observations import AddMonths, SceneValue, WriteJson
from py.paths import AnalysisDataDirectory


def Validate(Candidate, Lookup, Directory):
    Start = Date.fromisoformat(Candidate["season_start"])
    Previous = Lookup.get((Candidate["SOUID"], Start.replace(year=Start.year - 1)))
    Current = Lookup.get((Candidate["SOUID"], Start))
    if Candidate["ndvi_observed"] is None or Previous is None or Current is None:
        return None
    Saved = Directory / "independent_validation" / f"{Candidate['SOUID']}_{Start}.json"
    UsedDates = {Row["acquisition_date"] for Row in Candidate["accepted_scenes"]}
    if Saved.exists():
        Result = Json.loads(Saved.read_text())
        if Result["candidate"] != Candidate["ndvi_observed"]:
            raise ValueError("Cached validation has a different candidate; use a new label")
        if UsedDates & {Row["acquisition_date"] for Row in Result["heldout_scenes"]}:
            raise ValueError("Validation and candidate share acquisition dates")
        return Result
    CatalogFile = (
        Directory / "catalog" / f"catalog_{Candidate['SOUID']}_{Start}_{AddMonths(Start, 3)}.json"
    )
    Items = Json.loads(CatalogFile.read_text())
    Monthly, Heldout, Errors = [], [], []
    for Offset in range(3):
        Month = AddMonths(Start, Offset).isoformat()[:7]
        Options = sorted(
            [
                Item
                for Item in Items
                if Item["properties"]["datetime"].startswith(Month)
                and Item["properties"]["datetime"][:10] not in UsedDates
            ],
            key=lambda Item: (Item["properties"].get("eo:cloud_cover", 100), Item["id"]),
        )
        Values, Dates = [], set()
        for Item in Options[:24]:
            Day = Item["properties"]["datetime"][:10]
            if Day in Dates:
                continue
            try:
                Observation = SceneValue(Item, Candidate["cell_bounds_epsg3035"], Directory)
            except Exception as Error:
                Errors.append({"id": Item["id"], "error_type": type(Error).__name__})
                continue
            if Observation["ndvi"] is not None:
                Values.append(Observation["ndvi"])
                Dates.add(Day)
                Heldout.append(Observation)
                if len(Values) == 2:
                    break
        if Values:
            Monthly.append(float(Np.median(Values)))
    Target = float(Np.mean(Monthly)) if len(Monthly) == 3 else None
    Result = {
        "SOUID": Candidate["SOUID"],
        "season_start": str(Start),
        "country": Current["country"],
        "candidate": Candidate["ndvi_observed"],
        "carry_forward": Previous["ndvi"],
        "provider_current": Current["ndvi"],
        "independent_target": Target,
        "heldout_months": len(Monthly),
        "heldout_scenes": Heldout,
        "errors": Errors,
    }
    WriteJson(Saved, Result)
    print(f"Validation source={Candidate['SOUID']} season={Start} target={Target}", flush=True)
    return Result


def Metrics(Frame, Target):
    Frame = Frame.filter(Pl.col(Target).is_not_null()).with_columns(
        (Pl.col("candidate") - Pl.col(Target)).abs().alias("candidate_error"),
        (Pl.col("carry_forward") - Pl.col(Target)).abs().alias("carry_error"),
    )
    return {
        "source_seasons": len(Frame),
        "sources": Frame["SOUID"].n_unique(),
        "candidate_mae": Frame["candidate_error"].mean(),
        "carry_forward_mae": Frame["carry_error"].mean(),
        "candidate_better_cases": int((Frame["candidate_error"] < Frame["carry_error"]).sum()),
    }


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument("--label", dest="Label", default="sentinel2_pilot_v1")
    Parser.add_argument(
        "--missing-label", dest="MissingLabel", default="sentinel2_missing_pilot_v1"
    )
    Parser.add_argument("--workers", dest="Workers", type=int, default=8)
    Args = Parser.parse_args()
    if Args.Workers < 1 or any(
        "/" in Label or Label in ("", ".", "..") for Label in (Args.Label, Args.MissingLabel)
    ):
        Parser.error("Use positive workers and plain directory labels")
    Directory = AnalysisDataDirectory / "ndvi_observed" / Args.Label
    MissingDirectory = AnalysisDataDirectory / "ndvi_observed" / Args.MissingLabel
    ValidationDirectory = Directory / "independent_validation"
    ValidationDirectory.mkdir(exist_ok=True)
    Manifest = Json.loads((Directory / "manifest.json").read_text())
    MissingManifest = Json.loads((MissingDirectory / "manifest.json").read_text())
    if Manifest["input_sha256"] != MissingManifest["input_sha256"]:
        raise ValueError("Validation and missing-season pilots use different releases")
    Reference = Pl.read_parquet(Directory / "reference_ndvi.parquet")
    Lookup = {
        (Row["SOUID"], Row["ndvi_source_start"]): Row for Row in Reference.iter_rows(named=True)
    }
    Candidates = Pl.read_csv(Directory / "source_season_ndvi.csv")
    Cases = [
        Json.loads(
            (Directory / "seasons" / f"{Row['SOUID']}_{Row['season_start']}.json").read_text()
        )
        for Row in Candidates.iter_rows(named=True)
    ]
    with Futures.ThreadPoolExecutor(max_workers=Args.Workers) as Pool:
        Results = list(Pool.map(lambda Case: Validate(Case, Lookup, Directory), Cases))
    Rows = [
        {Key: Value for Key, Value in Row.items() if Key not in ("heldout_scenes", "errors")}
        for Row in Results
        if Row is not None
    ]
    if not Rows:
        raise ValueError("No candidates have both current and previous-year reference NDVI")
    Comparison = (
        Pl.DataFrame(Rows)
        .with_columns(
            (Pl.col("candidate") - Pl.col("independent_target")).abs().alias("candidate_abs_error"),
            (Pl.col("carry_forward") - Pl.col("independent_target")).abs().alias("carry_abs_error"),
            (Pl.col("provider_current") - Pl.col("independent_target"))
            .abs()
            .alias("provider_abs_error"),
        )
        .sort("SOUID", "season_start")
    )
    Comparison.write_csv(ValidationDirectory / "comparison.csv")
    Missing = Pl.read_csv(MissingDirectory / "source_season_ndvi.csv")
    Coverage = (
        Missing.group_by("season_start")
        .agg(
            Pl.len().alias("attempted_source_seasons"),
            Pl.col("ndvi_observed").is_not_null().sum().alias("observed_source_seasons"),
            (Pl.col("status") == "insufficient_month_coverage")
            .sum()
            .alias("insufficient_month_coverage"),
        )
        .sort("season_start")
    )
    AuditDirectory = AnalysisDataDirectory / "cleaning_audit"
    AuditDirectory.mkdir(exist_ok=True)
    Prefix = f"ndvi_{Args.Label}"
    ComparisonFile = AuditDirectory / f"{Prefix}_comparison.csv"
    CoverageFile = AuditDirectory / f"{Prefix}_missing_coverage.csv"
    Comparison.write_csv(ComparisonFile)
    Coverage.write_csv(CoverageFile)
    Summary = {
        "input_sha256": Manifest["input_sha256"],
        "candidate_label": Args.Label,
        "missing_label": Args.MissingLabel,
        "selection": "Country-stratified pilot; eligible sources have at least 12 observed historical seasons; hash seed 2026; no temperature or residual selection",
        "candidate_source_seasons": len(Candidates),
        "candidate_usable_source_seasons": Candidates["ndvi_observed"].is_not_null().sum(),
        "candidate_sources": Candidates["SOUID"].n_unique(),
        "against_existing_current_product": Metrics(Comparison, "provider_current"),
        "against_heldout_dates": Metrics(Comparison, "independent_target"),
        "heldout_definition": "Other acquisition dates from the same sensor and processing, excluded from the candidate; up to two dates per month, at most 24 scene attempts; require all three months",
        "missing_source_seasons": len(Missing),
        "missing_usable_source_seasons": Missing["ndvi_observed"].is_not_null().sum(),
        "failed_validation_fetches": len(Json.loads((Directory / "failures.json").read_text())),
        "failed_missing_fetches": len(Json.loads((MissingDirectory / "failures.json").read_text())),
        "decision": "Promising pilot; broader superiority not established; no change to the analysis release",
        "limitations": [
            "Held-out satellite observations are not independent ground truth and share sensor, masking and aggregation assumptions with the candidate",
            "Validation only covers spring and summer 2023, with a small subset having sufficient held-out coverage",
            "Original raster compositing and masking recipe is unknown; old-product agreement and held-out agreement answer different questions",
            "Sparse clear-date sampling is not a complete daily seasonal average; cloud and snow selection may be biased",
            "Quality thresholds and sampling budgets are provisional; unfilled cases are missing, not newly observed values",
            "A wider geography, season and urbanization validation is required before replacing carry-forward across the study",
        ],
        "evidence_sha256": {
            File.name: Hashlib.sha256(File.read_bytes()).hexdigest()
            for File in [ComparisonFile, CoverageFile]
        },
    }
    WriteJson(AuditDirectory / f"{Prefix}_review.json", Summary)
    print(Json.dumps(Summary, indent=2), flush=True)


if __name__ == "__main__":
    Main()
