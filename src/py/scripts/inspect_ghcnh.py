"""Download and inspect GHCNh candidates for the retained ECA&D sources."""

import argparse
import concurrent.futures as futures
import datetime
import difflib
import hashlib
import json
import re
import time
import unicodedata
import urllib.error as urllib_error
import urllib.request as urllib_request
import numpy as np
import pandas as pd
import polars as pl
from pyproj import Geod
from scipy.spatial import cKDTree as tree
from py.paths import (
    AnalysisDataDirectory as ANALYSIS_DATA_DIRECTORY,
    RawDataDirectory as RAW_DATA_DIRECTORY,
)

DIRECTORY = ANALYSIS_DATA_DIRECTORY / "ghcnh"
AUDIT_DIRECTORY = ANALYSIS_DATA_DIRECTORY / "cleaning_audit"
BASE_URL = "https://www.ncei.noaa.gov/oa/global-historical-climatology-network"
START_DATE = datetime.datetime(2020, 1, 1)
END_DATE = datetime.datetime(2025, 9, 1)


def download(url, file):
    file.parent.mkdir(parents=True, exist_ok=True)
    if file.exists():
        return file
    for attempt in range(3):
        try:
            with (
                urllib_request.urlopen(url, timeout=60) as response,
                file.with_suffix(file.suffix + ".part").open("wb") as stream,
            ):
                while chunk := response.read(1024 * 1024):
                    stream.write(chunk)
            file.with_suffix(file.suffix + ".part").replace(file)
            return file
        except urllib_error.HTTPError as error:
            if error.code == 404 or attempt == 2:
                raise
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)


def normal_name(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode().upper()
    return re.sub("[^A-Z0-9]", "", value)


def coordinates(lat, lon):
    lat, lon = (np.deg2rad(lat), np.deg2rad(lon))
    return np.column_stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])


