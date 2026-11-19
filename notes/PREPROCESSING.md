# Data preprocessing

Select European ECA&D daily maximum temperatures for comparison with ERA5-Land over **1 January 2020–31 August 2025**. Residual = station maximum minus ERA5-Land hourly-sampled maximum, in °C. The steps below select observations, resolve their time intervals, match grid cells and calculate temperature pairs.

**Current saved stage, 18 November 2026:** all **68 monthly files** are complete. They contain **9,837,164 observations**, including **8,712,539 matched maxima**. The final [source-day sample](../data2/station_era5_clean.parquet) is saved: **6,726,213 unique source-days**, **93.2 MiB**.

The pipeline code lives in [`py.preprocessing`](../src/py/preprocessing/). Run it from the repository root with [`./run.sh`](../run.sh), which calls `uv run python -m py.preprocessing` inside a dedicated tmux session. It logs to `data2/preprocessing.log` and writes `running`, then the exit code, to `data2/preprocessing.status`; `0` means success. The session ends with the command.

| Order | Python entry point | Output under `data2/` |
|:---|:---|:---|
| 1, if the cache is absent | `py.preprocessing.build_station_cache` | `station_data.parquet` |
| 2 | `py.preprocessing.select_station_observations` | `selected_station_observations.parquet` |
| 3 | `py.preprocessing.match_era5_grid` | `selected_station_era5_grid.parquet` |
| 4 | `py.preprocessing.build_monthly_era5_pairs` | `station_era5_monthly/YYYY-MM.parquet` |
| 5 | `py.preprocessing.export_clean_station_sample` | `station_era5_clean.parquet` |
| 6 | `py.preprocessing.coastal_distance` | `station_coastal_distance.parquet` |
| 7 | `py.preprocessing.ndvi` | `station_ndvi.parquet` |
| 8 | `build_source_elevation()` in `py.preprocessing.analysis_covariates` | `station_elevation.parquet` |
| 9 | `py.preprocessing.land_cover` | `station_land_cover.parquet` |
| 10 | `py.preprocessing.download_hourly_weather` | `era5_land_hourly_weather/YYYY-MM_{u10,v10,tp}.nc` |
| 11 | `py.preprocessing.hourly_weather` | `station_hourly_weather.parquet` |

The runner reuses the raw cache and rebuilds downstream outputs. The hourly temperature download, local covariate rasters, ECA&D source metadata and reviewed observation-window rules must already be available. The hourly weather step downloads missing wind and precipitation files through CDS and reuses completed files. Each stage saves counts and provenance under `data2/cleaning_audit/`; the selection script also saves spike and range exclusions.

## Inputs

| Dataset | Contents and units |
|:---|:---|
| ECA&D blended station series | Reported temperature maxima: `TX` in tenths of °C, date `DATE` (`YYYYMMDD`), station-series ID `STAID`, observation-source ID `SOUID`, quality flag `Q_TX`. Cached in `data2/station_data.parquet`. |
| ERA5-Land | Hourly 2 m air temperature (`t2m`, Kelvin) on a 0.1° grid, January 2020–August 2025. The downloaded hourly axes define the geographic footprint; their timestamps define the study period. |

## 1. Station quality

Keep daily observations with `Q_TX == 0` and `TX != -9999`: provider-valid records with a reported temperature.

## 2. Geographic selection

