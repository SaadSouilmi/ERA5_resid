"""Attach locations and observation-window codes to ECA&D sources."""

import polars as pl

from py.paths import RAW_DATA_DIRECTORY as raw_data_dir


def _decimal_degrees(column):
    parts = pl.col(column).str.split_exact(":", 2)
    degrees = parts.struct.field("field_0").cast(pl.Float64).abs()
    minutes = parts.struct.field("field_1").cast(pl.Float64)
    seconds = parts.struct.field("field_2").cast(pl.Float64)
    sign = pl.when(pl.col(column).str.starts_with("-")).then(-1).otherwise(1)
    return sign * (degrees + minutes / 60 + seconds / 3600)


def attach_source_locations(observation_sources):
    lines = (raw_data_dir / "ECA_blend_tx/sources.txt").read_text().splitlines()[25:]
    metadata = (
        pl.DataFrame({"line": lines})
        .select(
            pl.col("line").str.slice(0, 5).str.strip_chars().cast(pl.Int32).alias("STAID"),
            pl.col("line")
            .str.slice(6, 6)
            .str.strip_chars()
            .cast(pl.Int32)
            .alias("source_metadata_id"),
            pl.col("line").str.slice(54, 2).alias("country_code"),
            pl.col("line").str.slice(57, 9).str.strip_chars().alias("source_lat_dms"),
            pl.col("line").str.slice(67, 10).str.strip_chars().alias("source_lon_dms"),
            pl.col("line").str.slice(83, 4).str.strip_chars().alias("observation_window"),
            pl.col("line").str.slice(13, 40).str.strip_chars().alias("source_name"),
            pl.col("line")
            .str.slice(106, 5)
            .str.strip_chars()
            .replace("-", None)
            .cast(pl.Int32)
            .alias("provider_id"),
            pl.col("line").str.slice(112, 51).str.strip_chars().alias("provider_name"),
        )
        .unique()
    )
    metadata = metadata.with_columns(
        _decimal_degrees("source_lat_dms").alias("source_lat"),
        _decimal_degrees("source_lon_dms").alias("source_lon"),
    ).drop("source_lat_dms", "source_lon_dms")

    # Participant metadata IDs have a +100000 offset; synoptic IDs match directly.
    candidates = pl.concat(
        [
            metadata.with_columns(
                pl.col("source_metadata_id").alias("SOUID"),
                pl.lit(0).alias("source_id_offset"),
            ),
            metadata.filter(pl.col("source_metadata_id").is_between(100000, 899999)).with_columns(
                (pl.col("source_metadata_id") - 100000).alias("SOUID"),
                pl.lit(100000).alias("source_id_offset"),
            ),
        ]
    )
    return observation_sources.join(candidates, on=["STAID", "SOUID"], how="left", validate="1:1")