def inventory():
    metadata = DIRECTORY / "metadata"
    for name in ["ghcnh-station-list.csv", "ghcnh-inventory.txt"]:
        download(BASE_URL + "/hourly/doc/" + name, metadata / name)
    stations = (
        pl.read_csv(metadata / "ghcnh-station-list.csv", infer_schema_length=0)
        .with_columns(
            *[pl.col(name).cast(pl.Float64) for name in ["LATITUDE", "LONGITUDE", "ELEVATION"]]
        )
        .rename({"GHCN_ID": "ghcnh_id"})
    )
    assert stations["ghcnh_id"].n_unique() == stations.height
    months = []
    with (metadata / "ghcnh-inventory.txt").open() as stream:
        next(stream)
        for line in stream:
            parts = line.split()
            if len(parts) != 14:
                raise ValueError(f"Unexpected inventory row: {line[:100]}")
            year = int(parts[1])
            if 2020 <= year <= 2025:
                for month, count in enumerate(parts[2:], 1):
                    if year == 2025 and month > 8:
                        continue
                    months.append((parts[0], year, month, int(count)))
    monthly = pl.DataFrame(
        months, schema=["ghcnh_id", "year", "month", "all_variable_reports"], orient="row"
    )
    monthly.write_parquet(DIRECTORY / "inventory_2020_202508.parquet")
    active = (
        monthly.group_by("ghcnh_id")
        .agg(
            pl.col("all_variable_reports").sum(),
            (pl.col("all_variable_reports") > 0).sum().alias("months_with_any_reports"),
        )
        .filter(pl.col("all_variable_reports") > 0)
    )
    stations = stations.join(active, on="ghcnh_id", how="inner").filter(
        pl.col("LATITUDE").is_between(-90, 90) & pl.col("LONGITUDE").is_between(-180, 180)
    )
    source_metadata = pl.from_pandas(
        pd.read_fwf(
            RAW_DATA_DIRECTORY / "ECA_blend_tx/sources.txt",
            skiprows=25,
            header=None,
            colspecs=[(0, 5), (6, 12), (13, 53), (54, 56)],
            names=["STAID", "source_metadata_id", "ecad_source_name", "source_iso"],
        )
    ).unique()
    frame = (
        pl.scan_parquet(ANALYSIS_DATA_DIRECTORY / "clean/analysis.parquet")
        .select(
            "STAID",
            "SOUID",
            "source_metadata_id",
            "source_lat",
            "source_lon",
            "source_elevation",
            "date",
            "country",
            "place",
            "observation_window",
        )
        .collect()
    )
    sources = (
        frame.group_by(
            "STAID",
            "SOUID",
            "source_metadata_id",
            "source_lat",
            "source_lon",
            "source_elevation",
            "country",
            "place",
            "observation_window",
        )
        .agg(
            pl.len().alias("retained_days"),
            pl.col("date").min().alias("first_retained_date"),
            pl.col("date").max().alias("last_retained_date"),
        )
        .join(source_metadata, on=["STAID", "source_metadata_id"], how="left", validate="m:1")
        .sort("STAID", "SOUID")
    )
    assert sources["ecad_source_name"].null_count() == 0
    tree_index = tree(
        coordinates(stations["LATITUDE"].to_numpy(), stations["LONGITUDE"].to_numpy())
    )
    neighbors = tree_index.query_ball_point(
        coordinates(sources["source_lat"].to_numpy(), sources["source_lon"].to_numpy()),
        2 * np.sin(25.1 / (2 * 6371)),
    )
    geographic = Geod(ellps="WGS84")
    candidates, matches = ([], [])
    for source, indices in zip(sources.to_dicts(), neighbors):
        local = []
        for index in indices:
            station = stations.row(index, named=True)
            if station["ISO_CODE"] != source["source_iso"]:
                continue
            _, _, distance = geographic.inv(
                source["source_lon"],
                source["source_lat"],
                station["LONGITUDE"],
                station["LATITUDE"],
            )
            distance /= 1000
            if distance > 25:
                continue
            elevation = station["ELEVATION"]
            difference = (
                abs(source["source_elevation"] - elevation)
                if source["source_elevation"] is not None and elevation > -900
                else None
            )
            name_similarity = difflib.SequenceMatcher(
                None, normal_name(source["ecad_source_name"]), normal_name(station["NAME"])
            ).ratio()
            local.append(
                {
                    **source,
                    "ghcnh_id": station["ghcnh_id"],
                    "ghcnh_name": station["NAME"],
                    "ghcnh_lat": station["LATITUDE"],
                    "ghcnh_lon": station["LONGITUDE"],
                    "ghcnh_elevation": elevation,
                    "distance_km": distance,
                    "elevation_difference_m": difference,
                    "name_similarity": name_similarity,
                    "months_with_any_reports": station["months_with_any_reports"],
                    "all_variable_reports": station["all_variable_reports"],
                }
            )
        local.sort(key=lambda row: row["distance_km"])
        eligible = [
            row
            for row in local
            if row["distance_km"] <= 1
            and row["elevation_difference_m"] is not None
            and (row["elevation_difference_m"] <= 50)
            and (row["name_similarity"] >= 0.7)
        ]
        for rank, candidate in enumerate(local, 1):
            candidate["distance_rank"] = rank
            candidates.append(candidate.copy())
        best = eligible[0] if len(eligible) == 1 else local[0] if local else None
        matches.append(
            {
                **source,
                **(best or {}),
                "match_status": "unique_close_name_candidate"
                if len(eligible) == 1
                else "ambiguous_close_candidates"
                if len(eligible) > 1
                else "nearby_only"
                if local
                else "no_candidate_within_25km",
                "candidates_within_25km": len(local),
                "close_name_candidates": len(eligible),
            }
        )
    match_frame = pl.DataFrame(matches, infer_schema_length=None)
    candidate_frame = pl.DataFrame(candidates, infer_schema_length=None)
    match_frame.write_parquet(DIRECTORY / "source_candidates.parquet")
    candidate_frame.write_parquet(DIRECTORY / "all_candidates.parquet")
    match_frame.write_csv(AUDIT_DIRECTORY / "ghcnh_source_candidates.csv")
    summary = (
        match_frame.group_by("match_status")
        .agg(
            pl.len().alias("source_series"),
            pl.col("STAID").n_unique().alias("nominal_stations"),
            pl.col("retained_days").sum().alias("retained_station_days"),
            pl.col("ghcnh_id").drop_nulls().n_unique().alias("ghcnh_stations"),
        )
        .sort("retained_station_days", descending=True)
    )
    summary.write_csv(AUDIT_DIRECTORY / "ghcnh_inventory_overlap.csv")
    match_frame.group_by("country", "match_status").agg(
        pl.len().alias("source_series"),
        pl.col("STAID").n_unique().alias("nominal_stations"),
        pl.col("retained_days").sum().alias("retained_station_days"),
    ).sort("country", "match_status").write_csv(
        AUDIT_DIRECTORY / "ghcnh_inventory_overlap_by_country.csv"
    )
    print(
        json.dumps(
            {
                "active_ghcnh_stations_worldwide": stations.height,
                "retained_stations": frame["STAID"].n_unique(),
                "retained_days": frame.height,
                "source_series": sources.height,
                "overlap": summary.to_dicts(),
            },
            indent=2,
        ),
        flush=True,
    )


