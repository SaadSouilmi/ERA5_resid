"""Benchmark unchanged seasonal NDVI estimates on a fixed sample of pending work."""

import argparse
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import polars as pl
from affine import Affine

from py import ndvi_observations as original
from py.ndvi_fast import fetch_season
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--reader", choices=["original", "fast"], default="original")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--run", default="original_16")
    args = parser.parse_args()
    directory = DATA_DIRECTORY / "ndvi_observed/season_benchmark_v1"
    (directory / "catalog").mkdir(parents=True, exist_ok=True)
    if args.prepare:
        cases = []
        for label in ("sentinel2_selected_gap_v1", "sentinel2_selected_overlap_v1"):
            source = DATA_DIRECTORY / "ndvi_observed" / label
            manifest = json.loads((source / "manifest.json").read_text())
            tasks = pl.read_parquet(source / "tasks.parquet")
            completed = pl.read_parquet(source / "cell_season_ndvi.parquet")
            tasks = tasks.join(
                completed.select("cell_id", "season_start"),
                on=["cell_id", "season_start"],
                how="anti",
            )
            tasks = (
                tasks.with_columns(
                    pl.struct("cell_id", "season_start").hash(seed=2027).alias("rank")
                )
                .sort("rank")
                .head(16)
            )
            for row in tasks.iter_rows(named=True):
                cases.append(
                    {
                        "SOUID": row["cell_id"],
                        "source_lat": row["source_lat"],
                        "source_lon": row["source_lon"],
                        "season_start": str(row["season_start"]),
                        "transform": manifest["grid_transform"],
                    }
                )
        original.WriteJson(directory / "cases.json", cases)
        started = time.monotonic()

        def catalog(case):
            start = date.fromisoformat(case["season_start"])
            original.CatalogItems(case, start, original.AddMonths(start, 3), directory / "catalog")

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(catalog, cases))
        print(
            f"Prepared {len(cases)} pending seasons and identical catalogues in {time.monotonic() - started:.1f}s",
            flush=True,
        )
        return
    cases = json.loads((directory / "cases.json").read_text())
    output = directory / args.run
    for name in ("catalog", "scene_values", "product_metadata", "seasons"):
        (output / name).mkdir(parents=True, exist_ok=True)
    if any((output / "seasons").iterdir()):
        raise ValueError("Use a fresh run name")
    for path in (directory / "catalog").glob("*.json"):
        shutil.copyfile(path, output / "catalog" / path.name)
    reader = original.FetchSeason if args.reader == "original" else fetch_season

    def retrieve(case):
        started = time.monotonic()
        result = reader(
            case, date.fromisoformat(case["season_start"]), output, Affine(*case["transform"][:6])
        )
        return {
            "cell_id": case["SOUID"],
            "season_start": case["season_start"],
            "seconds": time.monotonic() - started,
            "ndvi": result["ndvi_observed"],
            "status": result["status"],
            "attempted_scenes": result["attempted_scenes"],
            "errors": len(result["errors"]),
        }

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(retrieve, cases))
    elapsed = time.monotonic() - started
    summary = {
        "reader": args.reader,
        "workers": args.workers,
        "seasons": len(cases),
        "elapsed_seconds": elapsed,
        "seasons_per_second": len(cases) / elapsed,
        "observed_seasons": sum(row["ndvi"] is not None for row in results),
        "attempted_scenes": sum(row["attempted_scenes"] for row in results),
        "scene_errors": sum(row["errors"] for row in results),
        "results": results,
    }
    original.WriteJson(output / "summary.json", summary)
    print(
        json.dumps({key: value for key, value in summary.items() if key != "results"}), flush=True
    )


if __name__ == "__main__":
    main()
