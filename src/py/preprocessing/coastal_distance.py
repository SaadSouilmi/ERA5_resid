"""Calculate coastal distance at the observation sources in the clean temperature sample."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import polars as pl
import shapely
from pyproj import Geod, Transformer

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY
from py.preprocessing.match_era5_grid import sha256

SOURCE_KEYS = ["SOUID", "source_lat", "source_lon"]
COORDINATE_KEYS = ["source_lat", "source_lon"]


def coast_distances(locations, coast_file, latitude="source_lat", longitude="source_lon"):
    coast = gpd.read_file(coast_file, bbox=(-45, 20, 75, 85))
    bounds = coast.bounds
    caspian = (bounds.minx > 46) & (bounds.maxx < 55) & (bounds.miny > 35) & (bounds.maxy < 49)
    segments = coast.loc[~caspian].to_crs("EPSG:3035").geometry.to_numpy()
    points = (
        gpd.GeoSeries(
            gpd.points_from_xy(locations[longitude], locations[latitude]), crs="EPSG:4326"
        )
        .to_crs("EPSG:3035")
        .to_numpy()
    )
    nearest = shapely.STRtree(segments).nearest(points)
    endpoints = shapely.get_point(shapely.shortest_line(points, segments[nearest]), 1)
    coast_lon, coast_lat = Transformer.from_crs(
        "EPSG:3035", "EPSG:4326", always_xy=True
    ).transform(shapely.get_x(endpoints), shapely.get_y(endpoints))
    _, _, metres = Geod(ellps="WGS84").inv(
        locations[longitude].to_numpy(), locations[latitude].to_numpy(), coast_lon, coast_lat
    )
    return locations.with_columns(
        pl.Series("coast_lat", coast_lat),
        pl.Series("coast_lon", coast_lon),
        pl.Series("dist_to_sea_km", metres / 1000),
    )


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    input_path = DATA_DIRECTORY / "station_era5_clean.parquet"
    coast_file = DATA_DIRECTORY / "clean/sources/ne_10m_coastline.zip"
    output = DATA_DIRECTORY / "station_coastal_distance.parquet"
    observations = pl.scan_parquet(input_path)
    sources = (
        observations.group_by(SOURCE_KEYS)
        .agg(pl.len().alias("observations"))
        .collect()
        .sort(SOURCE_KEYS)
    )
    locations = sources.select(COORDINATE_KEYS).unique().sort(COORDINATE_KEYS)
    print(f"Computing coastal distance for {locations.height:,} source coordinates", flush=True)
    distances = coast_distances(locations, coast_file)
    if not distances["dist_to_sea_km"].is_finite().all():
        raise ValueError("A source location has no finite coastal distance")
    lookup = sources.join(distances, on=COORDINATE_KEYS, how="left", validate="m:1")
    lookup.write_parquet(output, compression="zstd")
    joined = (
        observations.select(SOURCE_KEYS)
        .join(pl.scan_parquet(output), on=SOURCE_KEYS, how="left", validate="m:1")
        .select(
            pl.len().alias("observations"),
            pl.col("dist_to_sea_km").null_count().alias("missing_distances"),
        )
        .collect()
        .row(0, named=True)
    )
    if joined["observations"] != sources["observations"].sum() or joined["missing_distances"]:
        raise ValueError("The saved coastal lookup does not cover the clean sample")
    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "py.preprocessing.coastal_distance",
        "input": str(input_path),
        "input_sha256": sha256(input_path),
        "coastline": str(coast_file),
        "coastline_sha256": sha256(coast_file),
        "coastline_source": "https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-coastline/",
        "file": str(output),
        "sha256": sha256(output),
        "bytes": output.stat().st_size,
        "code_sha256": {__file__: sha256(Path(__file__))},
        "join_keys": SOURCE_KEYS,
        "sources": sources["SOUID"].n_unique(),
        "source_locations": lookup.height,
        "distinct_coordinates": locations.height,
        **joined,
        "distance_km": {
            "minimum": lookup["dist_to_sea_km"].min(),
            "median": lookup["dist_to_sea_km"].median(),
            "maximum": lookup["dist_to_sea_km"].max(),
        },
        "method": "Nearest point on the cached Natural Earth 1:10 million coastline in EPSG:3035; WGS84 ellipsoidal distance to that point, in kilometres.",
        "coastline_selection": "Features intersecting (-45, 20, 75, 85) degrees; Caspian Sea ring excluded by its bounds. Coastline geometries are not clipped to the ERA5 footprint.",
        "limitations": "Approximate coastal distance: coastline generalisation and the projected nearest-point search limit accuracy. Inland lake shores are not coastline.",
        "temperature_sample": "Unchanged; coastal distance is saved separately and joins many-to-one on SOUID and the source coordinates.",
    }
    audit_path = DATA_DIRECTORY / "cleaning_audit/station_coastal_distance.json"
    audit_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Saved {lookup.height:,} source locations: {output}", flush=True)
    print(json.dumps(joined, indent=2), flush=True)


if __name__ == "__main__":
    main()
