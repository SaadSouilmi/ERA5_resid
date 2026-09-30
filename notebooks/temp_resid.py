import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import altair as alt
    import geopandas as gpd
    import numpy as np
    import pandas as pd
    import polars as pl
    import pycountry
    import rasterio
    import reverse_geocoder as rg
    import xarray as xr
    from rasterio.warp import transform
    from tqdm import tqdm
    import marimo as mo
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    return Path, gpd, np, pd, pycountry, rasterio, rg, tqdm, transform, xr


@app.cell
def _(Path):
    DATA = Path("/home2/lobib/gen_hack/data/main")
    DATA2 = Path("/home2/lobib/gen_hack/data2/")
    degurba_path = (
        DATA2
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    return DATA, DATA2, degurba_path


@app.cell
def _(Path, degurba_path, gpd, np, pd, pycountry, rasterio, rg, transform):
    def dms_to_decimal(dms_str):
        """Convert DMS string (+DD:MM:SS) to decimal degrees."""
        dms_str = dms_str.strip()
        sign = 1 if dms_str[0] == "+" else -1
        dms_str = dms_str[1:]
        parts = dms_str.split(":")
        return sign * (float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600)

    def load_station_data(eca_tx_datafolder: Path) -> pd.DataFrame:
        stations_filepath = eca_tx_datafolder / "stations.txt"

        stations_df = pd.read_csv(
            stations_filepath, skiprows=17, skipinitialspace=True
        )
        stations_df["LAT_decimal"] = stations_df["LAT"].apply(dms_to_decimal)
        stations_df["LON_decimal"] = stations_df["LON"].apply(dms_to_decimal)
        stations_df["country"] = stations_df["CN"].apply(
            lambda x: pycountry.countries.get(alpha_2=x.rstrip(" ")).name
        )
        stations_df = stations_df.rename(columns={"HGHT": "elevation"})
        stations_df["place"] = [
            dico["name"]
            for dico in rg.search(
                list(zip(stations_df["LAT_decimal"], stations_df["LON_decimal"]))
            )
        ]

        stations_gdf = gpd.GeoDataFrame(
            stations_df,
            geometry=gpd.points_from_xy(
                stations_df["LON_decimal"], stations_df["LAT_decimal"]
            ),
            crs="EPSG:4326",
        ).drop(columns=["LAT", "LON", "LAT_decimal", "LON_decimal"])

        print(f"Number of registered stations: {len(stations_gdf)}")
        return stations_gdf


    def load_degurba_data(
        stations_gdf: gpd.GeoDataFrame, deburba_path: Path
    ) -> gpd.GeoDataFrame:
        with rasterio.open(degurba_path) as src:
            nodata = src.nodata
            lons = stations_gdf.geometry.x.values
            lats = stations_gdf.geometry.y.values

            # Reproject station coords from WGS84 to the raster CRS (Mollweide)
            xs, ys = transform("EPSG:4326", src.crs, lons, lats)

            degurba_vals = []
            for i in range(len(stations_gdf)):
                row, col = src.index(xs[i], ys[i])
                if 0 <= row < src.height and 0 <= col < src.width:
                    val = src.read(
                        1, window=rasterio.windows.Window(col, row, 1, 1)
                    )[0, 0]
                    degurba_vals.append(np.nan if val == nodata else int(val))
                else:
                    degurba_vals.append(np.nan)

        stations_gdf["degurba"] = degurba_vals
        print(
            f"degurba nulls: {stations_gdf['degurba'].isna().sum()} / {len(stations_gdf)}"
        )

        DEGURBA_LABELS = {
            10: "Water",
            11: "Very low density rural",
            12: "Low density rural",
            13: "Rural cluster",
            21: "Suburban",
            22: "Semi-dense urban cluster",
            23: "Dense urban cluster",
            30: "Urban centre",
        }

        stations_gdf["degurba_label"] = stations_gdf["degurba"].map(DEGURBA_LABELS)
        return stations_gdf


    def compute_distance_to_sea_km(
        stations_gdf: gpd.GeoDataFrame, europe_gdf: gpd.GeoDataFrame
    ) -> gpd.GeoDataFrame:
        import shapely
        from shapely import STRtree

        coastline = (
            europe_gdf.dissolve().to_crs("EPSG:3035").boundary.iloc[0].simplify(500)
        )
        # Split into per-ring/part geometries so the STRtree can prune candidates
        # before computing exact distances (O(n·log m) instead of O(n·m))
        segments = list(coastline.geoms) if coastline.geom_type == "MultiLineString" else [coastline]

        stations_3035 = stations_gdf.to_crs("EPSG:3035")
        points = stations_3035.geometry.values

        tree = STRtree(segments)
        nearest_idx = tree.nearest(points)
        distances = shapely.distance(points, np.array(segments, dtype=object)[nearest_idx])

        stations_gdf = stations_gdf.copy()
        stations_gdf["dist_to_sea_km"] = distances / 1000
        return stations_gdf


    return load_degurba_data, load_station_data


@app.cell
def _(Path, np, pd, pycountry, rasterio, tqdm, transform, xr):
    def load_era5_data(era5_dir: Path) -> xr.Dataset:
        era5_files = sorted(era5_dir.glob("*.nc"))
        era5_ds = xr.open_mfdataset(era5_files, combine="by_coords", join="inner")
        era5_ds["t2m_celsius"] = era5_ds["t2m"] - 273.15
        era5_ds["wind"] = np.sqrt(era5_ds["u10"] ** 2 + era5_ds["v10"] ** 2)
        return era5_ds

    def extract_era5_at_stations(era5_ds, stations_gdf):
        variables = ["t2m_celsius", "tp", "wind"]
        all_lats = xr.DataArray(stations_gdf.geometry.y.values, dims="station")
        all_lons = xr.DataArray(stations_gdf.geometry.x.values, dims="station")

        era5_all_stations = {
            var: era5_ds[var]
            .sel(latitude=all_lats, longitude=all_lons, method="nearest")
            .compute()
            for var in variables
        }

        nan_mask = era5_all_stations["t2m_celsius"].isnull().all(dim="valid_time")
        nan_indices = np.where(nan_mask.values)[0]
        print(f"Stations with no ERA5 data: {len(nan_indices)}")

        sample = era5_ds["t2m_celsius"].isel(valid_time=0).compute()
        land_points = sample.stack(point=("latitude", "longitude"))
        valid = land_points.notnull().values
        land_lat_vals = land_points.latitude.values[valid]
        land_lon_vals = land_points.longitude.values[valid]

        for station_idx in tqdm(nan_indices, colour="green"):
            slat = stations_gdf.geometry.y.values[station_idx]
            slon = stations_gdf.geometry.x.values[station_idx]
            dists = (land_lat_vals - slat) ** 2 + (land_lon_vals - slon) ** 2
            nearest = np.argmin(dists)
            nearest_lat = land_lat_vals[nearest]
            nearest_lon = land_lon_vals[nearest]
            for var in variables:
                era5_all_stations[var][:, station_idx] = era5_ds[var].sel(
                    latitude=nearest_lat, longitude=nearest_lon
                ).values

        return era5_all_stations

    def compute_residuals(stations_gdf, era5_all_stations, era5_ds, eca_tx_datafolder: Path):
        all_residuals = []
        era5_times = pd.DatetimeIndex(era5_ds.valid_time.values)

        for i, (_, row) in tqdm(
            enumerate(stations_gdf.iterrows()), total=len(stations_gdf), colour="green"
        ):
            filepath = eca_tx_datafolder / f"TX_STAID{row['STAID']:06d}.txt"
            if not filepath.exists():
                continue

            station_df = pd.read_csv(filepath, skiprows=20, skipinitialspace=True)
            station_df = station_df[station_df["Q_TX"] == 0].copy()
            station_df["DATE"] = pd.to_datetime(station_df["DATE"], format="%Y%m%d")
            station_df = station_df[station_df["DATE"].isin(era5_times)]
            if len(station_df) == 0:
                continue

            station_df["TX_celsius"] = station_df["TX"] / 10.0
            time_indices = era5_times.get_indexer(station_df["DATE"])

            all_residuals.append(
                pd.DataFrame({
                    "STAID": row["STAID"],
                    "country": row["country"],
                    "place": row["place"],
                    "elevation": row["elevation"],
                    "lon": row["geometry"].x,
                    "lat": row["geometry"].y,
                    "date": station_df["DATE"].values,
                    "station_celsius": station_df["TX_celsius"].values,
                    "era5_celsius": era5_all_stations["t2m_celsius"].values[time_indices, i],
                    "residual": station_df["TX_celsius"].values - era5_all_stations["t2m_celsius"].values[time_indices, i],
                    "tp": era5_all_stations["tp"].values[time_indices, i],
                    "wind": era5_all_stations["wind"].values[time_indices, i],
                })
            )

        return pd.concat(all_residuals, ignore_index=True)

    def add_ndvi(residuals_df, stations_gdf, ndvi_dir: Path):
        def quarter_tp(date):
            m, y = date.month, date.year
            if m < 3:
                return f"{y-1}-12-01_{y}-03-01"
            elif m < 6:
                return f"{y}-03-01_{y}-06-01"
            elif m < 9:
                return f"{y}-06-01_{y}-09-01"
            elif m < 12:
                return f"{y}-09-01_{y}-12-01"
            else:
                return f"{y}-12-01_{y+1}-03-01"

        available = sorted(
            [f.stem.replace("ndvi_", "") for f in ndvi_dir.glob("ndvi_*.tif")],
            reverse=True,
        )

        def resolve_quarter(date):
            for years_back in range(6):
                tp = quarter_tp(date - pd.DateOffset(years=years_back))
                if tp in available:
                    return tp
            return None

        sta_lats = stations_gdf.set_index("STAID")["geometry"].apply(lambda g: g.y)
        sta_lons = stations_gdf.set_index("STAID")["geometry"].apply(lambda g: g.x)

        residuals_df = residuals_df.copy()
        residuals_df["_ndvi_tp"] = residuals_df["date"].apply(resolve_quarter)

        lookup = {}
        for tp in tqdm(residuals_df["_ndvi_tp"].unique(), colour="green"):
            path = ndvi_dir / f"ndvi_{tp}.tif"
            if not path.exists():
                continue
            with rasterio.open(path) as src:
                nodata = src.nodata
                staids = residuals_df.loc[residuals_df["_ndvi_tp"] == tp, "STAID"].unique()
                lats = sta_lats.reindex(staids).values
                lons = sta_lons.reindex(staids).values
                xs, ys = (lons, lats) if src.crs.to_epsg() == 4326 else transform("EPSG:4326", src.crs, lons, lats)
                for i, staid in enumerate(staids):
                    r, c = src.index(xs[i], ys[i])
                    if 0 <= r < src.height and 0 <= c < src.width:
                        val = src.read(1, window=rasterio.windows.Window(c, r, 1, 1))[0, 0]
                        lookup[(staid, tp)] = np.nan if val == nodata else val / 254 * 2 - 1
                    else:
                        lookup[(staid, tp)] = np.nan

        residuals_df["ndvi"] = [
            lookup.get((s, t), np.nan)
            for s, t in zip(residuals_df["STAID"], residuals_df["_ndvi_tp"])
        ]
        residuals_df.drop(columns="_ndvi_tp", inplace=True)
        print(f"NDVI nulls: {residuals_df['ndvi'].isna().sum()} / {len(residuals_df)}")
        return residuals_df

    def add_country_code(residuals_df):
        residuals_df = residuals_df.copy()
        residuals_df["country_code"] = residuals_df["country"].apply(
            lambda x: pycountry.countries.get(name=x).alpha_3
        )
        return residuals_df

    return (
        add_country_code,
        add_ndvi,
        compute_residuals,
        extract_era5_at_stations,
        load_era5_data,
    )


@app.cell
def _(DATA, DATA2, degurba_path, gpd, load_degurba_data, load_station_data):
    europe_gdf = gpd.read_file(DATA / "gadm_410_europe.gpkg")

    stations_gdf = load_station_data(DATA2 / "ECA_blend_tx")
    stations_gdf = load_degurba_data(stations_gdf, degurba_path)
    # stations_gdf = compute_distance_to_sea_km(stations_gdf, europe_gdf)
    return (stations_gdf,)


@app.cell
def _(DATA2, pd, stations_gdf):
    stations_df = pd.read_csv(DATA2 / "stations_data.csv")
    stations_gdf["dist_to_sea_km"] = stations_df["dist_to_sea_km"]
    return


@app.cell
def _(DATA, extract_era5_at_stations, load_era5_data, stations_gdf):
    era5_ds = load_era5_data(DATA / "derived-era5-land-daily-statistics")
    era5_all_stations = extract_era5_at_stations(era5_ds, stations_gdf)
    return era5_all_stations, era5_ds


@app.cell
def _(
    DATA,
    DATA2,
    add_country_code,
    add_ndvi,
    compute_residuals,
    era5_all_stations,
    era5_ds,
    stations_gdf,
):
    residuals_df = compute_residuals(
        stations_gdf, era5_all_stations, era5_ds, DATA / "ECA_blend_tx"
    )
    residuals_df = residuals_df.merge(
        stations_gdf[["STAID", "dist_to_sea_km", "degurba", "degurba_label"]],
        on="STAID",
        how="left",
    )
    residuals_df = add_ndvi(residuals_df, stations_gdf, DATA / "sentinel2_ndvi")
    residuals_df = add_country_code(residuals_df)

    residuals_df.to_parquet(DATA2 / "residuals.parquet", index=False)
    print(f"Saved {len(residuals_df):,} rows to {DATA2 / 'residuals.parquet'}")
    residuals_df.info()
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
