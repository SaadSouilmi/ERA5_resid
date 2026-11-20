# Current results

The full run completed on **20 November 2026**. All **14 numerical analyses** use
the new station-window sample: **6,726,213 source-days**, **4,458 sources**,
1 January 2020–31 August 2025. Wind and precipitation use the saved station UTC
windows. Each analysis records its own covariate availability and subsample.

Start here when locating current results. The manuscript and the older
[numerical note](../../notes/NUMERICAL_ANALYSIS.md) have not been fully reconciled
with this run; their older pending labels do not describe the completed outputs.
Methods for the data selection are in [PREPROCESSING.md](../../notes/PREPROCESSING.md)
and [OBSERVATION_WINDOWS.md](../../notes/OBSERVATION_WINDOWS.md).

## Main figures

| Figure | Plot | Numerical source | Provenance |
|:---|:---|:---|:---|
| Source residual map | [PNG](station_map/station_map.png), [PDF](station_map/station_map.pdf) | [Source means](station_map/tables/source_means.csv) | [Manifest](station_map/manifest.json) |
| Six residual profiles | [PNG](partial_dependence/partial_dependence.png), [PDF](partial_dependence/partial_dependence.pdf) | [Tables](partial_dependence/tables/) | [Manifest](partial_dependence/manifest.json) |
| DEGURBA means and sample shares | [PNG](partial_dependence/degurba_seaborn.png), [PDF](partial_dependence/degurba_seaborn.pdf) | [Means](partial_dependence/tables/degurba.csv), [coverage](partial_dependence/tables/degurba_coverage.csv) | [Manifest](partial_dependence/degurba_manifest.json) |
| Four cross-interaction profiles | [PNG](interactions/interactions.png), [PDF](interactions/interactions.pdf) | [Tables](interactions/tables/) | [Manifest](interactions/manifest.json) |

The six profiles are station temperature, precipitation, wind, NDVI, coastal
distance and elevation. These are descriptive quantile-bin means; fitted-model
partial dependence is listed separately below.

## Numerical analyses

Each folder contains `results.json` with methods, sample counts and summaries;
`tables/*.csv` with the numerical estimates; and `manifest.json` with input hashes,
bootstrap units and generation code hashes. Later visual changes have separate
render provenance. Follow the local links below; absolute paths in JSON record
the generation machine's locations.

| Analysis | Main figure | Results and methods | Source tables |
|:---|:---|:---|:---|
| Sample and variable coverage | [PDF](numerical_analysis/descriptive/sample.pdf) | [JSON](numerical_analysis/descriptive/results.json) | [CSV](numerical_analysis/descriptive/tables/) |
| Observation-window sensitivity | [PDF](numerical_analysis/utc_windows/window_means.pdf) | [JSON](numerical_analysis/utc_windows/results.json) | [CSV](numerical_analysis/utc_windows/tables/) |
| Hot-day exceedances | [PDF](numerical_analysis/exceedances/threshold_exceedances.pdf) | [JSON](numerical_analysis/exceedances/results.json) | [CSV](numerical_analysis/exceedances/tables/) |
| Heat excess above 24°C | [PDF](numerical_analysis/heat_excess/heat_excess_by_year.pdf) | [JSON](numerical_analysis/heat_excess/results.json) | [CSV](numerical_analysis/heat_excess/tables/) |
| Hot spells of at least three days | [PDF](numerical_analysis/heatwaves/heatwave_ratios.pdf) | [JSON](numerical_analysis/heatwaves/results.json) | [CSV](numerical_analysis/heatwaves/tables/) |
| Seasonal temperature × wind | [PDF](numerical_analysis/seasonal/warmest_temperature_wind.pdf) | [JSON](numerical_analysis/seasonal/results.json) | [CSV](numerical_analysis/seasonal/tables/) |
| Within-source monthly anomalies | [PDF](numerical_analysis/fixed_effects/within_source_month.pdf) | [JSON](numerical_analysis/fixed_effects/results.json) | [CSV](numerical_analysis/fixed_effects/tables/) |
| Joint adjusted regression | [PDF](numerical_analysis/multivariate/adjusted_coefficients.pdf) | [JSON](numerical_analysis/multivariate/results.json) | [CSV](numerical_analysis/multivariate/tables/) |
| Tests across covariate deciles | [PDF](numerical_analysis/covariate_tests/decile_effect_ranges.pdf) | [JSON](numerical_analysis/covariate_tests/results.json) | [CSV](numerical_analysis/covariate_tests/tables/) |
| Observed-season NDVI sensitivity | [PDF](numerical_analysis/ndvi_sensitivity/observed_vs_carry_forward.pdf) | [JSON](numerical_analysis/ndvi_sensitivity/results.json) | [CSV](numerical_analysis/ndvi_sensitivity/tables/) |
| Geographic bin coverage | [PDF](numerical_analysis/geographic_deciles/sources_per_decile.pdf) | [JSON](numerical_analysis/geographic_deciles/results.json) | [CSV](numerical_analysis/geographic_deciles/tables/) |
| Relative elevation | [PDF](numerical_analysis/relative_elevation/neighbour_elevation_residual.pdf) | [JSON](numerical_analysis/relative_elevation/results.json) | [CSV](numerical_analysis/relative_elevation/tables/) |
| Held-out-source bias correction | [PDF](numerical_analysis/mos/held_out_source_performance.pdf) | [JSON](numerical_analysis/mos/results.json) | [CSV](numerical_analysis/mos/tables/) |
| Fitted-model partial dependence | [Standard](numerical_analysis/model_partial_dependence/gradient_boosting.pdf), [relative elevation](numerical_analysis/model_partial_dependence/gradient_boosting_relative_elevation.pdf) | [JSON](numerical_analysis/model_partial_dependence/results.json) | [CSV](numerical_analysis/model_partial_dependence/tables/) |

Companion figures: [UTC covariate profiles](numerical_analysis/utc_windows/utc_profiles.pdf)
and [bootstrap distributions of window means](numerical_analysis/utc_windows/window_bootstrap_means.pdf).
The generating code is under [src/py](../../src/py/), one `analysis_<name>.py`
module per numerical-analysis folder.

## Interpretation and reproduction

These are reruns on the new sample with source-based inference and documented
method changes, rather than a numerical replication of the earlier paper.
The retained pipeline excludes the archived post-stratification and other legacy
notebook workflows. Model training limits and held-out evaluation are documented
in the MOS results; models and predictions stay local under `data2/numerical_analysis/`.

The saved temperature sample is `data2/station_era5_clean.parquet`. Use
`py.load_data.load_data(include_weather=True)` to join its covariates. Large inputs
are ignored by Git; the compact result tables, JSON files and figures are the
reviewable outputs. Rerun commands are in the
[figure runner](../../src/py/scripts/run_numerical_analysis.py) and
[preprocessing entry point](../../src/py/preprocessing/__main__.py).
