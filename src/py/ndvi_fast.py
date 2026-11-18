"""Read the existing NDVI estimator with quality screening before reflectance I/O."""

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache

import numpy as np
import rasterio
from affine import Affine
from pyproj import Transformer
from rasterio.windows import Window

from py.ndvi_observations import PixelNdvi as pixel_ndvi
from py.ndvi_observations import AddMonths as add_months
from py.ndvi_observations import CatalogItems as catalog_items
from py.ndvi_observations import CellBounds as cell_bounds
from py.ndvi_observations import ReflectanceParameters as reflectance_parameters
from py.ndvi_observations import Sign as sign
from py.ndvi_observations import WriteJson as write_json


@lru_cache(maxsize=64)
def transformer(source_crs, target_crs):
    return Transformer.from_crs(source_crs, target_crs, always_xy=True)


def read_window(asset, window, crs):
    with rasterio.open(sign(asset["href"])) as raster:
        if (
            raster.transform != Affine(*asset["proj:transform"][:6])
            or list(raster.shape) != asset["proj:shape"]
            or raster.crs.to_epsg() != crs
        ):
            raise ValueError("Raster grid differs from catalogue metadata")
        return raster.read(1, window=window)


def scene_value(item, bounds, directory):
    cell_key = hashlib.sha256(json.dumps(bounds).encode()).hexdigest()[:16]
    file = directory / "scene_values" / f"{item['id']}_{cell_key}.json"
    if file.exists():
        return json.loads(file.read_text())
    assets = item["assets"]
    crs = item["properties"]["proj:epsg"]
    left, bottom, right, top = bounds
    x, y = transformer(3035, crs).transform([left, right, right, left], [bottom, bottom, top, top])
    transform = Affine(*assets["B04"]["proj:transform"][:6])
    height, width = assets["B04"]["proj:shape"]
    rows, columns = rasterio.transform.rowcol(transform, x, y)
    row_start, col_start = max(0, min(rows)), max(0, min(columns))
    row_end, col_end = min(height, max(rows) + 1), min(width, max(columns) + 1)
    if row_end <= row_start or col_end <= col_start:
        return {"id": item["id"], "valid_fraction": 0.0, "ndvi": None}
    window = Window(col_start, row_start, col_end - col_start, row_end - row_start)
    grid_rows, grid_cols = np.meshgrid(
        np.arange(row_start, row_end), np.arange(col_start, col_end), indexing="ij"
    )
    pixel_x = transform.c + (grid_cols + 0.5) * transform.a
    pixel_y = transform.f + (grid_rows + 0.5) * transform.e
    cell_x, cell_y = transformer(crs, 3035).transform(pixel_x, pixel_y)
    footprint = (cell_x >= left) & (cell_x < right) & (cell_y >= bottom) & (cell_y < top)
    quality_transform = Affine(*assets["SCL"]["proj:transform"][:6])
    q_rows, q_cols = rasterio.transform.rowcol(quality_transform, pixel_x.ravel(), pixel_y.ravel())
    q_rows, q_cols = np.asarray(q_rows), np.asarray(q_cols)
    q_height, q_width = assets["SCL"]["proj:shape"]
    if (
        (q_rows < 0).any()
        or (q_cols < 0).any()
        or (q_rows >= q_height).any()
        or (q_cols >= q_width).any()
    ):
        return {"id": item["id"], "valid_fraction": 0.0, "ndvi": None}
    q_row, q_col = q_rows.min(), q_cols.min()
    quality_window = Window(
        int(q_col), int(q_row), int(q_cols.max() - q_col + 1), int(q_rows.max() - q_row + 1)
    )
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_TIMEOUT="30",
        GDAL_HTTP_MAX_RETRY="1",
        GDAL_HTTP_RETRY_DELAY="1",
    ):
        quality = read_window(assets["SCL"], quality_window, crs)
        classes = quality[q_rows - q_row, q_cols - q_col].reshape(footprint.shape)
        clear = footprint & np.isin(classes, [4, 5, 6])
        if footprint.sum() < 50 or clear.sum() / footprint.sum() < 0.75:
            result = {
                "id": item["id"],
                "valid_fraction": float(clear.sum() / max(1, footprint.sum())),
                "ndvi": None,
            }
        else:
            if assets["B08"]["proj:transform"] != assets["B04"]["proj:transform"]:
                raise ValueError("Red and near-infrared grids differ")
            red = read_window(assets["B04"], window, crs)
            nir = read_window(assets["B08"], window, crs)
            quantification, red_offset, nir_offset = reflectance_parameters(
                item, directory / "product_metadata"
            )
            values, valid = pixel_ndvi(
                red, nir, classes, footprint, quantification, red_offset, nir_offset
            )
            fraction = float(valid.sum() / footprint.sum())
            result = {
                "id": item["id"],
                "valid_fraction": fraction,
                "ndvi": float(np.nanmean(values)) if fraction >= 0.75 else None,
                "quantification": quantification,
                "red_offset": red_offset,
                "nir_offset": nir_offset,
                "valid_pixels": int(valid.sum()),
                "footprint_pixels": int(footprint.sum()),
            }
    result["acquisition_date"] = item["properties"]["datetime"][:10]
    write_json(file, result)
    return result


def fetch_season(source, start, directory, transform, per_month=2, max_attempts=16):
    end = add_months(start, 3)
    file = directory / "seasons" / f"{source['SOUID']}_{start}.json"
    if file.exists():
        return json.loads(file.read_text())
    items = catalog_items(source, start, end, directory / "catalog")
    bounds = cell_bounds(source["source_lon"], source["source_lat"], transform)
    accepted, errors, monthly, checked = [], [], [], []
    attempts = 0
    for offset in range(3):
        month = add_months(start, offset).isoformat()[:7]
        checked.append(month)
        candidates = sorted(
            [item for item in items if item["properties"]["datetime"].startswith(month)],
            key=lambda item: (item["properties"].get("eo:cloud_cover", 100), item["id"]),
        )
        dates, values = set(), []
        for item in candidates[:max_attempts]:
            day = item["properties"]["datetime"][:10]
            if day in dates:
                continue
            attempts += 1
            try:
                result = scene_value(item, bounds, directory)
            except Exception as error:
                errors.append({"id": item["id"], "error_type": type(error).__name__})
                continue
            if result["ndvi"] is not None:
                dates.add(day)
                accepted.append(result)
                values.append(result["ndvi"])
                if len(values) >= per_month:
                    break
        if not values:
            break
        monthly.append(
            {"month": month, "ndvi": float(np.median(values)), "observations": len(values)}
        )
    qualified = len(monthly) == 3 and len(accepted) >= 3
    result = {
        "SOUID": source["SOUID"],
        "source_lat": source["source_lat"],
        "source_lon": source["source_lon"],
        "season_start": start.isoformat(),
        "season_end": end.isoformat(),
        "ndvi_observed": float(np.mean([row["ndvi"] for row in monthly])) if qualified else None,
        "status": "observed_season" if qualified else "insufficient_month_coverage",
        "valid_dates": len(accepted),
        "valid_months": len(monthly),
        "attempted_scenes": attempts,
        "catalog_scenes": len(items),
        "months_checked": checked,
        "stopped_after_empty_month": len(checked) < 3,
        "monthly": monthly,
        "accepted_scenes": accepted,
        "errors": errors,
        "cell_bounds_epsg3035": bounds,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "reader": "quality_first_v1",
    }
    write_json(file, result)
    return result
