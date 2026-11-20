# Station temperatures and ERA5-Land

We compare daily maximum temperatures recorded by European weather stations
with ERA5-Land estimates. We then study how the differences vary with weather,
vegetation, elevation, coastal distance and urbanisation. The aim is to
identify systematic discrepancies and assess how well ERA5-Land represents
local temperature extremes.

## Data preprocessing

We start with two temperature datasets:

- **ECA&D station observations.** The station archive is [ECA&D blended daily
  maximum temperature][ecad]. It contains records across 8,568
  weather stations. The raw temperature field, `TX`, is the maximum daily
  temperature in tenths of a degree Celsius.

- **ERA5-Land temperature estimates.** The comparison uses [ERA5-Land hourly 2
  m air temperature][era5-land]: January 2020–August 2025, with UTC timestamps.
  The coordinates are spaced by 0.1°. Values are instantaneous temperatures in
  Kelvin, converted to Celsius.

Each subsection below describes a preprocessing step, from identifying the
observation source to constructing comparable temperature pairs and adding
environmental covariates.

### Select European sources within ERA5 coverage

We keep sources in the [UN M49 European country and territory list][europe]
whose coordinates fall inside the downloaded ERA5-Land footprint. Its outer
cell edges are **34.95–69.95°N and 25.05°W–40.95°E**.

Iceland and the Nordic countries are included where covered. Türkiye, Cyprus
and Greenland are excluded by the country selection. Some northern European
locations lie beyond the extract. The study area is therefore European sources
within this available grid.

![European study area and ERA5-Land coverage][study-area-map]

Blue: eligible European land. Pale blue: European land outside the extract.
Gray: other countries. The orange dashed line marks the extract. Country
outlines: Natural Earth, 1:50 million. [Download the map as
PDF][study-area-pdf].

### Keep provider-valid observations

First keep provider-valid observations with a reported value: `Q_TX == 0` and
`TX != -9999`. The filters act on individual daily records.

### Remove isolated spikes and dips

Next remove an isolated maximum that is **at least 25°C above both adjacent
days, or at least 25°C below both**, using the spike-check convention described
by [Durre et al. (2010)][durre-2010]. Both neighbouring calendar days must be
present within the same source. Borrowed copies are counted once when
identifying spikes, then every copy of a flagged source-day is removed.

### Apply temperature bounds

Then retain daily maxima from **−60°C to 50°C, inclusive**. These provisional
plausibility bounds remove another 323 records: one below the lower limit and
322 above the upper limit.

### Recover the observation windows

A station's daily maximum need not cover midnight to midnight UTC. The `ELEI`
code in ECA&D source metadata identifies an observation convention; its clock
hours and date assignment can require provider-specific evidence.

We combine that code with the actual provider, country, documented observing
practice and checks against original observations. Rules apply within their
verified source and date scope. Existing ECA&D date shifts are already included
in the labelled date.

| Convention | Interval for labelled date D |
| --- | --- |
| `TX3`, `TX21` | D 00:00 → D+1 00:00 UTC |
| Verified `TX2` sources; Austrian `TX20` | D−1 18:00 → D 18:00 UTC |
| `TX7` | D 06:00 → D 18:00 UTC, 12 hours |
| `TX9`, `TX11` | D 09:00 → D+1 09:00 UTC |
| French `TX6` | D 06:00 → D+1 06:00 UTC |
| Verified Slovenian and Serbian `TX8` | D−1 20:00 → D 20:00 UTC |
| Danish local calendar days | Local midnight → next local midnight |
| Verified Luxembourg fixed-CET days | D−1 23:00 → D 23:00 UTC |

Danish local days are converted with `Europe/Copenhagen`, so daylight-saving
transitions span 23 or 25 hours. Luxembourg's verified days use fixed CET,
UTC+1. The 12-hour `TX7` interval is retained as such.

### Compute a maximum over the same hours

For a resolved station window, take the maximum of the instantaneous ERA5-Land
temperatures with **both endpoints included**:

```
window_start_utc <= valid_time <= window_end_utc
```

No one-hour shift is applied to instantaneous temperature. A 24-hour window
therefore contains **25 samples**. A station's recorded extreme can still occur
between those hourly samples.

![A 24-hour observation window contains 25 hourly temperature samples,
including both endpoints][window-diagram]

We use each station's observation coordinates to find the nearest ERA5-Land
grid point and select the corresponding temperature values.

### Attach the environmental covariates

We attach environmental information to each temperature pair using its
observation location and the relevant observation period.

**Coastal distance.** We use Natural Earth coastline data to calculate the
distance, in kilometres, from each station location to the nearest coastline.

**Elevation.** We take each observation site's elevation, in metres, from the
ECA&D source metadata.

**Urbanisation.** We assign each station location a DEGURBA class using the
2020 GHS-SMOD map from the Global Human Settlement Layer. This describes the
surrounding area, from rural locations to urban centres. The classification
is held fixed throughout the study.

**Vegetation.** We use the original seasonal Sentinel-2 NDVI maps to describe
vegetation greenness around each station, taking the value at its location.
The maps cover December 2019–November 2023. For later dates, we carry forward
the latest earlier valid value at that location, across seasons.

### Match wind and precipitation to the window

We use [hourly ERA5-Land data][era5-land] for wind and precipitation, matching
the same observation window as each temperature pair.

**Wind.** We average the hourly wind components over the observation window,
then calculate the magnitude of the resulting mean wind vector, in metres
per second.

**Precipitation.** We derive hourly rainfall amounts from the ERA5-Land
accumulations and sum them over the observation window to obtain total
precipitation, in metres.

[Source and reproduction instructions][repository]

[ecad]:
  https://www.ecad.eu/dailydata/

[era5-land]:
  https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land

[europe]:
  https://unstats.un.org/unsd/methodology/m49/overview/

[study-area-map]:
  assets/geographic_selection.png

[study-area-pdf]:
  assets/geographic_selection.pdf

[durre-2010]:
  https://www.ncei.noaa.gov/pub/data/ghcn/daily/papers/durre-menne-etal2010.pdf

[selection-counts]:
  assets/blog/selection_counts.csv

[window-rules]:
  assets/blog/verified_observation_window_rules.csv

[window-methods]:
  assets/blog/verified_observation_window_override_rules.csv

[unresolved-windows]:
  assets/blog/preprocessing_unresolved_windows.csv

[window-coverage]:
  assets/blog/preprocessing_window_coverage.csv

[window-diagram]:
  assets/observation_window.png

[monthly-coverage]:
  assets/blog/station_era5_monthly_coverage.csv

[ndvi-coverage]:
  assets/blog/station_ndvi_coverage.csv

[repository]:
  https://github.com/SaadSouilmi/ERA5_resid

[release-summary]:
  assets/blog/preprocessing-summary.json

[site-manifest]:
  assets/blog/site-manifest.json
