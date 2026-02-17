"""Dash dashboard for weather-station vs ERA5 temperature residuals."""

import argparse
from pathlib import Path

import dash_bootstrap_components as dbc
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.api as sm
from dash import Dash, Input, Output, State, ctx, dcc, html
from plotly.subplots import make_subplots
from sklearn.preprocessing import StandardScaler

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
# Figure builders
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


_NDVI_BINS = [-1, 0, 0.2, 0.5, 0.8, 1.0]
_NDVI_LABELS = [
    "Water/snow\n(-1, 0)",
    "Bare/urban\n(0, 0.2)",
    "Sparse veg\n(0.2, 0.5)",
    "Moderate veg\n(0.5, 0.8)",
    "Dense forest\n(0.8, 1.0)",
]

_PDP_FEATURES = [
    ("station_celsius",  "Station temp (\u00b0C)",    "rgb(255,140,0)",  None, None),
    ("tp",               "Precipitation (m/day)",      "rgb(30,144,255)", None, None),
    ("u10",              "U wind (m/s)",               "rgb(147,112,219)", None, None),
    ("v10",              "V wind (m/s)",               "rgb(220,20,60)",  None, None),
    ("ndvi",             "NDVI",                       "rgb(34,139,34)",  _NDVI_BINS, _NDVI_LABELS),
    ("dist_to_sea_km",   "Distance to sea (km)",       "rgb(70,130,180)", None, None),
]


def _pdp_trace(df, feature, n_bins=5, custom_bins=None, custom_labels=None):
    tmp = df.dropna(subset=[feature, "residual"]).copy()
    if len(tmp) == 0:
        return [], np.array([]), np.array([])
    if custom_bins is not None:
        tmp["bin"] = pd.cut(tmp[feature], bins=custom_bins, labels=custom_labels)
        centers = custom_labels
    else:
        tmp["bin"] = pd.qcut(tmp[feature], q=n_bins, duplicates="drop")
        centers = [f"{iv.mid:.2f}" for iv in tmp["bin"].cat.categories]
    grouped = tmp.groupby("bin", observed=True)["residual"]
    mean = grouped.mean()
    std = grouped.std()
    return centers, mean.values, std.values


def _build_pdp_figure(day_df: pd.DataFrame):
    """Build 2x3 partial dependence subplots."""
    fig = make_subplots(
        rows=2, cols=3,
        subplot_titles=[f[1] for f in _PDP_FEATURES],
        horizontal_spacing=0.08, vertical_spacing=0.15,
    )

    positions = [(1, 1), (1, 2), (1, 3), (2, 1), (2, 2), (2, 3)]

    for (col, label, rgb, cbins, clabels), (row, c) in zip(_PDP_FEATURES, positions):
        if col not in day_df.columns:
            continue

        rgba = rgb.replace("rgb(", "rgba(").replace(")", ",0.15)")
        centers, mean, std = _pdp_trace(day_df, col, custom_bins=cbins, custom_labels=clabels)

        if len(centers) == 0:
            continue

        fig.add_trace(go.Scatter(
            x=centers + centers[::-1],
            y=list(mean + std) + list((mean - std)[::-1]),
            fill="toself", fillcolor=rgba, line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ), row=row, col=c)

        fig.add_trace(go.Scatter(
            x=centers, y=mean,
            mode="lines+markers",
            marker=dict(size=8, color=rgb),
            line=dict(color=rgb, width=2),
            name=label, showlegend=False,
            hovertemplate=f"{label}: %{{x}}<br>Mean: %{{y:.3f}} \u00b0C<extra></extra>",
        ), row=row, col=c)

        fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.4, row=row, col=c)

    fig.update_layout(
        height=650, template="plotly_white",
        margin=dict(l=50, r=20, t=40, b=40),
    )
    fig.update_yaxes(title_text="Mean residual (\u00b0C)", col=1)
    return fig


def _build_mean_residual_map(df: pd.DataFrame):
    """Map of mean residual per station across all dates."""
    station_mean = df.groupby("STAID").agg(
        mean_residual=("residual", "mean"),
        lat=("lat", "first"),
        lon=("lon", "first"),
    ).reset_index()

    fig = px.scatter_mapbox(
        station_mean, lat="lat", lon="lon",
        color="mean_residual", color_continuous_scale="RdBu_r",
        range_color=[-3, 3], zoom=3,
        center={"lat": 50, "lon": 10},
        mapbox_style="open-street-map",
    )
    fig.update_traces(marker=dict(size=6))
    fig.update_layout(
        height=700,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        coloraxis_colorbar_title="Mean residual (\u00b0C)",
    )
    return fig


