"""Altair figures built from saved publication tables."""

import json
from pathlib import Path

import altair as alt
import polars as pl

from py.publication import BLUE

FEATURES = {
    "station_celsius": "Station temperature (°C)",
    "tp": "Precipitation (m; log₁₀)",
    "wind": "Wind speed (m s⁻¹)",
    "ndvi": "NDVI",
    "dist_to_sea_km": "Distance to sea (km)",
    "elevation": "Elevation (m)",
}
DEGURBA = [
    "Very low density rural",
    "Low density rural",
    "Rural cluster",
    "Suburban",
    "Semi-dense urban cluster",
    "Dense urban cluster",
    "Urban centre",
]
PAIRS = [("station_celsius", "wind"), ("elevation", "dist_to_sea_km")]
MAP_EXTENT = (-25, 45, 34, 72)


def data(frame):
    return alt.Data(values=frame.to_dicts())


def zero_rule(vertical=False, title=None):
    rule = alt.Chart(alt.Data(values=[{"zero": 0}])).mark_rule(
        color="#888888",
        strokeDash=[4, 4],
        strokeWidth=0.7,
    )
    return (
        rule.encode(x=alt.X("zero:Q", title=title))
        if vertical
        else rule.encode(y=alt.Y("zero:Q", title=title))
    )


def covariates(tables):
    summaries = [pl.read_csv(tables / f"covariate_{f}.csv") for f in FEATURES]
    low = min(0, min(frame["ci_low"].min() for frame in summaries))
    high = max(0, max(frame["ci_high"].max() for frame in summaries))
    pad = max((high - low) * 0.06, 0.1)
    scale = alt.Scale(domain=[low - pad, high + pad], nice=False)
    panels = []
    for i, ((feature, label), frame) in enumerate(zip(FEATURES.items(), summaries)):
        base = alt.Chart(data(frame)).encode(
            x=alt.X(
                "x:Q",
                title=label,
                scale=alt.Scale(zero=False),
                axis=alt.Axis(grid=False, tickCount=4),
            ),
        )
        ylabel = "Mean residual (°C)" if i % 3 == 0 else None
        yaxis = alt.Axis(tickCount=5, labels=i % 3 == 0, ticks=i % 3 == 0, domain=i % 3 == 0)
        y = alt.Y("mean:Q", title=ylabel, scale=scale, axis=yaxis)
        band = base.mark_area(color=BLUE, opacity=0.18).encode(
            y=alt.Y("ci_low:Q", title=ylabel, scale=scale, axis=yaxis),
            y2="ci_high:Q",
        )
        line = base.mark_line(color=BLUE, strokeWidth=1.5).encode(y=y)
        points = base.mark_point(color=BLUE, filled=True, size=25).encode(
            y=y,
            tooltip=["x:Q", "mean:Q", "ci_low:Q", "ci_high:Q", "n_stations:Q"],
        )
        panels.append(
            (zero_rule(title=ylabel) + band + line + points).properties(
                width=155,
                height=150,
                title=f"({chr(97 + i)})",
            )
        )
    return alt.vconcat(
        alt.hconcat(*panels[:3], spacing=16),
        alt.hconcat(*panels[3:], spacing=16),
        spacing=26,
    )


def urbanization(tables):
    frame = pl.read_csv(tables / "urbanization.csv")
    y = alt.Y(
        "bin:N", sort=DEGURBA, title=None, axis=alt.Axis(labelLimit=220, ticks=False, domain=False)
    )
    base = alt.Chart(data(frame)).encode(y=y)
    xscale = alt.Scale(domain=[min(0, frame["ci_low"].min()) - 0.1, frame["ci_high"].max() + 0.1])
    intervals = base.mark_rule(color=BLUE, strokeWidth=1.6).encode(
        x=alt.X("ci_low:Q", title="Mean residual (°C)", scale=xscale),
        x2="ci_high:Q",
    )
    points = base.mark_point(color=BLUE, filled=True, size=40).encode(
        x=alt.X("mean:Q", title="Mean residual (°C)", scale=xscale),
        tooltip=["bin:N", "mean:Q", "ci_low:Q", "ci_high:Q", "n_stations:Q"],
    )
    plot = (zero_rule(True, "Mean residual (°C)") + intervals + points).properties(
        width=310, height=230
    )
    counts = (
        base.mark_text(align="right", fontSize=10)
        .encode(
            y=alt.Y("bin:N", sort=DEGURBA, axis=None),
            x=alt.value(55),
            text=alt.Text("n_stations:Q", format=","),
        )
        .properties(
            width=55,
            height=230,
            title=alt.Title("Stations", fontSize=10, fontWeight="normal", anchor="end"),
        )
    )
    return alt.hconcat(plot, counts, spacing=12).resolve_scale(y="shared")


