# Station observation windows

Scope: **2020-01-01–2025-08-31**. `D` denotes the date already assigned by ECA&D. Existing ECA&D date shifts are preserved; do not shift `TX9` again.

Use the observation source (`SOUID`), provider and `ELEI` code to identify the interval. A country's civil time zone alone does not determine its observing window. Country abbreviations below refer only to the source/provider combinations in the [verified rules](../data2/cleaning_audit/verified_observation_window_rules.csv).

## Applied windows

All times are UTC unless explicitly marked local. **CET/MEZ is fixed UTC+1**; `Europe/Copenhagen` includes daylight saving time. ECA&D codes follow the [public dictionary](https://www.ecad.eu/dailydata/datadictionaryelement.php) and the supplied release definitions linked below.

| Source / code | Interval for date `D` | Evidence |
|:---|:---|:---|
| `TX3`, `TX21` | `D 00:00 → D+1 00:00` | [ECA&D definitions](../data/main/ECA_blend_tx/elements.txt) |
| `TX7` | `D 06:00 → D 18:00`; **12 hours** | [ECA&D definitions](../data/main/ECA_blend_tx/elements.txt) |
| `TX9`, `TX11` | `D 09:00 → D+1 09:00` | [ECA&D definitions](../data/main/ECA_blend_tx/elements.txt) |
| Sweden, `TX2` | `D−1 18:00 → D 18:00` | [SMHI](https://www.smhi.se/kunskapsbanken/meteorologi/temperatur/varmebolja) |
| Norway, `TX2` | `D−1 18:00 → D 18:00` | [MET report 7/2021, §2, p. 6](https://www.met.no/publikasjoner/met-report/met-report-2021/_/attachment/download/5abd0cf0-9a45-4c38-8ee2-1484150009f9:aa5a68ca6035f7baa3856a0d371f6a822c23c29b/MET-report-7-2021.pdf) |
| Finland, `TX2`; verified FMI `TX1` | `D−1 18:00 → D 18:00` | [FMI observation guidance](https://en.ilmatieteenlaitos.fi/guidance-to-observations); [archive checks](../data2/cleaning_audit/fmi_window_verification.csv) |
| Austria, `TX2`, `TX20` | `D−1 18:00 → D 18:00` | [GeoSphere](https://data.hub.geosphere.at/showcase/wetterstatistik-eines-bestimmten-tages-im-jahr) |
| Poland, `TX2` | `D−1 18:00 → D 18:00` | [IMGW observing history, p. 33](https://www.imgw.pl/wp-content/uploads/2024/11/monografia_imgw_2024_klimat-gorzowa.pdf) |
| Hungary, `TX2` | `D−1 18:00 → D 18:00` | [Automatic daily archive, p. 2](https://odp.met.hu/climate/observations_hungary/daily/historical/Leiras_automata_napi-HABP_1D_hist-hu.pdf) |
| Estonia, `TX2` | `D−1 18:00 → D 18:00` | [2020 yearbook](https://www.ilmateenistus.ee/wp-content/uploads/2022/07/meteoroloogia_aastaraamat_2020.pdf); [archive checks](../data2/cleaning_audit/estonia_window_verification.csv) |
| Romania, `TX2` | `D−1 18:00 → D 18:00` | [Dated ANM map reproduced on p. 218](https://asm.md/sites/default/files/2024-05/Stiinta%20in%20nordul%20Republcicii_Balti_24.05.2024_Balti.pdf); [value checks](../data2/cleaning_audit/romania_window_verification.csv) |
| Ukrainian provider, `TX2`, including its RU-coded Crimean source | `D−1 18:00 → D 18:00` | [Observing manual, §6.1.3, p. 10](https://www.cgo-sreznevskyi.kyiv.ua/images/PraciSpivrobitnikiv/mastanovy-3.pdf) |
| France, `TX6` | `D 06:00 → D+1 06:00` | [Météo-France station report](https://donneespubliques-int.meteofrance.fr/client/document/tempe_mois_station_exemple_102.pdf) |
| Slovenia, `TX8` | `D−1 20:00 → D 20:00` | [ARSO daily-data definitions](https://meteo.arso.gov.si/met/sl/climate/current/last-30-days/description/) |
| Serbia, verified `TX8`, **2021 only** | `D−1 20:00 → D 20:00` | [2021 yearbook, printed p. 3](https://www.hidmet.gov.rs/data/meteo_godisnjaci/Meteoroloski%20godisnjak%201%20-%20klimatoloski%20podaci%20-%202021.pdf) |
| Denmark, `TX14`; verified `TX16` days | Local `D 00:00 → D+1 00:00`, converted with `Europe/Copenhagen` | [DMI definitions](https://www.dmi.dk/friedata/dokumentation/climate-data); [dated API checks](../data2/cleaning_audit/dmi_2020_window_verification.csv) |
| Luxembourg ASTA, verified `TX13` days | `D−1 23:00 → D 23:00`; fixed CET | [ASTA time basis](https://data.public.lu/fr/datasets/inspire-annex-iii-meteorological-geographical-features-pointtimeseriesobservation-hourly-weather-measurements-of-asta/); [aggregation checks](../data2/cleaning_audit/luxembourg_window_aggregation_verification.csv) |
| GSOD, verified `TX1` hourly fallback | Reporting day `D 00:00 → D+1 00:00` | [NOAA GSOD format and flags](https://www.ncei.noaa.gov/data/global-summary-of-the-day/doc/readme.txt) |

## Limits and checks

- **Denmark:** normal winter days run `D−1 23:00 → D 23:00`; summer days run `D−1 22:00 → D 22:00`. DST transitions span **23 or 25 hours**. `TX16` evidence covers all 366 Vestervig days in 2020 and 230 matching Nordby days from 2020-05-15. API starts exclude midnight by 1 ms; saved bounds use nominal midnight.
- **Luxembourg:** apply only to matched days from **2024-11-17** onward. The fixed-CET aggregation reproduces all 92 complete cached hourly checks from January/July 2026. Those diagnostic observations are outside the analysis; older station days remain unresolved.
- **GSOD:** apply only when `MAX_ATTRIBUTES = "*"` and the original daily value matches within **0.051°C**, allowing Fahrenheit rounding. `window_sampling = "hourly_or_synoptic_samples"` identifies maxima of available samples. Their exact times and completeness remain unknown. Unflagged reported extremes require their original reporting periods.
- **Verification strength:** provider definitions establish declared conventions. Checks support date assignment: 369 FMI values; 369 Estonian values and 357 complete hourly windows; 12 Romanian map values. This does not audit every instrument log.

## Coverage

[Saved selection](../data2/selected_station_observations.parquet): **9,840,278 observations**. **9,651,857 (98.09%)** have UTC bounds, including **34,965 GSOD sampled reporting days**. **188,421** retain null bounds. Temperatures and observation membership are unchanged.

| Remaining group | Records | Missing information |
|:---|---:|:---|
| Luxembourg, older `TX13` | 57,030 | Original interval |
| Latvia, `TX19` / `TX1` | 56,220 | Sampling definition, date assignment or interval |
| GSOD explicit extremes, GR / AL / BG | 47,479 | Physical period of the extreme report |
| ME, HR, HU, BA, SK and remaining DK sources | 27,692 | Source-specific observing hour, interval or date assignment |

Full [unresolved-source findings](../data2/cleaning_audit/preprocessing_window_resolution.csv) and [coverage counts](../data2/cleaning_audit/preprocessing_window_coverage.csv) are saved alongside the data.

## Implementation

[observation_windows.py](../src/py/preprocessing/observation_windows.py) applies the [provider rules](../data2/cleaning_audit/verified_observation_window_rules.csv), then [verified source-day mappings](../data2/cleaning_audit/verified_observation_window_overrides.csv) with their [evidence](../data2/cleaning_audit/verified_observation_window_override_rules.csv). Source-day mappings require the same source, date, temperature and original window code; existing mapped intervals are preserved.

The Parquet stores `window_start_utc`, `window_end_utc`, `window_hours`, `window_rule_id`, `window_status` and `window_sampling`. Check ERA5 endpoint sampling and required-hour completeness before calculating comparable maxima.