def _build_monthly_boxplot(df: pd.DataFrame):
    """Boxplot of residual distribution by month (subsampled)."""
    import calendar

    month_colors = [
        "#1e88e5", "#1565c0", "#43a047", "#66bb6a", "#aed581", "#fdd835",
        "#ffb300", "#fb8c00", "#e53935", "#c62828", "#8e24aa", "#5e35b1",
    ]
    tmp = df.dropna(subset=["residual"]).copy()
    tmp["month"] = tmp["date"].dt.month

    fig = go.Figure()
    for m in range(1, 13):
        sub = tmp[tmp["month"] == m]["residual"]
        if len(sub) > 5000:
            sub = sub.sample(5000, random_state=42)
        fig.add_trace(go.Box(
            y=sub, name=calendar.month_abbr[m],
            marker_color=month_colors[m - 1],
        ))

    fig.update_layout(
        height=450, template="plotly_white",
        xaxis_title="Month", yaxis_title="Residual (\u00b0C)",
        showlegend=False,
        margin=dict(l=50, r=20, t=20, b=40),
    )
    return fig


_OLS_FEATURES = ["station_celsius", "tp", "u10", "v10", "ndvi", "dist_to_sea_km"]
_OLS_COLORS = ["#ff8c00", "#1e90ff", "#9370db", "#dc143c", "#228b22", "#4682b4"]


def _fit_ols(df: pd.DataFrame):
    """Fit standardized OLS and return model, reg_df, y, y_pred, std_resid, r2."""
    reg_df = df.dropna(subset=_OLS_FEATURES + ["residual"]).copy()
    scaler = StandardScaler()
    X_scaled = pd.DataFrame(
        scaler.fit_transform(reg_df[_OLS_FEATURES]), columns=_OLS_FEATURES,
    )
    X_scaled = sm.add_constant(X_scaled)
    y = reg_df["residual"].reset_index(drop=True)
    model = sm.OLS(y, X_scaled).fit()
    y_pred = model.predict(X_scaled)
    std_resid = (y.values - y_pred) / (y.values - y_pred).std()
    reg_df = reg_df.reset_index(drop=True)
    reg_df["std_resid"] = std_resid
    return model, reg_df, y, y_pred, std_resid


def _build_ols_coef_fig(model):
    """Horizontal bar chart of standardized coefficients with 95% CI."""
    coefs = model.params[1:]
    ci = model.conf_int().iloc[1:]
    names = coefs.index.tolist()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=coefs.values, y=names, orientation="h",
        marker_color=_OLS_COLORS,
        error_x=dict(
            type="data", symmetric=False,
            array=(ci[1] - coefs).values,
            arrayminus=(coefs - ci[0]).values,
        ),
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="grey")
    fig.update_layout(
        height=400, template="plotly_white",
        xaxis_title="Effect on residual (\u00b0C per 1 std)",
        yaxis=dict(autorange="reversed"),
        margin=dict(l=120, r=20, t=20, b=40),
    )
    return fig


def _build_corr_fig(reg_df):
    """Feature correlation heatmap."""
    corr = reg_df[_OLS_FEATURES + ["residual"]].corr()
    fig = go.Figure(go.Heatmap(
        z=corr.values, x=corr.columns, y=corr.columns,
        colorscale="RdBu_r", zmin=-1, zmax=1,
        text=corr.round(2).values, texttemplate="%{text}",
    ))
    fig.update_layout(
        height=500, width=600, template="plotly_white",
        margin=dict(l=100, r=20, t=20, b=40),
    )
    fig.update_yaxes(autorange="reversed")
    return fig


