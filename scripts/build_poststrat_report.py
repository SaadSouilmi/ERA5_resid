"""
Builds /home2/lobib/research-reports/era5-poststrat-report.html: a static,
self-contained report of the post-stratification / GREG analysis in
notebooks/poststrat_analysis.py.

Run with: uv run python scripts/build_poststrat_report.py
"""
import itertools
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import polars as pl
import rasterio
from plotly.subplots import make_subplots
from pyproj import Transformer
from shapely.geometry import Point
from shapely.strtree import STRtree
from sklearn.linear_model import LinearRegression

from era5_analysis import pdp

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "main"
DATA2 = ROOT / "data2"
DEGURBA_TIF = DATA2 / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0" / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
EUROPE_GPKG = DATA / "gadm_410_europe.gpkg"
RESIDUALS_PARQUET = DATA2 / "residuals.parquet"
OUT_HTML = Path("/home2/lobib/research-reports/era5-poststrat-report.html")

DEGURBA_LABELS = {
    10: "Water", 11: "Very low density rural", 12: "Low density rural", 13: "Rural cluster",
    21: "Suburban", 22: "Semi-dense urban cluster", 23: "Dense urban cluster", 30: "Urban centre",
}
DEGURBA_ORDER = [
    "Very low density rural", "Low density rural", "Rural cluster", "Suburban",
    "Semi-dense urban cluster", "Dense urban cluster", "Urban centre",
]
PALETTE = {
    "blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "yellow": "#eda100",
    "magenta": "#e87ba4", "green": "#008300", "violet": "#4a3aa7", "red": "#e34948",
}
GRID_COLOR, AXIS_COLOR, MUTED_INK = "#e1e0d9", "#c3c2b7", "#898781"
AX = dict(gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK))
CONFIG = dict(displayModeBar=False, responsive=True)


def hex_to_rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


print("Loading + filtering residuals_df...")
residuals_df = pl.read_parquet(RESIDUALS_PARQUET)
n0 = residuals_df["STAID"].n_unique()
residuals_df = residuals_df.filter(
    ~(
        ((pl.col("country") == "Türkiye") & (pl.col("lon") > 29.1))
        | ((pl.col("country") == "Russian Federation") & (pl.col("lon") > 69.07))
        | ((pl.col("country") == "Spain") & (pl.col("lon") < -12.0))
        | (pl.col("country") == "Israel")
        | (pl.col("country") == "Greenland")
    )
)
n1 = residuals_df["STAID"].n_unique()
n_rows = len(residuals_df)

station_df = residuals_df.group_by("STAID").agg(
    pl.col("residual").mean(), pl.col("elevation").first(), pl.col("dist_to_sea_km").first(),
    pl.col("degurba_label").first(), pl.col("degurba").first(), pl.col("ndvi").mean(),
    pl.col("lat").first(), pl.col("lon").first(), pl.col("country").first(),
    pl.len().alias("n_obs"),
)

print("Computing pop_degurba (GHS-SMOD raster crop)...")
transformer = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
x_min, y_min = transformer.transform(-15.0, 34.0)
x_max, y_max = transformer.transform(35.0, 72.0)
with rasterio.open(DEGURBA_TIF) as src:
    from rasterio.windows import from_bounds
    win = from_bounds(x_min, y_min, x_max, y_max, src.transform).round_lengths().round_offsets()
    data = src.read(1, window=win)
    nodata = src.nodata
valid = data.flatten()
valid = valid[valid != nodata].astype(int)
vals, counts = np.unique(valid, return_counts=True)
pixel_counts = dict(zip(vals.tolist(), counts.tolist()))
land_counts = {k: v for k, v in pixel_counts.items() if k != 10}
total_land = sum(land_counts.values())
pop_degurba = {DEGURBA_LABELS[k]: v / total_land for k, v in land_counts.items() if k in DEGURBA_LABELS}

print("Sampling reference distance-to-sea (this is the slow part)...")
N_SAMPLE = 8_000
europe_gdf = gpd.read_file(EUROPE_GPKG)
europe_geom = europe_gdf.dissolve().to_crs("EPSG:3035").geometry.iloc[0]
coastline = europe_geom.boundary.simplify(1000)
rng = np.random.default_rng(42)
minx, miny, maxx, maxy = europe_geom.bounds
pts = []
while len(pts) < N_SAMPLE:
    bx = rng.uniform(minx, maxx, N_SAMPLE * 4)
    by = rng.uniform(miny, maxy, N_SAMPLE * 4)
    for x, y in zip(bx, by):
        if europe_geom.contains(Point(x, y)):
            pts.append((x, y))
            if len(pts) >= N_SAMPLE:
                break
