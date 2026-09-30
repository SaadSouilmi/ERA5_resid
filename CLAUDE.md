# ERA5 Temperature Bias Analysis — Project Briefing

## What this project is

Research project quantifying how accurate ERA5-Land reanalysis temperature data is compared to ground-truth weather station measurements across Europe, and identifying which factors drive the errors (residuals). Supervised by Charles-Albert Lehalle (École Polytechnique). Targeting a research paper.

## Key commands

```bash
uv run python <script>          # always use uv, not python3
uv run marimo edit notebooks/resid_analysis.py     # main analysis
uv run marimo edit notebooks/poststrat_analysis.py # post-stratification
uv run marimo edit notebooks/temp_resid.py         # pipeline (needs raw data)
```

## Data layout

```
data2/residuals.parquet         # main analysis dataframe — start here
data2/stations_data.csv
data2/plot_data/
data2/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/   # DEGURBA urbanization raster
```

The heavy raw data (ERA5 netCDFs, station text files, Sentinel-2 NDVI rasters) lives in `data/main/` but is **not needed** to run the analysis — everything is already in `residuals.parquet`.

## residuals.parquet schema

| Column | Description |
|---|---|
| `STAID` | Weather station ID |
| `date` | Observation date |
| `station_celsius` | Observed station temperature (°C) |
| `residual` | ERA5 minus station temperature (bias) |
| `tp` | Total precipitation (daily mean) |
| `u10`, `v10` | Wind components |
| `ndvi` | Quarterly Sentinel-2 NDVI at station location |
| `dist_to_sea_km` | Distance to nearest coastline |
| `degurba_label` | Urbanization class from GHS-SMOD (Water / Very low density rural / Low density rural / Rural cluster / Suburban / Semi-dense urban cluster / Dense urban cluster / Urban centre) |

## Current notebooks (in `notebooks/`)

All active work is in **marimo** (`.py`) notebooks — run with `uv run marimo edit <file>`:

- `resid_analysis.py` — **main analysis**: spatial bias map, PDP plots (residual vs temp/wind/NDVI/dist_to_sea), DEGURBA-conditioned residual distributions, heatmaps. Reads only `residuals.parquet`.
- `poststrat_analysis.py` — **post-stratification**: representativeness analysis of the station network, post-stratification by DEGURBA class, GREG calibration (DEGURBA + dist_to_sea), bootstrap confidence intervals (B=1000, station resampling), weight analysis, geographic correction map. Reads only `residuals.parquet` + DEGURBA raster.
- `temp_resid.py` — **pipeline notebook**: loads raw station files + ERA5 netCDFs, builds the residuals dataframe. Only needed if regenerating `residuals.parquet` from scratch; requires `data/main/`.

Deprecated/archived: `temp_residuals.ipynb`, `residual_plots.ipynb`, `era5_errors_deprecated.ipynb`, `notebooks_v0/`, `notebooks_v1/` (students' prior work — do not edit).

## What has been done

- Pipeline built: ERA5 + station data merged, residuals computed, enriched with covariates
- Spatial bias map (mean residual per station)
- PDP/scatter plots: residual vs temperature, wind, NDVI, dist_to_sea
- Residual distribution conditioned by DEGURBA urbanization class
- OLS regression: `residual ~ standardized(temp, tp, u10, v10, ndvi, dist_to_sea)`
- Diagnostic plots: standardized residuals, monthly boxplots, country-level aggregation
- **Key finding**: ERA5 bias varies systematically with temperature level, wind speed, NDVI, distance to sea, and urbanization. Linear effects captured; nonlinear and cross-effects not yet modeled.

## What is left to do (open questions for next supervisor meeting)

1. **Aggregation strategy**: At what level to aggregate results (country, city, urbanization class)? Covariate shift problem — errors measured at stations but correction needed everywhere. DEGURBA strata may be the right reference distribution.

2. **Economically meaningful metric**: Beyond RMSE/MAE/bias, define a metric that captures economic impact (energy, agriculture, insurance, health use cases).

3. **Nonlinear effects**: Capture nonlinear relationships via gradient boosting + Shapley values (students previously explored random forests and neural nets with Shapley values).

4. **Interaction effects**: Does temperature bias depend differently on NDVI in urban vs rural? Model cross-effects between covariates.

5. **Paper writing**: After converging on the 4 points above. Needs a literature review / SOTA section. Shared Overleaf planned.

## Tech stack

- Python 3.11 via `uv`
- `marimo` — interactive notebook environment (replaces Jupyter for active work)
- `polars`, `pandas`, `geopandas`, `xarray`, `rasterio`
- `plotly`, `altair` — visualization
- `statsmodels` (OLS), `scikit-learn` (preprocessing)
