"""Resume a saved NDVI retrieval plan with the benchmarked quality-first reader."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import rasterio
from affine import Affine

from py.ndvi_fast import fetch_season
from py.ndvi_observations import WriteJson as write_json
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.scripts.fetch_ndvi_gap import RESULT_SCHEMA, TASK_KEYS, save_progress, sha256


def retrieve_task(task, directory, transform, retry_failed):
    cache = directory / "seasons" / f"{task['cell_id']}_{task['season_start']}.json"
    if retry_failed and cache.exists():
        previous = json.loads(cache.read_text())
        if previous["errors"] and previous["status"] != "observed_season":
            cache.unlink()
    source = {
        "SOUID": task["cell_id"],
        "source_lat": task["source_lat"],
        "source_lon": task["source_lon"],
    }
    result = fetch_season(source, task["season_start"], directory, transform)
    status = result["status"]
    if result["errors"] and status != "observed_season":
        status = "incomplete_fetch"
    return {
        **{key: task[key] for key in TASK_KEYS},
        **{
            key: result[key]
            for key in (
                "ndvi_observed",
                "valid_dates",
                "valid_months",
                "attempted_scenes",
                "catalog_scenes",
            )
        },
        "status": status,
        "scene_errors": len(result["errors"]),
        "error_type": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    if args.workers < 1 or Path(args.label).name != args.label or args.label in ("", ".", ".."):
        parser.error("Use positive workers and a plain output label")
    directory = DATA_DIRECTORY / "ndvi_observed" / args.label
    manifest = json.loads((directory / "manifest.json").read_text())
    if sha256(Path(manifest["input_file"])) != manifest["input_sha256"]:
        raise ValueError("Selected input changed since this retrieval was planned")
    tasks = pl.read_parquet(directory / "tasks.parquet")
    sources = pl.read_parquet(directory / "source_seasons.parquet")
    saved = pl.read_parquet(directory / "cell_season_ndvi.parquet")
    progress = json.loads((directory / "progress.json").read_text())
    previous_elapsed = progress["elapsed_seconds"]
    initial_completed = len(saved)
    complete = (
        saved.filter(~pl.col("status").is_in(["incomplete_fetch", "download_failed"]))
        if args.retry_failed
        else saved
    )
    pending_tasks = tasks.join(complete.select(TASK_KEYS), on=TASK_KEYS, how="anti")
    results = {(row["cell_id"], row["season_start"]): row for row in saved.iter_rows(named=True)}
    transform = Affine(*manifest["grid_transform"][:6])
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    runs = directory / "execution_runs"
    runs.mkdir(exist_ok=True)
    write_json(
        runs / f"{timestamp}.json",
        {
            "started_utc": timestamp,
            "reader": "quality_first_v1",
            "workers": args.workers,
            "retry_failed": args.retry_failed,
            "initial_completed_cell_seasons": initial_completed,
            "remaining_tasks_this_run": len(pending_tasks),
            "plan_manifest_sha256": sha256(directory / "manifest.json"),
            "tasks_sha256": sha256(directory / "tasks.parquet"),
            "code_sha256": {
                path.name: sha256(path)
                for path in (
                    Path(__file__),
                    Path(__file__).parents[1] / "ndvi_fast.py",
                    Path(__file__).parents[1] / "ndvi_observations.py",
                    Path(__file__).parent / "fetch_ndvi_gap.py",
                )
            },
            "estimator": "Unchanged grid, reflectance conversion, pixel masks, acquisition ordering and sampling limits; all three months required",
            "early_exit": "Stop after the first month without a qualifying acquisition. Missing seasons record months_checked; valid_months and valid_dates count inspected months only. Observed seasons inspect all three months.",
            "cache_policy": "Retain completed estimates; reuse scene values and catalogues; retry failed seasons only when requested",
        },
    )
    started = time.monotonic()
    processed = 0

    def checkpoint(finished=False):
        failures = save_progress(
            list(results.values()), sources, tasks, directory, started, finished
        )
        current = json.loads((directory / "progress.json").read_text())
        run_elapsed = current["elapsed_seconds"]
        current.update(
            elapsed_seconds=round(previous_elapsed + run_elapsed, 1),
            run_elapsed_seconds=run_elapsed,
            run_tasks_processed=processed,
            run_new_cell_seasons=len(results) - initial_completed,
            run_tasks_remaining=len(pending_tasks) - processed,
            reader="quality_first_v1",
            workers=args.workers,
        )
        write_json(directory / "progress.json", current)
        return failures

    checkpoint()
    print(
        f"Resuming {args.label}: {initial_completed}/{len(tasks)} saved; {len(pending_tasks)} tasks including retries; {args.workers} workers",
        flush=True,
    )
    last_saved = started
    with rasterio.Env(), ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(retrieve_task, task, directory, transform, args.retry_failed): task
            for task in pending_tasks.iter_rows(named=True)
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {key: None for key in RESULT_SCHEMA}
                result.update({key: task[key] for key in TASK_KEYS})
                result.update(status="download_failed", error_type=type(error).__name__)
            results[(task["cell_id"], task["season_start"])] = result
            processed += 1
            print(
                f"run={processed}/{len(pending_tasks)} total={len(results)}/{len(tasks)} {task['cell_id']} {task['season_start']} {result['status']} ndvi={result['ndvi_observed']} scene_errors={result['scene_errors']}",
                flush=True,
            )
            if processed % 50 == 0 or time.monotonic() - last_saved >= 60:
                checkpoint()
                last_saved = time.monotonic()
    failures = checkpoint(finished=True)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
