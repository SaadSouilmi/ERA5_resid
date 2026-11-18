"""Preserve Sentinel-2 cell pixels before any temporal or quality aggregation."""

import hashlib
import json
import os
import threading
from datetime import datetime, timezone

import numpy as np
import rasterio
from affine import Affine
from rasterio.windows import Window

from py.ndvi_fast import read_window, transformer
from py.ndvi_observations import PixelNdvi as pixel_ndvi
from py.ndvi_observations import ReflectanceParameters as reflectance_parameters

ARCHIVE_VERSION = "all_acquisitions_pixels_v1"


def archive_path(directory, item, bounds):
    cell_key = hashlib.sha256(json.dumps(bounds).encode()).hexdigest()[:16]
    return directory / "pixels" / cell_key / f"{item['id']}.npz"


def save_archive(path, arrays, metadata, summary):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with temporary.open("wb") as stream:
        np.savez_compressed(
            stream,
            **arrays,
            metadata_json=json.dumps(metadata, allow_nan=False),
            summary_json=json.dumps(summary, allow_nan=False),
        )
    temporary.replace(path)


def read_pixels(item, bounds, arrays, metadata, metadata_directory):
    assets = item["assets"]
    crs = item["properties"]["proj:epsg"]
    if (
        assets["B08"]["proj:transform"] != assets["B04"]["proj:transform"]
        or assets["B08"]["proj:shape"] != assets["B04"]["proj:shape"]
    ):
        raise ValueError("Red and near-infrared grids differ")
    left, bottom, right, top = bounds
    x, y = transformer(3035, crs).transform([left, right, right, left], [bottom, bottom, top, top])
    transform = Affine(*assets["B04"]["proj:transform"][:6])
    height, width = assets["B04"]["proj:shape"]
    rows, columns = rasterio.transform.rowcol(transform, x, y)
    row_start, col_start = max(0, min(rows)), max(0, min(columns))
    row_end, col_end = min(height, max(rows) + 1), min(width, max(columns) + 1)
    if row_end <= row_start or col_end <= col_start:
        return "outside_asset"
    window = Window(col_start, row_start, col_end - col_start, row_end - row_start)
    metadata["reflectance_window"] = [int(value) for value in window.flatten()]
    metadata["reflectance_window_transform"] = list(rasterio.windows.transform(window, transform))
    grid_rows, grid_cols = np.meshgrid(
        np.arange(row_start, row_end), np.arange(col_start, col_end), indexing="ij"
    )
    pixel_x, pixel_y = transform * (grid_cols + 0.5, grid_rows + 0.5)
    cell_x, cell_y = transformer(crs, 3035).transform(pixel_x, pixel_y)
    arrays["footprint"] = (cell_x >= left) & (cell_x < right) & (cell_y >= bottom) & (cell_y < top)
    quality_transform = Affine(*assets["SCL"]["proj:transform"][:6])
    q_rows, q_cols = rasterio.transform.rowcol(quality_transform, pixel_x.ravel(), pixel_y.ravel())
    q_rows, q_cols = np.asarray(q_rows), np.asarray(q_cols)
    q_height, q_width = assets["SCL"]["proj:shape"]
    covered = (q_rows >= 0) & (q_cols >= 0) & (q_rows < q_height) & (q_cols < q_width)
    arrays["scl_coverage"] = covered.reshape(arrays["footprint"].shape)
    if covered.any():
        q_row, q_col = q_rows[covered].min(), q_cols[covered].min()
        quality_window = Window(
            int(q_col),
            int(q_row),
            int(q_cols[covered].max() - q_col + 1),
            int(q_rows[covered].max() - q_row + 1),
        )
        metadata["scl_window"] = [int(value) for value in quality_window.flatten()]
        metadata["scl_window_transform"] = list(
            rasterio.windows.transform(quality_window, quality_transform)
        )
        if "scl_native" not in arrays:
            arrays["scl_native"] = read_window(assets["SCL"], quality_window, crs)
        classes = np.zeros(q_rows.shape, dtype=arrays["scl_native"].dtype)
        classes[covered] = arrays["scl_native"][q_rows[covered] - q_row, q_cols[covered] - q_col]
        arrays["scl"] = classes.reshape(arrays["footprint"].shape)
    else:
        arrays["scl"] = np.zeros(arrays["footprint"].shape, dtype=np.uint8)
    for name, band in (("red_dn", "B04"), ("nir_dn", "B08")):
        if name not in arrays:
            arrays[name] = read_window(assets[band], window, crs)
    if "quantification" not in metadata:
        quantification, red_offset, nir_offset = reflectance_parameters(item, metadata_directory)
        metadata.update(quantification=quantification, red_offset=red_offset, nir_offset=nir_offset)
    values, valid = pixel_ndvi(
        arrays["red_dn"],
        arrays["nir_dn"],
        arrays["scl"],
        arrays["footprint"],
        metadata["quantification"],
        metadata["red_offset"],
        metadata["nir_offset"],
    )
    arrays["ndvi_default_mask"] = values
    arrays["valid_default_mask"] = valid
    return "downloaded"