import shapely as shp
segments = list(coastline.geoms) if coastline.geom_type == "MultiLineString" else [coastline]
tree = STRtree(segments)
sample_arr = shp.from_wkt([Point(x, y).wkt for x, y in pts])
nearest_idx = tree.nearest(sample_arr)
nearest_segs = np.array(segments, dtype=object)[nearest_idx]
ref_dist_to_sea_km = shp.distance(sample_arr, nearest_segs) / 1000.0

print("Post-stratification + GREG...")
station_land = station_df.filter(pl.col("degurba_label") != "Water")
n_stations = len(station_land)
sample_counts = station_land.group_by("degurba_label").agg(pl.len().alias("n_s")).to_pandas().set_index("degurba_label")["n_s"].to_dict()
stratum_means = station_land.group_by("degurba_label").agg(pl.col("residual").mean().alias("m")).to_pandas().set_index("degurba_label")["m"].to_dict()
y_naive = float(station_land["residual"].mean())
y_poststrat = sum(pop_degurba.get(s, 0.0) * stratum_means.get(s, 0.0) for s in DEGURBA_ORDER)

strata_weights = {}
for s in DEGURBA_ORDER:
    p_pop = pop_degurba.get(s, 0.0)
    p_sample = sample_counts.get(s, 0) / n_stations
    strata_weights[s] = p_pop / p_sample if p_sample > 0 else 0.0
weight_map = pl.DataFrame({"degurba_label": list(strata_weights.keys()), "ps_weight": list(strata_weights.values())})
station_df_weighted = station_land.join(weight_map, on="degurba_label", how="left")

station_pd = station_df_weighted.to_pandas()
dummies = pd.get_dummies(station_pd["degurba_label"].astype(pd.CategoricalDtype(DEGURBA_ORDER)), prefix="deg", dtype=float)
dist_mean, dist_std = station_pd["dist_to_sea_km"].mean(), station_pd["dist_to_sea_km"].std()
dist_std_col = (station_pd["dist_to_sea_km"] - dist_mean) / dist_std
X_sample = np.hstack([dummies.values, dist_std_col.values.reshape(-1, 1)])
y_sample = station_pd["residual"].values
pop_deg_means = np.array([pop_degurba.get(s, 0.0) for s in DEGURBA_ORDER])
pop_dist_std_mean = (ref_dist_to_sea_km.mean() - dist_mean) / dist_std
X_pop_bar = np.concatenate([pop_deg_means, [pop_dist_std_mean]])
x_bar_sample = X_sample.mean(axis=0)
reg = LinearRegression(fit_intercept=False)
reg.fit(X_sample, y_sample, sample_weight=station_pd["n_obs"].values.astype(float))
beta = reg.coef_
y_greg = float(y_naive + (X_pop_bar - x_bar_sample) @ beta)
V_hat = (X_sample.T @ X_sample) / len(X_sample) + 1e-8 * np.eye(X_sample.shape[1])
greg_weights_raw = 1.0 + X_sample @ np.linalg.solve(V_hat, X_pop_bar - x_bar_sample)
station_df_greg = station_df_weighted.with_columns(pl.Series("greg_weight", greg_weights_raw.tolist()))

