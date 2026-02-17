"""Dash dashboard for weather-station vs ERA5 temperature residuals."""

import argparse
from pathlib import Path

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import Dash, Input, Output, State, callback, dcc, html

# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _dms_to_decimal(dms_str: str) -> float:
    dms_str = dms_str.strip()
    sign = 1 if dms_str[0] == "+" else -1
    dms_str = dms_str[1:]
    parts = dms_str.split(":")
    return sign * (float(parts[0]) + float(parts[1]) / 60 + float(parts[2]) / 3600)


def _load_data(data_dir: str) -> tuple[pd.DataFrame, list[str]]:
    """Return (merged DataFrame with lat/lon, sorted date strings)."""
    data_dir = Path(data_dir)

    # Residuals
    residuals = pd.read_parquet(data_dir / "residuals.parquet")

    # Station locations
    stations_path = Path("data/main/ECA_blend_tx/stations.txt")
    stations = pd.read_csv(stations_path, skiprows=17, skipinitialspace=True)
    stations["lat"] = stations["LAT"].apply(_dms_to_decimal)
    stations["lon"] = stations["LON"].apply(_dms_to_decimal)
    stations = stations[["STAID", "lat", "lon"]]

    # Merge
    merged = residuals.merge(stations, on="STAID")
    merged["date"] = pd.to_datetime(merged["date"])

    # Sorted unique dates as strings
    dates = sorted(merged["date"].dt.strftime("%Y-%m-%d").unique())

    return merged, dates


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _build_figure(day_df: pd.DataFrame):
    fig = px.scatter_mapbox(
        day_df,
        lat="lat",
        lon="lon",
        color="residual",
        color_continuous_scale="RdBu_r",
        range_color=[-5, 5],
        zoom=3,
        center={"lat": 50, "lon": 10},
        mapbox_style="open-street-map",
        hover_data={"STAID": True, "lat": ":.1f", "lon": ":.1f",
                     "station_celsius": ":.1f", "era5_celsius": ":.1f",
                     "residual": ":.1f"},
    )
    fig.update_traces(
        marker={"size": 8},
        hovertemplate=(
            "<b>Station %{customdata[0]}</b><br>"
            "Lat: %{lat:.1f}\u00b0  Lon: %{lon:.1f}\u00b0<br>"
            "Observed: %{customdata[3]:.1f} \u00b0C<br>"
            "ERA5: %{customdata[4]:.1f} \u00b0C<br>"
            "Residual: %{customdata[5]:.1f} \u00b0C"
            "<extra></extra>"
        ),
    )
    fig.update_layout(
        height=700,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        coloraxis_colorbar_title="WS_TX \u2212 ERA5 (\u00b0C)",
    )
    return fig


def _summary_stats(day_df: pd.DataFrame) -> dict:
    residuals = day_df["residual"].dropna()
    return {
        "stations": len(residuals),
        "mean": residuals.mean() if len(residuals) else 0.0,
        "std": residuals.std() if len(residuals) > 1 else 0.0,
    }