def fetch_year(station, year):
    name = f"GHCNh_{station}_{year}.parquet"
    url = f"{BASE_URL}/hourly/access/by-year/{year}/parquet/{name}"
    file = DIRECTORY / "raw" / str(year) / name
    result = {"ghcnh_id": station, "year": year, "url": url, "path": str(file)}
    try:
        download(url, file)
        result.update(
            status="downloaded",
            bytes=file.stat().st_size,
            sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
            local_file_time_utc=datetime.datetime.fromtimestamp(
                file.stat().st_mtime, datetime.timezone.utc
            ).isoformat(),
        )
    except (OSError, urllib_error.URLError) as error:
        result.update(status="unavailable", error=str(error), bytes=0)
    print(f"{station} {year}: {result['status']}", flush=True)
    return result


def temperature_quality():
    code = pl.col("temperature_Quality_Code").fill_null("").str.strip_chars()
    source = pl.col("temperature_Source_Code").fill_null("").str.strip_chars()
    good_legacy = source.is_in(["220", "221", "222", "223", "347", "348"]) & code.eq("1")
    passed_legacy = source.is_in(
        ["313", "314", "315", "322", "335", "343", "344", "346"]
    ) & code.is_in(["1", "5"])
    return code.eq("") | good_legacy | passed_legacy