print("Bootstrap (B=1000)...")
B, ALPHA = 1000, 0.05
station_pd_bs = station_df_greg.to_pandas().copy()
n = len(station_pd_bs)
rng2 = np.random.default_rng(0)
dist_mean_bs, dist_std_bs = station_pd_bs["dist_to_sea_km"].mean(), station_pd_bs["dist_to_sea_km"].std()
pop_dist_std_mean_bs = (ref_dist_to_sea_km.mean() - dist_mean_bs) / dist_std_bs
pop_deg_means_bs = np.array([pop_degurba.get(s, 0.0) for s in DEGURBA_ORDER])
boot_naive, boot_ps, boot_greg = np.empty(B), np.empty(B), np.empty(B)
for b in range(B):
    idx = rng2.integers(0, n, size=n)
    s = station_pd_bs.iloc[idx]
    boot_naive[b] = s["residual"].mean()
    boot_ps[b] = sum(
        pop_degurba.get(st, 0.0) * s.loc[s["degurba_label"] == st, "residual"].mean()
        for st in DEGURBA_ORDER if (s["degurba_label"] == st).any()
    )
    dummies_b = pd.get_dummies(s["degurba_label"].astype(pd.CategoricalDtype(DEGURBA_ORDER)), prefix="deg", dtype=float)
    dist_std_b = (s["dist_to_sea_km"] - dist_mean_bs) / dist_std_bs
    Xb = np.hstack([dummies_b.values, dist_std_b.values.reshape(-1, 1)])
    reg_b = LinearRegression(fit_intercept=False)
    reg_b.fit(Xb, s["residual"].values, sample_weight=s["n_obs"].values.astype(float))
    X_pop_b = np.concatenate([pop_deg_means_bs, [pop_dist_std_mean_bs]])
    boot_greg[b] = boot_naive[b] + (X_pop_b - Xb.mean(axis=0)) @ reg_b.coef_

ci = lambda a: np.percentile(a, [100 * ALPHA / 2, 100 * (1 - ALPHA / 2)])
ci_naive, ci_ps, ci_greg = ci(boot_naive), ci(boot_ps), ci(boot_greg)
bootstrap_results = {
    "Naive": {"mean": y_naive, "ci_lo": ci_naive[0], "ci_hi": ci_naive[1]},
    "Post-stratified": {"mean": y_poststrat, "ci_lo": ci_ps[0], "ci_hi": ci_ps[1]},
    "GREG": {"mean": y_greg, "ci_lo": ci_greg[0], "ci_hi": ci_greg[1]},
}

print("Building figures...")

# ---- Figure 1, 2: representativeness ----
station_pct_map = (
    station_df.filter(pl.col("degurba_label") != "Water")
    .group_by("degurba_label").agg(pl.len().alias("count"))
    .with_columns((pl.col("count") / len(station_df)).alias("pct"))
    .to_pandas().set_index("degurba_label")["pct"]
)
fig1 = go.Figure()
fig1.add_bar(name="Stations", x=DEGURBA_ORDER, y=[float(station_pct_map.get(l, 0)) for l in DEGURBA_ORDER], marker_color=PALETTE["blue"])
fig1.add_bar(name="GHS-SMOD land", x=DEGURBA_ORDER, y=[pop_degurba.get(l, 0) for l in DEGURBA_ORDER], marker_color=PALETTE["orange"])
fig1.update_layout(template="plotly_white", barmode="group", bargap=0.25, height=320,
                    legend=dict(orientation="h", y=1.08, x=0),
                    xaxis=dict(title=None, tickangle=-30, **AX), yaxis=dict(title="Share", tickformat=".0%", **AX),
                    margin=dict(t=20, b=70))

station_dist = station_df["dist_to_sea_km"].to_pandas().clip(upper=800)
ref_dist = np.clip(ref_dist_to_sea_km, None, 800)
fig2 = go.Figure()
fig2.add_histogram(name="Stations", x=station_dist, nbinsx=40, marker_color=PALETTE["blue"], opacity=0.55)
fig2.add_histogram(name="Land sample", x=ref_dist, nbinsx=40, marker_color=PALETTE["orange"], opacity=0.55)
fig2.update_layout(template="plotly_white", barmode="overlay", height=300, legend=dict(orientation="h", y=1.08, x=0),
                    xaxis=dict(title="km, clipped at 800", **AX), yaxis=dict(title="Count", **AX), margin=dict(t=20, b=50))

# ---- Figure 3: results ----
est_order = ["Naive", "Post-stratified", "GREG"]
colors = [PALETTE["blue"], PALETTE["orange"], PALETTE["aqua"]]
means = [bootstrap_results[e]["mean"] for e in est_order]
err_plus = [bootstrap_results[e]["ci_hi"] - bootstrap_results[e]["mean"] for e in est_order]
err_minus = [bootstrap_results[e]["mean"] - bootstrap_results[e]["ci_lo"] for e in est_order]
fig3 = go.Figure(go.Bar(
    x=est_order, y=means, marker_color=colors, width=0.5,
    error_y=dict(type="data", symmetric=False, array=err_plus, arrayminus=err_minus, color=MUTED_INK, thickness=1.5, width=6),
))
fig3.update_layout(template="plotly_white", showlegend=False, height=340,
                    xaxis=dict(title=None, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK)),
                    yaxis=dict(title="Mean residual (°C)", **AX), margin=dict(t=20, b=30))