def create_app(data_dir: str = "data2") -> Dash:
    df, dates = _load_data(data_dir)

    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

    # --- Slider marks: ~10 evenly spaced labels ---
    step = max(1, len(dates) // 10)
    slider_marks = {i: dates[i] for i in range(0, len(dates), step)}

    # --- Initial state ---
    init_day = df[df["date"] == dates[0]].dropna(subset=["residual"])
    init_stats = _summary_stats(init_day)

    # --- Layout ---
    app.layout = dbc.Container(
        fluid=True,
        className="py-3",
        children=[
            # Header
            dbc.Row(
                dbc.Col(
                    [
                        html.H2("Weather Station vs ERA5 Temperature Residuals",
                                className="mb-0"),
                        html.P("Daily observed minus reanalysis TX across Europe",
                               className="text-muted mb-0"),
                    ],
                    width=12,
                ),
                className="mb-3",
            ),

            # Controls
            dbc.Card(
                dbc.CardBody(
                    dbc.Row(
                        [
                            # Play / Pause
                            dbc.Col(
                                dbc.Button(
                                    "Play", id="play-btn", n_clicks=0,
                                    outline=True, color="primary", size="sm",
                                ),
                                width="auto",
                                className="d-flex align-items-center",
                            ),
                            # Speed dropdown
                            dbc.Col(
                                dbc.Select(
                                    id="speed-select",
                                    options=[
                                        {"label": "Fast (200 ms)", "value": "200"},
                                        {"label": "Medium (500 ms)", "value": "500"},
                                        {"label": "Slow (1 s)", "value": "1000"},
                                    ],
                                    value="200",
                                    size="sm",
                                ),
                                width=2,
                                className="d-flex align-items-center",
                            ),
                            # Current date badge
                            dbc.Col(
                                dbc.Badge(
                                    dates[0], id="date-badge",
                                    color="info", className="fs-6",
                                ),
                                width="auto",
                                className="d-flex align-items-center",
                            ),
                            # Slider
                            dbc.Col(
                                dcc.Slider(
                                    id="date-slider",
                                    min=0,
                                    max=len(dates) - 1,
                                    value=0,
                                    marks=slider_marks,
                                    step=1,
                                    tooltip={"placement": "bottom", "always_visible": False},
                                ),
                                className="d-flex align-items-center",
                            ),
                        ],
                        align="center",
                        className="g-3",
                    )
                ),
                className="mb-3",
            ),

            # Interval (hidden)
            dcc.Interval(id="interval", interval=200, disabled=True),

            # Summary stats row
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Small("Stations", className="text-muted"),
                                    html.H5(str(init_stats["stations"]), id="stat-stations",
                                            className="mb-0"),
                                ]
                            ),
                        ),
                        md=2,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Small("Mean residual", className="text-muted"),
                                    html.H5(f"{init_stats['mean']:.2f} \u00b0C",
                                            id="stat-mean", className="mb-0"),
                                ]
                            ),
                        ),
                        md=2,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Small("Std dev", className="text-muted"),
                                    html.H5(f"{init_stats['std']:.2f} \u00b0C",
                                            id="stat-std", className="mb-0"),
                                ]
                            ),
                        ),
                        md=2,
                    ),
                    dbc.Col(
                        dbc.Card(
                            dbc.CardBody(
                                [
                                    html.Small("Date range", className="text-muted"),
                                    html.H5(f"{dates[0]}  \u2192  {dates[-1]}",
                                            id="stat-range", className="mb-0"),
                                ]
                            ),
                        ),
                        md=6,
                    ),
                ],
                className="mb-3 g-3",
            ),

            # Map card
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(id="map", figure=_build_figure(init_day)),
                ),
            ),
        ],
    )

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------

    @app.callback(
        Output("map", "figure"),
        Output("date-badge", "children"),
        Output("stat-stations", "children"),
        Output("stat-mean", "children"),
        Output("stat-std", "children"),
        Input("date-slider", "value"),
    )
    def update_map(slider_idx):
        date_str = dates[slider_idx]
        day_df = df[df["date"] == date_str].dropna(subset=["residual"])
        stats = _summary_stats(day_df)
        return (
            _build_figure(day_df),
            date_str,
            str(stats["stations"]),
            f"{stats['mean']:.2f} \u00b0C",
            f"{stats['std']:.2f} \u00b0C",
        )

    @app.callback(
        Output("interval", "disabled"),
        Output("play-btn", "children"),
        Input("play-btn", "n_clicks"),
        State("interval", "disabled"),
    )
    def toggle_play(n_clicks, currently_disabled):
        if n_clicks == 0:
            return True, "Play"
        if currently_disabled:
            return False, "Pause"
        return True, "Play"

    @app.callback(
        Output("interval", "interval"),
        Input("speed-select", "value"),
    )
    def update_speed(value):
        return int(value)

    @app.callback(
        Output("date-slider", "value"),
        Input("interval", "n_intervals"),
        State("date-slider", "value"),
    )
    def advance_slider(n_intervals, current_value):
        if current_value is None:
            return 0
        return (current_value + 1) % len(dates)

    return app


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Launch residuals dashboard")
    parser.add_argument("--port", type=int, default=8050, help="Port to serve on")
    parser.add_argument("--data-dir", default="data2", help="Directory containing residuals.parquet")
    args = parser.parse_args()

    app = create_app(data_dir=args.data_dir)
    app.run(debug=False, port=args.port)


if __name__ == "__main__":
    main()