def _build_std_resid_vs_pred_fig(y_pred, std_resid):
    """Standardized residuals vs predicted scatter (subsampled)."""
    np.random.seed(42)
    n = min(50_000, len(y_pred))
    idx = np.random.choice(len(y_pred), size=n, replace=False)

    fig = go.Figure(go.Scattergl(
        x=y_pred[idx], y=std_resid[idx],
        mode="markers", marker=dict(size=2, opacity=0.1, color="steelblue"),
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="grey")
    fig.add_hline(y=2, line_dash="dot", line_color="red", opacity=0.5)
    fig.add_hline(y=-2, line_dash="dot", line_color="red", opacity=0.5)
    fig.update_layout(
        height=450, template="plotly_white",
        xaxis_title="Predicted (\u00b0C)", yaxis_title="Standardized residual",
        margin=dict(l=50, r=20, t=20, b=40),
    )
    return fig


def _build_std_resid_hist_fig(std_resid):
    """Distribution of standardized residuals (subsampled)."""
    np.random.seed(42)
    n = min(50_000, len(std_resid))
    idx = np.random.choice(len(std_resid), size=n, replace=False)

    fig = go.Figure(go.Histogram(
        x=std_resid[idx], nbinsx=100, marker_color="steelblue",
    ))
    fig.add_vline(x=-2, line_dash="dot", line_color="red", opacity=0.5)
    fig.add_vline(x=2, line_dash="dot", line_color="red", opacity=0.5)
    fig.update_layout(
        height=400, template="plotly_white",
        xaxis_title="Standardized residual", yaxis_title="Count",
        margin=dict(l=50, r=20, t=20, b=40),
    )
    return fig


def _build_std_resid_per_feature_fig(reg_df, std_resid):
    """Per-feature scatter of standardized residuals with binned mean trend."""
    np.random.seed(42)
    n = min(50_000, len(reg_df))
    idx = np.random.choice(len(reg_df), size=n, replace=False)
    sample = reg_df.iloc[idx]

    fig = make_subplots(
        rows=2, cols=3, subplot_titles=_OLS_FEATURES,
        horizontal_spacing=0.08, vertical_spacing=0.15,
    )

    for i, (feat, color) in enumerate(zip(_OLS_FEATURES, _OLS_COLORS)):
        row, col = divmod(i, 3)
        row += 1
        col += 1

        fig.add_trace(go.Scattergl(
            x=sample[feat].values, y=sample["std_resid"].values,
            mode="markers", marker=dict(size=2, opacity=0.08, color=color),
            showlegend=False, hoverinfo="skip",
        ), row=row, col=col)

        # Binned mean trend
        tmp = reg_df[[feat, "std_resid"]].copy()
        tmp["bin"] = pd.qcut(tmp[feat], q=20, duplicates="drop")
        binned = tmp.groupby("bin", observed=True)["std_resid"]
        centers = [iv.mid for iv in binned.mean().index]
        means = binned.mean().values

        fig.add_trace(go.Scatter(
            x=centers, y=means, mode="lines",
            line=dict(color="black", width=2), showlegend=False,
        ), row=row, col=col)

        fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.3,
                      row=row, col=col)

    fig.update_layout(
        height=650, template="plotly_white",
        margin=dict(l=50, r=20, t=40, b=40),
    )
    fig.update_yaxes(title_text="Std residual", col=1)
    return fig


