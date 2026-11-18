"""Publication figures and the notebook's Plotly station map."""

import json as Json
from pathlib import Path

import altair as Alt
import polars as Pl

from py.publication import Blue

FeatureLabels = {
    "station_celsius": "Station temperature (°C)",
    "tp": "Precipitation proxy (m; log₁₀)",
    "wind": "Mean wind vector (m s⁻¹)",
    "ndvi": "NDVI (incl. extrapolation)",
    "dist_to_sea_km": "Distance to sea (km)",
    "elevation": "Elevation (m)",
}
DegurbaClasses = [
    "Very low density rural",
    "Low density rural",
    "Rural cluster",
    "Suburban",
    "Semi-dense urban cluster",
    "Dense urban cluster",
    "Urban centre",
]
FeaturePairs = [("station_celsius", "wind"), ("elevation", "dist_to_sea_km")]
MapExtent = (-25, 45, 34, 72)


def Data(Frame):
    return Alt.Data(values=Frame.to_dicts())


def ZeroRule(Vertical=False, Title=None):
    Rule = Alt.Chart(Alt.Data(values=[{"zero": 0}])).mark_rule(
        color="#888888",
        strokeDash=[4, 4],
        strokeWidth=0.7,
    )
    return (
        Rule.encode(x=Alt.X("zero:Q", title=Title))
        if Vertical
        else Rule.encode(y=Alt.Y("zero:Q", title=Title))
    )


def Covariates(Tables):
    Summaries = [Pl.read_csv(Tables / f"covariate_{F}.csv") for F in FeatureLabels]
    Low = min(0, min(Frame["ci_low"].min() for Frame in Summaries))
    High = max(0, max(Frame["ci_high"].max() for Frame in Summaries))
    Pad = max((High - Low) * 0.06, 0.1)
    Scale = Alt.Scale(domain=[Low - Pad, High + Pad], nice=False)
    Panels = []
    for Index, ((Feature, Label), Frame) in enumerate(zip(FeatureLabels.items(), Summaries)):
        Base = Alt.Chart(Data(Frame)).encode(
            x=Alt.X(
                "x:Q",
                title=Label,
                scale=Alt.Scale(zero=False),
                axis=Alt.Axis(grid=False, tickCount=4),
            ),
        )
        Ylabel = "Mean residual (°C)" if Index % 3 == 0 else None
        Yaxis = Alt.Axis(
            tickCount=5, labels=Index % 3 == 0, ticks=Index % 3 == 0, domain=Index % 3 == 0
        )
        Y = Alt.Y("mean:Q", title=Ylabel, scale=Scale, axis=Yaxis)
        Band = Base.mark_area(color=Blue, opacity=0.18).encode(
            y=Alt.Y("ci_low:Q", title=Ylabel, scale=Scale, axis=Yaxis),
            y2="ci_high:Q",
        )
        Line = Base.mark_line(color=Blue, strokeWidth=1.5).encode(y=Y)
        Points = Base.mark_point(color=Blue, filled=True, size=25).encode(
            y=Y,
            tooltip=["x:Q", "mean:Q", "ci_low:Q", "ci_high:Q", "n_stations:Q"],
        )
        Panels.append(
            (ZeroRule(Title=Ylabel) + Band + Line + Points).properties(
                width=155,
                height=150,
                title=f"({chr(97 + Index)})",
            )
        )
    return Alt.vconcat(
        Alt.hconcat(*Panels[:3], spacing=16),
        Alt.hconcat(*Panels[3:], spacing=16),
        spacing=26,
    )


def Urbanization(Tables):
    Frame = Pl.read_csv(Tables / "urbanization.csv")
    Y = Alt.Y(
        "bin:N",
        sort=DegurbaClasses,
        title=None,
        axis=Alt.Axis(labelLimit=220, ticks=False, domain=False),
    )
    Base = Alt.Chart(Data(Frame)).encode(y=Y)
    Xscale = Alt.Scale(domain=[min(0, Frame["ci_low"].min()) - 0.1, Frame["ci_high"].max() + 0.1])
    Intervals = Base.mark_rule(color=Blue, strokeWidth=1.6).encode(
        x=Alt.X("ci_low:Q", title="Mean residual (°C)", scale=Xscale),
        x2="ci_high:Q",
    )
    Points = Base.mark_point(color=Blue, filled=True, size=40).encode(
        x=Alt.X("mean:Q", title="Mean residual (°C)", scale=Xscale),
        tooltip=["bin:N", "mean:Q", "ci_low:Q", "ci_high:Q", "n_stations:Q"],
    )
    Plot = (ZeroRule(True, "Mean residual (°C)") + Intervals + Points).properties(
        width=310, height=230
    )
    Counts = (
        Base.mark_text(align="right", fontSize=10)
        .encode(
            y=Alt.Y("bin:N", sort=DegurbaClasses, axis=None),
            x=Alt.value(55),
            text=Alt.Text("n_stations:Q", format=","),
        )
        .properties(
            width=55,
            height=230,
            title=Alt.Title("Stations", fontSize=10, fontWeight="normal", anchor="end"),
        )
    )
    return Alt.hconcat(Plot, Counts, spacing=12).resolve_scale(y="shared")


