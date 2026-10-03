import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import geopandas as Gpd
    import marimo as Mo
    import numpy as Np
    import pandas as Pd
    import pycountry as Pycountry
    import rasterio as Rasterio
    import reverse_geocoder as Rg
    import xarray as Xr
    from rasterio.warp import transform as Transform
    from tqdm import tqdm as Tqdm

    from py.cleaning import AttachStationDistances, GridExtent, LoadResiduals

    return (
        Path,
        Gpd,
        Mo,
        Np,
        Pd,
        Pycountry,
        Rasterio,
        Rg,
        Tqdm,
        Transform,
        Xr,
        AttachStationDistances,
        GridExtent,
        LoadResiduals,
    )


@app.cell
def _(Path, Mo):
    from py.paths import AnalysisDataDirectory, RawDataDirectory

    DegurbaPath = (
        AnalysisDataDirectory
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    Rebuild = bool(Mo.cli_args().get("rebuild", False))
    return RawDataDirectory, AnalysisDataDirectory, DegurbaPath, Rebuild


@app.cell
def _(Path, DegurbaPath, Gpd, Np, Pd, Pycountry, Rasterio, Rg, Transform):
    def DmsToDecimal(DmsStr):
        """Convert DMS string (+DD:MM:SS) to decimal degrees."""
        DmsStr = DmsStr.strip()
        Sign = 1 if DmsStr[0] == "+" else -1
        DmsStr = DmsStr[1:]
        Parts = DmsStr.split(":")
        return Sign * (float(Parts[0]) + float(Parts[1]) / 60 + float(Parts[2]) / 3600)

    def LoadStationData(EcaTxDatafolder: Path) -> Pd.DataFrame:
        StationsFilepath = EcaTxDatafolder / "stations.txt"

        StationsDf = Pd.read_csv(StationsFilepath, skiprows=17, skipinitialspace=True)
        StationsDf["LAT_decimal"] = StationsDf["LAT"].apply(DmsToDecimal)
        StationsDf["LON_decimal"] = StationsDf["LON"].apply(DmsToDecimal)
        StationsDf["country"] = StationsDf["CN"].apply(
            lambda X: Pycountry.countries.get(alpha_2=X.rstrip(" ")).name
        )
        StationsDf = StationsDf.rename(columns={"HGHT": "elevation"})
        StationsDf["place"] = [
            Dico["name"]
            for Dico in Rg.search(list(zip(StationsDf["LAT_decimal"], StationsDf["LON_decimal"])))
        ]

        StationsGdf = Gpd.GeoDataFrame(
            StationsDf,
            geometry=Gpd.points_from_xy(StationsDf["LON_decimal"], StationsDf["LAT_decimal"]),
            crs="EPSG:4326",
        ).drop(columns=["LAT", "LON", "LAT_decimal", "LON_decimal"])

        print(f"Number of registered stations: {len(StationsGdf)}")
        return StationsGdf

    def LoadDegurbaData(StationsGdf: Gpd.GeoDataFrame, DegurbaRaster: Path) -> Gpd.GeoDataFrame:
        with Rasterio.open(DegurbaRaster) as Src:
            Nodata = Src.nodata
            Lons = StationsGdf.geometry.x.values
            Lats = StationsGdf.geometry.y.values

            # Reproject station coords from WGS84 to the raster CRS (Mollweide)
            Xs, Ys = Transform("EPSG:4326", Src.crs, Lons, Lats)

            DegurbaVals = []
            for Index in range(len(StationsGdf)):
                Row, Col = Src.index(Xs[Index], Ys[Index])
                if 0 <= Row < Src.height and 0 <= Col < Src.width:
                    Val = Src.read(1, window=Rasterio.windows.Window(Col, Row, 1, 1))[0, 0]
                    DegurbaVals.append(Np.nan if Val == Nodata else int(Val))
                else:
                    DegurbaVals.append(Np.nan)

        StationsGdf["degurba"] = DegurbaVals
        print(f"degurba nulls: {StationsGdf['degurba'].isna().sum()} / {len(StationsGdf)}")

        DegurbaLabels = {
            10: "Water",
            11: "Very low density rural",
            12: "Low density rural",
            13: "Rural cluster",
            21: "Suburban",
            22: "Semi-dense urban cluster",
            23: "Dense urban cluster",
            30: "Urban centre",
        }

        StationsGdf["degurba_label"] = StationsGdf["degurba"].map(DegurbaLabels)
        return StationsGdf

    def ComputeDistanceToSeaKm(
        StationsGdf: Gpd.GeoDataFrame, EuropeGdf: Gpd.GeoDataFrame
    ) -> Gpd.GeoDataFrame:
        import shapely as Shapely
        from shapely import STRtree

        Coastline = EuropeGdf.dissolve().to_crs("EPSG:3035").boundary.iloc[0].simplify(500)
        # Split into per-ring/part geometries so the STRtree can prune candidates
        # before computing exact distances (O(n·log m) instead of O(n·m))
        Segments = (
            list(Coastline.geoms) if Coastline.geom_type == "MultiLineString" else [Coastline]
        )

        Stations3035 = StationsGdf.to_crs("EPSG:3035")
        Points = Stations3035.geometry.values

        Tree = STRtree(Segments)
        NearestIdx = Tree.nearest(Points)
        Distances = Shapely.distance(Points, Np.array(Segments, dtype=object)[NearestIdx])

        StationsGdf = StationsGdf.copy()
        StationsGdf["dist_to_sea_km"] = Distances / 1000
        return StationsGdf

    return LoadDegurbaData, LoadStationData


@app.cell
def _(Path, Np, Pd, Pycountry, Rasterio, Tqdm, Transform, Xr):
    def LoadEra5Data(Era5Dir: Path) -> Xr.Dataset:
        Era5Files = sorted(Era5Dir.glob("*.nc"))
        Era5Ds = Xr.open_mfdataset(Era5Files, combine="by_coords", join="inner")
        Era5Ds["t2m_celsius"] = Era5Ds["t2m"] - 273.15
        Era5Ds["wind"] = Np.sqrt(Era5Ds["u10"] ** 2 + Era5Ds["v10"] ** 2)
        return Era5Ds

    def ExtractEra5AtStations(Era5Ds, StationsGdf):
        from sklearn.neighbors import BallTree

        Variables = ["t2m_celsius", "tp", "wind"]
        AllLats = Xr.DataArray(StationsGdf.geometry.y.values, dims="station")
        AllLons = Xr.DataArray(StationsGdf.geometry.x.values, dims="station")

        Era5AllStations = {
            Var: Era5Ds[Var].sel(latitude=AllLats, longitude=AllLons, method="nearest").compute()
            for Var in Variables
        }

        NanMask = Era5AllStations["t2m_celsius"].isnull().all(dim="valid_time")
        NanIndices = Np.where(NanMask.values)[0]
        print(f"Stations with no ERA5 data: {len(NanIndices)}")

        Sample = Era5Ds["t2m_celsius"].isel(valid_time=0).compute()
        LandPoints = Sample.stack(point=("latitude", "longitude"))
        Valid = LandPoints.notnull().values
        LandLatVals = LandPoints.latitude.values[Valid]
        LandLonVals = LandPoints.longitude.values[Valid]
        LandTree = BallTree(
            Np.radians(Np.column_stack([LandLatVals, LandLonVals])), metric="haversine"
        )

        for StationIdx in Tqdm(NanIndices, colour="green"):
            Slat = StationsGdf.geometry.y.values[StationIdx]
            Slon = StationsGdf.geometry.x.values[StationIdx]
            _, NearestIndex = LandTree.query(Np.radians([[Slat, Slon]]), k=1)
            Nearest = NearestIndex[0, 0]
            NearestLat = LandLatVals[Nearest]
            NearestLon = LandLonVals[Nearest]
            for Var in Variables:
                Era5AllStations[Var][:, StationIdx] = (
                    Era5Ds[Var].sel(latitude=NearestLat, longitude=NearestLon).values
                )

        return Era5AllStations

    def ComputeResiduals(StationsGdf, Era5AllStations, Era5Ds, EcaTxDatafolder: Path):
        AllResiduals = []
        Era5Times = Pd.DatetimeIndex(Era5Ds.valid_time.values)

        for Index, (_, Row) in Tqdm(
            enumerate(StationsGdf.iterrows()), total=len(StationsGdf), colour="green"
        ):
            Filepath = EcaTxDatafolder / f"TX_STAID{Row['STAID']:06d}.txt"
            if not Filepath.exists():
                continue

            StationDf = Pd.read_csv(Filepath, skiprows=20, skipinitialspace=True)
            StationDf = StationDf[(StationDf["Q_TX"] == 0) & (StationDf["TX"] != -9999)].copy()
            StationDf["DATE"] = Pd.to_datetime(StationDf["DATE"], format="%Y%m%d")
            StationDf = StationDf[StationDf["DATE"].isin(Era5Times)]
            if StationDf["DATE"].duplicated().any():
                raise ValueError(f"Duplicate dates at station {Row['STAID']}")
            if len(StationDf) == 0:
                continue

            StationDf["TX_celsius"] = StationDf["TX"] / 10.0
            TimeIndices = Era5Times.get_indexer(StationDf["DATE"])

            AllResiduals.append(
                Pd.DataFrame(
                    {
                        "STAID": Row["STAID"],
                        "country": Row["country"],
                        "place": Row["place"],
                        "elevation": Row["elevation"],
                        "lon": Row["geometry"].x,
                        "lat": Row["geometry"].y,
                        "date": StationDf["DATE"].values,
                        "station_celsius": StationDf["TX_celsius"].values,
                        "era5_celsius": Era5AllStations["t2m_celsius"].values[TimeIndices, Index],
                        "residual": StationDf["TX_celsius"].values
                        - Era5AllStations["t2m_celsius"].values[TimeIndices, Index],
                        "tp": Era5AllStations["tp"].values[TimeIndices, Index],
                        "wind": Era5AllStations["wind"].values[TimeIndices, Index],
                    }
                )
            )

        return Pd.concat(AllResiduals, ignore_index=True)

    def AddNdvi(ResidualsDf, StationsGdf, NdviDir: Path):
        import polars as Pl

        from py.covariates import AddSeasonalNdvi

        return AddSeasonalNdvi(Pl.from_pandas(ResidualsDf), NdviDir).to_pandas()

    def AddCountryCode(ResidualsDf):
        ResidualsDf = ResidualsDf.copy()
        ResidualsDf["country_code"] = ResidualsDf["country"].apply(
            lambda X: Pycountry.countries.get(name=X).alpha_3
        )
        return ResidualsDf

    return (
        AddCountryCode,
        AddNdvi,
        ComputeResiduals,
        ExtractEra5AtStations,
        LoadEra5Data,
    )


@app.cell
def _(RawDataDirectory, DegurbaPath, LoadDegurbaData, LoadStationData, Rebuild, GridExtent):
    StationsGdf = None
    if Rebuild:
        StationsGdf = LoadStationData(RawDataDirectory / "ECA_blend_tx")
        StationsGdf = StationsGdf[
            StationsGdf.geometry.x.between(*GridExtent[:2])
            & StationsGdf.geometry.y.between(*GridExtent[2:])
        ].copy()
        StationsGdf = LoadDegurbaData(StationsGdf, DegurbaPath)
    return (StationsGdf,)


@app.cell
def _(AnalysisDataDirectory, Pd, StationsGdf, AttachStationDistances, Rebuild):
    StationsWithDistances = None
    if Rebuild:
        StationsDf = Pd.read_csv(AnalysisDataDirectory / "stations_data.csv")
        StationsWithDistances = AttachStationDistances(StationsGdf, StationsDf)
    return (StationsWithDistances,)


@app.cell
def _(RawDataDirectory, ExtractEra5AtStations, LoadEra5Data, StationsWithDistances, Rebuild):
    Era5Ds, Era5AllStations = None, None
    if Rebuild:
        Era5Ds = LoadEra5Data(RawDataDirectory / "derived-era5-land-daily-statistics")
        Era5AllStations = ExtractEra5AtStations(Era5Ds, StationsWithDistances)
    return Era5AllStations, Era5Ds


@app.cell
def _(
    RawDataDirectory,
    AnalysisDataDirectory,
    AddCountryCode,
    AddNdvi,
    ComputeResiduals,
    Era5AllStations,
    Era5Ds,
    StationsWithDistances,
    Rebuild,
    LoadResiduals,
    Mo,
):
    if Rebuild:
        ResidualsDf = ComputeResiduals(
            StationsWithDistances, Era5AllStations, Era5Ds, RawDataDirectory / "ECA_blend_tx"
        )
        ResidualsDf = ResidualsDf.merge(
            StationsWithDistances[["STAID", "dist_to_sea_km", "degurba", "degurba_label"]],
            on="STAID",
            how="left",
            validate="many_to_one",
        )
        ResidualsDf = AddNdvi(
            ResidualsDf, StationsWithDistances, RawDataDirectory / "sentinel2_ndvi"
        )
        ResidualsDf = AddCountryCode(ResidualsDf)
        ResidualsDf.to_parquet(AnalysisDataDirectory / "residuals_rebuilt.parquet", index=False)
        print(f"Saved {len(ResidualsDf):,} rebuilt rows; original parquet preserved.")
    else:
        ResidualsDf = LoadResiduals()
        print(
            f"{len(ResidualsDf):,} conservatively screened rows, {ResidualsDf['STAID'].n_unique():,} stations"
        )
        print(ResidualsDf.null_count())
        print(f"Extrapolated NDVI values: {ResidualsDf['ndvi_is_extrapolated'].sum():,}")
    Mo.md("""## Data preparation

    This export reads `data2/clean/analysis.parquet`. Original observations remain in `data2/residuals.parquet`.
    Use the notebook's `rebuild` CLI flag to explicitly rebuild the raw inputs into
    `data2/residuals_rebuilt.parquet`. The rebuild uses geodesic nearest-land matching;
    the conservative analysis table excludes nearest-land substitutions.

    The clean build validates all saved station-day values, screens station series,
    traces source observations, and recalculates covariates. NDVI carries the latest
    matching season forward when unavailable, with explicit provenance and diagnostics.
    Observation windows remain labelled; a UTC-day subset is saved separately.
    See the clean dataset methods for the screening policy and remaining limitations.
    """)
    return


if __name__ == "__main__":
    app.run()