Keep observation sources in [UN M49 Europe](https://unstats.un.org/unsd/methodology/m49/overview/) and inside the ERA5 extract: **34.95–69.95°N, 25.05°W–40.95°E**, including the outer half-cell margins. Iceland and the Nordic countries are included; Türkiye, Cyprus and Greenland are excluded. The eligible ISO country and territory codes are:

```text
AL AD AT AX BY BE BA BG HR CZ DK EE FO FI FR DE GI GR GG VA HU IS IE IM
IT JE LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU UA SM RS SK SI ES SJ SE
CH GB
```

Use the source's country and coordinates: blended station series can borrow observations from other locations. Join source metadata on `(STAID, SOUID)`, accounting for the +100000 participant metadata-ID offset; synoptic IDs match directly.

![European geographic selection and ERA5 extract boundary](assets/geographic_selection.png)

Blue: eligible European land. Pale blue: European land outside the extract. Gray: other countries. Orange dashed line: ERA5 boundary. Country outlines: Natural Earth, 1:50 million. [SVG](assets/geographic_selection.svg) · [PDF](assets/geographic_selection.pdf).

## 3. Isolated spikes and dips

Exclude a daily maximum **at least 25°C above both adjacent days, or at least 25°C below both**, following the spike-check convention cited in [Durre et al. (2010)](https://www.ncei.noaa.gov/pub/data/ghcn/daily/papers/durre-menne-etal2010.pdf).

Compare consecutive calendar days within the same `SOUID`; both neighbours must be present. Count borrowed observations once when calculating flags, then remove every copy of each flagged source-day. Calculate flags once, before the range and study-period filters. This removes **46 source-days, represented by 69 records**, while retaining the other days.

## 4. Temperature bounds

Keep maxima from **−60°C to 50°C, inclusive**. These provisional bounds remove another **323 records**: one below −60°C and 322 above 50°C. Original values remain unchanged in the raw archive.

## 5. Study period

Keep labelled observation dates from **1 January 2020 to 31 August 2025**, matching the hourly ERA5 download.

| Stage, in execution order | Daily records retained |
|:---|---:|
| Raw archive: 8,568 station series | 175,615,474 |
| Provider-valid observations | 133,209,364 |
| European sources | 127,711,784 |
| European sources inside ERA5 | 113,368,058 |
| After spike removal | 113,367,989 |
| After temperature bounds | 113,367,666 |
| Within the study period | **9,840,278** |

Stages before the date restriction use the full historical archive. The study-period selection contains **5,613 station-series IDs and 4,984 observation-source IDs**. Borrowed source observations can still appear in multiple station series.

## 6. Observation windows in UTC

Use each source's observation-window code (`ELEI` in `sources.txt`), country and provider. Resolve the clock, time zone and labelled date from provider definitions and checks against original observations, within each verified source/date scope. ECA&D's existing date shifts are already included in `DATE`.

Intervals include UTC calendar days, previous-day 18:00 → labelled-day 18:00, morning-to-morning windows and `TX7`'s **06:00–18:00 UTC** interval. Danish local calendar days use `Europe/Copenhagen`, spanning **23 or 25 hours** at DST transitions. Verified Luxembourg days use fixed CET (UTC+1). GSOD hourly-fallback maxima cover a UTC reporting day but retain a separate sampling flag: their exact sample times and completeness remain unknown. Detailed provider assignments and evidence are in [Observation windows](OBSERVATION_WINDOWS.md).

Save `window_start_utc`, `window_end_utc`, `window_hours`, `window_rule_id`, `window_status` and `window_sampling`. Unsupported boundaries remain null; every study-period observation is retained.

- **9,651,857 records (98.09%)** have UTC bounds, including **34,965 GSOD sampled reporting days**, explicitly labelled by `window_sampling`.
- **188,421 records (1.91%)** remain unresolved. See the [unresolved-source audit](../data2/cleaning_audit/preprocessing_unresolved_windows.csv) and [coverage table](../data2/cleaning_audit/preprocessing_window_coverage.csv).

## 7. Saved selection

[selected_station_observations.parquet](../data2/selected_station_observations.parquet) contains all **9,840,278 observations**, their raw fields, `station_celsius = TX / 10`, source coordinates, country/provider metadata and UTC-window fields. Zstandard compression: **36.6 MiB**. The [manifest](../data2/cleaning_audit/selected_station_observations.json) records counts and source hashes.

This selection precedes the geographical lookup and monthly ERA5 extraction below. The selected input retains observations whose windows extend outside the download; the monthly extraction drops them.

## 8. Geographical ERA5 lookup

Run `py.preprocessing.match_era5_grid` to match the **4,775 distinct source coordinate pairs** to the nearest coordinate on each actual hourly ERA5-Land grid axis. Exact ties use the larger coordinate. All **68 monthly files** have identical axes and array ordering. Masked cells remain at their nearest grid position; no land fallback is applied.

[selected_station_era5_grid.parquet](../data2/selected_station_era5_grid.parquet) has **7,413 rows**, one per `(STAID, SOUID, source_lat, source_lon)`, and joins to all **9,840,278 observations**. It contains the join keys, observation count, first/last labelled dates, `latitude_index`, `longitude_index`, `grid_cell_id`, `era5_lat`, `era5_lon`, `era5_cell_masked` and `grid_match_status`.

Indices are zero-based positions in the downloaded arrays. Latitude is descending; longitude is ascending. `grid_cell_id = latitude_index * 660 + longitude_index` identifies a cell on this specific grid.

| Match status | Distinct source coordinates | Station/source locations | Observations |
|:---|---:|---:|---:|
| Available cell | 4,346 | 6,782 | 8,880,929 |
| Masked cell | 429 | 631 | 959,349 |
| Outside grid footprint | 0 | 0 | 0 |

The available locations use **3,690 distinct grid cells**. The mask flag records non-finite temperature at the first downloaded hour; extraction must also respect the hourly completeness audit. This step saves spatial matches only, preserving all observations and their window metadata. The [lookup manifest](../data2/cleaning_audit/selected_station_era5_grid.json) records hashes, grid identity, matching rules and the saved-lookup join check.

## 9. Monthly observations with ERA5 maxima

`py.preprocessing.build_monthly_era5_pairs` has saved **68 files**, [2020-01.parquet through 2025-08.parquet](../data2/station_era5_monthly/). Each observation belongs to its ECA&D `DATE` month, even when its UTC interval crosses a month boundary. The script reads monthly ERA5 arrays in storage-aligned blocks, caches neighbouring months and computes maxima in NumPy batches.

Use **both endpoints**: `window_start_utc <= valid_time <= window_end_utc`. ERA5-Land `2m_temperature` is instantaneous at its UTC timestamp, with **no one-hour shift**. A 24-hour window therefore contains **25 samples**; 12-, 23- and 25-hour windows contain 13, 24 and 26 samples. Adjacent windows can share their boundary sample.

Drop observations if the start is before **2020-01-01 00:00 UTC** or the end is after **2025-08-31 23:00 UTC**. Record their input row IDs and boundaries in [station_era5_monthly_dropped.csv](../data2/cleaning_audit/station_era5_monthly_dropped.csv). In particular, a window ending at 2025-09-01 00:00 requires a sample outside this download.

Preserve the original station columns and UTC-window metadata, including `window_sampling`, and add the geographical lookup and:

| Column | Meaning |
|:---|:---|
| `observation_id` | Zero-based row position in the input Parquet identified by the manifest hash. |
| `era5_tmax_celsius` | Maximum of all required hourly samples, converted from Kelvin to °C; null unless every sample is finite. |
| `era5_expected_samples`, `era5_available_samples` | Required and finite sample counts. |
| `era5_window_closure` | `both`. |
| `era5_match_status` | `matched`, `unknown_window`, `masked_cell`, `outside_grid` or `incomplete_era5_hours`. |
| `residual_celsius` | Station maximum minus ERA5 hourly-sampled maximum, in °C. |

Unknown windows and unavailable temperatures remain as rows with null ERA5 maxima and explicit status. A matched GSOD sampled reporting day retains its sampling flag; its original sample times need not coincide with every ERA5 hour. No ERA5-based temperature filtering, interpolation or land fallback is applied.

| Extraction outcome | Observations |
|:---|---:|
| Matched maximum | **8,712,539** |
| Unknown UTC window; retained with null maximum | 188,421 |
| Masked grid cell; retained with null maximum | 936,204 |
| Outside grid / incomplete ERA5 hours | 0 |
| Total saved across 68 monthly files | **9,837,164** |
| Dropped: window extends outside the download | 3,114 |
| Selected input | **9,840,278** |

The status counts assign unknown windows before checking the grid mask; they therefore differ from the geographical lookup's mask counts. **25,696 matched records** are GSOD sampled reporting days.

The [monthly coverage table](../data2/cleaning_audit/station_era5_monthly_coverage.csv) records counts and output hashes. The [manifest](../data2/cleaning_audit/station_era5_monthly.json) records input, source and code hashes, endpoint rules, dropped counts and completion status. All 68 saved file hashes match the coverage table.

## 10. Final temperature sample

`py.preprocessing.export_clean_station_sample` writes [station_era5_clean.parquet](../data2/station_era5_clean.parquet) from the completed monthly files. It verifies their listed hashes, then applies two filters:

```python
(era5_match_status == "matched") & (window_sampling == "provider_daily_maximum")
```

Keep one row per `(SOUID, DATE)`, choosing the smallest input `observation_id`. Reject conflicting station or ERA5 temperatures, source coordinates, grid cells or UTC boundaries before deduplicating.

| Selection from the saved monthly files | Records |
|:---|---:|
| Complete provider daily maxima | 8,686,843 |
| Repeated blended records removed | 1,960,630 |
| Unique source-days | **6,726,213** |

There are **no conflicting source-days**. All resolved durations are retained, including **12-hour windows** and 23/25-hour daylight-saving days. GSOD sampled reporting days are excluded by the sampling filter.

The saved Parquet has been read back and checked: one row per source-day, the smallest eligible `observation_id`, complete ERA5 hours, finite temperatures and the recorded file hash. Residuals equal station minus ERA5 temperature. The [manifest](../data2/cleaning_audit/station_era5_clean.json) records counts and input, output and code hashes. The earlier screened release remains at `data2/clean/analysis.parquet`.

## 11. Coastal distance

[`py.preprocessing.coastal_distance`](../src/py/preprocessing/coastal_distance.py) reads the clean temperature sample and the cached [Natural Earth 1:10 million coastline](https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/) at `data2/clean/sources/ne_10m_coastline.zip`. Run this covariate step separately from the temperature pipeline:

```bash
uv run python -m py.preprocessing.coastal_distance
```

No download is needed.

For each distinct observation-source coordinate, find the nearest coastline point in **EPSG:3035**, then calculate the **WGS84 ellipsoidal distance in kilometres** to that point. Exclude the Caspian Sea ring; retain ocean coastline beyond the ERA5 footprint. This is an approximate distance because of coastline generalisation and the projected nearest-point search.

[station_coastal_distance.parquet](../data2/station_coastal_distance.parquet) contains **4,458 source locations** at **4,272 distinct coordinates**. It stores `SOUID`, `source_lat`, `source_lon`, observation count, `coast_lat`, `coast_lon` and `dist_to_sea_km`. Join on **`(SOUID, source_lat, source_lon)`**, many-to-one. All **6,726,213 observations** have a distance; the temperature Parquet is unchanged. The [manifest](../data2/cleaning_audit/station_coastal_distance.json) records coverage, method and input/output/code hashes.

## 12. Original seasonal NDVI

[`py.preprocessing.ndvi`](../src/py/preprocessing/ndvi.py) samples the 16 original rasters under `data/main/sentinel2_ndvi/` at the observation-source coordinates. They cover **1 December 2019–30 November 2023**. Valid encoded values `0..254` map to `value / 254 * 2 - 1`; `255` is nodata.

Use the matching raster within each covered season. For later dates without a raster, **carry forward the latest earlier valid value at that location, across seasons**. Thus the September–November 2023 value is normally held through August 2025. Missing pixels inside a covered season remain missing; locations without a previous value remain missing. No future season is used to fill an earlier date.

```bash
uv run python -m py.preprocessing.ndvi
```

[station_ndvi.parquet](../data2/station_ndvi.parquet) stores **79,656 source-seasons**. Join on `(SOUID, source_lat, source_lon, ndvi_season)`, where `ndvi_season` is the season's starting date as `YYYYMMDD`. The lookup records `ndvi`, source filename/start/end, `ndvi_method` and `ndvi_is_extrapolated`. The loader adds `ndvi_lag_days`: zero within a covered season, otherwise days since the last date covered by the source raster.

| NDVI assignment | Observations |
|:---|---:|
| Observed seasonal raster | 4,845,070 |
| Last value carried forward | 1,870,410 |
| Missing | 10,733 |

Counts and hashes are in the [NDVI manifest](../data2/cleaning_audit/station_ndvi.json) and [coverage table](../data2/cleaning_audit/station_ndvi_coverage.csv). These values use only the original rasters; the separate acquisition archive is not an input.

## 13. Elevation and land cover

`build_source_elevation()` in [`py.preprocessing.analysis_covariates`](../src/py/preprocessing/analysis_covariates.py) reads each observation source's `HGHT` from ECA&D `sources.txt`, in metres. Sentinel heights `−999` and `−9999` remain missing. [station_elevation.parquet](../data2/station_elevation.parquet) joins on `(STAID, source_metadata_id)`.

The standalone `py.preprocessing.analysis_covariates` command now builds elevation only. Daily weather extraction has been retired; wind and rain use the hourly pipeline below.

[`py.preprocessing.land_cover`](../src/py/preprocessing/land_cover.py) samples the existing 2020 GHS-SMOD raster at source coordinates. [station_land_cover.parquet](../data2/station_land_cover.parquet) stores `degurba` and `degurba_label`, joining on `(SOUID, source_lat, source_lon)`. Unknown raster values remain missing. The categorical interaction plot uses the seven rural/urban classes; water and unknown classes are excluded from that figure only.

## 14. Hourly wind and precipitation

[`py.preprocessing.download_hourly_weather`](../src/py/preprocessing/download_hourly_weather.py) requests `10m_u_component_of_wind`, `10m_v_component_of_wind` and `total_precipitation` from [ERA5-Land hourly](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land). Use the same 0.1° grid as the temperature files and every UTC hour needed by the clean sample. Download **31 December 2019–31 August 2025**; the extra starting day supports midnight precipitation de-accumulation. There are **207 monthly variable requests**, with two concurrent retrievals. Each completed file is checked for grid, timestamps, units and instantaneous/accumulated field type. Completed files are reused on restart.

Raw files go to `data2/era5_land_hourly_weather/`. Credentials are read from `CDSAPI_RC`, the ignored owner-only `data2/.cdsapirc`, or the CDS client's normal configuration. No key is saved in audits. The [plan](../data2/cleaning_audit/hourly_weather_plan.json), [progress](../data2/cleaning_audit/hourly_weather_progress.json) and [completed-file table](../data2/cleaning_audit/hourly_weather_downloads.csv) record retrieval and hashes.

[`py.preprocessing.hourly_weather`](../src/py/preprocessing/hourly_weather.py) aggregates each station's saved UTC bounds:

- **Wind:** integrate instantaneous `u10` and `v10` with trapezoidal weights, including both endpoints, then divide by window duration. `wind` is the magnitude of this mean vector in m/s. `wind_mean_speed_mps` separately averages the instantaneous speed with the same weights.
- **Precipitation:** de-accumulate the ERA5-Land forecast fields. At 01 UTC the value is already the first hourly amount; at other hours subtract the preceding accumulation, including the 00 UTC field from the previous forecast. Sum amounts stamped on **`(start, end]`**, in metres. A 24-hour window uses **24 rainfall intervals and 25 wind samples**. See [ECMWF's de-accumulation procedure](https://confluence.ecmwf.int/pages/viewpage.action?navigatingVersions=true&pageId=737545913).
- **Missing hours:** retain the temperature observation and leave its affected covariate null. Negative rainfall increments remain unchanged and receive an explicit review flag. The 12-hour and 23/25-hour windows use their actual durations.

The completed `station_hourly_weather.parquet` joins on `(SOUID, DATE, grid_cell_id, window_start_utc, window_end_utc)`. It includes `wind`, `tp`, component means, mean speed, expected/available counts and `wind_status`/`precipitation_status`. Its manifest is `data2/cleaning_audit/station_hourly_weather.json`.

The existing date-labelled daily files remain separate review inputs under `data2/station_weather/`; current weather plots use the new hourly aggregates. All twelve old wind files record zero-shift UTC calendar-day means. Their periods match **3,576,314** observations, whereas the hourly pipeline supports every resolved station window. The old precipitation files are accumulated fields despite their `daily_mean` names.

The running `hourly-weather` tmux job uses [`hourly_weather.sh`](../src/py/preprocessing/hourly_weather.sh): download, aggregate, refresh land cover, export all six residual profiles and four interaction heatmaps, then run all numerical analyses. Follow `data2/hourly_weather.log` and `data2/hourly_weather.status`; status is `downloading`, `aggregating`, `plotting`, `analysing`, then the exit code (`0` means the entire sequence succeeded).

## 15. Load for analysis

[`load_data()`](../src/py/load_data.py) returns a Polars DataFrame with all temperature-sample columns, coastal distance, source elevation, land cover and NDVI with its provenance. After the hourly job finishes, use `load_data(include_weather=True)` to add the window-matched wind and precipitation fields. Joins check many-to-one matching and preserve every original observation and its row order.

```python
from py.load_data import load_data

data = load_data()
```

## 16. Residual profiles and interactions

[`py.scripts.plot_partial_dependence`](../src/py/scripts/plot_partial_dependence.py) saves Seaborn/Matplotlib figures and CSV source tables under `figures/notebooks/partial_dependence/`. The default profiles are station temperature, NDVI, coastal distance and elevation. The hourly job requests all six with `--features station_celsius tp wind ndvi dist_to_sea_km elevation` after building the matched covariates.

Use `uv run python -m py.scripts.plot_partial_dependence --from-tables` to restyle the saved statistics. Figures use a light grid and omit the bottom caption.

These are observation-weighted mean residuals in ten quantile bins, with 1,000 source-ID bootstrap draws and pointwise 95% percentile intervals, seed `1337`. They are descriptive associations. Temperature also appears in the residual's definition. Each plot uses available values for its own feature; the temperature sample is retained in full. The precipitation profile excludes negative window totals, reports their count, and uses `log10(max(tp, 1e-9))` for nonnegative totals. Negative values remain in the saved covariates. Histograms use the same per-feature eligibility as the profile. The [figure manifest](../figures/notebooks/partial_dependence/manifest.json) identifies inputs, code and per-feature sample sizes.

[`py.scripts.plot_interactions`](../src/py/scripts/plot_interactions.py) exports the four existing joint-bin heatmaps: station temperature × wind, elevation × coastal distance, elevation × wind, and coastal distance × DEGURBA. Numeric axes use eight quantile bins; DEGURBA uses its seven ordered classes. Cells show observation-weighted residual means, with full-sample marginal counts. PNG/PDF exports, source tables and the input manifest are under `figures/notebooks/interactions/`.

## 17. Additional numerical analyses

[`run_numerical_analysis.sh`](../src/py/scripts/run_numerical_analysis.sh) reruns the additional analyses from the supplied ZIP, one file per analysis under `src/py/analysis_*.py`. It uses this temperature sample and its saved covariates, clusters on actual source IDs, and preserves per-analysis sample counts. The 2020 land cover and original seasonal NDVI policies are unchanged.

The hourly-weather job invokes it automatically after aggregation and plotting. Each analysis saves CSV tables, PNG/PDF figures, results and input/code hashes in `figures/notebooks/numerical_analysis/`. The runner refreshes manuscript CSV/LaTeX tables and [NUMERICAL_ANALYSIS.md](NUMERICAL_ANALYSIS.md), which opens with DEGURBA and documents the methods and completed results. Model predictions and fold models stay local in `data2/numerical_analysis/`. Follow `data2/numerical_analysis.progress.json`, `.log` and `.status`.
