"""Station-only selection rules applied before matching ERA5 temperatures."""

import polars as pl

EUROPEAN_COUNTRY_CODES = """
AL AD AT AX BY BE BA BG HR CZ DK EE FO FI FR DE GI GR GG VA HU IS IE IM
IT JE LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU UA SM RS SK SI ES SJ SE
CH GB
""".split()
SPIKE_THRESHOLD_C = 25
MIN_TEMPERATURE_C = -60
MAX_TEMPERATURE_C = 50


def filter_station_quality(observations):
    return observations.filter((pl.col("Q_TX") == 0) & (pl.col("TX") != -9999))


def find_spike_days(observations):
    source_days = (
        observations.select("SOUID", "DATE", "TX")
        .unique()
        .with_columns(pl.col("DATE").cast(pl.String).str.to_date("%Y%m%d").alias("date"))
        .sort("SOUID", "date")
    )
    context = source_days.with_columns(
        pl.col("TX").shift(1).over("SOUID").alias("previous_tx"),
        pl.col("TX").shift(-1).over("SOUID").alias("next_tx"),
        (
            (pl.col("date").diff().over("SOUID").dt.total_days() == 1)
            & (pl.col("date").diff(-1).over("SOUID").dt.total_days() == -1)
        )
        .fill_null(False)
        .alias("testable"),
    )
    above_previous = pl.col("TX") - pl.col("previous_tx")
    above_next = pl.col("TX") - pl.col("next_tx")
    threshold = SPIKE_THRESHOLD_C * 10
    return context.filter(
        pl.col("testable")
        & (
            ((above_previous >= threshold) & (above_next >= threshold))
            | ((above_previous <= -threshold) & (above_next <= -threshold))
        )
    )


def select_station_observations(valid, source_metadata, bounds, first_date, last_date):
    west, south, east, north = bounds
    counts = {"provider_valid": valid.height}
    european_sources = source_metadata.filter(pl.col("country_code").is_in(EUROPEAN_COUNTRY_CODES))
    observations = valid.join(
        european_sources.select("STAID", "SOUID"), on=["STAID", "SOUID"], how="semi"
    )
    counts["european_sources"] = observations.height
    inside = european_sources.filter(
        pl.col("source_lat").is_between(south, north) & pl.col("source_lon").is_between(west, east)
    )
    observations = observations.join(
        inside.select("STAID", "SOUID"), on=["STAID", "SOUID"], how="semi"
    )
    counts["inside_era5_footprint"] = observations.height
    spikes = find_spike_days(observations)
    observations = observations.join(
        spikes.select("SOUID", "DATE"), on=["SOUID", "DATE"], how="anti"
    )
    counts["after_spike_filter"] = observations.height
    in_range = pl.col("TX").is_between(10 * MIN_TEMPERATURE_C, 10 * MAX_TEMPERATURE_C)
    range_exclusions = observations.filter(~in_range)
    observations = observations.filter(in_range)
    counts["after_temperature_bounds"] = observations.height
    observations = observations.filter(pl.col("DATE").is_between(first_date, last_date))
    counts["study_period"] = observations.height
    return observations, counts, spikes, range_exclusions