# ---- Figure 4, 5: weights ----
p_pop = [pop_degurba.get(s, 0.0) for s in DEGURBA_ORDER]
weights = [strata_weights.get(s, 0.0) for s in DEGURBA_ORDER]
p_sample = [pp / w if w > 0 else 0.0 for pp, w in zip(p_pop, weights)]
fig4 = go.Figure()
fig4.add_bar(name="GHS population", x=DEGURBA_ORDER, y=p_pop, marker_color=PALETTE["blue"])
fig4.add_bar(name="Station sample", x=DEGURBA_ORDER, y=p_sample, marker_color=PALETTE["orange"])
fig4.update_layout(template="plotly_white", barmode="group", bargap=0.25, height=320,
                    legend=dict(orientation="h", y=1.08, x=0),
                    xaxis=dict(title=None, tickangle=-30, **AX), yaxis=dict(title="Share", tickformat=".0%", **AX),
                    margin=dict(t=20, b=70))

bar_colors = [PALETTE["red"] if w > 1.0 else PALETTE["blue"] for w in weights]
fig5 = go.Figure(go.Bar(x=DEGURBA_ORDER, y=weights, marker_color=bar_colors))
fig5.add_hline(y=1.0, line_dash="dash", line_color=MUTED_INK, annotation_text="w = 1")
fig5.update_layout(template="plotly_white", height=320, xaxis=dict(title=None, tickangle=-30, **AX),
                    yaxis=dict(title="w_s", rangemode="tozero", **AX), margin=dict(t=20, b=70))

# ---- Figure 6: map ----
map_pd = station_df_greg.select(["lat", "lon", "ps_weight", "degurba_label", "country", "STAID"]).to_pandas()
diverging_scale = [[0.0, PALETTE["blue"]], [0.5, "#f0efec"], [1.0, PALETTE["red"]]]
fig6 = px.scatter_map(map_pd, lat="lat", lon="lon", color="ps_weight", color_continuous_scale=diverging_scale,
                       color_continuous_midpoint=1.0, zoom=2.6, center={"lat": 50, "lon": 10},
                       hover_data={"STAID": True, "degurba_label": True, "country": True, "ps_weight": ":.3f"})
fig6.update_traces(marker=dict(size=5, opacity=0.8))
fig6.update_layout(height=560, template="plotly_white", margin=dict(t=10, b=0, l=0, r=0),
                    coloraxis_colorbar=dict(title="w_s", tickformat=".2f"))

# ---- PDPs ----
residuals_df_weighted = residuals_df.join(station_df_greg.select(["STAID", "ps_weight", "greg_weight"]), on="STAID", how="inner")


def make_pdp(df, feature, xlabel, n_bins=10, log10=False, weight_col="greg_weight", n_boot=400):
    dfx = df
    if log10:
        dfx = dfx.with_columns(pl.col(feature).clip(lower_bound=1e-9).log(base=10).alias(feature))
    df_binned, bins = pdp.bin_features(dfx, feature, n_bins=n_bins)
    means_u, lo_u, hi_u = pdp.pdp_cluster_bootstrap(df_binned, "bin", bins, rng=np.random.default_rng(1337), n_boot=n_boot)
    means_w, lo_w, hi_w = pdp.pdp_cluster_bootstrap(df_binned, "bin", bins, rng=np.random.default_rng(1337), weight_col=weight_col, n_boot=n_boot)
    centers = pdp.bin_centers(bins, df_binned[feature].min(), df_binned[feature].max())
    xl = f"{xlabel} (log₁₀)" if log10 else xlabel
    fig = go.Figure()
    for name, m, lo, hi, color in [("Unweighted", means_u, lo_u, hi_u, PALETTE["blue"]), ("GREG-weighted", means_w, lo_w, hi_w, PALETTE["orange"])]:
        fig.add_scatter(x=centers + centers[::-1], y=list(hi) + list(lo[::-1]), fill="toself",
                         fillcolor=hex_to_rgba(color, 0.15), line=dict(color="rgba(255,255,255,0)"), hoverinfo="skip", showlegend=False)
        fig.add_scatter(x=centers, y=m, mode="lines+markers", name=name, line=dict(color=color, width=2), marker=dict(size=6))
    fig.add_hline(y=0, line_dash="dash", line_color=MUTED_INK, opacity=0.6)
    fig.update_layout(template="plotly_white", height=300, legend=dict(orientation="h", y=1.1, x=0),
                       xaxis=dict(title=xl, **AX), yaxis=dict(title="Mean residual (°C)", **AX), margin=dict(t=30, b=40))
    return fig


