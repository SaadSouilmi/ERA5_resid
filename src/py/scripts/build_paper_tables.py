"""Rebuild manuscript tables from the current source-window numerical analyses."""

import argparse
import json
from pathlib import Path

import polars as pl

from py import analysis_common as common
from py.analysis_catalog import ANALYSES, WEATHER_ANALYSES
from py.paths import NotebookFiguresDirectory, ProjectRoot

DIRECTORY = ProjectRoot / "paper/tables"


def tex_escape(value):
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "_": r"\_",
        "#": r"\#",
        "°": r"$^\circ$",
        "×": r"$\times$",
        "−": "-",
        "–": "--",
        "≥": r"$\geq$",
    }
    return "".join(replacements.get(char, char) for char in str(value))


def format_value(value):
    if value is None:
        return "---"
    if isinstance(value, float):
        return f"{value:.4g}"
    if isinstance(value, int):
        return f"{value:,}"
    return tex_escape(value)


def write_table(name, table, caption, label, headers=None):
    table.write_csv(DIRECTORY / f"{name}.csv")
    headers = headers or [column.replace("_", " ") for column in table.columns]
    lines = [
        r"\begin{table}[htbp]",
        r"\centering",
        r"\small",
        f"\\caption{{{tex_escape(caption)}}}",
        f"\\label{{{label}}}",
        r"\fitwidetable{%",
        r"\begin{tabular}{l" + "r" * (table.width - 1) + "}",
        r"\toprule",
        " & ".join(tex_escape(header) for header in headers) + r" \\",
        r"\midrule",
        *[" & ".join(format_value(value) for value in row) + r" \\" for row in table.iter_rows()],
        r"\bottomrule",
        r"\end{tabular}}",
        r"\end{table}",
    ]
    (DIRECTORY / f"{name}.tex").write_text("\n".join(lines) + "\n")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    DIRECTORY.mkdir(exist_ok=True)
    temperature = common.DATA_DIRECTORY / "station_era5_clean.parquet"
    digest = common.sha256(temperature)
    results, tables, manifests = {}, {}, {}
    for name, *_ in ANALYSES:
        directory = common.OUTPUT_DIRECTORY / name
        manifest_path = directory / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest["inputs"].get(str(temperature)) != digest:
            raise ValueError(f"Rerun {name}: its temperature sample differs")
        if name in WEATHER_ANALYSES and not manifest["hourly_weather_included"]:
            raise ValueError(f"Complete the hourly-weather rerun for {name}")
        result = json.loads((directory / "results.json").read_text())
        if common.sha256(directory / "results.json") != manifest["results_sha256"]:
            raise ValueError(f"Results changed after {name}'s manifest was saved")
        tables[name] = {}
        for label, item in result["tables"].items():
            path = Path(item["file"])
            if common.sha256(path) != item["sha256"]:
                raise ValueError(f"Source table changed: {path}")
            tables[name][label] = pl.read_csv(path)
        results[name] = result
        manifests[str(manifest_path)] = common.sha256(manifest_path)
    descriptive = tables["descriptive"]
    write_table(
        "descriptive_continuous",
        descriptive["continuous"].drop("observations"),
        "Continuous variables in the current source-day sample. Temperatures: °C; wind: magnitude of the window-mean vector (m/s); precipitation: station-window total (m). Negative precipitation values remain in this descriptive table and are flagged in the covariates.",
        "tab:desc_continuous",
    )
    write_table(
        "descriptive_degurba",
        descriptive["degurba"],
        "Current DEGURBA coverage at actual source coordinates, including water. Percentages use all retained source-days; the land-class figure omits water.",
        "tab:desc_degurba",
    )
    countries = descriptive["countries"].sort("sources", descending=True)
    write_table(
        "descriptive_countries",
        countries.head(10),
        "Top ten countries by distinct observation-source count. Percentages use the full current sample; source counts replace nominal blended station counts.",
        "tab:desc_country_top10",
    )
    countries.write_csv(DIRECTORY / "descriptive_countries_all.csv")
    summary = results["descriptive"]["summary"]
    overview = pl.DataFrame(
        {
            "Quantity": [
                "Source-days",
                "Actual sources (SOUID)",
                "Nominal station IDs",
                "First date",
                "Last date",
                "Countries",
                "Mean residual (°C)",
                "Source-bootstrap 95% interval (°C)",
            ],
            "Value": [
                f"{summary['observations']:,}",
                f"{summary['sources']:,}",
                f"{summary['nominal_station_ids']:,}",
                summary["first_date"],
                summary["last_date"],
                str(summary["countries"]),
                f"{summary['mean']:.3f}",
                f"{summary['ci_low']:.3f} to {summary['ci_high']:.3f}",
            ],
        }
    )
    write_table(
        "data_summary",
        overview,
        "Current window-matched source-day temperature sample; covariates are selected separately by analysis.",
        "tab:data-summary",
    )
    clean = json.loads(
        (common.DATA_DIRECTORY / "cleaning_audit/station_era5_clean.json").read_text()
    )
    monthly = json.loads(
        (common.DATA_DIRECTORY / "cleaning_audit/station_era5_monthly.json").read_text()
    )
    selection = pl.DataFrame(
        {
            "Step": [
                "After station-only selection and study period",
                "Inside hourly download boundaries",
                "Complete provider-window matches",
                "Unique source-days",
            ],
            "Remaining": [
                monthly["input_records"],
                clean["input_records"],
                clean["matched_provider_records"],
                clean["source_days"],
            ],
        }
    )
    selection = selection.with_columns(
        (pl.col("Remaining").shift(1) - pl.col("Remaining")).fill_null(0).alias("Removed")
    )
    write_table(
        "cleaning_selection",
        selection.select("Step", "Removed", "Remaining"),
        "Sequential selection after provider quality, geography, spike, range and study-period filtering. The final step removes repeated source-days. Upstream station-only rules are documented in the preprocessing note.",
        "tab:cleaning-selection",
    )
    figure_directory = NotebookFiguresDirectory / "partial_dependence"
    profile_manifest = json.loads((figure_directory / "manifest.json").read_text())
    if profile_manifest["inputs"].get(str(temperature)) != digest:
        raise ValueError("Rebuild the residual profiles for the current temperature sample")
    ranges = []
    for feature in [*common.FEATURES, "degurba"]:
        path = (
            figure_directory
            / "tables"
            / ("degurba.csv" if feature == "degurba" else f"pdp_{feature}.csv")
        )
        curve = pl.read_csv(path)
        low, high = curve["mean"].min(), curve["mean"].max()
        ranges.append(
            {
                "Covariate": feature,
                "Minimum mean (°C)": low,
                "Maximum mean (°C)": high,
                "Range (°C)": high - low,
            }
        )
        manifests[str(path)] = common.sha256(path)
    write_table(
        "results_summary",
        pl.DataFrame(ranges),
        "Ranges of observed residual means across current quantile bins or land classes. These descriptive ranges are not significance tests or causal effects.",
        "tab:results-summary",
    )
    for name, title, _, table_name, columns in ANALYSES:
        if table_name:
            table = tables[name][table_name].select(columns)
        elif name == "fixed_effects":
            rows = []
            for feature in ["station_celsius", "era5_celsius", "midpoint", "wind"]:
                curve = tables[name][f"{feature}_within"]
                rows.append(
                    {
                        "Conditioning anomaly": feature,
                        "Lowest-bin residual": curve["mean"][0],
                        "Highest-bin residual": curve["mean"][-1],
                        "Difference (°C)": curve["mean"][-1] - curve["mean"][0],
                    }
                )
            table = pl.DataFrame(rows)
        elif name == "geographic_deciles":
            table = pl.concat(
                [
                    tables[name][feature]
                    .select("decile", "x_low", "x_high", "observations", "sources", "mean")
                    .with_columns(pl.lit(feature).alias("feature"))
                    for feature in ["dist_to_sea_km", "elevation"]
                ]
            )
        else:
            rows = []
            for model in ["gradient_boosting", "gradient_boosting_relative_elevation"]:
                for group in tables[name][f"{model}_profiles"].partition_by("feature"):
                    rows.append(
                        {
                            "model": model,
                            "feature": group["feature"][0],
                            "grid_low": group["x"].min(),
                            "grid_high": group["x"].max(),
                            "prediction_min": group["mean"].min(),
                            "prediction_max": group["mean"].max(),
                            "prediction_range": group["mean"].max() - group["mean"].min(),
                        }
                    )
            table = pl.DataFrame(rows)
        write_table(
            f"numerical_{name}",
            table,
            title
            + ". Methods, analysis-specific denominators and source tables are recorded in the numerical-analysis note and per-analysis manifests.",
            f"tab:numerical-{name.replace('_', '-')}",
        )
    tables["mos"]["metrics"].write_csv(DIRECTORY / "numerical_mos_all_metrics.csv")
    tables["multivariate"]["coefficients"].write_csv(
        DIRECTORY / "numerical_multivariate_all_coefficients.csv"
    )
    metadata = {
        "input": str(temperature),
        "input_sha256": digest,
        "source_days": summary["observations"],
        "sources": summary["sources"],
        "analysis_manifests": manifests,
        "tables": {path.name: common.sha256(path) for path in DIRECTORY.glob("numerical_*.csv")},
        "entry_point": "py.scripts.build_paper_tables",
    }
    (DIRECTORY / "table_sources.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Rebuilt current manuscript tables in {DIRECTORY}", flush=True)


if __name__ == "__main__":
    main()
