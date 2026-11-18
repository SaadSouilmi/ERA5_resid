"""Measure NDVI scene-reader speed and numerical agreement on saved acquisitions."""

import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import polars as pl
import rasterio

from py import ndvi_observations as original
from py.ndvi_fast import scene_value
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY


def prepare_cases(directory, count):
    cases = []
    for label in ("sentinel2_selected_gap_v1", "sentinel2_selected_overlap_v1"):
        source = DATA_DIRECTORY / "ndvi_observed" / label
        cells = pl.read_parquet(source / "cell_season_ndvi.parquet").filter(
            pl.col("scene_errors") == 0
        )
        cells = cells.with_columns(
            pl.struct("cell_id", "season_start").hash(seed=2026).alias("rank")
        ).sort("rank")
        for row in cells.head(count // 2).iter_rows(named=True):
            name = f"{row['cell_id']}_{row['season_start']}"
            season = json.loads((source / "seasons" / f"{name}.json").read_text())
            bounds = season["cell_bounds_epsg3035"]
            cell_key = hashlib.sha256(json.dumps(bounds).encode()).hexdigest()[:16]
            catalog = json.loads(
                (source / "catalog" / f"catalog_{name}_{season['season_end']}.json").read_text()
            )
            candidates = sorted(
                catalog,
                key=lambda item: (item["properties"].get("eo:cloud_cover", 100), item["id"]),
            )
            selected = {}
            for item in candidates:
                saved = source / "scene_values" / f"{item['id']}_{cell_key}.json"
                if not saved.exists():
                    continue
                value = json.loads(saved.read_text())
                kind = "clear" if value["ndvi"] is not None else "rejected"
                if kind not in selected:
                    selected[kind] = {
                        "item": item,
                        "bounds": bounds,
                        "reference": value,
                        "kind": kind,
                    }
                if len(selected) == 2:
                    break
            cases.extend(selected.values())
            if len(cases) >= count * (0.5 if label.endswith("gap_v1") else 1):
                break
    original.WriteJson(directory / "cases.json", cases[:count])
    print(f"Saved {min(len(cases), count)} scene cases", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--count", type=int, default=96)
    parser.add_argument("--reader", choices=["original", "fast"], default="original")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--run", default="original_16")
    args = parser.parse_args()
    directory = DATA_DIRECTORY / "ndvi_observed/reader_benchmark_v1"
    directory.mkdir(exist_ok=True)
    if args.prepare:
        prepare_cases(directory, args.count)
        return
    output = directory / args.run
    for name in ("scene_values", "product_metadata"):
        (output / name).mkdir(parents=True, exist_ok=True)
    cases = json.loads((directory / "cases.json").read_text())
    if any((output / "scene_values").iterdir()):
        raise ValueError("Use a new run name; benchmark must not reuse saved scene values")
    reader = original.SceneValue if args.reader == "original" else scene_value

    def retrieve(case):
        started = time.monotonic()
        try:
            value = reader(case["item"], case["bounds"], output)
            return {
                "id": case["item"]["id"],
                "kind": case["kind"],
                "seconds": time.monotonic() - started,
                "matches": value == case["reference"],
                "error": None,
            }
        except Exception as error:
            return {
                "id": case["item"]["id"],
                "kind": case["kind"],
                "seconds": time.monotonic() - started,
                "matches": False,
                "error": type(error).__name__,
                "error_detail": re.sub(r"https?://[^\s\"']+", "<url>", str(error))[:500],
            }

    started = time.monotonic()
    with rasterio.Env(), ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(retrieve, cases))
    elapsed = time.monotonic() - started
    summary = {
        "reader": args.reader,
        "workers": args.workers,
        "scenes": len(cases),
        "elapsed_seconds": elapsed,
        "scenes_per_second": len(cases) / elapsed,
        "matches": sum(row["matches"] for row in results),
        "failures": sum(row["error"] is not None for row in results),
        "mismatches_without_error": sum(
            not row["matches"] and row["error"] is None for row in results
        ),
        "results": results,
    }
    original.WriteJson(output / "summary.json", summary)
    print(
        json.dumps({key: value for key, value in summary.items() if key != "results"}), flush=True
    )


if __name__ == "__main__":
    main()