pdp_specs = [
    ("station_celsius", "Station temp (°C)", False),
    ("tp", "Precipitation (m/day)", True),
    ("wind", "Wind speed (m/s)", False),
    ("ndvi", "NDVI", False),
    ("dist_to_sea_km", "Distance to sea (km)", False),
    ("elevation", "Elevation (m)", False),
]
print("  6 PDPs...")
pdp_figs = [make_pdp(residuals_df_weighted, f, l, log10=lg) for f, l, lg in pdp_specs]

# ---- Cross heatmaps ----


def make_cross_heatmap(df, feat_x, feat_y, xlabel, ylabel, n_bins=8, weight_col="greg_weight",
                        color_feat="residual", color_title=None, diverging=True, sequential_hue="red", log10_color=False):
    dfx = df
    if log10_color:
        dfx = dfx.with_columns(pl.col(color_feat).clip(lower_bound=1e-9).log(base=10).alias(color_feat))
    color_title = color_title or ("Mean residual (°C)" if color_feat == "residual" else f"Mean {color_feat}")
    if log10_color:
        color_title = f"{color_title} (log₁₀)"
    dfx, bins_x = pdp.bin_features(dfx, feat_x, n_bins=n_bins)
    dfx = dfx.rename({"bin": "bin_x"})
    dfx, bins_y = pdp.bin_features(dfx, feat_y, n_bins=n_bins)
    dfx = dfx.rename({"bin": "bin_y"})

    def parse_edges(bins, dmin, dmax):
        out = []
        for b in bins:
            lo, hi = b.strip("(]").split(", ")
            out.append((dmin if lo == "-inf" else float(lo), dmax if hi == "inf" else float(hi)))
        return out

    edges_x = parse_edges(bins_x, float(dfx[feat_x].min()), float(dfx[feat_x].max()))
    edges_y = parse_edges(bins_y, float(dfx[feat_y].min()), float(dfx[feat_y].max()))
    x_labels = [f"{lo:.3g}–{hi:.3g}" for lo, hi in edges_x]
    y_labels = [f"{lo:.3g}–{hi:.3g}" for lo, hi in edges_y]
    full_grid = pd.DataFrame(list(itertools.product(bins_x, bins_y)), columns=["bin_x", "bin_y"])

    def grid(weight):
        if weight is None:
            agg = dfx.group_by(["bin_x", "bin_y"]).agg(pl.col(color_feat).mean().alias("v"))
        else:
            agg = dfx.group_by(["bin_x", "bin_y"]).agg(((pl.col(color_feat) * pl.col(weight)).sum() / pl.col(weight).sum()).alias("v"))
        heat = full_grid.merge(agg.to_pandas(), on=["bin_x", "bin_y"], how="left")
        z = heat.pivot(index="bin_y", columns="bin_x", values="v").reindex(index=bins_y, columns=bins_x)
        return z.to_numpy()

    z_u, z_w = grid(None), grid(weight_col)
    all_z = np.concatenate([z_u.flatten(), z_w.flatten()])
    if diverging:
        abs_max = np.nanmax(np.abs(all_z))
        zmin, zmax = -abs_max, abs_max
        scale = [[0.0, PALETTE["blue"]], [0.5, "#f0efec"], [1.0, PALETTE["red"]]]
    else:
        zmin, zmax = float(np.nanmin(all_z)), float(np.nanmax(all_z))
        scale = [[0.0, "#ffffff"], [1.0, PALETTE[sequential_hue]]]

    fig = make_subplots(rows=1, cols=2, subplot_titles=["Unweighted", "GREG-weighted"], horizontal_spacing=0.15)
    for col, z in enumerate([z_u, z_w], start=1):
        fig.add_trace(go.Heatmap(z=z, x=x_labels, y=y_labels, zmin=zmin, zmax=zmax, colorscale=scale,
                                  showscale=(col == 2), colorbar=dict(title=color_title) if col == 2 else None), row=1, col=col)
    fig.update_layout(template="plotly_white", height=380, margin=dict(t=40, b=70))
    fig.update_xaxes(title=xlabel, tickangle=-30, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))
    fig.update_yaxes(title=ylabel, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))
    return fig