def sample(workers):
    matches = pl.read_parquet(DIRECTORY / "source_candidates.parquet").filter(
        pl.col("match_status") == "unique_close_name_candidate"
    )
    selected = (
        matches.sort(
            ["retained_days", "name_similarity", "distance_km", "STAID", "SOUID"],
            descending=[True, True, False, False, False],
        )
        .unique("country", keep="first", maintain_order=True)
        .sort("country")
    )
    selected.write_csv(AUDIT_DIRECTORY / "ghcnh_sample_selection.csv")
    ids = selected["ghcnh_id"].to_list()
    print(f"Downloading {len(ids)} stations, six years each", flush=True)
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        tasks = [
            pool.submit(fetch_year, station, year) for station in ids for year in range(2020, 2026)
        ]
        downloads = [task.result() for task in futures.as_completed(tasks)]
    manifest = pl.DataFrame(downloads, infer_schema_length=None).sort("ghcnh_id", "year")
    manifest.write_csv(AUDIT_DIRECTORY / "ghcnh_download_manifest.csv")
    frames, file_stats, variables = ([], [], [])
    codes = [
        "temperature_" + name
        for name in [
            "Measurement_Code",
            "Quality_Code",
            "Report_Type",
            "Source_Code",
            "Source_Station_ID",
        ]
    ]
    columns = ["STATION", "DATE", "LATITUDE", "LONGITUDE", "ELEVATION", "temperature", *codes]
    start_utc = START_DATE.replace(tzinfo=datetime.timezone.utc)
    end_utc = END_DATE.replace(tzinfo=datetime.timezone.utc)
    for download_row in manifest.filter(pl.col("status") == "downloaded").iter_rows(named=True):
        raw = pl.read_parquet(download_row["path"])
        frame = (
            raw.select(columns)
            .rename({"STATION": "ghcnh_id"})
            .with_columns(pl.col("DATE").str.to_datetime(time_zone="UTC").alias("timestamp"))
            .filter((pl.col("timestamp") >= start_utc) & (pl.col("timestamp") < end_utc))
        )
        if frame.height:
            assert frame["ghcnh_id"].unique().to_list() == [download_row["ghcnh_id"]]
            assert frame["timestamp"].dt.year().unique().to_list() == [download_row["year"]]
        frame = frame.with_columns(
            pl.col("timestamp").dt.date().alias("date"),
            pl.col("timestamp").dt.truncate("1h").alias("hour_bin"),
            pl.col("temperature").is_finite().fill_null(False).alias("temperature_present"),
            pl.col("temperature_Quality_Code")
            .fill_null("")
            .str.strip_chars()
            .eq("")
            .alias("quality_code_blank"),
        ).with_columns(
            (pl.col("temperature_present") & temperature_quality()).alias("screened_temperature")
        )
        frames.append(frame)
        available = frame.filter(pl.col("temperature_present"))
        unflagged = frame.filter(pl.col("screened_temperature"))
        on_hour = unflagged.filter(pl.col("timestamp") == pl.col("hour_bin"))
        first = max(
            start_utc, datetime.datetime(download_row["year"], 1, 1, tzinfo=datetime.timezone.utc)
        )
        last = min(
            end_utc, datetime.datetime(download_row["year"] + 1, 1, 1, tzinfo=datetime.timezone.utc)
        )
        expected = int((last - first).total_seconds() / 3600)
        duplicates = available.group_by("timestamp").agg(
            pl.len().alias("rows"), pl.col("temperature").n_unique().alias("distinct_values")
        )
        file_stats.append(
            {
                "ghcnh_id": download_row["ghcnh_id"],
                "year": download_row["year"],
                "rows_in_window": frame.height,
                "temperature_rows": available.height,
                "excluded_temperature_rows": available.height - unflagged.height,
                "distinct_temperature_timestamps": available["timestamp"].n_unique(),
                "duplicate_temperature_timestamps": duplicates.filter(pl.col("rows") > 1).height,
                "conflicting_temperature_timestamps": duplicates.filter(
                    pl.col("distinct_values") > 1
                ).height,
                "raw_temperature_hour_bins": available["hour_bin"].n_unique(),
                "screened_hour_bins": unflagged["hour_bin"].n_unique(),
                "screened_exact_hours": on_hour["timestamp"].n_unique(),
                "expected_hours": expected,
                "hour_bin_coverage_pct": 100 * unflagged["hour_bin"].n_unique() / expected,
                "exact_hour_coverage_pct": 100 * on_hour["timestamp"].n_unique() / expected,
                "first_temperature_utc": available["timestamp"].min(),
                "last_temperature_utc": available["timestamp"].max(),
                "temperature_min_c": available["temperature"].min(),
                "temperature_max_c": available["temperature"].max(),
                "screened_temperature_min_c": unflagged["temperature"].min(),
                "screened_temperature_max_c": unflagged["temperature"].max(),
            }
        )
        print(
            f"Inspected {download_row['ghcnh_id']} {download_row['year']}: {available.height} temperatures",
            flush=True,
        )
        mask = (pl.col("DATE") >= START_DATE.isoformat()) & (pl.col("DATE") < END_DATE.isoformat())
        for variable in [
            "temperature",
            "dew_point_temperature",
            "relative_humidity",
            "wind_speed",
            "wind_direction",
            "station_level_pressure",
            "sea_level_pressure",
            "precipitation_1_hour",
            "snow_depth",
        ]:
            if variable in raw.columns:
                variables.append(
                    {
                        "ghcnh_id": download_row["ghcnh_id"],
                        "year": download_row["year"],
                        "variable": variable,
                        "nonmissing_rows": raw.filter(mask)[variable].drop_nulls().len(),
                    }
                )
    if not frames:
        raise RuntimeError("No observation files downloaded")
    observations = pl.concat(frames).sort("ghcnh_id", "timestamp")
    observations.write_parquet(DIRECTORY / "sample_temperature.parquet")
    year_stats = pl.DataFrame(file_stats).sort("ghcnh_id", "year")
    assert year_stats.filter(pl.col("screened_hour_bins") > pl.col("expected_hours")).is_empty()
    year_stats.join(selected.select("ghcnh_id", "country", "ghcnh_name"), on="ghcnh_id").write_csv(
        AUDIT_DIRECTORY / "ghcnh_sample_yearly.csv"
    )
    pl.DataFrame(variables).write_csv(AUDIT_DIRECTORY / "ghcnh_sample_variables.csv")
    valid = observations.filter(pl.col("screened_temperature"))
    daily = valid.group_by("ghcnh_id", "date").agg(
        pl.col("hour_bin").n_unique().alias("hour_bins"),
        pl.col("timestamp")
        .filter(pl.col("timestamp") == pl.col("hour_bin"))
        .n_unique()
        .alias("exact_hours"),
    )
    daily.write_parquet(DIRECTORY / "sample_daily_coverage.parquet")
    gaps = valid.with_columns(
        pl.col("timestamp").diff().over("ghcnh_id").dt.total_minutes().alias("gap_minutes")
    )
    gaps.group_by("ghcnh_id").agg(
        pl.col("timestamp").min().alias("first_screened_temperature_utc"),
        pl.col("timestamp").max().alias("last_screened_temperature_utc"),
        pl.col("gap_minutes").drop_nulls().mode().sort().first().alias("modal_interval_minutes"),
        pl.col("gap_minutes").median().alias("median_interval_minutes"),
        pl.col("gap_minutes").max().alias("longest_internal_gap_minutes"),
    ).join(selected.select("ghcnh_id", "ghcnh_name", "country"), on="ghcnh_id").sort(
        "country"
    ).write_csv(AUDIT_DIRECTORY / "ghcnh_sample_timing.csv")
    code_counts = []
    for code in codes:
        for row in (
            observations.filter(pl.col("temperature_present"))
            .group_by(code)
            .len()
            .iter_rows(named=True)
        ):
            code_counts.append({"field": code, "code": row[code], "temperature_rows": row["len"]})
    pl.DataFrame(code_counts).sort("field", "code").write_csv(
        AUDIT_DIRECTORY / "ghcnh_sample_codes.csv"
    )
    observations.filter(pl.col("temperature_present")).group_by(
        "temperature_Source_Code", "temperature_Quality_Code", "screened_temperature"
    ).len().sort("temperature_Source_Code", "temperature_Quality_Code").write_csv(
        AUDIT_DIRECTORY / "ghcnh_sample_quality_by_source.csv"
    )
    valid.group_by("ghcnh_id", pl.col("timestamp").dt.minute().alias("minute")).len().sort(
        "ghcnh_id", "minute"
    ).write_csv(AUDIT_DIRECTORY / "ghcnh_sample_minutes.csv")
    keys = [
        "STAID",
        "SOUID",
        "source_metadata_id",
        "source_lat",
        "source_lon",
        "source_elevation",
        "observation_window",
    ]
    mapping = matches.filter(pl.col("ghcnh_id").is_in(ids)).select(*keys, "ghcnh_id").unique()
    assert mapping.unique(keys).height == mapping.height
    retained = (
        pl.scan_parquet(ANALYSIS_DATA_DIRECTORY / "clean/analysis.parquet")
        .select(*keys, pl.col("date").dt.date())
        .collect()
        .join(mapping, on=keys, how="inner", validate="m:1")
    )
    coverage = retained.join(
        daily, on=["ghcnh_id", "date"], how="left", validate="m:1"
    ).with_columns(pl.col("hour_bins", "exact_hours").fill_null(0))
    retained_stats = coverage.group_by("ghcnh_id").agg(
        pl.col("STAID").n_unique().alias("retained_station_ids"),
        pl.len().alias("retained_station_days"),
        (pl.col("hour_bins") > 0).sum().alias("retained_days_any_temperature"),
        (pl.col("hour_bins") == 24).sum().alias("retained_days_24_hour_bins"),
        (pl.col("exact_hours") == 24).sum().alias("retained_days_24_exact_hours"),
        pl.col("hour_bins").sum().alias("available_hour_bins_on_retained_days"),
        pl.col("exact_hours").sum().alias("available_exact_hours_on_retained_days"),
    )
    total_hours = int((END_DATE - START_DATE).total_seconds() / 3600)
    station_stats = (
        year_stats.group_by("ghcnh_id")
        .agg(
            pl.len().alias("downloaded_years"),
            *[
                pl.col(name).sum()
                for name in [
                    "temperature_rows",
                    "excluded_temperature_rows",
                    "raw_temperature_hour_bins",
                    "screened_hour_bins",
                    "screened_exact_hours",
                ]
            ],
        )
        .with_columns(
            (100 * pl.col("screened_hour_bins") / total_hours).alias("hour_bin_coverage_pct"),
            (100 * pl.col("screened_exact_hours") / total_hours).alias("exact_hour_coverage_pct"),
        )
    )
    station_stats = (
        selected.select("ghcnh_id", "ghcnh_name", "country", "distance_km", "name_similarity")
        .join(station_stats, on="ghcnh_id", how="left")
        .join(retained_stats, on="ghcnh_id", how="left")
        .sort("country")
    )
    station_stats.write_csv(AUDIT_DIRECTORY / "ghcnh_sample_stations.csv")
    summary = {
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "study_start": START_DATE.date().isoformat(),
        "study_end_inclusive": (END_DATE - datetime.timedelta(days=1)).date().isoformat(),
        "selection": "One unique close/name candidate per country, prioritizing retained ECA&D days, then name similarity and distance. Purposive sample; not representative.",
        "candidate_rule": "Same ISO country, distance <= 1 km, elevation difference <= 50 m, normalized name similarity >= 0.7; exactly one eligible candidate. Identity remains unconfirmed.",
        "quality_rule": "Finite, nonmissing temperature; accept blank/null QC, legacy code 1 (Good) for sources 220/221/222/223/347/348, or legacy codes 1/5 (passed all checks) for 313/314/315/322/335/343/344/346. Exclude other nonempty codes, including calculated and suspect values. Provisional screening, not independent validation; all raw values preserved.",
        "coverage_definition": "Unique UTC hour bins with at least one screened temperature. Exact-hour coverage counts timestamps precisely on the hour. Missing years count as no coverage. No interpolation.",
        "retained_day_caveat": "Coverage on retained ECA&D dates uses the UTC calendar day bearing that date, not the station's potentially shifted daily-maximum observation window. This is an availability audit, not a validated temperature-pair analysis.",
        "temperature_semantics": "Dry-bulb air temperature about 2 m above ground, in degrees C. Timestamped readings, not a universal full-hour average or maximum; source-specific measurement/averaging conventions require investigation.",
        "inventory_caveat": "Monthly inventory counts all-variable reports, not temperature observations or distinct hours.",
        "selected_stations": len(ids),
        "selected_countries": selected["country"].n_unique(),
        "candidate_ecad_station_ids": matches["STAID"].n_unique(),
        "candidate_ghcnh_station_ids": matches["ghcnh_id"].n_unique(),
        "candidate_retained_station_days": matches["retained_days"].sum(),
        "requested_files": len(downloads),
        "downloaded_files": manifest.filter(pl.col("status") == "downloaded").height,
        "unavailable_files": manifest.filter(pl.col("status") != "downloaded").height,
        "download_bytes": manifest["bytes"].sum(),
        "rows_in_study_window": observations.height,
        "temperature_rows": observations["temperature_present"].sum(),
        "screened_temperature_rows": valid.height,
        "station_hour_slots": total_hours * len(ids),
        "screened_hour_bins": year_stats["screened_hour_bins"].sum(),
        "screened_exact_hours": year_stats["screened_exact_hours"].sum(),
        "duplicate_temperature_timestamps": year_stats["duplicate_temperature_timestamps"].sum(),
        "conflicting_temperature_timestamps": year_stats[
            "conflicting_temperature_timestamps"
        ].sum(),
        "retained_station_days_in_sample_candidates": coverage.height,
        "retained_station_days_any_temperature": coverage.filter(pl.col("hour_bins") > 0).height,
        "retained_station_days_24_hour_bins": coverage.filter(pl.col("hour_bins") == 24).height,
        "retained_station_days_24_exact_hours": coverage.filter(pl.col("exact_hours") == 24).height,
        "input_analysis_sha256": hashlib.sha256(
            (ANALYSIS_DATA_DIRECTORY / "clean/analysis.parquet").read_bytes()
        ).hexdigest(),
        "source_documentation_caveat": "Downloaded source-list PDF does not describe all source codes present in this release, including 999. Blank QC is retained provisionally; source measurement conventions remain to be verified before scientific use.",
        "metadata_sha256": {
            file.name: hashlib.sha256(file.read_bytes()).hexdigest()
            for file in (DIRECTORY / "metadata").iterdir()
            if file.suffix in [".csv", ".txt", ".pdf"]
        },
    }
    (AUDIT_DIRECTORY / "ghcnh_sample_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["inventory", "sample"])
    parser.add_argument("--workers", type=int, default=6)
    arguments = parser.parse_args()
    DIRECTORY.mkdir(exist_ok=True)
    if arguments.mode == "inventory":
        inventory()
    else:
        sample(arguments.workers)


if __name__ == "__main__":
    main()
