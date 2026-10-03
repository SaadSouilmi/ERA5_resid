import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import altair as Alt
    import geopandas as Gpd
    import marimo as Mo
    import numpy as Np
    import pandas as Pd
    import plotly.graph_objects as Go
    import pycountry as Pycountry
    import rasterio as Rasterio
    import reverse_geocoder as Rg
    from plotly.subplots import make_subplots as MakeSubplots
    from rasterio.warp import transform as Transform

    from py.publication import ExportNotebookFigure

    _ = Alt.data_transformers.disable_max_rows()

    return (
        ExportNotebookFigure,
        Path,
        Alt,
        Go,
        Gpd,
        MakeSubplots,
        Mo,
        Np,
        Pd,
        Pycountry,
        Rasterio,
        Rg,
        Transform,
    )


@app.cell
def _(Path):
    from py.paths import AnalysisDataDirectory, RawDataDirectory

    DegurbaPath = (
        AnalysisDataDirectory
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0/GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    return RawDataDirectory, AnalysisDataDirectory, DegurbaPath


@app.cell
def _(Path, DegurbaPath, Gpd, Np, Pd, Pycountry, Rasterio, Rg, Transform):
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
        Coastline = EuropeGdf.dissolve().to_crs("EPSG:3035").boundary.iloc[0].simplify(1000)
        Stations3035 = StationsGdf.to_crs("EPSG:3035")
        StationsGdf["dist_to_sea_km"] = Stations3035.geometry.distance(Coastline) / 1000
        return StationsGdf

    return LoadDegurbaData, LoadStationData


@app.cell
def _(RawDataDirectory, AnalysisDataDirectory, DegurbaPath, Gpd, LoadDegurbaData, LoadStationData):
    StationsGdf = LoadStationData(AnalysisDataDirectory / "ECA_homblend_tx")
    StationsGdf = LoadDegurbaData(StationsGdf, DegurbaPath)
    # stations_gdf = compute_distance_to_sea_km(stations_gdf, europe_gdf)

    StationsGdfOld = LoadStationData(RawDataDirectory / "ECA_blend_tx")
    StationsGdfOld = LoadDegurbaData(StationsGdfOld, DegurbaPath)
    # stations_gdf_old = compute_distance_to_sea_km(stations_gdf_old, europe_gdf)
    return StationsGdf, StationsGdfOld


@app.cell
def _(Go, MakeSubplots, Mo, StationsGdf, StationsGdfOld):
    Fig = MakeSubplots(
        rows=1,
        cols=2,
        specs=[[{"type": "map"}, {"type": "map"}]],
        subplot_titles=["New stations (data2)", "Old stations (data/main)"],
    )

    for _Gdf, _Col in [(StationsGdf, 1), (StationsGdfOld, 2)]:
        Fig.add_trace(
            Go.Scattermap(
                lat=_Gdf.geometry.y,
                lon=_Gdf.geometry.x,
                mode="markers",
                marker=dict(size=4),
                text=_Gdf["STAID"].astype(str),
            ),
            row=1,
            col=_Col,
        )

    Fig.update_layout(
        height=500,
        map=dict(zoom=2, center={"lat": 50, "lon": 10}),
        map2=dict(zoom=2, center={"lat": 50, "lon": 10}),
        showlegend=False,
    )

    Mo.vstack(
        [
            Mo.md(
                "## Station coverage\nGeographic distribution of ECA&D weather stations for the new (`data2`) and old (`data/main`) datasets. Each point is one station."
            ),
            Fig,
        ]
    )
    return


@app.cell
def _(Go, Mo, StationsGdf, StationsGdfOld):
    NewIds = set(StationsGdf["STAID"])
    OldIds = set(StationsGdfOld["STAID"])
    OnlyNew = NewIds - OldIds
    OnlyOld = OldIds - NewIds
    Shared = NewIds & OldIds

    GdfOnlyNew = StationsGdf[StationsGdf["STAID"].isin(OnlyNew)]
    GdfOnlyOld = StationsGdfOld[StationsGdfOld["STAID"].isin(OnlyOld)]
    GdfShared = StationsGdf[StationsGdf["STAID"].isin(Shared)]

    FigOverlap = Go.Figure()
    for _Gdf, _Name, _Color in [
        (GdfShared, "Shared", "steelblue"),
        (GdfOnlyNew, "Only in new", "green"),
        (GdfOnlyOld, "Only in old", "red"),
    ]:
        FigOverlap.add_trace(
            Go.Scattermap(
                lat=_Gdf.geometry.y,
                lon=_Gdf.geometry.x,
                mode="markers",
                marker=dict(size=5, color=_Color),
                name=_Name,
                text=_Gdf["STAID"].astype(str),
            )
        )

    FigOverlap.update_layout(
        height=550,
        map=dict(zoom=2, center={"lat": 50, "lon": 10}),
        title="Station overlap: new vs old dataset",
        legend=dict(orientation="h"),
    )

    Mo.vstack(
        [
            Mo.md(
                f"## Dataset overlap\nComparing station IDs across datasets: **{len(Shared):,} shared**, **{len(OnlyNew):,} only in new** (green), **{len(OnlyOld):,} only in old** (red). New dataset has same coverage plus some new stations. New stations in Ireland are not covered by ERA5 so not much use."
            ),
            FigOverlap,
        ]
    )
    return


@app.cell
def _(Alt, Mo, Np, Pd, StationsGdf, StationsGdfOld, ExportNotebookFigure):
    from sklearn.neighbors import BallTree

    def NndKm(Gdf):
        Coords = Np.radians(Np.column_stack([Gdf.geometry.y.values, Gdf.geometry.x.values]))
        Tree = BallTree(Coords, metric="haversine")
        Dists, _ = Tree.query(Coords, k=2)
        return Dists[:, 1] * 6371

    NndNew = NndKm(StationsGdf)
    NndOld = NndKm(StationsGdfOld)

    NndDf = Pd.concat(
        [
            Pd.DataFrame(
                {
                    "log_nnd_km": Np.log10(
                        NndNew, where=NndNew > 0, out=Np.full_like(NndNew, Np.nan)
                    ),
                    "dataset": f"New (mean={NndNew.mean():.1f}km, std={NndNew.std():.1f}km)",
                }
            ),
            Pd.DataFrame(
                {
                    "log_nnd_km": Np.log10(
                        NndOld, where=NndOld > 0, out=Np.full_like(NndOld, Np.nan)
                    ),
                    "dataset": f"Old (mean={NndOld.mean():.1f}km, std={NndOld.std():.1f}km)",
                }
            ),
        ]
    )
    NndDf["weight"] = NndDf.groupby("dataset")["log_nnd_km"].transform(lambda X: 1 / len(X))
    print(
        f"Co-located stations omitted from logarithmic axis: {(NndNew == 0).sum()} new, {(NndOld == 0).sum()} old"
    )

    NndChart = ExportNotebookFigure(
        Alt.Chart(NndDf)
        .mark_bar(opacity=0.6)
        .encode(
            Alt.X(
                "log_nnd_km:Q",
                bin=Alt.Bin(maxbins=80),
                title="log₁₀ Distance to nearest station (km)",
            ),
            Alt.Y("sum(weight):Q", stack=None, title="Proportion"),
            Alt.Color("dataset:N"),
        )
        .properties(width=600, height=300),
        Notebook="data_comparison",
        Name="nearest_station_distance",
    )

    Mo.vstack(
        [
            Mo.md("""## Spatial uniformity

        For each station, we compute the distance to its closest neighbor. A more uniform dataset has a tighter, higher-mean distribution. Both datasets have seemingly the same distribution."""),
            Mo.ui.altair_chart(NndChart),
        ]
    )
    return


@app.cell
def _(
    Alt,
    DegurbaPath,
    Mo,
    Pd,
    Rasterio,
    StationsGdf,
    StationsGdfOld,
    Transform,
    ExportNotebookFigure,
):
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

    EuropeLons = [-25, 45, 45, -25]
    EuropeLats = [35, 35, 72, 72]
    with Rasterio.open(DegurbaPath) as Src:
        Xs, Ys = Transform("EPSG:4326", Src.crs, EuropeLons, EuropeLats)
        Rows, Cols = zip(*[Src.index(X, Y) for X, Y in zip(Xs, Ys)])
        Window = Rasterio.windows.Window(
            max(0, min(Cols)),
            max(0, min(Rows)),
            min(Src.width, max(Cols)) - max(0, min(Cols)),
            min(Src.height, max(Rows)) - max(0, min(Rows)),
        )
        Data = Src.read(1, window=Window)
        Nodata = Src.nodata
        Data = Data[(Data != Nodata) & (Data > 0)]

    EuropeDist = {Label: int((Data == Code).sum()) for Code, Label in DegurbaLabels.items()}

    def DegurbaDist(Df):
        Counts = Df["degurba_label"].value_counts()
        return dict(zip(Counts.index, Counts.values))

    AllLabels = list(DegurbaLabels.values())
    NonWaterLabels = [Label for Label in AllLabels if Label != "Water"]

    def Normalize(D, Lbls):
        Total = sum(D.get(Label, 0) for Label in Lbls)
        return [D.get(Label, 0) / Total * 100 for Label in Lbls]

    RowsList = (
        [
            {"label": Label, "pct": P, "dataset": "New"}
            for Label, P in zip(AllLabels, Normalize(DegurbaDist(StationsGdf), AllLabels))
        ]
        + [
            {"label": Label, "pct": P, "dataset": "Old"}
            for Label, P in zip(AllLabels, Normalize(DegurbaDist(StationsGdfOld), AllLabels))
        ]
        + [
            {"label": Label, "pct": P, "dataset": "Europe"}
            for Label, P in zip(NonWaterLabels, Normalize(EuropeDist, NonWaterLabels))
        ]
    )
    DegurbaDf = Pd.DataFrame(RowsList)

    DegurbaChart = ExportNotebookFigure(
        Alt.Chart(DegurbaDf)
        .mark_bar()
        .encode(
            Alt.X("label:N", title=None, axis=Alt.Axis(labelAngle=-30, labelAlign="right")),
            Alt.Y("pct:Q", title="% of total"),
            Alt.Color("dataset:N"),
            Alt.XOffset("dataset:N"),
        )
        .properties(width=500, height=300),
        Notebook="data_comparison",
        Name="degurba_distribution",
    )

    Mo.vstack(
        [
            Mo.md("""## DEGURBA distribution

        We removed Water from Europe's distribution, otherwise it dominates without giving much insight."""),
            Mo.ui.altair_chart(DegurbaChart),
        ]
    )
    return


@app.function
def DmsToDecimal(DmsStr):
    """Convert DMS string (+DD:MM:SS) to decimal degrees."""
    DmsStr = DmsStr.strip()
    Sign = 1 if DmsStr[0] == "+" else -1
    DmsStr = DmsStr[1:]
    Parts = DmsStr.split(":")
    return Sign * (float(Parts[0]) + float(Parts[1]) / 60 + float(Parts[2]) / 3600)


if __name__ == "__main__":
    app.run()