print("  cross-heatmaps...")
fig8 = make_cross_heatmap(residuals_df_weighted, "elevation", "dist_to_sea_km", "Elevation (m)", "Distance to sea (km)")
fig9 = make_cross_heatmap(residuals_df_weighted, "station_celsius", "wind", "Station temp (°C)", "Wind speed (m/s)")

df_dg = residuals_df_weighted.filter(pl.col("degurba_label").is_in(DEGURBA_ORDER))
df_dg, bins_dist = pdp.bin_features(df_dg, "dist_to_sea_km", n_bins=8)
df_dg = df_dg.rename({"bin": "bin_dist"})


def parse(bins, dmin, dmax):
    out = []
    for b in bins:
        lo, hi = b.strip("(]").split(", ")
        out.append((dmin if lo == "-inf" else float(lo), dmax if hi == "inf" else float(hi)))
    return out


edges = parse(bins_dist, float(df_dg["dist_to_sea_km"].min()), float(df_dg["dist_to_sea_km"].max()))
x_labels_dg = [f"{lo:.3g}–{hi:.3g}" for lo, hi in edges]
full = pd.DataFrame(list(itertools.product(bins_dist, DEGURBA_ORDER)), columns=["bin_dist", "degurba_label"])


def grid_dg(weight):
    if weight is None:
        agg = df_dg.group_by(["bin_dist", "degurba_label"]).agg(pl.col("residual").mean().alias("v"))
    else:
        agg = df_dg.group_by(["bin_dist", "degurba_label"]).agg(((pl.col("residual") * pl.col(weight)).sum() / pl.col(weight).sum()).alias("v"))
    heat = full.merge(agg.to_pandas(), on=["bin_dist", "degurba_label"], how="left")
    z = heat.pivot(index="degurba_label", columns="bin_dist", values="v").reindex(index=DEGURBA_ORDER, columns=bins_dist)
    return z.to_numpy()


z_u_dg, z_w_dg = grid_dg(None), grid_dg("greg_weight")
abs_max_dg = np.nanmax(np.abs(np.concatenate([z_u_dg.flatten(), z_w_dg.flatten()])))
scale_dg = [[0.0, PALETTE["blue"]], [0.5, "#f0efec"], [1.0, PALETTE["red"]]]
fig10 = make_subplots(rows=1, cols=2, subplot_titles=["Unweighted", "GREG-weighted"], horizontal_spacing=0.2)
for col, z in enumerate([z_u_dg, z_w_dg], start=1):
    fig10.add_trace(go.Heatmap(z=z, x=x_labels_dg, y=DEGURBA_ORDER, zmin=-abs_max_dg, zmax=abs_max_dg, colorscale=scale_dg,
                                showscale=(col == 2), colorbar=dict(title="Mean residual (°C)") if col == 2 else None), row=1, col=col)
fig10.update_layout(template="plotly_white", height=380, margin=dict(t=40, b=60))
fig10.update_xaxes(title="Distance to sea (km)", tickangle=-30, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))
fig10.update_yaxes(gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))

kw = dict(df=residuals_df_weighted, feat_x="elevation", feat_y="dist_to_sea_km",
          xlabel="Elevation (m)", ylabel="Distance to sea (km)", diverging=False)
fig11a = make_cross_heatmap(**kw, color_feat="station_celsius", sequential_hue="orange")
fig11b = make_cross_heatmap(**kw, color_feat="ndvi", sequential_hue="green")
fig11c = make_cross_heatmap(**kw, color_feat="tp", sequential_hue="blue", log10_color=True)
fig11d = make_cross_heatmap(**kw, color_feat="wind", sequential_hue="violet")

print("Assembling HTML...")


def fig_div(fig, fid):
    return pio.to_html(fig, full_html=False, include_plotlyjs=False, config=CONFIG, div_id=fid)


from plotly.offline import get_plotlyjs
plotly_js_tag = f"<script>{get_plotlyjs()}</script>"

