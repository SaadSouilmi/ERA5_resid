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

    return (
        Path,
        alt,
        go,
        gpd,
        make_subplots,
        mo,
        np,
        pd,
        pycountry,
        rasterio,
        rg,
        transform,
    )


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
        coastline = europe_gdf.dissolve().to_crs("EPSG:3035").boundary.iloc[0].simplify(1000)
        stations_3035 = stations_gdf.to_crs("EPSG:3035")
        stations_gdf["dist_to_sea_km"] = stations_3035.geometry.distance(coastline) / 1000
        return stations_gdf


    return load_degurba_data, load_station_data


@app.cell
def _(DATA, DATA2, degurba_path, gpd, load_degurba_data, load_station_data):
    europe_gdf = gpd.read_file(DATA / "gadm_410_europe.gpkg")

    stations_gdf = load_station_data(DATA2 / "ECA_homblend_tx")
    stations_gdf = load_degurba_data(stations_gdf, degurba_path)
    # stations_gdf = compute_distance_to_sea_km(stations_gdf, europe_gdf)

    stations_gdf_old = load_station_data(DATA / "ECA_blend_tx")
    stations_gdf_old = load_degurba_data(stations_gdf_old, degurba_path)
    # stations_gdf_old = compute_distance_to_sea_km(stations_gdf_old, europe_gdf)
    return stations_gdf, stations_gdf_old


@app.cell
def _(go, make_subplots, mo, stations_gdf, stations_gdf_old):
    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "map"}, {"type": "map"}]],
        subplot_titles=["New stations (data2)", "Old stations (data/main)"],
    )

    for _gdf, _col in [(stations_gdf, 1), (stations_gdf_old, 2)]:
        fig.add_trace(
            go.Scattermap(
                lat=_gdf.geometry.y,
                lon=_gdf.geometry.x,
                mode="markers",
                marker=dict(size=4),
                text=_gdf["STAID"].astype(str),
            ),
            row=1,
            col=_col,
        )

    fig.update_layout(
        height=500,
        map=dict(zoom=2, center={"lat": 50, "lon": 10}),
        map2=dict(zoom=2, center={"lat": 50, "lon": 10}),
        showlegend=False,
    )

    mo.vstack([
        mo.md("## Station coverage\nGeographic distribution of ECA&D weather stations for the new (`data2`) and old (`data/main`) datasets. Each point is one station."),
        fig,
    ])
    return


@app.cell
def _(go, mo, stations_gdf, stations_gdf_old):
    new_ids = set(stations_gdf["STAID"])
    old_ids = set(stations_gdf_old["STAID"])
    only_new = new_ids - old_ids
    only_old = old_ids - new_ids
    shared = new_ids & old_ids

    gdf_only_new = stations_gdf[stations_gdf["STAID"].isin(only_new)]
    gdf_only_old = stations_gdf_old[stations_gdf_old["STAID"].isin(only_old)]
    gdf_shared = stations_gdf[stations_gdf["STAID"].isin(shared)]

    fig_overlap = go.Figure()
    for _gdf, _name, _color in [
        (gdf_shared, "Shared", "steelblue"),
        (gdf_only_new, "Only in new", "green"),
        (gdf_only_old, "Only in old", "red"),
    ]:
        fig_overlap.add_trace(go.Scattermap(
            lat=_gdf.geometry.y,
            lon=_gdf.geometry.x,
            mode="markers",
            marker=dict(size=5, color=_color),
            name=_name,
            text=_gdf["STAID"].astype(str),
        ))

    fig_overlap.update_layout(
        height=550,
        map=dict(zoom=2, center={"lat": 50, "lon": 10}),
        title="Station overlap: new vs old dataset",
        legend=dict(orientation="h"),
    )

    mo.vstack([
        mo.md(f"## Dataset overlap\nComparing station IDs across datasets: **{len(shared):,} shared**, **{len(only_new):,} only in new** (green), **{len(only_old):,} only in old** (red). New dataset has same coverage plus some new stations. New stations in Ireland are not covered by ERA5 so not much use."),
        fig_overlap,
    ])
    return


