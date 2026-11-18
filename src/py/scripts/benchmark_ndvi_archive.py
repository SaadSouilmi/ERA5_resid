"""Estimate full-history acquisition counts, archive size and retrieval time."""

import argparse
import ctypes
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import polars as pl
import rasterio
from affine import Affine

from py.ndvi_acquisitions import fetch_acquisition
from py.ndvi_observations import CellBounds as cell_bounds
from py.ndvi_observations import WriteJson as write_json
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.scripts.fetch_ndvi_acquisitions import load_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--cells", type=int, default=32)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--count", type=int, default=256)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--run", default="full_pixels_32")
    parser.add_argument("--measure-transfer", action="store_true")
    args = parser.parse_args()
    root = DATA_DIRECTORY / "ndvi_observed"
    source_directory = root / "sentinel2_full_history_plan_v1"
    directory = root / "full_archive_benchmark_v1"
    directory.mkdir(exist_ok=True)
    manifest = json.loads((source_directory / "manifest.json").read_text())
    transform = Affine(*manifest["grid_transform"][:6])
    if args.prepare:
        tasks = pl.read_parquet(source_directory / "tasks.parquet")
        cells = (
            tasks.select("cell_id")
            .unique()
            .with_columns(pl.col("cell_id").hash(seed=20261119).alias("rank"))
            .sort("rank")
            .head(args.cells)
        )
        sample = tasks.join(cells.select("cell_id"), on="cell_id", how="inner")

        def inspect(task):
            try:
                items = load_catalog(task, source_directory, manifest)
                ordered = sorted(
                    items, key=lambda item: hashlib.sha256(item["id"].encode()).hexdigest()
                )
                return {
                    "cell_id": task["cell_id"],
                    "season_start": str(task["season_start"]),
                    "count": len({item["id"] for item in items}),
                    "error": None,
                    "case": {
                        "item": ordered[0],
                        "bounds": cell_bounds(task["source_lon"], task["source_lat"], transform),
                    }
                    if items
                    else None,
                }
            except Exception as error:
                return {
                    "cell_id": task["cell_id"],
                    "season_start": str(task["season_start"]),
                    "count": None,
                    "error": type(error).__name__,
                    "case": None,
                }

        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(inspect, sample.iter_rows(named=True)))
        cases = [row.pop("case") for row in results]
        cases = [case for case in cases if case is not None]
        cases.sort(
            key=lambda case: hashlib.sha256(
                json.dumps(case["bounds"]).encode() + case["item"]["id"].encode()
            ).hexdigest()
        )
        counts = pl.DataFrame(
            results,
            schema={
                "cell_id": pl.String,
                "season_start": pl.String,
                "count": pl.Int64,
                "error": pl.String,
            },
        )
        counts.write_parquet(directory / "catalog_counts.parquet")
        per_cell = counts.group_by("cell_id").agg(
            pl.col("count").sum(), pl.col("error").is_not_null().sum().alias("errors")
        )
        good = per_cell.filter(pl.col("errors") == 0)["count"].to_numpy()
        estimated_total = float(good.mean() * manifest["cells"])
        standard_error = float(good.std(ddof=1) / np.sqrt(len(good)) * manifest["cells"])
        summary = {
            "sampled_cells": len(cells),
            "sampled_cell_periods": len(sample),
            "catalog_errors": counts["error"].is_not_null().sum(),
            "sample_acquisitions": counts["count"].sum(),
            "full_study_cells": manifest["cells"],
            "estimated_acquisitions": estimated_total,
            "estimate_standard_error": standard_error,
            "catalog_seconds": time.monotonic() - started,
            "scope": "2019-01-01 through 2025-08-31, all selected locations, all catalogue item IDs",
            "sampling": "32 cells selected by fixed-seed hash, all 27 periods per cell; one acquisition per nonempty cell-period available for timing",
        }
        write_json(directory / "cases.json", cases)
        write_json(directory / "catalog_summary.json", summary)
        print(json.dumps(summary), flush=True)
        return
    cases = json.loads((directory / "cases.json").read_text())[
        args.offset : args.offset + args.count
    ]
    output = directory / args.run
    output.mkdir(exist_ok=True)
    if (output / "pixels").exists():
        raise ValueError("Use a new run label for an uncached benchmark")

    def fetch(case):
        return fetch_acquisition(
            case["item"], case["bounds"], output, source_directory / "product_metadata"
        )

    transfer = {}
    if args.measure_transfer:
        library = ctypes.CDLL(rasterio._env.__file__)
        library.VSINetworkStatsReset.argtypes = []
        library.VSINetworkStatsReset.restype = None
        library.VSINetworkStatsGetAsSerializedJSON.argtypes = [ctypes.c_void_p]
        library.VSINetworkStatsGetAsSerializedJSON.restype = ctypes.c_void_p
        library.VSIFree.argtypes = [ctypes.c_void_p]
        library.VSIFree.restype = None
        library.VSINetworkStatsReset()
    started = time.monotonic()
    with (
        rasterio.Env(CPL_VSIL_NETWORK_STATS_ENABLED="YES" if args.measure_transfer else "NO"),
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        results = list(pool.map(fetch, cases))
    elapsed = time.monotonic() - started
    if args.measure_transfer:
        pointer = library.VSINetworkStatsGetAsSerializedJSON(None)
        statistics = json.loads(ctypes.string_at(pointer))
        library.VSIFree(pointer)
        transfer = statistics.get("methods", {})
    logical_bytes, allocated_bytes, verified = [], [], 0
    for result in results:
        path = output / result["pixel_archive"]
        logical_bytes.append(path.stat().st_size)
        allocated_bytes.append(path.stat().st_blocks * 512)
        if result["status"] != "downloaded":
            continue
        with np.load(path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata_json"]))
            red = (archive["red_dn"].astype(float) + metadata["red_offset"]) / metadata[
                "quantification"
            ]
            nir = (archive["nir_dn"].astype(float) + metadata["nir_offset"]) / metadata[
                "quantification"
            ]
            valid = archive["valid_default_mask"]
            expected = (nir[valid] - red[valid]) / (nir[valid] + red[valid])
            if not np.array_equal(expected, archive["ndvi_default_mask"][valid]):
                raise ValueError("Saved raw pixels do not reproduce saved NDVI")
            if valid.any() and float(expected.mean()) != result["ndvi_mean"]:
                raise ValueError("Saved pixels do not reproduce acquisition mean")
            verified += 1
    summary = {
        "workers": args.workers,
        "scenes": len(cases),
        "elapsed_seconds": elapsed,
        "scenes_per_second": len(cases) / elapsed,
        "verified_complete_archives": verified,
        "errors": sum(row["status"] == "fetch_error" for row in results),
        "mean_archive_bytes": float(np.mean(logical_bytes)),
        "mean_allocated_bytes": float(np.mean(allocated_bytes)),
        "archive_bytes": sum(logical_bytes),
        "allocated_bytes": sum(allocated_bytes),
        "gdal_transfer": transfer,
        "transfer_note": "GDAL network statistics: actual raster response body bytes, excluding XML/catalogue traffic and HTTP overhead",
        "results": results,
    }
    write_json(output / "summary.json", summary)
    print(
        json.dumps({key: value for key, value in summary.items() if key != "results"}), flush=True
    )


if __name__ == "__main__":
    main()