def interactions(tables, min_stations=10):
    frames = [pl.read_csv(tables / f"{x}_by_{y}.csv") for x, y in PAIRS]
    vmax = max(
        [0.01]
        + [
            f.filter(pl.col("n_stations") >= min_stations)["residual"].abs().max() or 0
            for f in frames
        ]
    )
    panels = []
    for i, ((fx, fy), frame) in enumerate(zip(PAIRS, frames)):
        # Complete the grid so absent cells have the same grey as sparse cells.
        xs = frame.select("bin_x", "x_lo", "x_hi").unique()
        ys = frame.select("bin_y", "y_lo", "y_hi").unique()
        frame = (
            xs.join(ys, how="cross")
            .join(frame, on=xs.columns + ys.columns, how="left")
            .sort("y_lo", "x_lo")
        )
        chart = (
            alt.Chart(data(frame))
            .mark_rect()
            .encode(
                x=alt.X(
                    "x_lo:Q",
                    title=FEATURES[fx],
                    scale=alt.Scale(zero=False, nice=False),
                    axis=alt.Axis(grid=False, tickCount=4),
                ),
                x2="x_hi:Q",
                y=alt.Y(
                    "y_lo:Q",
                    title=FEATURES[fy],
                    scale=alt.Scale(zero=False, nice=False),
                    axis=alt.Axis(grid=False, tickCount=4),
                ),
                y2="y_hi:Q",
                color=alt.condition(
                    f"isValid(datum.residual) && datum.n_stations >= {min_stations}",
                    alt.Color(
                        "residual:Q",
                        title="Mean residual (°C)",
                        scale=alt.Scale(scheme="redblue", reverse=True, domain=[-vmax, vmax]),
                        legend=alt.Legend(
                            orient="bottom",
                            gradientLength=220,
                            direction="horizontal",
                            titleOrient="bottom",
                        ),
                    ),
                    alt.value("#ebebeb"),
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
            .properties(width=225, height=190, title=f"({chr(97 + i)})")
        )
        panels.append(chart)
    return alt.hconcat(*panels, spacing=30).resolve_scale(color="shared")


def map_geometry(tables, cache):
    """Cache clipped Natural Earth geometry alongside the figure data."""
    import cartopy
    import geopandas as gpd
    from cartopy.io import shapereader
    from shapely.geometry import box

    cartopy.config["data_dir"] = Path(cache)
    extent = box(MAP_EXTENT[0], MAP_EXTENT[2], MAP_EXTENT[1], MAP_EXTENT[3])
    for name, category in [
        ("land", "physical"),
        ("coastline", "physical"),
        ("admin_0_boundary_lines_land", "cultural"),
    ]:
        output = tables / f"map_{name}.geojson"
        if not output.exists():
            source = shapereader.natural_earth("50m", category, name)
            frame = gpd.read_file(source, bbox=extent.bounds)[["geometry"]]
            frame = frame.clip(extent)
            output.write_text(frame.to_json(drop_id=True))


def station_map(tables):
    frame = pl.read_csv(tables / "station_means.csv").filter(
        pl.col("lon").is_between(*MAP_EXTENT[:2]) & pl.col("lat").is_between(*MAP_EXTENT[2:])
    )
    layers = []
    for name, fill, stroke, width in [
        ("land", "#f5f4ef", None, 0),
        ("coastline", None, "#777777", 0.4),
        ("admin_0_boundary_lines_land", None, "#aaaaaa", 0.3),
    ]:
        features = json.loads((tables / f"map_{name}.geojson").read_text())["features"]
        layers.append(
            alt.Chart(alt.Data(values=features)).mark_geoshape(
                fill=fill,
                stroke=stroke,
                strokeWidth=width,
                clip=True,
            )
        )
    layers.append(
        alt.Chart(alt.graticule(step=[10, 10])).mark_geoshape(
            stroke="#cccccc",
            strokeWidth=0.3,
            strokeDash=[2, 2],
            clip=True,
        )
    )
    layers.append(
        alt.Chart(data(frame))
        .mark_circle(size=8, opacity=1, clip=True)
        .encode(
            longitude="lon:Q",
            latitude="lat:Q",
            color=alt.Color(
                "residual:Q",
                title="Mean residual (°C)",
                scale=alt.Scale(scheme="redblue", reverse=True, domain=[-3, 3], clamp=True),
                legend=alt.Legend(
                    gradientLength=220,
                    values=[-3, -2, -1, 0, 1, 2, 3],
                    labelExpr="datum.value == -3 ? '≤ −3' : datum.value == 3 ? '≥ 3' : datum.label",
                ),
            ),
            tooltip=["STAID:Q", "residual:Q", "n_observations:Q"],
        )
    )
    bounds = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "MultiPoint",
            "coordinates": [[lon, lat] for lon in range(-25, 46, 5) for lat in (34, 72)],
        },
    }
    return (
        alt.layer(*layers)
        .project(
            type="conicConformal",
            parallels=[33, 45],
            rotate=[-12, 0, 0],
            center=[0, 53],
            fit=bounds,
        )
        .properties(width=470, height=360, view=alt.ViewConfig(fill="#f2f6f8", stroke=None))
    )