def Interactions(Tables, MinStations=10):
    Frames = [Pl.read_csv(Tables / f"{X}_by_{Y}.csv") for X, Y in FeaturePairs]
    Vmax = max(
        [0.01]
        + [
            F.filter(Pl.col("n_stations") >= MinStations)["residual"].abs().max() or 0
            for F in Frames
        ]
    )
    Panels = []
    for Index, ((Fx, Fy), Frame) in enumerate(zip(FeaturePairs, Frames)):
        # Complete the grid so absent cells have the same grey as sparse cells.
        Xs = Frame.select("bin_x", "x_lo", "x_hi").unique()
        Ys = Frame.select("bin_y", "y_lo", "y_hi").unique()
        Frame = (
            Xs.join(Ys, how="cross")
            .join(Frame, on=Xs.columns + Ys.columns, how="left")
            .sort("y_lo", "x_lo")
        )
        Chart = (
            Alt.Chart(Data(Frame))
            .mark_rect()
            .encode(
                x=Alt.X(
                    "x_lo:Q",
                    title=FeatureLabels[Fx],
                    scale=Alt.Scale(zero=False, nice=False),
                    axis=Alt.Axis(grid=False, tickCount=4),
                ),
                x2="x_hi:Q",
                y=Alt.Y(
                    "y_lo:Q",
                    title=FeatureLabels[Fy],
                    scale=Alt.Scale(zero=False, nice=False),
                    axis=Alt.Axis(grid=False, tickCount=4),
                ),
                y2="y_hi:Q",
                color=Alt.condition(
                    f"isValid(datum.residual) && datum.n_stations >= {MinStations}",
                    Alt.Color(
                        "residual:Q",
                        title="Mean residual (°C)",
                        scale=Alt.Scale(scheme="redblue", reverse=True, domain=[-Vmax, Vmax]),
                        legend=Alt.Legend(
                            orient="bottom",
                            gradientLength=220,
                            direction="horizontal",
                            titleOrient="bottom",
                        ),
                    ),
                    Alt.value("#ebebeb"),
                ),
                tooltip=[
                    "x_lo:Q",
                    "x_hi:Q",
                    "y_lo:Q",
                    "y_hi:Q",
                    "residual:Q",
                    "n_observations:Q",
                    "n_stations:Q",
                ],
            )
            .properties(width=225, height=190, title=f"({chr(97 + Index)})")
        )
        Panels.append(Chart)
    return Alt.hconcat(*Panels, spacing=30).resolve_scale(color="shared")


def MapGeometry(Tables, Cache):
    """Cache clipped Natural Earth geometry alongside the figure data."""
    import cartopy as Cartopy
    import geopandas as Gpd
    from cartopy.io import shapereader as Shapereader
    from shapely.geometry import box as Box

    Cartopy.config["data_dir"] = Path(Cache)
    Extent = Box(MapExtent[0], MapExtent[2], MapExtent[1], MapExtent[3])
    for Name, Category in [
        ("land", "physical"),
        ("coastline", "physical"),
        ("admin_0_boundary_lines_land", "cultural"),
    ]:
        Output = Tables / f"map_{Name}.geojson"
        if not Output.exists():
            Source = Shapereader.natural_earth("50m", Category, Name)
            Frame = Gpd.read_file(Source, bbox=Extent.bounds)[["geometry"]]
            Frame = Frame.clip(Extent)
            Output.write_text(Frame.to_json(drop_id=True))


