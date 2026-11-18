"""Archive every catalogued Sentinel-2 acquisition in a saved station-cell plan."""

import argparse
import hashlib
import json
import signal
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import rasterio
from affine import Affine

from py.ndvi_acquisitions import ARCHIVE_VERSION, fetch_acquisition
from py.ndvi_observations import AddMonths as add_months
from py.ndvi_observations import CatalogItems as catalog_items
from py.ndvi_observations import CellBounds as cell_bounds
from py.ndvi_observations import WriteJson as write_json
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY

ACQUISITION_SCHEMA = {
    "cell_id": pl.String,
    "season_start": pl.Date,
    "scene_id": pl.String,
    "acquisition_datetime": pl.Datetime("us", "UTC"),
    "tile_cloud_cover": pl.Float64,
    "processing_baseline": pl.String,
    "native_epsg": pl.Int32,
    "status": pl.String,
    "error_type": pl.String,
    "ndvi_mean": pl.Float64,
    "valid_fraction": pl.Float64,
    "valid_pixels": pl.Int32,
    "footprint_pixels": pl.Int32,
    "qualifies_default_mask": pl.Boolean,
    "scl_counts": pl.List(pl.Int32),
    "quantification": pl.Float64,
    "red_offset": pl.Float64,
    "nir_offset": pl.Float64,
    "pixel_archive": pl.String,
    "saved_arrays": pl.List(pl.String),
    "retrieved_utc": pl.String,
    "archive_version": pl.String,
}
PROGRESS_SCHEMA = {
    "cell_id": pl.String,
    "season_start": pl.Date,
    "status": pl.String,
    "catalog_acquisitions": pl.Int64,
    "saved_acquisitions": pl.Int64,
    "downloaded_acquisitions": pl.Int64,
    "failed_acquisitions": pl.Int64,
    "outside_asset_acquisitions": pl.Int64,
    "error_type": pl.String,
}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save_parquet(frame, path):
    temporary = path.with_suffix(".tmp")
    frame.write_parquet(temporary, compression="zstd")
    temporary.replace(path)


def season_progress(task, rows, count, status, error_type=None):
    return {
        "cell_id": task["cell_id"],
        "season_start": task["season_start"],
        "status": status,
        "catalog_acquisitions": count,
        "saved_acquisitions": len(rows),
        "downloaded_acquisitions": sum(row["status"] == "downloaded" for row in rows.values()),
        "failed_acquisitions": sum(row["status"] == "fetch_error" for row in rows.values()),
        "outside_asset_acquisitions": sum(
            row["status"] == "outside_asset" for row in rows.values()
        ),
        "error_type": error_type,
    }


def load_catalog(task, source_directory, source_manifest):
    end = task.get("season_end", add_months(task["season_start"], 3))
    name = f"catalog_{task['cell_id']}_{task['season_start']}_{end}.json"
    for path in source_manifest.get("reuse_catalog_directories", []):
        cached = Path(path) / name
        if cached.exists():
            return json.loads(cached.read_text())
    source = {
        "SOUID": task["cell_id"],
        "source_lat": task["source_lat"],
        "source_lon": task["source_lon"],
    }
    return catalog_items(source, task["season_start"], end, source_directory / "catalog")


