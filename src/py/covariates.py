"""Sample source coordinates without interpolating or filling raster nodata."""

import numpy as np
import rasterio
from rasterio.warp import transform


def sample_raster(path, sources):
    with rasterio.open(path) as raster:
        if raster.crs is None:
            raise ValueError(f"Raster CRS missing: {path}")
        xs, ys = transform(
            "EPSG:4326", raster.crs, sources["lon"].to_list(), sources["lat"].to_list()
        )
        rows, columns = rasterio.transform.rowcol(raster.transform, xs, ys)
        valid = (
            (np.asarray(rows) >= 0)
            & (np.asarray(rows) < raster.height)
            & (np.asarray(columns) >= 0)
            & (np.asarray(columns) < raster.width)
        )
        values = np.full(len(sources), np.nan)
        indices = np.flatnonzero(valid)
        for index, sample in zip(
            indices,
            raster.sample([(xs[item], ys[item]) for item in indices], indexes=1, masked=True),
        ):
            if not np.ma.is_masked(sample[0]):
                values[index] = float(sample[0])
        return values