def StationMap(Tables):
    Frame = Pl.read_csv(Tables / "station_means.csv").filter(
        Pl.col("lon").is_between(*MapExtent[:2]) & Pl.col("lat").is_between(*MapExtent[2:])
    )
    Layers = []
    for Name, Fill, Stroke, Width in [
        ("land", "#f5f4ef", None, 0),
        ("coastline", None, "#777777", 0.4),
        ("admin_0_boundary_lines_land", None, "#aaaaaa", 0.3),
    ]:
        Features = Json.loads((Tables / f"map_{Name}.geojson").read_text())["features"]
        Layers.append(
            Alt.Chart(Alt.Data(values=Features)).mark_geoshape(
                fill=Fill,
                stroke=Stroke,
                strokeWidth=Width,
                clip=True,
            )
        )
    Layers.append(
        Alt.Chart(Alt.graticule(step=[10, 10])).mark_geoshape(
            stroke="#cccccc",
            strokeWidth=0.3,
            strokeDash=[2, 2],
            clip=True,
        )
    )
    Layers.append(
        Alt.Chart(Data(Frame))
        .mark_circle(size=8, opacity=1, clip=True)
        .encode(
            longitude="lon:Q",
            latitude="lat:Q",
            color=Alt.Color(
                "residual:Q",
                title="Mean residual (°C)",
                scale=Alt.Scale(scheme="redblue", reverse=True, domain=[-3, 3], clamp=True),
                legend=Alt.Legend(
                    gradientLength=220,
                    values=[-3, -2, -1, 0, 1, 2, 3],
                    labelExpr="datum.value == -3 ? '≤ −3' : datum.value == 3 ? '≥ 3' : datum.label",
                ),
            ),
            tooltip=["STAID:Q", "residual:Q", "n_observations:Q"],
        )
    )
    Bounds = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "MultiPoint",
            "coordinates": [[Lon, Lat] for Lon in range(-25, 46, 5) for Lat in (34, 72)],
        },
    }
    return (
        Alt.layer(*Layers)
        .project(
            type="conicConformal",
            parallels=[33, 45],
            rotate=[-12, 0, 0],
            center=[0, 53],
            fit=Bounds,
        )
        .properties(width=470, height=360, view=Alt.ViewConfig(fill="#f2f6f8", stroke=None))
    )


async def ExportNotebookStationMap(Frame):
    import math as Math

    import plotly.express as Px

    from py.paths import NotebookFiguresDirectory
    from py.publication import ExportNotebookPlotlyFigure, Font

    Directory = NotebookFiguresDirectory / "resid_analysis"
    Tables = Directory / "tables"
    Tables.mkdir(parents=True, exist_ok=True)
    Stations = (
        Frame.group_by("STAID")
        .agg(
            Pl.col("residual").mean(),
            Pl.col("lat").first(),
            Pl.col("lon").first(),
            Pl.col("place").first(),
            Pl.col("country").first(),
            Pl.len().alias("n_observations"),
        )
        .sort("STAID")
    )
    Stations.write_csv(Tables / "station_means.csv")
    West, East = Stations["lon"].min(), Stations["lon"].max()
    South, North = Stations["lat"].min(), Stations["lat"].max()
    SouthY, NorthY = [
        Math.asinh(Math.tan(Math.radians(Latitude))) / (2 * Math.pi) for Latitude in (South, North)
    ]
    MapWidth, Padding = 800, 24
    LongitudeSpan = (East - West) / 360
    Height = MapWidth
    Zoom = Math.log2((MapWidth - 2 * Padding) / (512 * max(LongitudeSpan, NorthY - SouthY)))
    Center = {
        "lat": Math.degrees(Math.atan(Math.sinh(Math.pi * (SouthY + NorthY)))),
        "lon": (West + East) / 2,
    }
    Figure = Px.scatter_map(
        Stations,
        lat="lat",
        lon="lon",
        color="residual",
        color_continuous_scale="RdBu_r",
        range_color=[-3, 3],
        zoom=Zoom,
        center=Center,
        hover_data=["STAID", "place", "country", "residual", "n_observations"],
    )
    Figure.update_traces(
        lat=Stations["lat"].to_list(),
        lon=Stations["lon"].to_list(),
        marker={"size": 6, "color": Stations["residual"].to_list()},
    )
    Figure.update_layout(
        width=MapWidth + 120,
        height=Height,
        margin={"l": 0, "r": 120, "t": 0, "b": 0, "autoexpand": False},
        template="plotly_white",
        font={"family": Font, "size": 19},
        map_style="open-street-map",
        coloraxis_colorbar={
            "title": {"text": "Mean<br>residual<br>(°C)"},
            "thickness": 22,
            "len": 0.85,
            "x": 1.01,
            "xanchor": "left",
            "tickvals": [-3, -2, -1, 0, 1, 2, 3],
            "ticktext": ["≤ −3", "−2", "−1", "0", "1", "2", "≥ 3"],
        },
        meta={"export_width_mm": 180, "map_dpi": 900, "station_padding_px": Padding},
    )
    return await ExportNotebookPlotlyFigure(Figure, "resid_analysis", "station_map", Dpi=900)
