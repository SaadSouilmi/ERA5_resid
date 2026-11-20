"""Map documented ECA&D TX windows to UTC boundaries without guessing missing metadata."""

import polars as pl

from py.paths import ANALYSIS_DATA_DIRECTORY as data_dir


def observation_window_rules():
    # Offsets are minutes from midnight on the DATE already assigned by ECA&D.
    return pl.DataFrame(
        [
            ("TX1", None, None, None, None, "interval_unknown"),
            ("TX2", "18:00", "18:00", None, None, "date_anchor_unknown"),
            ("TX3", "00:00", "00:00", 0, 1440, "mapped"),
            ("TX5", None, None, None, None, "hour_unknown"),
            ("TX6", None, None, None, None, "hour_unknown"),
            ("TX7", "06:00", "18:00", 360, 1080, "mapped"),
            ("TX8", "20:00", "20:00", None, None, "date_anchor_unknown"),
            ("TX9", "09:00", "09:00", 540, 1980, "mapped"),
            ("TX10", "20:30", "20:30", -210, 1230, "mapped"),
            ("TX11", "09:00", "09:00", 540, 1980, "mapped"),
            ("TX12", "19:00", "19:00", None, None, "date_anchor_unknown"),
            ("TX13", None, None, None, None, "interval_unknown"),
            ("TX14", None, None, None, None, "time_zone_unknown"),
            ("TX15", "16:00", "16:00", None, None, "date_anchor_unknown"),
            ("TX16", None, None, None, None, "hour_unknown"),
            ("TX17", "17:00", "17:00", None, None, "date_anchor_unknown"),
            ("TX18", "15:00", "15:00", None, None, "date_anchor_unknown"),
            ("TX19", "22:00", "21:00", None, None, "sampling_unknown"),
            ("TX20", "18:00", "18:00", None, None, "date_anchor_unknown"),
            ("TX21", "00:00", "00:00", 0, 1440, "mapped"),
        ],
        schema=[
            "observation_window",
            "utc_start_clock",
            "utc_end_clock",
            "start_offset_minutes",
            "end_offset_minutes",
            "window_status",
        ],
        schema_overrides={"start_offset_minutes": pl.Int32, "end_offset_minutes": pl.Int32},
        orient="row",
    )


def verified_window_rules():
    return pl.read_csv(
        data_dir / "cleaning_audit/verified_observation_window_rules.csv",
        schema_overrides={
            name: pl.Int32
            for name in [
                "provider_id",
                "valid_from",
                "valid_to",
                "start_offset_minutes",
                "end_offset_minutes",
            ]
        },
    )


def verified_window_overrides():
    audit_dir = data_dir / "cleaning_audit"
    overrides = pl.read_csv(
        audit_dir / "verified_observation_window_overrides.csv",
        schema_overrides={
            "SOUID": pl.Int32,
            "DATE": pl.Int32,
            "TX": pl.Int16,
            "start_offset_minutes": pl.Int32,
            "end_offset_minutes": pl.Int32,
        },
    )
    evidence = pl.read_csv(audit_dir / "verified_observation_window_override_rules.csv")
    return overrides.join(
        evidence.select("window_rule_id", "window_sampling"),
        on="window_rule_id",
        how="left",
        validate="m:1",
    ).with_columns(pl.col("observation_window").cast(pl.Categorical))


def _utc_boundary(offset_column):
    naive = pl.col("_date") + pl.duration(minutes=pl.col(offset_column))
    local = pl.col("_window_time_zone") == "Europe/Copenhagen"
    local_time = pl.when(local).then(naive).otherwise(None)
    return (
        pl.when(local)
        .then(local_time.dt.replace_time_zone("Europe/Copenhagen").dt.convert_time_zone("UTC"))
        .otherwise(naive.dt.replace_time_zone("UTC"))
    )


