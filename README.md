# European station–ERA5-Land residuals

Compare ECA&D daily maximum temperatures with hourly ERA5-Land maxima over each
source's verified UTC observation window. Residual = station − ERA5-Land, in °C.

The current temperature sample is `data2/station_era5_clean.parquet`: **6,726,213
source-days**, **4,458 sources**, 1 January 2020–31 August 2025. Covariates stay in
separate Parquet files and join through the loader.

- [Preprocessing](notes/PREPROCESSING.md): inputs, ordered filters, matching and covariates.
- [Observation windows](notes/OBSERVATION_WINDOWS.md): provider conventions and sources.
- [Numerical analysis](notes/NUMERICAL_ANALYSIS.md): methods, plots and available results.
- [Cleanup record](notes/CLEANUP.md): retained scope, archive and remaining publication work.

## Load the data

```sh
uv sync --locked
```

```python
from py.load_data import load_data

data = load_data()
data_with_weather = load_data(include_weather=True)
```

The second call requires `data2/station_hourly_weather.parquet`. The hourly weather
job is downloading its inputs; aggregation and the full numerical rerun are queued.
The numerical note distinguishes completed results from pending weather analyses.

Both calls return Polars DataFrames and preserve the temperature rows and order.
NDVI uses the original seasonal rasters, with the latest earlier valid value
carried forward across missing seasons. Source dates, lag and extrapolation flags
remain available. Missing pixels within existing seasons remain missing.

## Rebuild

Large inputs stay local and ignored. Required inputs are listed in the
[preprocessing note](notes/PREPROCESSING.md#inputs). Supply the ECA&D files, hourly
temperature NetCDFs, original NDVI rasters, GHS-SMOD raster, cached coastline and
verified window-rule CSVs before rebuilding.

```sh
./run.sh
```

This starts the `station-preprocessing` tmux session and runs:

1. Cache the station files; select quality-valid European observations inside the grid.
2. Remove isolated spikes, apply −60°C to 50°C bounds, restrict the study period.
3. Resolve source coordinates and UTC windows; match nearest ERA5 cells.
4. Calculate complete-window temperature maxima and retain unique eligible source-days.
5. Build coastal distance, seasonal NDVI, source elevation and land cover lookups.
6. Retrieve hourly wind/rain and aggregate them over the saved station windows.

Logs: `data2/preprocessing.log`. Status: `data2/preprocessing.status`; `0` means
success. The tmux session ends with the command. Do not start a second rebuild
while the current hourly-weather job is running.

The optional temperature retrieval command is
`uv run python -m py.preprocessing.download_era5_hourly prepare`, followed by
`download`. Its default period is 2020-01-01 through 2025-08-31. Preparation writes
a request plan without submitting downloads. CDS configuration stays local in
`~/.cdsapirc`, `CDSAPI_RC`, or ignored `data2/.cdsapirc`.

To resume weather retrieval, aggregation and all queued analyses, use
`bash src/py/preprocessing/hourly_weather.sh` in a dedicated tmux session.
Follow `data2/hourly_weather.log`, `data2/hourly_weather.status` and
`data2/cleaning_audit/hourly_weather_progress.json`. Completed downloads are reused.

## Analyses

```sh
bash src/py/scripts/run_numerical_analysis.sh
```

The runner starts its own tmux session. It exports DEGURBA, six residual profiles
and four interaction plots, then runs the fourteen modules below and refreshes
manuscript tables and the numerical note. It requires the hourly weather lookup.

| Module under `src/py/` | Analysis |
|:---|:---|
| `analysis_descriptive.py` | Sample, coverage and residual distribution |
| `analysis_utc_windows.py` | UTC-window sensitivity and companion profiles |
| `analysis_exceedances.py` | Hot-day thresholds and count ratios |
| `analysis_heat_excess.py` | Daily-maximum heat excess above 24°C |
| `analysis_heatwaves.py` | Consecutive hot spells |
| `analysis_seasonal.py` | Seasonal temperature × wind |
| `analysis_fixed_effects.py` | Within-source monthly anomalies |
| `analysis_multivariate.py` | Joint adjusted regression |
| `analysis_covariate_tests.py` | Source-clustered tests across deciles |
| `analysis_ndvi_sensitivity.py` | Observed-season versus carried-forward NDVI |
| `analysis_geographic_deciles.py` | Geographic bin coverage |
| `analysis_relative_elevation.py` | Elevation relative to nearby sources |
| `analysis_mos.py` | Bias correction with held-out sources |
| `analysis_model_partial_dependence.py` | Fitted-model partial dependence |

Each module can also run as `uv run python -m py.analysis_<name>` inside a dedicated
tmux session. Method definitions and caveats are in the numerical note.

Figures, CSV source tables, results and manifests live under
`figures/notebooks/{partial_dependence,interactions,numerical_analysis}/`.
The folder name is retained for output-path compatibility; the active workflow
uses Python modules. Models and predictions stay local in `data2/numerical_analysis/`.

Current plotting entry points are `py.scripts.plot_degurba`,
`plot_partial_dependence`, `plot_interactions` and `plot_station_map`.
The station map uses actual source locations and the approved Plotly/OpenStreetMap
renderer. To restyle saved figures without refitting, use
`py.scripts.restyle_note_figures`; `py.scripts.plot_bootstrap_means` previews the
bootstrap distributions. Default exports are PNG/PDF.

## Manuscript

`paper/paper.tex` is the working draft. Its existing numerical text and publication
assets still need reconciliation with the current release. The bibliography
`paper/downscaling.bib` is missing. See [paper/README.md](paper/README.md).

After the full rerun and station-map export, `py.scripts.sync_paper_figures` copies
only the draft's selected PDFs, their CSV/specification sources and input manifests.
Use `--check` to validate those sources without copying. It rejects figures whose
sample or weather inputs differ. `py.scripts.build_paper_tables` builds the current
CSV/LaTeX tables after all required analyses finish.

## Layout

All active Python lives in `src/py`: preprocessing in `preprocessing/`, analyses
in the package root and commands in `scripts/`. Paths come from
`py.paths`. Keep datasets, credentials, logs and models out of Git.

Historical notebooks, earlier sample builders, website exports and separate NDVI
acquisition experiments are archived outside the active tree. Git commit `5ee9293`
also preserves the earlier workflow. The registered `report/` worktree, local
inputs, environments and running download remain available.
