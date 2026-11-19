"""Refresh the numerical-analysis note from current saved results and source tables."""

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

import polars as pl

from py import analysis_common as common
from py.analysis_catalog import ANALYSES, NOTES, WEATHER_ANALYSES
from py.paths import NotebookFiguresDirectory, ProjectRoot

NOTE = ProjectRoot / "notes/NUMERICAL_ANALYSIS.md"
ASSETS = NOTE.parent / "assets"


def local_link(path):
    import os

    return Path(os.path.relpath(path, NOTE.parent)).as_posix()


def result_tables(name):
    directory = common.OUTPUT_DIRECTORY / name
    result = json.loads((directory / "results.json").read_text())
    tables = {label: pl.read_csv(item["file"]) for label, item in result["tables"].items()}
    return result, tables


def display_table(table):
    labels = {
        "variable": "Variable",
        "sample": "Sample",
        "observations": "Source-days",
        "sources": "Sources",
        "missing": "Missing",
        "mean": "Mean",
        "sd": "SD",
        "ci_low": "95% low",
        "ci_high": "95% high",
        "threshold_celsius": "Threshold (°C)",
        "station_days": "Station days",
        "era5_days": "ERA5 days",
        "estimate": "Station / ERA5",
        "measure": "Counted",
        "station_count": "Station",
        "era5_count": "ERA5",
        "feature": "Covariate",
        "range_celsius": "Bin range (°C)",
        "wald_f": "Wald F",
        "p_value": "p",
        "station_total_celsius_days": "Station heat excess (°C·days)",
        "era5_total_celsius_days": "ERA5 heat excess (°C·days)",
        "term": "Term",
        "coefficient": "Coefficient",
        "cluster_se": "Cluster SE",
        "season": "Season",
        "elevation_band": "Elevation band",
        "mean_relative_elevation_m": "Relative height (m)",
        "percent_below_neighbours": "Below neighbours (%)",
        "mean_source_residual": "Mean source residual (°C)",
        "model": "Model",
        "mean_bias_celsius": "Bias (°C)",
        "mae_celsius": "MAE (°C)",
        "rmse_celsius": "RMSE (°C)",
        "hot30_recall_percent": ">30°C recall (%)",
        "hot35_recall_percent": ">35°C recall (%)",
        "decile": "Decile",
        "x_low": "Bin low",
        "x_high": "Bin high",
    }
    return common.markdown_table(
        table.rename({column: labels[column] for column in table.columns if column in labels})
    )


def degurba_section():
    source = NotebookFiguresDirectory / "partial_dependence"
    ASSETS.mkdir(exist_ok=True)
    for extension in ("png", "pdf"):
        shutil.copy2(source / f"degurba_seaborn.{extension}", ASSETS / f"degurba.{extension}")
    for path in [
        source / "degurba_manifest.json",
        *(source / "tables").glob("degurba*.csv"),
    ]:
        shutil.copy2(path, ASSETS / path.name)
    manifest = json.loads((source / "degurba_manifest.json").read_text())
    frame = pl.read_csv(source / "tables/degurba.csv").sort("degurba_label")
    display = frame.select(
        pl.col("degurba_label").alias("Class"),
        pl.col("mean").alias("Mean (°C)"),
        pl.col("ci_low").alias("95% low"),
        pl.col("ci_high").alias("95% high"),
        pl.col("observations").alias("Source-days"),
        pl.col("sources").alias("Sources"),
        (100 * pl.col("observation_share")).alias("Sample (%)"),
    )
    lines = [
        "# Numerical analysis",
        "",
        "## 1. DEGURBA partial dependence",
        "",
        "![Mean residual and observation share by DEGURBA class](assets/degurba.png)",
        "",
        "Upper panel: mean **station maximum − ERA5-Land maximum**, with pointwise 95% source-bootstrap intervals. Lower panel: share of all retained source-days. [PDF](assets/degurba.pdf) · [Source table](assets/degurba.csv).",
        "",
        f"The current sample contains **{manifest['input_records']:,} source-days**. The seven land classes contain **{manifest['plotted_observations']:,} observations**; **{manifest['omitted_observations']:,} water-class observations** are omitted. Shares retain the full-sample denominator. The 2020 GHS-SMOD classification is sampled at actual source coordinates and held fixed over time.",
        "",
        common.markdown_table(display, digits=2),
        "",
        "These are unadjusted, observation-weighted class means. Intervals use 1,000 draws of SOUIDs within each class, retaining each source's days together; seed 1337. The figure preserves the paper's layout, colours and displayed class order, with Seaborn styling and light horizontal grids. Class differences do not isolate an urbanisation effect.",
        "",
        "[Coverage](assets/degurba_coverage.csv) · [Source classifications](assets/degurba_sources.csv) · [Manifest](assets/degurba_manifest.json)",
        "",
    ]
    lowest, highest = frame.sort("mean").row(0, named=True), frame.sort("mean").row(-1, named=True)
    lines += [
        f"Class means range from **{lowest['mean']:+.2f}°C** ({lowest['degurba_label']}) to **{highest['mean']:+.2f}°C** ({highest['degurba_label']}, **{highest['sources']:,} sources**).",
        "",
    ]
    return lines, manifest