def attach_utc_windows(observations, source_metadata):
    """Keep every row; unresolved UTC boundaries remain null with an explicit status."""
    rules = observation_window_rules().select(
        "observation_window", "start_offset_minutes", "end_offset_minutes", "window_status"
    )
    verified = (
        verified_window_rules()
        .drop("evidence_url", "evidence_note")
        .rename(
            {
                "start_offset_minutes": "_verified_start",
                "end_offset_minutes": "_verified_end",
            }
        )
    )
    sources = (
        source_metadata.select(
            "STAID", "SOUID", "country_code", "provider_id", "observation_window"
        )
        .join(rules, on="observation_window", how="left", validate="m:1")
        .join(
            verified,
            on=["country_code", "provider_id", "observation_window"],
            how="left",
            validate="m:1",
        )
        .drop("country_code", "provider_id")
        .with_columns(
            pl.col("observation_window", "window_status", "window_rule_id", "time_zone").cast(
                pl.Categorical
            )
        )
    )
    overrides = verified_window_overrides().rename(
        {
            "start_offset_minutes": "_override_start",
            "end_offset_minutes": "_override_end",
            "window_rule_id": "_override_rule_id",
            "window_sampling": "_override_sampling",
        }
    )
    use_override = pl.col("_override_rule_id").is_not_null() & (pl.col("window_status") != "mapped")
    frame = (
        observations.join(sources, on=["STAID", "SOUID"], how="left", validate="m:1")
        .with_columns(
            pl.col("DATE").cast(pl.String).str.to_datetime("%Y%m%d").alias("_date"),
            pl.col("DATE")
            .is_between(pl.col("valid_from"), pl.col("valid_to"))
            .fill_null(False)
            .alias("_verified"),
        )
        .with_columns(
            pl.when(pl.col("_verified"))
            .then(pl.col("_verified_start"))
            .otherwise(pl.col("start_offset_minutes"))
            .alias("start_offset_minutes"),
            pl.when(pl.col("_verified"))
            .then(pl.col("_verified_end"))
            .otherwise(pl.col("end_offset_minutes"))
            .alias("end_offset_minutes"),
            pl.when(pl.col("_verified"))
            .then(pl.col("time_zone").cast(pl.String))
            .otherwise(pl.lit("UTC"))
            .alias("_window_time_zone"),
            pl.when(pl.col("_verified"))
            .then(pl.lit("mapped"))
            .when(pl.col("window_rule_id").is_not_null() & (pl.col("window_status") != "mapped"))
            .then(pl.lit("historical_window_unknown"))
            .otherwise(pl.col("window_status").cast(pl.String).fill_null("unmapped_code"))
            .cast(pl.Categorical)
            .alias("window_status"),
            pl.when(pl.col("_verified"))
            .then(pl.col("window_rule_id").cast(pl.String))
            .otherwise(pl.concat_str(pl.lit("ecad_"), pl.col("observation_window").cast(pl.String)))
            .cast(pl.Categorical)
            .alias("window_rule_id"),
        )
        .join(
            overrides,
            on=["SOUID", "DATE", "TX", "observation_window"],
            how="left",
            validate="m:1",
        )
        .with_columns(
            *[
                pl.when(use_override).then(value).otherwise(pl.col(name)).alias(name)
                for name, value in {
                    "start_offset_minutes": pl.col("_override_start"),
                    "end_offset_minutes": pl.col("_override_end"),
                    "_window_time_zone": pl.lit("UTC"),
                    "window_status": pl.lit("mapped"),
                    "window_rule_id": pl.col("_override_rule_id"),
                }.items()
            ],
            pl.when(use_override)
            .then(pl.col("_override_sampling"))
            .when(pl.col("window_status") == "mapped")
            .then(pl.lit("provider_daily_maximum"))
            .otherwise(pl.lit("unknown"))
            .alias("window_sampling"),
        )
        .with_columns(
            pl.col("window_status", "window_rule_id", "window_sampling").cast(pl.Categorical)
        )
        .with_columns(
            _utc_boundary("start_offset_minutes").alias("window_start_utc"),
            _utc_boundary("end_offset_minutes").alias("window_end_utc"),
        )
        .with_columns(
            (pl.col("window_end_utc") - pl.col("window_start_utc"))
            .dt.total_minutes()
            .truediv(60)
            .alias("window_hours")
        )
    )
    return frame.drop(
        "_date",
        "start_offset_minutes",
        "end_offset_minutes",
        "_verified",
        "_verified_start",
        "_verified_end",
        "valid_from",
        "valid_to",
        "time_zone",
        "_window_time_zone",
        "_override_start",
        "_override_end",
        "_override_rule_id",
        "_override_sampling",
    )