named_figs = {
    "f1": fig1, "f2": fig2, "f3": fig3, "f4": fig4, "f5": fig5, "f6": fig6,
    "pdp1": pdp_figs[0], "pdp2": pdp_figs[1], "pdp3": pdp_figs[2],
    "pdp4": pdp_figs[3], "pdp5": pdp_figs[4], "pdp6": pdp_figs[5],
    "f8": fig8, "f9": fig9, "f10": fig10,
    "f11a": fig11a, "f11b": fig11b, "f11c": fig11c, "f11d": fig11d,
}
figs = {key: fig_div(fig, f"fig_{key}") for key, fig in named_figs.items()}
pdp_ids = ["pdp1", "pdp2", "pdp3", "pdp4", "pdp5", "pdp6"]

est_rows = "\n".join(
    f'<tr><td>{e}</td><td>{bootstrap_results[e]["mean"]:+.4f}</td>'
    f'<td>[{bootstrap_results[e]["ci_lo"]:+.4f}, {bootstrap_results[e]["ci_hi"]:+.4f}]</td></tr>'
    for e in est_order
)

CSS = """
:root{
  --surface:#ffffff; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --rule:#e1e0d9; --max:920px;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--surface); color:var(--ink);
  font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;
}
main{max-width:var(--max); margin:0 auto; padding:64px 24px 96px}
header{margin-bottom:48px}
h1{font-size:22px; font-weight:600; margin:0 0 4px; letter-spacing:-0.01em}
.subtitle{color:var(--ink-2); font-size:14px; margin:0 0 12px}
.meta{color:var(--muted); font-size:12.5px; font-variant-numeric:tabular-nums}
h2{
  font-size:14px; font-weight:600; text-transform:uppercase; letter-spacing:0.04em;
  color:var(--ink); border-bottom:1px solid var(--rule); padding-bottom:8px; margin:56px 0 20px;
}
p{color:var(--ink-2); margin:0 0 16px; max-width:68ch}
code{background:#f0efec; padding:1px 5px; border-radius:3px; font-size:0.9em}
.cap{color:var(--muted); font-size:12.5px; margin:6px 0 28px; max-width:68ch}
.cap b{color:var(--ink-2); font-weight:600}
.fig{margin-bottom:8px}
.grid2{display:grid; grid-template-columns:1fr 1fr; gap:24px 32px}
table{border-collapse:collapse; margin:0 0 16px; font-size:13.5px; font-variant-numeric:tabular-nums}
td,th{padding:5px 18px 5px 0; text-align:left; border-bottom:1px solid var(--rule)}
th{color:var(--muted); font-weight:500; font-size:12px; text-transform:uppercase; letter-spacing:0.03em}
.eq{font-size:13.5px; color:var(--ink-2); background:#f6f5f2; padding:10px 14px; border-radius:4px; margin:0 0 16px}
footer{margin-top:64px; padding-top:16px; border-top:1px solid var(--rule); color:var(--muted); font-size:12px}
@media(max-width:760px){ .grid2{grid-template-columns:1fr} }
"""

# Kept as a plain raw string (not part of the f-string below) so LaTeX braces
# and backslashes don't need doubling/escaping.
EQ_HTML = r"""<div class="eq">
$$\bar{y}_{PS} = \sum_s p_s^{pop} \cdot \bar{y}_s, \quad w_s = \frac{p_s^{pop}}{p_s^{sample}}$$
$$\hat{y}_{GREG} = \bar{y} + (\bar{X}_{pop} - \bar{x}_{sample})^\top \hat{\beta}$$
</div>"""

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Post-Stratification of ERA5 Temperature Bias</title>
<style>{CSS}</style>
{plotly_js_tag}
<script>
MathJax = {{ tex: {{ inlineMath: [['$', '$']], displayMath: [['$$', '$$']] }} }};
</script>
<script id="MathJax-script" async src="https://cdnjs.cloudflare.com/ajax/libs/mathjax/3.2.2/es5/tex-mml-chtml.min.js"></script>
</head>
<body>
<main>

<header>
  <h1>Post-Stratification of ERA5 Temperature Bias</h1>
  <p class="subtitle">Correcting for station-network sampling bias via DEGURBA class and distance to sea</p>
  <div class="meta">ERA5-Land vs. ECA&amp;D, 2020–2025 &middot; residual = ERA5 &minus; station</div>
</header>

<h2>Data</h2>
<p>
<code>residuals.parquet</code>, filtered to stations where <code>dist_to_sea_km</code> is reliable.
The reference coastline (<code>gadm_410_europe.gpkg</code>) has incomplete geometry for five
groups, all excluded: Anatolian Türkiye, far-eastern Russia, the Canary Islands, Israel, Greenland.
</p>
<table>
<tr><th>Stations, before filter</th><td>{n0:,}</td></tr>
<tr><th>Stations, after filter</th><td>{n1:,}</td></tr>
<tr><th>Rows</th><td>{n_rows:,}</td></tr>
</table>