def select_display(name, tables, table_name, columns):
    if not table_name:
        return None
    table = tables[table_name]
    if name == "exceedances":
        table = table.filter(pl.col("sample") == "all")
    if name == "multivariate":
        table = table.filter(~pl.col("term").str.starts_with("month_"))
    return table.select(columns)


def refresh(require_complete=False):
    lines, degurba = degurba_section()
    first = datetime.strptime(str(degurba["first_date"]), "%Y%m%d").strftime("%-d %B %Y")
    last = datetime.strptime(str(degurba["last_date"]), "%Y%m%d").strftime("%-d %B %Y")
    expected = common.sha256(common.DATA_DIRECTORY / "station_era5_clean.parquet")
    if expected != degurba["inputs"][str(common.DATA_DIRECTORY / "station_era5_clean.parquet")]:
        raise ValueError(
            "Rebuild DEGURBA for the current temperature sample before refreshing the note"
        )
    lines += [
        "## 2. Sample and interpretation",
        "",
        f"Study period: **{first}–{last}**. One source-day is one `(SOUID, DATE)`. All temperatures use resolved provider UTC windows and complete hourly ERA5 coverage, including both boundary samples. Resolved 12-hour and 23/25-hour windows remain included. Wind and rain use those same windows. The pipeline retains the temperature sample and selects available covariates per analysis.",
        "",
        "NDVI uses the original seasonal rasters; dates without a raster carry forward the latest earlier valid location value across seasons. Source dates and extrapolation flags remain available. The separate NDVI acquisition archive is not used.",
        "",
        "The additional analyses below are reruns of the ZIP's `pending_remarks_analysis.py` and `supplemental_v3_checks.py`. They use the current sample, rather than the earlier 6.96-million-row release. Bootstrap and clustered inference use actual observation sources (`SOUID`), replacing nominal blended station IDs. Unless stated otherwise, bootstrap intervals use 1,000 draws and seed 1337. They address within-source dependence, not dependence between nearby sources.",
        "",
        "## 3. Descriptive residual profiles",
        "",
        f"![Quantile-binned residual profiles]({local_link(NotebookFiguresDirectory / 'partial_dependence/partial_dependence.png')})",
        "",
        "Observation-weighted means in ten quantile bins, with pointwise source-bootstrap intervals. These are descriptive conditional means. Station temperature also enters the residual definition. Each vertical range follows its mean curve and confidence band.",
        "",
        f"[Profile tables]({local_link(NotebookFiguresDirectory / 'partial_dependence/tables')}/) · [Manifest]({local_link(NotebookFiguresDirectory / 'partial_dependence/manifest.json')})",
        "",
        "## 4. Cross-interaction profiles",
        "",
        f"![Joint-bin residual heatmaps]({local_link(NotebookFiguresDirectory / 'interactions/interactions.png')})",
        "",
        "Eight quantile bins per numeric axis; seven land DEGURBA classes. Cells show observation-weighted mean residuals, with all available observations in the marginal histograms. Each panel has its own colour scale. No cell confidence intervals are shown.",
        "",
    ]
    profile_manifest = json.loads(
        (NotebookFiguresDirectory / "partial_dependence/manifest.json").read_text()
    )
    if "wind" not in profile_manifest["features"]:
        location = lines.index("## 4. Cross-interaction profiles")
        lines[location:location] = [
            "**Hourly weather pending:** the current composite contains the four available profiles. All six are queued after hourly aggregation.",
            "",
        ]
    interaction_manifest = json.loads(
        (NotebookFiguresDirectory / "interactions/manifest.json").read_text()
    )
    if len(interaction_manifest["pairs"]) < 4:
        lines += [
            "**Hourly wind pending:** the current composite contains elevation × coast and coast × DEGURBA. The two wind panels are queued.",
            "",
        ]
    pending = []
    inventory = []
    for number, (name, title, figure, table_name, columns) in enumerate(ANALYSES, start=5):
        directory = common.OUTPUT_DIRECTORY / name
        result_path = directory / "results.json"
        source = ProjectRoot / f"src/py/analysis_{name}.py"
        lines += [f"## {number}. {title}", "", NOTES[name], ""]
        status = "Pending"
        if result_path.exists():
            manifest = json.loads((directory / "manifest.json").read_text())
            current = (
                manifest["inputs"].get(str(common.DATA_DIRECTORY / "station_era5_clean.parquet"))
                == expected
            )
            if current:
                result, tables = result_tables(name)
                partial = name in WEATHER_ANALYSES and not manifest["hourly_weather_included"]
                status = "Weather portion pending" if partial else "Complete"
                if partial:
                    pending.append(name)
                    lines += [
                        "**Partial rerun:** temperature and static-covariate results are current; hourly-weather results are pending.",
                        "",
                    ]
                image = directory / f"{figure}.png"
                lines += [f"![{title}]({local_link(image)})", ""]
                display = select_display(name, tables, table_name, columns)
                if display is not None:
                    lines += [display_table(display), ""]
                if name == "descriptive":
                    summary = result["summary"]
                    lines += [
                        f"Mean disagreement: **{summary['mean']:+.2f}°C**, 95% source-bootstrap interval **{summary['ci_low']:.2f}–{summary['ci_high']:.2f}°C**. Giving every source equal weight gives **{summary['source_weighted_mean']:+.2f}°C**.",
                        "",
                    ]
                if name == "heat_excess":
                    ratio = result["summary"]["estimate"]
                    message = (
                        f"The station heat-excess total is **{ratio:.2f} times** the ERA5-Land total over the same retained source-days."
                        if ratio is not None
                        else "The ERA5-Land heat-excess total is zero; the station/ERA5 ratio is undefined."
                    )
                    lines += [message, ""]
                if name == "ndvi_sensitivity":
                    observed = (
                        tables["wald_tests"]
                        .filter(pl.col("sample") == "observed_only")
                        .row(0, named=True)
                    )
                    lines += [
                        f"Observed-only decile means span **{observed['range_celsius']:.3f}°C**; the source-clustered equality test gives **p = {observed['p_value']:.3g}**.",
                        "",
                    ]
                if name == "multivariate":
                    summary = result["summary"]
                    lines += [
                        f"Complete-case sample: **{summary['observations']:,} observations**, **{summary['sources']:,} sources**; R² = **{summary['r_squared']:.3f}**.",
                        "",
                    ]
                if name == "relative_elevation":
                    summary = result["summary"]
                    lines += [
                        f"Proxy available at **{summary['sources_with_two_neighbours']:,} sources**. Source-level Pearson r = **{summary['pearson_r']:.3f}**; descriptive slope = **{summary['slope_celsius_per_100m']:.3f}°C per 100 m**.",
                        "",
                    ]
                if name == "fixed_effects":
                    rows = []
                    for feature in ["station_celsius", "era5_celsius", "midpoint", "wind"]:
                        key = f"{feature}_within"
                        if key in tables:
                            table = tables[key]
                            rows.append(
                                {
                                    "Conditioning anomaly": feature,
                                    "Lowest-bin residual": table["mean"][0],
                                    "Highest-bin residual": table["mean"][-1],
                                    "High − low (°C)": table["mean"][-1] - table["mean"][0],
                                }
                            )
                    lines += [common.markdown_table(pl.DataFrame(rows)), ""]
                if name == "geographic_deciles":
                    for feature in ["dist_to_sea_km", "elevation"]:
                        lines += [
                            display_table(
                                tables[feature].select(
                                    "decile", "x_low", "x_high", "observations", "sources", "mean"
                                )
                            ),
                            "",
                        ]
                if name == "utc_windows" and not partial:
                    lines += [
                        f"![UTC covariate profiles]({local_link(directory / 'utc_profiles.png')})",
                        "",
                    ]
                if name == "model_partial_dependence":
                    lines += [
                        f"![Fitted model including relative elevation]({local_link(directory / 'gradient_boosting_relative_elevation.png')})",
                        "",
                    ]
                lines += [
                    f"[PDF]({local_link(directory / f'{figure}.pdf')}) · [Tables]({local_link(directory / 'tables')}/) · [Methods and results]({local_link(result_path)}) · [Input manifest]({local_link(directory / 'manifest.json')})",
                    "",
                ]
            else:
                pending.append(name)
                lines += [
                    "**Pending:** saved results use a different temperature sample and are not displayed.",
                    "",
                ]
        else:
            pending.append(name)
            lines += [
                "**Pending rerun.** Weather-dependent sections run automatically after hourly aggregation.",
                "",
            ]
        inventory.append(
            {"Analysis": title, "File": f"[{source.name}]({local_link(source)})", "Status": status}
        )
    lines += [
        "## Reproduction",
        "",
        common.markdown_table(pl.DataFrame(inventory)),
        "",
        "Run all sections in a dedicated tmux session:",
        "",
        "```bash",
        "bash src/py/scripts/run_numerical_analysis.sh",
        "```",
        "",
        "Run one analysis with `uv run python -m py.analysis_<name>` in its own tmux session. The full runner refreshes DEGURBA, all six descriptive profiles, four interaction plots, the additional analyses, manuscript tables and this note. Each analysis writes its own CSV tables, PNG/PDF figures, results and input/code hashes under `figures/notebooks/numerical_analysis/<name>/`.",
        "",
        "Progress: `data2/numerical_analysis.progress.json`; log: `data2/numerical_analysis.log`; exit status: `data2/numerical_analysis.status` (`0` means success). The existing hourly-weather job is configured to invoke this runner after aggregation. No new NDVI acquisition is started.",
        "",
        f"**Rerun status:** {len(ANALYSES) - len(pending)}/{len(ANALYSES)} additional analysis files complete."
        if pending
        else "**Rerun status:** all additional analyses complete; current tables and figures use the input hashes recorded in their manifests.",
        "",
    ]
    if require_complete and pending:
        raise ValueError(f"Analyses still pending: {', '.join(pending)}")
    NOTE.write_text("\n".join(lines))
    print(f"Updated {NOTE}; {len(pending)} analyses pending", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true")
    refresh(parser.parse_args().require_complete)


if __name__ == "__main__":
    main()