def fetch_cell_season(task, directory, source_directory, source_manifest, transform, stop, update):
    rows = {}
    path = directory / "acquisitions" / str(task["season_start"]) / f"{task['cell_id']}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        rows = {row["scene_id"]: row for row in pl.read_parquet(path).iter_rows(named=True)}
    try:
        items = load_catalog(task, source_directory, source_manifest)
    except Exception as error:
        update(season_progress(task, rows, None, "catalog_error", type(error).__name__))
        return
    items = {item["id"]: item for item in items}
    bounds = cell_bounds(task["source_lon"], task["source_lat"], transform)
    update(season_progress(task, rows, len(items), "running"))
    processed = 0
    last_saved = time.monotonic()
    for item in sorted(
        items.values(), key=lambda item: (item["properties"]["datetime"], item["id"])
    ):
        if stop.is_set():
            break
        previous = rows.get(item["id"])
        if previous is not None and previous["status"] != "fetch_error":
            continue
        metadata_directory = source_directory / "product_metadata"
        for previous_directory in source_manifest.get("reuse_metadata_directories", []):
            if (Path(previous_directory) / f"{item['id']}.xml").exists():
                metadata_directory = Path(previous_directory)
                break
        result = fetch_acquisition(item, bounds, directory, metadata_directory)
        result = {
            **result,
            "cell_id": task["cell_id"],
            "season_start": task["season_start"],
            "acquisition_datetime": datetime.fromisoformat(
                result["acquisition_datetime"].replace("Z", "+00:00")
            ),
        }
        rows[item["id"]] = result
        processed += 1
        update(season_progress(task, rows, len(items), "running"))
        if processed % 10 == 0 or time.monotonic() - last_saved >= 30:
            save_parquet(pl.DataFrame(list(rows.values()), schema=ACQUISITION_SCHEMA), path)
            last_saved = time.monotonic()
    save_parquet(pl.DataFrame(list(rows.values()), schema=ACQUISITION_SCHEMA), path)
    status = (
        "stopped"
        if stop.is_set()
        else (
            "complete_with_errors"
            if any(row["status"] == "fetch_error" for row in rows.values())
            else "complete"
        )
    )
    update(season_progress(task, rows, len(items), status))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-label", required=True, help="Existing seasonal retrieval plan and caches"
    )
    parser.add_argument("--label", required=True, help="Separate acquisition archive label")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    for label in (args.label, args.source_label):
        if Path(label).name != label or label in ("", ".", ".."):
            parser.error("Use plain directory labels")
    if args.label == args.source_label or args.workers < 1:
        parser.error("Use a separate output label and positive workers")
    source_directory = DATA_DIRECTORY / "ndvi_observed" / args.source_label
    directory = DATA_DIRECTORY / "ndvi_observed" / args.label
    directory.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads((source_directory / "manifest.json").read_text())
    if sha256(Path(source_manifest["input_file"])) != source_manifest["input_sha256"]:
        raise ValueError("Selected station input changed since the source plan was made")
    tasks = pl.read_parquet(source_directory / "tasks.parquet")
    manifest = {
        "archive_version": ARCHIVE_VERSION,
        "source_label": args.source_label,
        "source_plan_sha256": sha256(source_directory / "manifest.json"),
        "input_file": source_manifest["input_file"],
        "input_sha256": source_manifest["input_sha256"],
        "tasks_sha256": sha256(source_directory / "tasks.parquet"),
        "source_seasons_sha256": sha256(source_directory / "source_seasons.parquet"),
        "start": source_manifest["start"],
        "end_exclusive": source_manifest["end_exclusive"],
        "cell_seasons": len(tasks),
        "grid_transform": source_manifest["grid_transform"],
        "collection": "sentinel-2-l2a",
        "provider": "Microsoft Planetary Computer",
        "catalog_cache": str(source_directory / "catalog"),
        "product_metadata_cache": str(source_directory / "product_metadata"),
        "reuse_catalog_directories": source_manifest.get("reuse_catalog_directories", []),
        "reuse_metadata_directories": source_manifest.get("reuse_metadata_directories", []),
        "scope": "All item IDs returned by the station-cell-centre catalogue query for each planned cell-season; no monthly cap, date deduplication, cloud rejection or early missing-month exit",
        "pixels": "Native B04/B08 DN and SCL windows, aligned SCL, footprint and default valid mask; cloudy, snowy, nodata and rejected pixels are preserved",
        "metadata": "Full saved STAC properties/assets, acquisition timestamp, CRS, native/window transforms, cell bounds, product quantification and band offsets; compressed NPZ with no pickle",
        "summary": "Per-acquisition mean of valid native-pixel NDVI is retained even below the 75% threshold; qualifies_default_mask records that threshold separately; raw pixels allow other masks and aggregates",
        "limitations": "Only planned station cells and catalogued acquisition times; no observations on days without acquisitions; no wider spatial windows or extra spectral bands",
        "adopted_into_analysis": False,
    }
    manifest_path = directory / "manifest.json"
    if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
        raise ValueError("Archive plan changed; use a new output label")
    write_json(manifest_path, manifest)
    for name in ("tasks.parquet", "source_seasons.parquet"):
        if not (directory / name).exists():
            (directory / name).write_bytes((source_directory / name).read_bytes())
    if args.plan_only:
        print(f"Planned {len(tasks)} cell-seasons in {directory}", flush=True)
        return
    saved_path = directory / "cell_season_progress.parquet"
    saved = (
        pl.read_parquet(saved_path) if saved_path.exists() else pl.DataFrame(schema=PROGRESS_SCHEMA)
    )
    results = {(row["cell_id"], row["season_start"]): row for row in saved.iter_rows(named=True)}
    done_statuses = (
        ["complete"] if args.retry_failed else ["complete", "complete_with_errors", "catalog_error"]
    )
    done = saved.filter(pl.col("status").is_in(done_statuses)).select("cell_id", "season_start")
    pending = tasks.join(done, on=["cell_id", "season_start"], how="anti")
    if "priority" in pending.columns:
        pending = pending.sort("priority", "season_start", "cell_order")
    lock, stop = threading.Lock(), threading.Event()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signal_number, lambda *_: stop.set())
    started = time.monotonic()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs = directory / "execution_runs"
    runs.mkdir(exist_ok=True)
    write_json(
        runs / f"{timestamp}.json",
        {
            "started_utc": timestamp,
            "workers": args.workers,
            "retry_failed": args.retry_failed,
            "manifest_sha256": sha256(manifest_path),
            "code_sha256": {
                path.name: sha256(path)
                for path in (
                    Path(__file__),
                    Path(__file__).parents[1] / "ndvi_acquisitions.py",
                    Path(__file__).parents[1] / "ndvi_fast.py",
                    Path(__file__).parents[1] / "ndvi_observations.py",
                )
            },
        },
    )

    def update(row):
        with lock:
            results[(row["cell_id"], row["season_start"])] = row

    def checkpoint(finished=False):
        with lock:
            frame = pl.DataFrame(list(results.values()), schema=PROGRESS_SCHEMA).sort(
                "cell_id", "season_start"
            )
        save_parquet(frame, saved_path)
        failures = (
            frame["failed_acquisitions"].sum()
            + frame.filter(pl.col("status") == "catalog_error").height
        )
        complete = frame.filter(
            pl.col("status").is_in(["complete", "complete_with_errors", "catalog_error"])
        ).height
        value = {
            "status": "stopped"
            if stop.is_set()
            else ("complete_with_errors" if failures else "complete")
            if finished
            else "running",
            "updated_utc": datetime.now(timezone.utc).isoformat(),
            "run_elapsed_seconds": round(time.monotonic() - started, 1),
            "total_cell_seasons": len(tasks),
            "finished_cell_seasons": complete,
            "remaining_cell_seasons": len(tasks) - complete,
            "catalogued_cell_seasons": frame["catalog_acquisitions"].is_not_null().sum(),
            **{
                name: frame[name].sum()
                for name in (
                    "catalog_acquisitions",
                    "saved_acquisitions",
                    "downloaded_acquisitions",
                    "failed_acquisitions",
                    "outside_asset_acquisitions",
                )
            },
            "catalog_errors": frame.filter(pl.col("status") == "catalog_error").height,
            "workers": args.workers,
            "archive_version": ARCHIVE_VERSION,
            "catalog_count_is_partial": frame["catalog_acquisitions"].is_not_null().sum()
            < len(tasks),
            "adopted_into_analysis": False,
        }
        write_json(directory / "progress.json", value)
        print(json.dumps(value), flush=True)
        return failures

    checkpoint()
    iterator = iter(pending.iter_rows(named=True))
    transform = Affine(*manifest["grid_transform"][:6])
    with rasterio.Env(), ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = set()

        def submit():
            task = next(iterator, None)
            if task is not None and not stop.is_set():
                futures.add(
                    pool.submit(
                        fetch_cell_season,
                        task,
                        directory,
                        source_directory,
                        source_manifest,
                        transform,
                        stop,
                        update,
                    )
                )

        for _ in range(args.workers):
            submit()
        last_saved = time.monotonic()
        while futures:
            finished, _ = wait(futures, timeout=30, return_when=FIRST_COMPLETED)
            for future in finished:
                futures.remove(future)
                future.result()
                submit()
            if time.monotonic() - last_saved >= 30:
                checkpoint()
                last_saved = time.monotonic()
    failures = checkpoint(finished=True)
    raise SystemExit(130 if stop.is_set() else (1 if failures else 0))


if __name__ == "__main__":
    main()
