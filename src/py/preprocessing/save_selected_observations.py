"""Save the selected station observations after UTC-window mapping."""

import hashlib
import json
from datetime import datetime, timezone

import polars as pl

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.paths import ProjectRoot as PROJECT_ROOT
from py.paths import RawDataDirectory as RAW_DIRECTORY
from py.preprocessing.observation_windows import observation_window_rules


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_selected_observations(
    observations, source_metadata, *, output_dir=DATA_DIRECTORY, era5_files=()
):
    metadata = source_metadata.select(
        "STAID",
        "SOUID",
        "source_metadata_id",
        "source_id_offset",
        "country_code",
        "source_name",
        "provider_id",
        "provider_name",
        "source_lat",
        "source_lon",
    ).with_columns(pl.col("country_code", "source_name", "provider_name").cast(pl.Categorical))
    selected = observations.join(metadata, on=["STAID", "SOUID"], how="left", validate="m:1")
    selected = selected.with_columns((pl.col("TX") / 10).alias("station_celsius"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "selected_station_observations.parquet"
    selected.write_parquet(output, compression="zstd")

    summary = selected.select(
        pl.len().alias("daily_records"),
        pl.col("STAID").n_unique().alias("station_series"),
        pl.col("SOUID").n_unique().alias("sources"),
        pl.col("DATE").min().alias("first_date"),
        pl.col("DATE").max().alias("last_date"),
        (pl.col("window_status") == "mapped").sum().alias("mapped_records"),
        (pl.col("window_status") != "mapped").sum().alias("unresolved_records"),
        (pl.col("window_sampling") == "hourly_or_synoptic_samples")
        .sum()
        .alias("sampled_reporting_day_records"),
    ).row(0, named=True)
    inputs = [
        DATA_DIRECTORY / "station_data.parquet",
        RAW_DIRECTORY / "ECA_blend_tx/sources.txt",
        RAW_DIRECTORY / "ECA_blend_tx/elements.txt",
        DATA_DIRECTORY / "cleaning_audit/verified_observation_window_rules.csv",
        DATA_DIRECTORY / "cleaning_audit/verified_observation_window_overrides.csv",
        DATA_DIRECTORY / "cleaning_audit/verified_observation_window_override_rules.csv",
        *dict.fromkeys(era5_files),
    ]
    code = [
        PROJECT_ROOT / "src/py/preprocessing" / name
        for name in [
            "station_selection.py",
            "station_metadata.py",
            "observation_windows.py",
            "save_selected_observations.py",
            "select_station_observations.py",
        ]
    ]
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "stage": "Station selection through UTC-window mapping",
        "file": str(output),
        "sha256": _sha256(output),
        "bytes": output.stat().st_size,
        **summary,
        "unresolved_policy": "Keep observations with null UTC boundaries and explicit window_status.",
        "utc_window_meaning": "Documented observation or reporting boundaries. window_sampling distinguishes GSOD sample maxima from other provider daily maxima. ERA5 extraction checks hourly completeness and includes both endpoints.",
        "entry_point": "py.preprocessing.select_station_observations",
        "code_sha256": {str(path): _sha256(path) for path in code},
        "inputs": [{"path": str(path), "sha256": _sha256(path)} for path in inputs],
    }
    manifest_path = output_dir / "cleaning_audit/selected_station_observations.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return output, manifest


def save_window_audits(observations, source_metadata, output_dir, first_date, last_date):
    audit_dir = output_dir / "cleaning_audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    counts = (
        observations.group_by("observation_window", "window_status", "window_sampling")
        .agg(
            pl.len().alias("daily_records"),
            pl.col("STAID").n_unique().alias("station_series"),
            pl.col("SOUID").n_unique().alias("sources"),
        )
        .sort("daily_records", descending=True)
    )
    sources = (
        observations.group_by(
            "STAID", "SOUID", "observation_window", "window_status", "window_rule_id"
        )
        .agg(
            pl.len().alias("daily_records"),
            pl.col("DATE").min().alias("first_date"),
            pl.col("DATE").max().alias("last_date"),
        )
        .join(
            source_metadata.select(
                "STAID",
                "SOUID",
                "source_metadata_id",
                "source_name",
                "country_code",
                "provider_id",
                "provider_name",
                "source_lat",
                "source_lon",
            ),
            on=["STAID", "SOUID"],
            how="left",
            validate="m:1",
        )
    )
    unresolved = (
        sources.filter(pl.col("window_status") != "mapped")
        .group_by(
            "country_code", "provider_id", "provider_name", "observation_window", "window_status"
        )
        .agg(
            pl.col("daily_records").sum(),
            pl.col("SOUID").n_unique().alias("sources"),
            pl.col("first_date").min(),
            pl.col("last_date").max(),
        )
        .sort("daily_records", descending=True)
    )
    coverage = observations.select(
        pl.lit(first_date).alias("first_date"),
        pl.lit(last_date).alias("last_date"),
        pl.len().alias("daily_records"),
        (pl.col("window_status") == "mapped").sum().alias("mapped_records"),
        (pl.col("window_sampling") == "hourly_or_synoptic_samples")
        .sum()
        .alias("sampled_reporting_day_records"),
    ).with_columns(
        (pl.col("daily_records") - pl.col("mapped_records")).alias("unresolved_records"),
        (100 * pl.col("mapped_records") / pl.col("daily_records")).alias("mapped_percent"),
    )
    for name, frame in [
        ("rules", observation_window_rules()),
        ("counts", counts),
        ("sources", sources),
        ("coverage", coverage),
    ]:
        frame.write_csv(audit_dir / f"preprocessing_window_{name}.csv")
    unresolved.write_csv(audit_dir / "preprocessing_unresolved_windows.csv")
