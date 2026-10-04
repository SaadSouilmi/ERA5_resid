# ERA5-Land temperature residuals

Compare ECA&D station daily maximum temperature with ERA5-Land daily maximum
temperature across Europe. Residual = station minus ERA5, in °C.
The working paper is `paper/paper.tex`.

## Current dataset

Analyses use `data2/clean/analysis.parquet`: 6,958,414 screened station-day pairs
at 4,217 nominal station IDs, from 2020-01-01 to 2025-08-31. The original
`data2/residuals.parquet` remains unchanged. Release counts, limitations and hashes
are in [summary.json](data2/clean/summary.json).

The cleaning pipeline checks saved station values against TX/Q_TX, validates
ERA5 extraction against all supplied in-grid daily values, excludes substituted
land cells and source-location mismatches, quarantines series using station-only
evidence, and keeps each `(SOUID, date)` once. Residual magnitude is not an
exclusion rule. Screening thresholds are provisional, not validated climatological QC.

NDVI, elevation, DEGURBA and coastal distance refer to the actual observation
source, including borrowed observations. Missing NDVI seasons use the latest
earlier raster from the same season, with provenance and an extrapolation flag.
Spatial nodata stays missing. Each figure selects its own available covariates.

The main dataset retains mixed observation-day windows; the separate UTC subset
contains 3,528,147 pairs at 2,154 station IDs. Precipitation remains a proxy in
metres pending its upstream accumulation recipe. Wind is the magnitude of the
daily mean vector. Post-stratification results remain exploratory.

## Setup and layout

```bash
uv sync --locked
uv run marimo edit src/py/notebooks/cleaning_process.py
```

Active Python lives under `src/py`: analysis modules at the package root,
entry points in `py.scripts`, Marimo notebooks in `py.notebooks`, and tests in
`py.tests`. Use PascalCase for Python bindings and snake_case for filenames.
External API names, columns and serialized keys keep their required spelling.
Shared paths come from `py.paths`.

| Notebook | Purpose |
|:---|:---|
| `cleaning_process.py` | Cleaning decisions, sequential exclusions, source checks, NDVI policy and live release assertions. |
| `resid_analysis.py` | Residual maps, covariate profiles, urbanization and joint-bin figures. |
| `poststrat_analysis.py` | Exploratory station representativeness and calibration, with method caveats. |
| `data_comparison.py` | Comparison of station metadata releases; independent of cleaned residual pairs. |
| `temp_resid.py` | Inspect the current dataset; an explicit rebuild mode runs the raw matching pipeline. |

## Required local data

Large datasets are intentionally excluded from Git. To reproduce analyses,
restore the saved Parquet files and the source datasets at these paths:

| Path | Contents |
|:---|:---|
| `data2/residuals.parquet` | Preserved supplied station–ERA5 pairs. |
| `data2/residuals_cleaned.parquet` | Intermediate audit output. |
| `data2/clean/*.parquet` | Screened pairs, UTC subset, covariates, exclusions and observation provenance. |
| `data/main/ECA_blend_tx/` | Original station observations, station metadata and source metadata. |
| `data/main/derived-era5-land-daily-statistics/` | Supplied daily ERA5-Land NetCDF files. |
| `data/main/sentinel2_ndvi/` | Original dated seasonal NDVI rasters. |
| `data2/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/` | GHS-SMOD 2020 urbanization raster. |
| `data/main/gadm_410_europe.gpkg` | Boundary data required by the exploratory post-stratification notebook. |
| `data2/ECA_homblend_tx/stations.txt` | Alternative station metadata for `data_comparison.py`. |

These files are not fetched by `uv sync` and are not present in a plain Git clone.
The clean-dataset build requires `data2/residuals.parquet` and the source files
above. Once they are restored, run the processing audit before building:

```bash
uv run python -m py.scripts.audit_cleaning
uv run python -m py.scripts.build_clean_dataset
```

The audit creates `data2/residuals_cleaned.parquet` and the audit manifest used
by the clean-dataset builder. Do not substitute `residuals_rebuilt.parquet`
without reviewing its notebook export first.

