"""Refresh manuscript tables from the screened release and saved notebook estimates."""

import argparse as Argparse
import hashlib as Hashlib
import json as Json

import polars as Pl

from py.cleaning import FeatureRows
from py.paths import AnalysisDataDirectory, NotebookFiguresDirectory, ProjectRoot


def WriteTable(Directory, Name, Caption, Label, Headers, Rows, Compact=False):
    Lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\footnotesize" if Compact else r"\small",
        *(
            [
                r"\setlength{\tabcolsep}{4pt}",
                r"\captionsetup{font=footnotesize,skip=4pt,width=0.8\linewidth}",
            ]
            if Compact
            else []
        ),
        rf"\caption{{{Caption}}}",
        rf"\label{{{Label}}}",
        r"\fitwidetable{%",
        r"\begin{tabular}{l" + "r" * (len(Headers) - 1) + "}",
        r"\toprule",
        " & ".join(Headers) + r" \\",
        r"\midrule",
        *(" & ".join(map(str, Row)) + r" \\" for Row in Rows),
        r"\bottomrule",
        r"\end{tabular}}",
        r"\end{table}",
    ]
    (Directory / f"{Name}.tex").write_text("\n".join(Lines) + "\n")


def Main():
    Argparse.ArgumentParser(description=__doc__).parse_args()
    Source = AnalysisDataDirectory / "clean/analysis.parquet"
    Release = Json.loads((Source.parent / "summary.json").read_text())
    with Source.open("rb") as Stream:
        Digest = Hashlib.file_digest(Stream, "sha256").hexdigest()
    if Digest != Release["cleaned_data_sha256"]:
        raise ValueError("Dataset differs from the saved cleaning release")
    Frame = Pl.read_parquet(Source)
    Directory = ProjectRoot / "paper/tables"
    Directory.mkdir(exist_ok=True)
    Count, Stations = len(Frame), Frame["STAID"].n_unique()
    Audit = Json.loads((AnalysisDataDirectory / "cleaning_audit/summary.json").read_text())
    Exclusions = {Row["exclusion_reason"]: Row["len"] for Row in Release["exclusions"]}
    Remaining = Audit["input_rows"]
    Selection = [{"step": "Raw matched input", "removed": 0, "remaining": Remaining}]
    for Name, Removed in (
        ("Outside grid footprint", Audit["outside_grid_rows"]),
        ("Substituted land cell", Exclusions.get("era5_land_fallback", 0)),
        ("Quarantined station series", Exclusions.get("station_series_quarantined", 0)),
        ("Invalid observation source", Exclusions.get("invalid_observation_source", 0)),
        ("Source-location grid mismatch", Exclusions.get("source_location_grid_mismatch", 0)),
        ("Repeated source-day", Exclusions.get("reused_source_observation", 0)),
    ):
        Remaining -= Removed
        Selection.append({"step": Name, "removed": Removed, "remaining": Remaining})
    if Remaining != Count:
        raise ValueError("Sequential exclusions do not reconcile with the manuscript sample")
    Pl.DataFrame(Selection).write_csv(Directory / "cleaning_selection.csv")
    WriteTable(
        Directory,
        "cleaning_selection",
        "Sequential selection. Counts removed at each step "
        "refer only to rows surviving preceding steps.",
        "tab:cleaning-selection",
        ["Step", "Removed", "Remaining"],
        [[Row["step"], f"{Row['removed']:,}", f"{Row['remaining']:,}"] for Row in Selection],
    )
    Continuous = []
    for Column in (
        "station_celsius",
        "era5_celsius",
        "residual",
        "wind",
        "tp",
        "dist_to_sea_km",
        "elevation",
        "ndvi",
    ):
        Values = FeatureRows(Frame, [Column])[Column]
        Continuous.append(
            {
                "variable": Column,
                "missing": Count - len(Values),
                "mean": Values.mean(),
                "std": Values.std(),
                **{
                    f"p{Q:02}": Values.quantile(Q / 100, interpolation="linear")
                    for Q in (5, 25, 50, 75, 95)
                },
            }
        )
    Pl.DataFrame(Continuous).write_csv(Directory / "descriptive_continuous.csv")
    WriteTable(
        Directory,
        "descriptive_continuous",
        "Continuous variables in the screened sample. Missing counts include nonfinite "
        "and invalid elevation values. Temperatures are in degrees Celsius, wind is the "
        "magnitude of the daily mean vector (m/s), and precipitation is a proxy in metres.",
        "tab:desc_continuous",
        ["Variable", "Missing", "Mean", "SD", "P05", "P25", "P50", "P75", "P95"],
        [
            [
                Row["variable"].replace("_", r"\_"),
                f"{Row['missing']:,}",
                *(f"{Row[Key]:.3g}" for Key in ("mean", "std", "p05", "p25", "p50", "p75", "p95")),
            ]
            for Row in Continuous
        ],
    )
    for Name, Columns, Caption, Label, Headers in (
        (
            "descriptive_degurba",
            ["degurba", "degurba_label"],
            "DEGURBA coverage in the screened sample. A nominal station ID may occur in "
            "more than one class when its observation source changes.",
            "tab:desc_degurba",
            ["Code", "Class"],
        ),
        (
            "descriptive_countries",
            ["country"],
            "Top ten countries by nominal station count; "
            "percentages refer to the full screened sample.",
            "tab:desc_country_top10",
            ["Country"],
        ),
    ):
        Counts = (
            Frame.group_by(Columns)
            .agg(Pl.len().alias("observations"), Pl.col("STAID").n_unique().alias("stations"))
            .with_columns(
                (100 * Pl.col("observations") / Count).alias("observation_percent"),
                (100 * Pl.col("stations") / Stations).alias("station_percent"),
            )
        )
        Counts = (
            Counts.sort("degurba")
            if Name == "descriptive_degurba"
            else Counts.sort(["stations", "country"], descending=[True, False])
        )
        Counts.write_csv(Directory / f"{Name}.csv")
        Display = Counts if Name == "descriptive_degurba" else Counts.head(10)
        WriteTable(
            Directory,
            Name,
            Caption,
            Label,
            [*Headers, "Observations", r"Obs. (\%)", "Station IDs", r"IDs (\%)"],
            [
                [
                    *(str(Row[Key]).replace("&", r"\&") for Key in Columns),
                    f"{Row['observations']:,}",
                    f"{Row['observation_percent']:.1f}",
                    f"{Row['stations']:,}",
                    f"{Row['station_percent']:.1f}",
                ]
                for Row in Display.to_dicts()
            ],
            Compact=Name == "descriptive_countries",
        )
    WriteTable(
        Directory,
        "data_summary",
        "Screened temperature-pair sample; "
        "each figure uses available values for its own covariates.",
        "tab:data-summary",
        ["Quantity", "Value"],
        [
            ["Nominal station IDs", f"{Stations:,}"],
            ["Station-days", f"{Count:,}"],
            ["Time period", f"{Frame['date'].min():%Y-%m-%d} to {Frame['date'].max():%Y-%m-%d}"],
            ["Countries covered", Frame["country"].n_unique()],
            [
                r"Residual mean (SD), $^\circ$C",
                f"{Frame['residual'].mean():.2f} ({Frame['residual'].std():.2f})",
            ],
        ],
    )
    Ranges, Inputs = [], {}
    for Name, Label, Pattern in (
        ("pdp_station_celsius", "Station temperature", "Increasing"),
        ("pdp_wind", "Mean wind vector", "Decreasing"),
        ("pdp_dist_to_sea_km", "Distance to sea", "Non-monotonic; lower inland"),
        ("degurba", "DEGURBA land classes", "Non-monotonic across classes"),
        ("pdp_elevation", "Elevation", "Non-monotonic"),
        ("pdp_tp", "Precipitation proxy", "Small variation"),
        ("pdp_ndvi", "NDVI", "Small variation"),
    ):
        File = NotebookFiguresDirectory / "resid_analysis" / f"{Name}.vl.json"
        Spec = Json.loads(File.read_text())
        Means = [Row["mean"] for Rows in Spec["datasets"].values() for Row in Rows if "mean" in Row]
        Ranges.append(
            {"variable": Label, "pattern": Pattern, "low": min(Means), "high": max(Means)}
        )
        Inputs[str(File.relative_to(ProjectRoot))] = Hashlib.sha256(File.read_bytes()).hexdigest()
    Pl.DataFrame(Ranges).write_csv(Directory / "results_summary.csv")
    WriteTable(
        Directory,
        "results_summary",
        "Descriptive ranges of the mean residual across the displayed bins or land classes. "
        "These ranges are not tests of statistical significance.",
        "tab:results-summary",
        ["Covariate", "Observed pattern", r"Range ($^\circ$C)"],
        [
            [Row["variable"], Row["pattern"], f"{Row['low']:.2f}--{Row['high']:.2f}"]
            for Row in Ranges
        ],
    )
    (Directory / "table_sources.json").write_text(
        Json.dumps(
            {
                "data": str(Source.relative_to(ProjectRoot)),
                "data_sha256": Digest,
                "observations": Count,
                "station_ids": Stations,
                "notebook_specifications": Inputs,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"Updated manuscript tables in {Directory}")


if __name__ == "__main__":
    Main()