def scene_summary(item, path, directory, arrays, metadata, status, error_type):
    footprint = arrays.get("footprint")
    valid = arrays.get("valid_default_mask")
    count = int(footprint.sum()) if footprint is not None else 0
    valid_count = int(valid.sum()) if valid is not None else None
    fraction = valid_count / count if valid_count is not None and count else None
    value = float(arrays["ndvi_default_mask"][valid].mean()) if valid_count else None
    classes = arrays.get("scl")
    class_counts = (
        np.bincount(classes[footprint], minlength=12).tolist() if classes is not None else None
    )
    return {
        "scene_id": item["id"],
        "acquisition_datetime": item["properties"]["datetime"],
        "tile_cloud_cover": item["properties"].get("eo:cloud_cover"),
        "processing_baseline": item["properties"].get("s2:processing_baseline"),
        "native_epsg": item["properties"]["proj:epsg"],
        "status": status,
        "error_type": error_type,
        "ndvi_mean": value,
        "valid_fraction": fraction,
        "valid_pixels": valid_count,
        "footprint_pixels": count,
        "qualifies_default_mask": status == "downloaded" and count >= 50 and fraction >= 0.75,
        "scl_counts": class_counts,
        "quantification": metadata.get("quantification"),
        "red_offset": metadata.get("red_offset"),
        "nir_offset": metadata.get("nir_offset"),
        "pixel_archive": str(path.relative_to(directory)),
        "saved_arrays": sorted(arrays),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "archive_version": ARCHIVE_VERSION,
    }


def fetch_acquisition(item, bounds, directory, metadata_directory):
    path = archive_path(directory, item, bounds)
    arrays = {}
    metadata = {
        "archive_version": ARCHIVE_VERSION,
        "collection": "sentinel-2-l2a",
        "item": item,
        "cell_bounds_epsg3035": bounds,
        "default_mask": "SCL 4/5/6, positive DN, nonnegative corrected reflectance, positive sum",
        "array_geometry": "Red/NIR and aligned SCL on the native 10 m grid; scl_native on its original 20 m grid; footprint marks pixel centres inside the 80 m EPSG:3035 cell",
    }
    if path.exists():
        with np.load(path, allow_pickle=False) as archive:
            previous = json.loads(str(archive["summary_json"]))
            if previous["status"] in ("downloaded", "outside_asset"):
                return previous
            metadata = json.loads(str(archive["metadata_json"]))
            arrays = {name: archive[name] for name in archive.files if not name.endswith("_json")}
    error_type = None
    try:
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_HTTP_TIMEOUT="30",
            GDAL_HTTP_MAX_RETRY="1",
            GDAL_HTTP_RETRY_DELAY="1",
        ):
            status = read_pixels(item, bounds, arrays, metadata, metadata_directory)
    except Exception as error:
        status, error_type = "fetch_error", type(error).__name__
    summary = scene_summary(item, path, directory, arrays, metadata, status, error_type)
    save_archive(path, arrays, metadata, summary)
    return summary