<h2>Sample representativeness</h2>
<p>The station network over-samples suburban and near-coast locations relative to true European land coverage.</p>
<div class="grid2">
  <div>
    <div class="fig">{figs['f1']}</div>
    <div class="cap"><b>Figure 1.</b> DEGURBA class: station sample vs. GHS-SMOD land population.</div>
  </div>
  <div>
    <div class="fig">{figs['f2']}</div>
    <div class="cap"><b>Figure 2.</b> Distance to sea: station sample vs. a random land sample (n={N_SAMPLE:,}).</div>
  </div>
</div>

<h2>Post-stratification and GREG calibration</h2>
{EQ_HTML}
<p>Post-stratified mean, weighted by GHS-SMOD land share per DEGURBA stratum. GREG adds a
distance-to-sea calibration on top, with $\\hat{{\\beta}}$ from regressing residual on DEGURBA
dummies + standardized <code>dist_to_sea_km</code>.</p>

<div class="fig">{figs['f3']}</div>
<div class="cap"><b>Figure 3.</b> Mean residual by estimator, 95% bootstrap CI (B=1,000, station resampling).</div>

<table>
<tr><th>Estimator</th><th>Mean (°C)</th><th>95% CI</th></tr>
{est_rows}
</table>

<div class="grid2">
  <div>
    <div class="fig">{figs['f4']}</div>
    <div class="cap"><b>Figure 4.</b> Population vs. sample proportion per DEGURBA class.</div>
  </div>
  <div>
    <div class="fig">{figs['f5']}</div>
    <div class="cap"><b>Figure 5.</b> Post-stratification weight w<sub>s</sub>. Red: under-represented (upweighted). Blue: over-represented (downweighted).</div>
  </div>
</div>

<div class="fig">{figs['f6']}</div>
<div class="cap"><b>Figure 6.</b> Post-stratification weight per station.</div>

<h2>Partial dependence: unweighted vs. GREG-weighted</h2>
<p>Each panel overlays the raw sample mean against the GREG-weighted mean. Close agreement means the
pattern is unlikely to be an artifact of station-network composition.</p>
<div class="grid2">
  {''.join(f'<div><div class="fig">{figs[fid]}</div></div>' for fid in pdp_ids)}
</div>
<div class="cap"><b>Figure 7.</b> Left to right, top to bottom: station temperature, precipitation (log&#8321;&#8320;), wind speed, NDVI, distance to sea, elevation.</div>

<h2>Cross heatmaps: unweighted vs. GREG-weighted</h2>

<div class="fig">{figs['f8']}</div>
<div class="cap"><b>Figure 8.</b> Mean residual, elevation &times; distance to sea. Neither axis is a GREG calibration variable, so a shift between panels is a clean signal of composition effects.</div>

<div class="fig">{figs['f9']}</div>
<div class="cap"><b>Figure 9.</b> Mean residual, station temperature &times; wind speed.</div>

<div class="fig">{figs['f10']}</div>
<div class="cap"><b>Figure 10.</b> Mean residual, distance to sea &times; DEGURBA class. Both axes are GREG calibration variables here &mdash; the weighted panel shows which cells dominate the corrected estimate, not whether the pattern itself changes.</div>

<div class="fig">{figs['f11a']}</div>
<div class="cap"><b>Figure 11a.</b> Elevation &times; distance to sea, colored by mean station temperature.</div>

<div class="fig">{figs['f11b']}</div>
<div class="cap"><b>Figure 11b.</b> Mean NDVI.</div>

<div class="fig">{figs['f11c']}</div>
<div class="cap"><b>Figure 11c.</b> Mean precipitation (log&#8321;&#8320;).</div>

<div class="fig">{figs['f11d']}</div>
<div class="cap"><b>Figure 11d.</b> Mean wind speed.</div>

<footer>Generated by scripts/build_poststrat_report.py from data2/residuals.parquet.</footer>

</main>
</body>
</html>
"""

OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
OUT_HTML.write_text(html, encoding="utf-8")
print(f"Wrote {OUT_HTML} ({OUT_HTML.stat().st_size / 1e6:.1f} MB)")