The raw rebuild notebook also uses `data2/stations_data.csv` for a validated
station-distance join. Exact source-file hashes are saved in
`data2/clean/*_source_files.csv`. Natural Earth coastline data is downloaded by
the cleaning builder when absent. Do not substitute different source releases
without rebuilding and reviewing the audit.

Compact audit CSV/JSON files are versioned. Opening the cleaning notebook requires
the saved audit products and Parquet inputs; rebuilding them requires the original
sources above. Paper figures can be restyled from committed tables without raw data.

## Cleaning and exports

Run computational work in a dedicated tmux session, which ends with its command:

```bash
tmux new-session -s era5-audit 'uv run python -m py.scripts.audit_cleaning'
tmux new-session -s era5-clean 'uv run python -m py.scripts.build_clean_dataset'
tmux new-session -s era5-notebooks 'uv run python -m py.scripts.export_notebooks'
tmux new-session -s era5-figures 'uv run python -m py.scripts.build_paper_figures'
```

Run the audit before the clean build and regenerate exports after rebuilding data.
To export only the cleaning walkthrough:

```bash
tmux new-session -s era5-cleaning-html 'uv run python -m py.scripts.export_notebooks cleaning_process'
```

HTML reports, logs, `exports.json`, `index.html` and a combined notebook PDF are
written under `/home2/lobib/research-reports/saad.souilmi/era5-notebooks/`.
Set `ERA5_REPORTS_DIR` to change the report root on another machine.
`cleaning_process.html` is the full walkthrough; `clean_dataset.html` is the
generated release summary; `data_cleaning.html` records the earlier processing audit.
Export manifests identify notebook source and input hashes. The cleaning notebook
also records the audit files used in its export.

Individual Altair PDFs and self-contained Vega-Lite specifications are saved in
`paper/figures/notebooks/`, grouped by notebook. The specifications contain the exact
plotted data. Other interactive figures remain in their HTML notebooks.

The optional raw rebuild writes `data2/residuals_rebuilt.parquet`:

```bash
uv run marimo export html src/py/notebooks/temp_resid.py -o /tmp/temp_resid.html -- --rebuild
```

Review that output before adopting it as a replacement input.

## Publication figures

`paper/figures/paper/` contains:

- `01_covariates`: binned residual means and 95% station-bootstrap intervals.
- `02_urbanization`: residual means by land urbanization class.
- `03_interactions`: temperature × wind and elevation × coast-distance joint bins.
- `04_station_map`: mean residuals in a European map window.
- Individual PDF, SVG and 600 dpi PNG exports, plus `all_figures.pdf`.
- `captions.txt`, `metadata.json`, self-contained Vega-Lite specifications and CSV source tables.

Altair figures use a white background, serif text and a fixed 180 mm width.
PDF fonts are embedded; SVG text uses DejaVu Serif. Estimates weight observations
equally, with pointwise station-cluster bootstrap intervals. These are descriptive
conditional means, not model-based partial dependence or causal effects.

Restyle saved results without rerunning statistics:

```bash
uv run python -m py.scripts.build_paper_figures --from-tables
```

## Checks

```bash
tests/run.sh all
uv run ruff check src/py
uv run marimo check src/py/notebooks/*.py
```

Run these in a dedicated tmux session as well. Tests use plain functions and
`Run`/`Expect*` helpers, count failed tests, and exit with the failure count.
Individual suites are `cleaning`, `pdp`, `publication` and `layout`.

## Retired work

Historical Jupyter notebooks, duplicate Quarto/HTML reports, old cached plot data
and the standalone `build_poststrat_report.py` exporter have been removed from
the active tree. The Marimo export workflow replaces those entry points.
Unused dashboard, Jupyter and earlier modelling dependencies have been removed.
Raw rasters are excluded from the cleaned commit but stay available locally.
This cleanup does not rewrite Git history or shrink earlier commits.

Tracked historical files remain in Git history; `5ee9293` is the last pre-refactor
checkpoint. A hash-verified local archive also preserves uncommitted historical
work at `/home2/lobib/research-reports/saad.souilmi/archives/deprecated_repo_20261003.tar.gz`.
The pre-cleaning figures are retained locally in
`paper/figures/archive/before_cleaned_graphs_20261003.tar.gz`.
The nested report worktree is kept locally and ignored, rather than altering its
separate Git state.