@app.cell
def _(alt, mo, np, pd, stations_gdf, stations_gdf_old):
    from sklearn.neighbors import BallTree

    def nnd_km(gdf):
        coords = np.radians(np.column_stack([gdf.geometry.y.values, gdf.geometry.x.values]))
        tree = BallTree(coords, metric="haversine")
        dists, _ = tree.query(coords, k=2)
        return dists[:, 1] * 6371

    nnd_new = nnd_km(stations_gdf)
    nnd_old = nnd_km(stations_gdf_old)

    nnd_df = pd.concat([
        pd.DataFrame({"log_nnd_km": np.log10(nnd_new), "dataset": f"New (mean={nnd_new.mean():.1f}km, std={nnd_new.std():.1f}km)"}),
        pd.DataFrame({"log_nnd_km": np.log10(nnd_old), "dataset": f"Old (mean={nnd_old.mean():.1f}km, std={nnd_old.std():.1f}km)"}),
    ])
    nnd_df["weight"] = nnd_df.groupby("dataset")["log_nnd_km"].transform(lambda x: 1 / len(x))

    nnd_chart = alt.Chart(nnd_df).mark_bar(opacity=0.6).encode(
        alt.X("log_nnd_km:Q", bin=alt.Bin(maxbins=80), title="log₁₀ Distance to nearest station (km)"),
        alt.Y("sum(weight):Q", stack=None, title="Proportion"),
        alt.Color("dataset:N"),
    ).properties(width=600, height=300)

    mo.vstack([
        mo.md("""## Spatial uniformity

        For each station, we compute the distance to its closest neighbor. A more uniform dataset has a tighter, higher-mean distribution. Both datasets have seemingly the same distribution."""),
        mo.ui.altair_chart(nnd_chart),
    ])
    return


@app.cell
def _(
    alt,
    degurba_path,
    mo,
    pd,
    rasterio,
    stations_gdf,
    stations_gdf_old,
    transform,
):
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

    europe_lons = [-25, 45, 45, -25]
    europe_lats = [35, 35, 72, 72]
    with rasterio.open(degurba_path) as src:
        xs, ys = transform("EPSG:4326", src.crs, europe_lons, europe_lats)
        rows, cols = zip(*[src.index(x, y) for x, y in zip(xs, ys)])
        window = rasterio.windows.Window(
            max(0, min(cols)), max(0, min(rows)),
            min(src.width, max(cols)) - max(0, min(cols)),
            min(src.height, max(rows)) - max(0, min(rows)),
        )
        data = src.read(1, window=window)
        nodata = src.nodata
        data = data[(data != nodata) & (data > 0)]

    europe_dist = {label: int((data == code).sum()) for code, label in DEGURBA_LABELS.items()}

    def degurba_dist(df):
        counts = df["degurba_label"].value_counts()
        return dict(zip(counts.index, counts.values))

    all_labels = list(DEGURBA_LABELS.values())
    non_water_labels = [l for l in all_labels if l != "Water"]

    def normalize(d, lbls):
        total = sum(d.get(l, 0) for l in lbls)
        return [d.get(l, 0) / total * 100 for l in lbls]

    rows_list = (
        [{"label": l, "pct": p, "dataset": "New"} for l, p in zip(all_labels, normalize(degurba_dist(stations_gdf), all_labels))]
        + [{"label": l, "pct": p, "dataset": "Old"} for l, p in zip(all_labels, normalize(degurba_dist(stations_gdf_old), all_labels))]
        + [{"label": l, "pct": p, "dataset": "Europe"} for l, p in zip(non_water_labels, normalize(europe_dist, non_water_labels))]
    )
    degurba_df = pd.DataFrame(rows_list)

    degurba_chart = alt.Chart(degurba_df).mark_bar().encode(
        alt.X("label:N", title=None, axis=alt.Axis(labelAngle=-30, labelAlign="right")),
        alt.Y("pct:Q", title="% of total"),
        alt.Color("dataset:N"),
        alt.XOffset("dataset:N"),
    ).properties(width=500, height=300)

    mo.vstack([
        mo.md("""## DEGURBA distribution

        We removed Water from Europe's distribution, otherwise it dominates without giving much insight."""),
        mo.ui.altair_chart(degurba_chart),
    ])
    return


@app.function
def dms_to_decimal(dms_str):
    """Convert DMS string (+DD:MM:SS) to decimal degrees."""
    dms_str = dms_str.strip()
    sign = 1 if dms_str[0] == "+" else -1
    dms_str = dms_str[1:]
    parts = dms_str.split(":")
    return sign * (float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600)


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