def _summary_stats(day_df: pd.DataFrame) -> dict:
    residuals = day_df["residual"].dropna()
    return {
        "stations": len(residuals),
        "mean": residuals.mean() if len(residuals) else 0.0,
        "std": residuals.std() if len(residuals) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(data_dir: str = "data2") -> Dash:
    df, dates = _load_data(data_dir)

    app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

    # --- Slider marks: ~10 evenly spaced labels ---
    step = max(1, len(dates) // 10)
    slider_marks = {i: dates[i] for i in range(0, len(dates), step)}

    # --- Initial state ---
    init_day = df[df["date"] == dates[0]].dropna(subset=["residual"])
    init_stats = _summary_stats(init_day)

    # --- OLS fit (once at load time) ---
    ols_model, ols_reg_df, ols_y, ols_y_pred, ols_std_resid = _fit_ols(df)
    ols_r2 = ols_model.rsquared

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

            # Section title
            html.H3("Daily Residuals", className="text-center mt-2 mb-3"),

            # Controls
            dbc.Card(
                dbc.CardBody([
                    # Top row: play, speed, date picker
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Button(
                                    "Play", id="play-btn", n_clicks=0,
                                    outline=True, color="primary", size="sm",
                                ),
                                width="auto",
                                className="d-flex align-items-center",
                            ),
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
                            dbc.Col(
                                dcc.DatePickerSingle(
                                    id="date-picker",
                                    date=dates[0],
                                    min_date_allowed=dates[0],
                                    max_date_allowed=dates[-1],
                                    display_format="YYYY-MM-DD",
                                    style={"fontSize": "0.85rem"},
                                ),
                                width="auto",
                                className="d-flex align-items-center",
                            ),
                        ],
                        align="center",
                        className="g-3 mb-3",
                    ),
                    # Full-width slider below
                    dcc.Slider(
                        id="date-slider",
                        min=0,
                        max=len(dates) - 1,
                        value=0,
                        marks=slider_marks,
                        step=1,
                        tooltip={"placement": "bottom", "always_visible": False},
                    ),
                ]),
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
                className="mb-3",
            ),

            # PDP title + card
            html.H4("Partial Dependence Plots", className="mt-2 mb-2"),
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(id="pdp", figure=_build_pdp_figure(init_day)),
                ),
                className="mb-3",
            ),

            # --- Aggregated Statistics ---
            html.H3("Aggregated Statistics", className="text-center mt-4 mb-3"),

            html.H5("Mean residual per station (all dates)", className="text-muted mb-2"),
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(id="mean-map", figure=_build_mean_residual_map(df)),
                ),
                className="mb-3",
            ),

            html.H5("Residual distribution by month", className="text-muted mb-2"),
            dbc.Card(
                dbc.CardBody(
                    dcc.Graph(id="monthly-box", figure=_build_monthly_boxplot(df)),
                ),
                className="mb-3",
            ),

            # --- OLS Fit ---
            html.H3(f"OLS Fit (R\u00b2 = {ols_r2:.3f})",
                     className="text-center mt-4 mb-3"),

            html.H5("Standardized coefficients (\u00b195% CI)", className="text-muted mb-2"),
            dbc.Card(dbc.CardBody(
                dcc.Graph(figure=_build_ols_coef_fig(ols_model)),
            ), className="mb-3"),

            html.H5("Feature correlation matrix", className="text-muted mb-2"),
            dbc.Card(dbc.CardBody(
                dcc.Graph(figure=_build_corr_fig(ols_reg_df)),
            ), className="mb-3"),

            html.H5("Standardized residuals vs predicted", className="text-muted mb-2"),
            dbc.Card(dbc.CardBody(
                dcc.Graph(figure=_build_std_resid_vs_pred_fig(ols_y_pred, ols_std_resid)),
            ), className="mb-3"),

            html.H5("Distribution of standardized residuals", className="text-muted mb-2"),
            dbc.Card(dbc.CardBody(
                dcc.Graph(figure=_build_std_resid_hist_fig(ols_std_resid)),
            ), className="mb-3"),

            html.H5("Standardized residuals vs features (50k subsample)",
                     className="text-muted mb-2"),
            dbc.Card(dbc.CardBody(
                dcc.Graph(figure=_build_std_resid_per_feature_fig(
                    ols_reg_df, ols_std_resid)),
            )),
        ],
    )

    # -----------------------------------------------------------------------
    # Callbacks
    # -----------------------------------------------------------------------

    # Build a date→index lookup for the picker
    date_to_idx = {d: i for i, d in enumerate(dates)}

    def _get_day_df(slider_idx, picker_date):
        """Resolve slider/picker to a day DataFrame."""
        trigger = ctx.triggered_id
        if trigger == "date-picker" and picker_date:
            picked = picker_date[:10]
            if picked in date_to_idx:
                slider_idx = date_to_idx[picked]
            else:
                slider_idx = min(
                    range(len(dates)),
                    key=lambda i: abs(pd.Timestamp(dates[i]) - pd.Timestamp(picked)),
                )
        date_str = dates[slider_idx]
        day_df = df[df["date"] == date_str].dropna(subset=["residual"])
        return slider_idx, date_str, day_df

    @app.callback(
        Output("map", "figure"),
        Output("date-slider", "value", allow_duplicate=True),
        Output("date-picker", "date"),
        Output("stat-stations", "children"),
        Output("stat-mean", "children"),
        Output("stat-std", "children"),
        Input("date-slider", "value"),
        Input("date-picker", "date"),
        prevent_initial_call=True,
    )
    def update_map(slider_idx, picker_date):
        slider_idx, date_str, day_df = _get_day_df(slider_idx, picker_date)
        stats = _summary_stats(day_df)
        return (
            _build_figure(day_df),
            slider_idx,
            date_str,
            str(stats["stations"]),
            f"{stats['mean']:.2f} \u00b0C",
            f"{stats['std']:.2f} \u00b0C",
        )

    @app.callback(
        Output("pdp", "figure"),
        Input("date-slider", "value"),
        Input("date-picker", "date"),
        Input("interval", "disabled"),
        prevent_initial_call=True,
    )
    def update_pdp(slider_idx, picker_date, interval_disabled):
        # Only update PDP when play is stopped (interval disabled)
        # or when triggered by manual slider/picker change
        trigger = ctx.triggered_id
        if trigger == "interval" or (not interval_disabled and trigger == "date-slider"):
            # Skip PDP update during playback — too slow
            from dash import no_update
            return no_update
        _, _, day_df = _get_day_df(slider_idx, picker_date)
        return _build_pdp_figure(day_df)

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
