import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import plotly.graph_objects as go
    import polars as pl
    import rasterio
    from plotly.subplots import make_subplots
    from pyproj import Transformer
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    from sklearn.linear_model import LinearRegression

    import itertools
    from era5_analysis import pdp

    return (
        LinearRegression,
        Path,
        Point,
        STRtree,
        Transformer,
        go,
        gpd,
        itertools,
        make_subplots,
        mo,
        np,
        pd,
        pdp,
        pl,
        px,
        rasterio,
    )


@app.cell
def _(Path):
    DATA = Path("/home2/lobib/gen_hack/data/main")
    DATA2 = Path("/home2/lobib/gen_hack/data2")
    DEGURBA_TIF = (
        DATA2
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0"
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    EUROPE_GPKG = DATA / "gadm_410_europe.gpkg"
    RESIDUALS_PARQUET = DATA2 / "residuals.parquet"

    # DEGURBA integer code → label (Water excluded from land analysis)
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
    # Land-only strata in urbanisation order
    DEGURBA_ORDER = [
        "Very low density rural",
        "Low density rural",
        "Rural cluster",
        "Suburban",
        "Semi-dense urban cluster",
        "Dense urban cluster",
        "Urban centre",
    ]

    # Shared plotly_white chart chrome: validated categorical + diverging colors
    PALETTE = {
        "blue": "#2a78d6",
        "orange": "#eb6834",
        "aqua": "#1baf7a",
        "yellow": "#eda100",
        "magenta": "#e87ba4",
        "green": "#008300",
        "violet": "#4a3aa7",
        "red": "#e34948",
    }
    GRID_COLOR = "#e1e0d9"
    AXIS_COLOR = "#c3c2b7"
    MUTED_INK = "#898781"
    return (
        AXIS_COLOR,
        DEGURBA_LABELS,
        DEGURBA_ORDER,
        DEGURBA_TIF,
        EUROPE_GPKG,
        GRID_COLOR,
        MUTED_INK,
        PALETTE,
        RESIDUALS_PARQUET,
    )


@app.cell
def _(RESIDUALS_PARQUET, pl):
    residuals_df = pl.read_parquet(RESIDUALS_PARQUET)

    # Filter to weather stations where dist_to_sea_km is accurate. dist_to_sea_km
    # is measured against gadm_410_europe.gpkg, which:
    #   - only covers Türkiye's European sliver (Thrace, lon <= 29.1) -- Anatolia
    #     is entirely absent, so mainland Turkish stations show inflated distances
    #   - only covers Russia west of lon ~69.07 -- far-eastern stations are
    #     measured against a landmass that doesn't reach them
    #   - excludes the Canary Islands (Spain, lon < -12) -- classified as African,
    #     not part of this "Europe" extract, so island stations show ~500km
    #   - excludes Israel and Greenland entirely -- not in the GADM file at all,
    #     so their stations are measured against the nearest unrelated landmass
    _n_before = residuals_df["STAID"].n_unique()
    residuals_df = residuals_df.filter(
        ~(
            ((pl.col("country") == "Türkiye") & (pl.col("lon") > 29.1))
            | ((pl.col("country") == "Russian Federation") & (pl.col("lon") > 69.07))
            | ((pl.col("country") == "Spain") & (pl.col("lon") < -12.0))
            | (pl.col("country") == "Israel")
            | (pl.col("country") == "Greenland")
        )
    )
    _n_after = residuals_df["STAID"].n_unique()
    print(
        f"Dropped {_n_before - _n_after} stations with unreliable dist_to_sea_km "
        "(Anatolian Türkiye, far-eastern Russia, Canary Islands, Israel, Greenland)"
    )
    return (residuals_df,)


@app.cell
def _(
    AXIS_COLOR,
    DEGURBA_ORDER,
    GRID_COLOR,
    MUTED_INK,
    PALETTE,
    go,
    mo,
    pl,
    residuals_df,
):
    station_df = residuals_df.group_by("STAID").agg(
        pl.col("residual").mean(),
        pl.col("elevation").first(),
        pl.col("dist_to_sea_km").first(),
        pl.col("degurba_label").first(),
        pl.col("degurba").first(),
        pl.col("ndvi").mean(),
        pl.col("lat").first(),
        pl.col("lon").first(),
        pl.col("country").first(),
        pl.len().alias("n_obs"),
    )
    print(f"Station-level dataframe: {len(station_df)} stations")

    _order = ["Water"] + DEGURBA_ORDER
    _colors = [PALETTE["blue"], PALETTE["orange"], PALETTE["aqua"], PALETTE["yellow"],
               PALETTE["magenta"], PALETTE["green"], PALETTE["violet"], PALETTE["red"]]
    _pct = station_df["degurba_label"].value_counts(normalize=True).to_pandas().set_index("degurba_label")["proportion"]
    _y = [float(_pct.get(lbl, 0.0)) for lbl in _order]

    fig_degurba_dist = go.Figure(
        go.Bar(
            x=_order,
            y=_y,
            marker_color=_colors,
            hovertemplate="%{x}<br>%{y:.2%}<extra></extra>",
        )
    )
    fig_degurba_dist.update_layout(
        template="plotly_white",
        title="Station distribution across DEGURBA classes",
        width=800,
        height=520,
        xaxis=dict(title="DEGURBA class", tickangle=-35, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK)),
        yaxis=dict(title="Share of stations", tickformat=".0%", gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK)),
        margin=dict(t=60, b=110),
    )
    mo.vstack([fig_degurba_dist])
    return (station_df,)


@app.cell
def _():
    return


@app.cell
def _():
    # residuals_df = pl.read_parquet(RESIDUALS_PARQUET).drop_nulls(
    #     subset=["residual", "degurba_label", "dist_to_sea_km", "elevation"]
    # )

    # # dist_to_sea_km is measured against a coastline built from gadm_410_europe.gpkg,
    # # which only partially covers two countries: Türkiye (European Thrace only,
    # # lon <= 29.1) and Russia (west of lon 69.07 only). Stations past those bounds
    # # sit outside the landmass geometry entirely, so their nearest-coastline
    # # distance doesn't reflect their real nearby coast (unreliable, often inflated).
    # _n_before = residuals_df["STAID"].n_unique()
    # residuals_df = residuals_df.filter(
    #     ~(
    #         ((pl.col("country") == "Türkiye") & (pl.col("lon") > 29.1))
    #         | ((pl.col("country") == "Russian Federation") & (pl.col("lon") > 69.07))
    #     )
    # )
    # _n_after = residuals_df["STAID"].n_unique()
    # print(
    #     f"Dropped {_n_before - _n_after} stations with unreliable dist_to_sea_km "
    #     "(Anatolian Türkiye / far-eastern Russia)"
    # )

    # print(
    #     f"Loaded {len(residuals_df):,} observations "
    #     f"· {residuals_df['STAID'].n_unique()} stations"
    # )

    # station_df = residuals_df.group_by("STAID").agg(
    #     pl.col("residual").mean(),
    #     pl.col("elevation").first(),
    #     pl.col("dist_to_sea_km").first(),
    #     pl.col("degurba_label").first(),
    #     pl.col("degurba").first(),
    #     pl.col("ndvi").mean(),
    #     pl.col("lat").first(),
    #     pl.col("lon").first(),
    #     pl.col("country").first(),
    #     pl.len().alias("n_obs"),
    # )
    # print(f"Station-level dataframe: {len(station_df)} stations")
    # print(station_df["degurba_label"].value_counts().sort("degurba_label"))
    return


@app.cell
def _(DEGURBA_LABELS, DEGURBA_ORDER, DEGURBA_TIF, Transformer, np, rasterio):
    """
    Crop the GHS-SMOD raster to the European bounding box (lon -15→35, lat 34→72),
    extract all non-nodata pixels, and compute the proportion of land pixels per
    DEGURBA class. Water pixels (class 10) are excluded from the land proportions.
    """
    _transformer = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
    _x_min, _y_min = _transformer.transform(-15.0, 34.0)
    _x_max, _y_max = _transformer.transform(35.0, 72.0)

    with rasterio.open(DEGURBA_TIF) as _src:
        from rasterio.windows import from_bounds as _from_bounds

        _win = _from_bounds(_x_min, _y_min, _x_max, _y_max, _src.transform)
        _win_int = _win.round_lengths().round_offsets()
        _data = _src.read(1, window=_win_int)
        _nodata = _src.nodata

    _flat = _data.flatten()
    _valid = _flat[_flat != _nodata].astype(int)
    print(f"Valid GHS pixels in European bbox: {len(_valid):,}")

    _unique_vals, _counts = np.unique(_valid, return_counts=True)
    _pixel_counts = dict(zip(_unique_vals.tolist(), _counts.tolist()))
    print("Pixel counts per class:")
    for _v, _c in sorted(_pixel_counts.items()):
        print(f"  {_v:2d}  {DEGURBA_LABELS.get(_v, '?'):30s}: {_c:>9,}")

    # Land-only proportions (exclude Water class 10)
    _land_counts = {k: v for k, v in _pixel_counts.items() if k != 10}
    _total_land = sum(_land_counts.values())
    pop_degurba = {
        DEGURBA_LABELS[k]: v / _total_land
        for k, v in _land_counts.items()
        if k in DEGURBA_LABELS
    }
    print("\nPopulation proportions (land only):")
    for _label in DEGURBA_ORDER:
        print(f"  {_label:30s}: {pop_degurba.get(_label, 0):.4f}")
    return (pop_degurba,)


@app.cell
def _(EUROPE_GPKG, Point, STRtree, gpd, np):
    """
    Sample 20,000 random points from the European land polygon (EPSG:3035),
    compute distance to coastline for each, and return a numpy array of km values.
    This constitutes the reference population distribution of dist_to_sea.
    """
    _N_SAMPLE = 20_000
    _RNG_SEED = 42

    print("Loading Europe polygon…")
    _europe_gdf = gpd.read_file(EUROPE_GPKG)
    _europe_3035 = _europe_gdf.dissolve().to_crs("EPSG:3035")
    _europe_geom = _europe_3035.geometry.iloc[0]

    print("Extracting and simplifying coastline…")
    _coastline = _europe_geom.boundary.simplify(1000)

    print(f"Sampling {_N_SAMPLE:,} random land points…")
    _rng = np.random.default_rng(_RNG_SEED)
    _minx, _miny, _maxx, _maxy = _europe_geom.bounds
    _pts = []
    _attempts = 0
    while len(_pts) < _N_SAMPLE:
        _bx = _rng.uniform(_minx, _maxx, _N_SAMPLE * 4)
        _by = _rng.uniform(_miny, _maxy, _N_SAMPLE * 4)
        _attempts += len(_bx)
        for _x, _y in zip(_bx, _by):
            if _europe_geom.contains(Point(_x, _y)):
                _pts.append((_x, _y))
                if len(_pts) >= _N_SAMPLE:
                    break
    print(f"  Accepted {len(_pts)} points from {_attempts:,} attempts")

    # STRtree on coastline segments (MultiLineString → iterate geoms)
    import shapely as _shapely
    _segments = list(_coastline.geoms) if _coastline.geom_type == "MultiLineString" else [_coastline]
    _tree = STRtree(_segments)
    _sample_pts = [Point(x, y) for x, y in _pts]
    _sample_arr = _shapely.from_wkt([p.wkt for p in _sample_pts])
    _nearest_idx = _tree.nearest(_sample_arr)
    _nearest_segs = np.array(_segments, dtype=object)[_nearest_idx]
    _dists_m = _shapely.distance(_sample_arr, _nearest_segs)
    ref_dist_to_sea_km = _dists_m / 1000.0
    print(
        f"Reference dist_to_sea: mean={ref_dist_to_sea_km.mean():.1f} km, "
        f"median={np.median(ref_dist_to_sea_km):.1f} km"
    )
    return (ref_dist_to_sea_km,)


@app.cell
def _(
    AXIS_COLOR,
    DEGURBA_ORDER,
    GRID_COLOR,
    MUTED_INK,
    PALETTE,
    go,
    mo,
    np,
    pl,
    pop_degurba,
    ref_dist_to_sea_km,
    station_df,
):
    """
    Three charts showing how weather stations differ from the true European
    land population:
      A) DEGURBA class distribution (stations vs. GHS-SMOD population)
      B) dist_to_sea distribution (stations vs. random land sample)
      C) Elevation distribution (stations only — no population DEM available)
    """
    _MAX_ROWS = 2499
    _axis_style = dict(
        gridcolor=GRID_COLOR,
        linecolor=AXIS_COLOR,
        tickfont=dict(color=MUTED_INK),
        title_font=dict(color=MUTED_INK),
    )
    _legend_style = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)

    # --- Panel A: DEGURBA grouped bar chart ---
    _n_total = len(station_df)
    _station_pct_map = (
        station_df
        .filter(pl.col("degurba_label") != "Water")
        .group_by("degurba_label")
        .agg(pl.len().alias("count"))
        .with_columns((pl.col("count") / _n_total).alias("station_pct"))
        .to_pandas()
        .set_index("degurba_label")["station_pct"]
        .to_dict()
    )
    _pop_pct = [pop_degurba.get(lbl, 0.0) for lbl in DEGURBA_ORDER]
    _station_pct = [_station_pct_map.get(lbl, 0.0) for lbl in DEGURBA_ORDER]

    fig_degurba = go.Figure()
    fig_degurba.add_bar(
        name="Stations",
        x=DEGURBA_ORDER,
        y=_station_pct,
        marker_color=PALETTE["blue"],
        hovertemplate="%{x}<br>Stations: %{y:.2%}<extra></extra>",
    )
    fig_degurba.add_bar(
        name="European land (GHS-SMOD)",
        x=DEGURBA_ORDER,
        y=_pop_pct,
        marker_color=PALETTE["orange"],
        hovertemplate="%{x}<br>Population: %{y:.2%}<extra></extra>",
    )
    fig_degurba.update_layout(
        template="plotly_white",
        title="A) DEGURBA class: stations vs. population",
        barmode="group",
        bargap=0.25,
        bargroupgap=0.05,
        height=340,
        legend=_legend_style,
        xaxis=dict(title="DEGURBA class", tickangle=-35, **_axis_style),
        yaxis=dict(title="Proportion", tickformat=".0%", **_axis_style),
        margin=dict(t=60, b=90),
    )

    # --- Panel B: dist_to_sea overlaid histograms ---
    _rng_b = np.random.default_rng(0)
    _station_dist = (
        station_df
        .select(["dist_to_sea_km"])
        .sample(n=min(_MAX_ROWS, len(station_df)), seed=0)
        .to_pandas()["dist_to_sea_km"]
        .clip(upper=800)
    )
    _ref_idx = _rng_b.choice(
        len(ref_dist_to_sea_km),
        size=min(_MAX_ROWS, len(ref_dist_to_sea_km)),
        replace=False,
    )
    _ref_dist = np.clip(ref_dist_to_sea_km[_ref_idx], None, 800)

    fig_dist = go.Figure()
    fig_dist.add_histogram(
        name="Stations",
        x=_station_dist,
        nbinsx=40,
        marker_color=PALETTE["blue"],
        opacity=0.55,
    )
    fig_dist.add_histogram(
        name="European land (random sample)",
        x=_ref_dist,
        nbinsx=40,
        marker_color=PALETTE["orange"],
        opacity=0.55,
    )
    fig_dist.update_layout(
        template="plotly_white",
        title="B) Distance to sea: stations vs. land sample",
        barmode="overlay",
        bargap=0.05,
        height=340,
        legend=_legend_style,
        xaxis=dict(title="Distance to sea (km, clipped at 800)", **_axis_style),
        yaxis=dict(title="Count", **_axis_style),
        margin=dict(t=60, b=60),
    )

    # --- Panel C: Elevation (stations only) ---
    _elev = (
        station_df
        .filter(pl.col("elevation") > -9000)
        .select(["elevation"])
        .sample(n=min(_MAX_ROWS, len(station_df)), seed=0)
        .to_pandas()["elevation"]
    )

    fig_elev = go.Figure()
    fig_elev.add_histogram(
        x=_elev,
        nbinsx=40,
        marker_color=PALETTE["blue"],
        showlegend=False,
        hovertemplate="Elevation: %{x} m<br>Count: %{y}<extra></extra>",
    )
    fig_elev.update_layout(
        template="plotly_white",
        title="C) Elevation: stations only (no population DEM reference)",
        bargap=0.05,
        height=320,
        xaxis=dict(title="Elevation (m)", **_axis_style),
        yaxis=dict(title="Count", **_axis_style),
        margin=dict(t=60, b=60),
    )

    mo.vstack([
        mo.md(
            "## Representativeness Analysis\n\n"
            "Weather stations are **not** a random sample of European land. "
            "Panel A shows suburban and low-density rural classes are over-represented "
            "relative to the GHS-SMOD land pixel distribution. "
            "Panel B confirms stations cluster close to coasts. "
            "These biases motivate post-stratification and GREG weighting."
        ),
        fig_degurba,
        fig_dist,
        fig_elev,
    ])
    return


@app.cell
def _(DEGURBA_ORDER, mo, pl, pop_degurba, station_df):
    """
    Post-stratified estimator (Lehalle 2023 / Zhang 2000):
        ȳ_PS = Σ_s  p_s^{pop} · ȳ_s

    where p_s^{pop} is the GHS-SMOD land proportion and ȳ_s is the mean
    residual among stations in stratum s.

    Per-station weight: w_s = p_s^{pop} / p_s^{sample}
    """
    # Exclude water stations from land analysis
    _station_land = station_df.filter(pl.col("degurba_label") != "Water")
    _n_stations = len(_station_land)

    _sample_counts = (
        _station_land
        .group_by("degurba_label")
        .agg(pl.len().alias("n_s"))
        .to_pandas()
        .set_index("degurba_label")["n_s"]
        .to_dict()
    )

    _stratum_means = (
        _station_land
        .group_by("degurba_label")
        .agg(pl.col("residual").mean().alias("mean_resid"))
        .to_pandas()
        .set_index("degurba_label")["mean_resid"]
        .to_dict()
    )

    # Naive unweighted mean and post-stratified mean
    y_naive = float(_station_land["residual"].mean())
    y_poststrat = sum(
        pop_degurba.get(s, 0.0) * _stratum_means.get(s, 0.0)
        for s in DEGURBA_ORDER
    )

    # Per-stratum weights
    strata_weights = {}
    for _s in DEGURBA_ORDER:
        _p_pop = pop_degurba.get(_s, 0.0)
        _p_sample = _sample_counts.get(_s, 0) / _n_stations
        strata_weights[_s] = _p_pop / _p_sample if _p_sample > 0 else 0.0

    # Attach per-station weights
    _weight_map = pl.DataFrame({
        "degurba_label": list(strata_weights.keys()),
        "ps_weight": list(strata_weights.values()),
    })
    station_df_weighted = _station_land.join(_weight_map, on="degurba_label", how="left")

    print(f"Naive mean residual:           {y_naive:+.4f} °C")
    print(f"Post-stratified mean residual: {y_poststrat:+.4f} °C")
    print(f"Correction:                    {y_poststrat - y_naive:+.4f} °C")
    print()
    print(f"{'Stratum':35s} {'p_pop':>7} {'p_sample':>9} {'weight':>7} {'ȳ_s':>8} {'n_s':>6}")
    for _s in DEGURBA_ORDER:
        _pp = pop_degurba.get(_s, 0.0)
        _ps = _sample_counts.get(_s, 0) / _n_stations
        _w = strata_weights[_s]
        _ym = _stratum_means.get(_s, float("nan"))
        _n = _sample_counts.get(_s, 0)
        print(f"  {_s:33s} {_pp:7.4f} {_ps:9.4f} {_w:7.4f} {_ym:8.4f} {_n:6d}")

    mo.md(f"""
    ### Post-stratification by DEGURBA class

    | Estimator | Mean residual (°C) |
    |-----------|-------------------|
    | Naive (unweighted station mean) | **{y_naive:+.4f}** |
    | Post-stratified (DEGURBA weights) | **{y_poststrat:+.4f}** |
    | Correction | **{y_poststrat - y_naive:+.4f}** |

    Post-stratification re-weights each stratum so the weighted sample matches the
    GHS-SMOD land pixel distribution. Strata with more land pixels than station
    coverage receive higher weights.
    """)
    return station_df_weighted, strata_weights, y_naive, y_poststrat


@app.cell
def _(
    DEGURBA_ORDER,
    LinearRegression,
    mo,
    np,
    pd,
    pl,
    pop_degurba,
    ref_dist_to_sea_km,
    station_df_weighted,
    y_naive,
):
    """
    GREG (generalised regression) calibration following Zhang (2000):

        ŷ_GREG = ȳ + (X̄_pop − x̄_sample)ᵀ β̂

    Auxiliary variables x_i:
      • One-hot encoding of DEGURBA class (7 dummies)
      • dist_to_sea_km standardised to zero mean / unit variance

    Population means X̄_pop:
      • DEGURBA: from GHS-SMOD land pixel proportions
      • dist_to_sea: mean of the 20k random European land sample

    Per-station calibration weight (Zhang 2000 eq. 2.3):
        w_i = 1 + (X̄_pop − x̄_sample)ᵀ V̂⁻¹ x_i
    """
    _station_pd = station_df_weighted.to_pandas()

    # Design matrix
    _dummies = pd.get_dummies(
        _station_pd["degurba_label"].astype(
            pd.CategoricalDtype(DEGURBA_ORDER)
        ),
        prefix="deg",
        dtype=float,
    )
    _dist_mean = _station_pd["dist_to_sea_km"].mean()
    _dist_std = _station_pd["dist_to_sea_km"].std()
    _dist_std_col = (_station_pd["dist_to_sea_km"] - _dist_mean) / _dist_std
    _X_sample = np.hstack([_dummies.values, _dist_std_col.values.reshape(-1, 1)])
    _y_sample = _station_pd["residual"].values

    # Population means for each auxiliary variable
    _pop_deg_means = np.array([pop_degurba.get(s, 0.0) for s in DEGURBA_ORDER])
    _pop_dist_std_mean = (ref_dist_to_sea_km.mean() - _dist_mean) / _dist_std
    _X_pop_bar = np.concatenate([_pop_deg_means, [_pop_dist_std_mean]])
    _x_bar_sample = _X_sample.mean(axis=0)

    # WLS regression weighted by n_obs (more observations = more reliable station mean)
    _n_obs_weights = _station_pd["n_obs"].values.astype(float)
    _reg = LinearRegression(fit_intercept=False)
    _reg.fit(_X_sample, _y_sample, sample_weight=_n_obs_weights)
    _beta = _reg.coef_

    # GREG point estimate
    y_greg = float(y_naive + (_X_pop_bar - _x_bar_sample) @ _beta)

    # Per-station calibration weights: w_i = 1 + (X̄_pop − x̄)ᵀ V̂⁻¹ x_i
    _V_hat = (_X_sample.T @ _X_sample) / len(_X_sample)
    _V_hat_reg = _V_hat + 1e-8 * np.eye(_V_hat.shape[0])
    _diff = _X_pop_bar - _x_bar_sample
    _greg_weights_raw = 1.0 + _X_sample @ np.linalg.solve(_V_hat_reg, _diff)

    station_df_greg = station_df_weighted.with_columns(
        pl.Series("greg_weight", _greg_weights_raw.tolist())
    )

    print(f"Naive mean:          {y_naive:+.4f} °C")
    print(f"GREG mean:           {y_greg:+.4f} °C")
    print(f"Correction vs naive: {y_greg - y_naive:+.4f} °C")
    print(f"\nGREG β̂:")
    for _col, _b in zip(list(_dummies.columns) + ["dist_std"], _beta):
        print(f"  {_col:35s}: {_b:+.4f}")

    mo.md(f"""
    ### GREG Calibration (DEGURBA + distance to sea)

    $$\\hat{{y}}_{{GREG}} = \\bar{{y}} + (\\bar{{X}}_{{pop}} - \\bar{{x}}_{{sample}})^\\top \\hat{{\\beta}}$$

    | Estimator | Mean residual (°C) |
    |-----------|-------------------|
    | Naive | **{y_naive:+.4f}** |
    | GREG (DEGURBA + dist_to_sea) | **{y_greg:+.4f}** |

    Population mean dist_to_sea (reference): **{ref_dist_to_sea_km.mean():.1f} km**
    Sample mean dist_to_sea (stations): **{_dist_mean:.1f} km**

    Stations are on average closer to the coast than the European land average,
    so the GREG correction adjusts for this spatial concentration bias.
    """)
    return station_df_greg, y_greg


@app.cell
def _(
    DEGURBA_ORDER,
    LinearRegression,
    mo,
    np,
    pd,
    pop_degurba,
    ref_dist_to_sea_km,
    station_df_greg,
    y_greg,
    y_naive,
    y_poststrat,
):
    """
    Bootstrap (B=1000) by resampling stations with replacement.
    Provides 95% percentile CIs for naive, post-stratified, and GREG estimators.
    """
    _B = 1000
    _ALPHA = 0.05
    _RNG_SEED = 0

    _station_pd_bs = station_df_greg.to_pandas().copy()
    _n = len(_station_pd_bs)
    _rng = np.random.default_rng(_RNG_SEED)

    # Pre-compute dist_to_sea standardisation constants (keep consistent with cell 8)
    _dist_mean_bs = _station_pd_bs["dist_to_sea_km"].mean()
    _dist_std_bs = _station_pd_bs["dist_to_sea_km"].std()
    _pop_dist_std_mean_bs = (ref_dist_to_sea_km.mean() - _dist_mean_bs) / _dist_std_bs
    _pop_deg_means_bs = np.array([pop_degurba.get(s, 0.0) for s in DEGURBA_ORDER])

    _boot_naive = np.empty(_B)
    _boot_ps = np.empty(_B)
    _boot_greg = np.empty(_B)

    for _b in range(_B):
        _idx = _rng.integers(0, _n, size=_n)
        _s = _station_pd_bs.iloc[_idx]

        # Naive
        _boot_naive[_b] = _s["residual"].mean()

        # Post-stratified
        _ps_val = 0.0
        for _stratum in DEGURBA_ORDER:
            _rows = _s[_s["degurba_label"] == _stratum]
            if len(_rows) > 0:
                _ps_val += pop_degurba.get(_stratum, 0.0) * _rows["residual"].mean()
        _boot_ps[_b] = _ps_val

        # GREG
        _dummies_b = pd.get_dummies(
            _s["degurba_label"].astype(pd.CategoricalDtype(DEGURBA_ORDER)),
            prefix="deg",
            dtype=float,
        )
        _dist_std_b = (_s["dist_to_sea_km"] - _dist_mean_bs) / _dist_std_bs
        _Xb = np.hstack([_dummies_b.values, _dist_std_b.values.reshape(-1, 1)])
        _yb = _s["residual"].values
        _wb = _s["n_obs"].values.astype(float)
        _X_pop_b = np.concatenate([_pop_deg_means_bs, [_pop_dist_std_mean_bs]])
        _x_bar_b = _Xb.mean(axis=0)
        _reg_b = LinearRegression(fit_intercept=False)
        _reg_b.fit(_Xb, _yb, sample_weight=_wb)
        _boot_greg[_b] = _boot_naive[_b] + (_X_pop_b - _x_bar_b) @ _reg_b.coef_

    _ci_naive = np.percentile(_boot_naive, [100 * _ALPHA / 2, 100 * (1 - _ALPHA / 2)])
    _ci_ps = np.percentile(_boot_ps, [100 * _ALPHA / 2, 100 * (1 - _ALPHA / 2)])
    _ci_greg = np.percentile(_boot_greg, [100 * _ALPHA / 2, 100 * (1 - _ALPHA / 2)])

    bootstrap_results = {
        "Naive": {
            "mean": float(y_naive),
            "ci_lo": float(_ci_naive[0]),
            "ci_hi": float(_ci_naive[1]),
        },
        "Post-stratified": {
            "mean": float(y_poststrat),
            "ci_lo": float(_ci_ps[0]),
            "ci_hi": float(_ci_ps[1]),
        },
        "GREG": {
            "mean": float(y_greg),
            "ci_lo": float(_ci_greg[0]),
            "ci_hi": float(_ci_greg[1]),
        },
    }

    print("Bootstrap 95% CIs (B=1000, station-level resampling):")
    for _est, _vals in bootstrap_results.items():
        print(
            f"  {_est:20s}: {_vals['mean']:+.4f}  "
            f"95% CI [{_vals['ci_lo']:+.4f}, {_vals['ci_hi']:+.4f}]"
        )

    mo.md(f"""
    ### Bootstrap Confidence Intervals (B=1,000, station resampling)

    | Estimator | Mean (°C) | 95% CI |
    |-----------|-----------|--------|
    | Naive | **{y_naive:+.4f}** | [{_ci_naive[0]:+.4f}, {_ci_naive[1]:+.4f}] |
    | Post-stratified | **{y_poststrat:+.4f}** | [{_ci_ps[0]:+.4f}, {_ci_ps[1]:+.4f}] |
    | GREG | **{y_greg:+.4f}** | [{_ci_greg[0]:+.4f}, {_ci_greg[1]:+.4f}] |

    **Interpretation**: A positive residual means *station > ERA5*, i.e. ERA5
    under-estimates surface temperature. Post-stratification and GREG correct for the
    over-representation of suburban and near-coast stations.
    """)
    return (bootstrap_results,)


@app.cell
def _(
    AXIS_COLOR,
    GRID_COLOR,
    MUTED_INK,
    PALETTE,
    bootstrap_results,
    go,
    mo,
    np,
    station_df_greg,
):
    """
    Visual summary of point estimates and 95% bootstrap CIs.
    Also reports effective sample size for each estimator.
    """
    _est_order = ["Naive", "Post-stratified", "GREG"]
    _colors = [PALETTE["blue"], PALETTE["orange"], PALETTE["aqua"]]
    _means = [bootstrap_results[e]["mean"] for e in _est_order]
    _ci_lo = [bootstrap_results[e]["ci_lo"] for e in _est_order]
    _ci_hi = [bootstrap_results[e]["ci_hi"] for e in _est_order]
    _err_plus = [hi - m for hi, m in zip(_ci_hi, _means)]
    _err_minus = [m - lo for m, lo in zip(_means, _ci_lo)]

    results_chart = go.Figure(
        go.Bar(
            x=_est_order,
            y=_means,
            marker_color=_colors,
            width=0.5,
            error_y=dict(
                type="data",
                symmetric=False,
                array=_err_plus,
                arrayminus=_err_minus,
                color=MUTED_INK,
                thickness=1.5,
                width=6,
            ),
            hovertemplate="%{x}<br>mean %{y:+.4f}<extra></extra>",
        )
    )
    results_chart.update_layout(
        template="plotly_white",
        title="ERA5 temperature bias estimates with 95% bootstrap CI",
        showlegend=False,
        height=380,
        width=420,
        xaxis=dict(title=None, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK, size=13)),
        yaxis=dict(
            title="Mean residual (°C)",
            gridcolor=GRID_COLOR,
            linecolor=AXIS_COLOR,
            tickfont=dict(color=MUTED_INK),
            title_font=dict(color=MUTED_INK),
            zeroline=False,
        ),
        margin=dict(t=60, b=40),
    )

    # Effective sample size: n_eff = (Σ w_i)² / Σ w_i²
    def _eff_n(w: np.ndarray) -> float:
        return float(w.sum() ** 2 / (w ** 2).sum())

    _ps_w = station_df_greg["ps_weight"].to_numpy()
    _gr_w = station_df_greg["greg_weight"].to_numpy()
    _n_total = len(_ps_w)
    _n_eff_ps = _eff_n(_ps_w)
    _n_eff_gr = _eff_n(_gr_w)

    print(f"n               : {_n_total}")
    print(f"n_eff (post-strat): {_n_eff_ps:.0f}  ({100*_n_eff_ps/_n_total:.1f}% of n)")
    print(f"n_eff (GREG)      : {_n_eff_gr:.0f}  ({100*_n_eff_gr/_n_total:.1f}% of n)")

    mo.vstack([
        results_chart,
        mo.md(f"""
    | Estimator | n stations | n_eff |
    |-----------|-----------|-------|
    | Naive | {_n_total} | {_n_total} (100%) |
    | Post-stratified | {_n_total} | {_n_eff_ps:.0f} ({100*_n_eff_ps/_n_total:.1f}%) |
    | GREG | {_n_total} | {_n_eff_gr:.0f} ({100*_n_eff_gr/_n_total:.1f}%) |

    n_eff decreases when weights are unequal. Upweighted strata contribute more
    variance, which is the price of correcting the sampling bias.
        """),
    ])
    return


@app.cell
def _(
    AXIS_COLOR,
    DEGURBA_ORDER,
    GRID_COLOR,
    MUTED_INK,
    PALETTE,
    go,
    mo,
    pop_degurba,
    strata_weights,
):
    """
    Two charts:
      1) Grouped bar: population proportion vs station proportion per stratum
      2) Bar chart of post-stratification weights w_s with w=1 reference line
    """
    _axis_style = dict(
        gridcolor=GRID_COLOR,
        linecolor=AXIS_COLOR,
        tickfont=dict(color=MUTED_INK),
        title_font=dict(color=MUTED_INK),
    )
    _legend_style = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)

    _p_pop = [pop_degurba.get(s, 0.0) for s in DEGURBA_ORDER]
    _weights = [strata_weights.get(s, 0.0) for s in DEGURBA_ORDER]
    _p_sample = [pp / w if w > 0 else 0.0 for pp, w in zip(_p_pop, _weights)]

    # Chart 1: population vs sample proportions
    fig_prop = go.Figure()
    fig_prop.add_bar(
        name="GHS population",
        x=DEGURBA_ORDER,
        y=_p_pop,
        marker_color=PALETTE["blue"],
        hovertemplate="%{x}<br>Population: %{y:.2%}<extra></extra>",
    )
    fig_prop.add_bar(
        name="Station sample",
        x=DEGURBA_ORDER,
        y=_p_sample,
        marker_color=PALETTE["orange"],
        hovertemplate="%{x}<br>Stations: %{y:.2%}<extra></extra>",
    )
    fig_prop.update_layout(
        template="plotly_white",
        title="Population vs. sample proportions per DEGURBA class",
        barmode="group",
        bargap=0.25,
        bargroupgap=0.05,
        height=340,
        legend=_legend_style,
        xaxis=dict(title="DEGURBA class", tickangle=-35, **_axis_style),
        yaxis=dict(title="Proportion", tickformat=".0%", **_axis_style),
        margin=dict(t=60, b=90),
    )

    # Chart 2: weights, colored by over-/under-representation, w=1 reference line
    _bar_colors = [PALETTE["red"] if w > 1.0 else PALETTE["blue"] for w in _weights]
    fig_weights = go.Figure()
    fig_weights.add_bar(
        x=DEGURBA_ORDER,
        y=_weights,
        marker_color=_bar_colors,
        showlegend=False,
        customdata=list(zip(_p_pop, _p_sample)),
        hovertemplate=(
            "%{x}<br>weight %{y:.3f}<br>p_pop %{customdata[0]:.3f}"
            "<br>p_sample %{customdata[1]:.3f}<extra></extra>"
        ),
    )
    fig_weights.add_hline(
        y=1.0,
        line_dash="dash",
        line_color=MUTED_INK,
        opacity=0.8,
        annotation_text="w = 1",
        annotation_position="top right",
        annotation_font_color=MUTED_INK,
    )
    fig_weights.update_layout(
        template="plotly_white",
        title="Post-stratification weights (w_s = p_pop / p_sample)",
        bargap=0.25,
        height=340,
        xaxis=dict(title="DEGURBA class", tickangle=-35, **_axis_style),
        yaxis=dict(title="Post-stratification weight w_s", rangemode="tozero", **_axis_style),
        margin=dict(t=60, b=90),
    )

    mo.vstack([
        mo.md("""## Weight Analysis

    **Blue bars** (w < 1): stratum is over-represented in stations — downweighted.
    **Red bars** (w > 1): stratum is under-represented — upweighted.
    A perfectly representative sample would have w = 1 for all strata (dashed line).
        """),
        fig_prop,
        fig_weights,
    ])
    return


@app.cell
def _(PALETTE, mo, px, station_df_greg):
    """
    Plotly scatter_map coloured by post-stratification weight.
    High-weight stations (red) belong to under-represented strata and receive
    more weight in the corrected estimator; their geographic pattern reveals
    where the station network is thin relative to the land population.
    """
    _map_pd = station_df_greg.select(
        ["lat", "lon", "ps_weight", "degurba_label", "residual", "country", "STAID"]
    ).to_pandas()

    _diverging_scale = [
        [0.0, PALETTE["blue"]],
        [0.5, "#f0efec"],
        [1.0, PALETTE["red"]],
    ]

    _fig = px.scatter_map(
        _map_pd,
        lat="lat",
        lon="lon",
        color="ps_weight",
        color_continuous_scale=_diverging_scale,
        color_continuous_midpoint=1.0,
        zoom=3,
        center={"lat": 50, "lon": 10},
        hover_data={
            "STAID": True,
            "degurba_label": True,
            "country": True,
            "ps_weight": ":.3f",
            "residual": ":.3f",
        },
        title="Post-stratification weight per station — red = under-represented stratum",
    )
    _fig.update_traces(marker=dict(size=6, opacity=0.8))
    _fig.update_layout(
        height=700,
        template="plotly_white",
        coloraxis_colorbar=dict(title="w_s", tickformat=".2f"),
    )

    mo.vstack([
        mo.md("""## Geographic Pattern of the Sampling Correction

    Stations in very-low-density rural and urban-centre areas receive the highest
    weights (red) because those land types are under-represented in the station
    network. Dense suburban clusters (blue) are downweighted. The spatial pattern
    of weights reveals which parts of Europe are statistically thin relative to
    their land area in the GHS-SMOD reference.
        """),
        _fig,
    ])
    return


@app.cell
def _(residuals_df, station_df_greg):
    """
    Attach each station's ps_weight / greg_weight onto the observation-level
    residuals_df, so the PDPs and cross-heatmaps below can compare an unweighted
    mean against the population-representative (GREG-calibrated) mean.

    Inner join: station_df_greg only has land stations (Water excluded during
    post-stratification), so Water-labelled stations drop out of this weighted
    view — consistent with the rest of this notebook's land-only scope.
    """
    residuals_df_weighted = residuals_df.join(
        station_df_greg.select(["STAID", "ps_weight", "greg_weight"]),
        on="STAID",
        how="inner",
    )
    print(
        f"{len(residuals_df_weighted):,} rows with weights attached "
        f"({residuals_df_weighted['STAID'].n_unique()} stations)"
    )
    return (residuals_df_weighted,)


@app.cell
def _(AXIS_COLOR, GRID_COLOR, MUTED_INK, PALETTE, go, np, pdp):
    """
    PDP: mean residual vs. a binned covariate, cluster-bootstrap 95% CI band.
    Overlays the unweighted (raw sample) curve against the GREG-weighted
    (population-representative) curve, plus a raw-value histogram below.
    """
    def _hex_to_rgba(hex_color, alpha):
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return f"rgba({r},{g},{b},{alpha})"

    def make_pdp_and_hist(df, feature, xlabel, n_bins=10, hist_bins=50, log10=False, weight_col="greg_weight"):
        import polars as _pl

        _df = df
        if log10:
            _df = _df.with_columns(_pl.col(feature).clip(lower_bound=1e-9).log(base=10).alias(feature))

        df_binned, bins = pdp.bin_features(_df, feature, n_bins=n_bins)
        means_u, lo_u, hi_u = pdp.pdp_cluster_bootstrap(df_binned, "bin", bins, rng=np.random.default_rng(1337))
        means_w, lo_w, hi_w = pdp.pdp_cluster_bootstrap(
            df_binned, "bin", bins, rng=np.random.default_rng(1337), weight_col=weight_col
        )
        centers = pdp.bin_centers(bins, df_binned[feature].min(), df_binned[feature].max())
        _xlabel = f"{xlabel} (log₁₀)" if log10 else xlabel

        fig = go.Figure()
        for _name, _means, _lo, _hi, _color in [
            ("Unweighted", means_u, lo_u, hi_u, PALETTE["blue"]),
            ("GREG-weighted", means_w, lo_w, hi_w, PALETTE["orange"]),
        ]:
            fig.add_scatter(
                x=centers + centers[::-1], y=list(_hi) + list(_lo[::-1]),
                fill="toself", fillcolor=_hex_to_rgba(_color, 0.15),
                line=dict(color="rgba(255,255,255,0)"), hoverinfo="skip", showlegend=False,
            )
            fig.add_scatter(
                x=centers, y=_means, mode="lines+markers", name=_name,
                line=dict(color=_color, width=2), marker=dict(size=7),
                hovertemplate=f"{_name}<br>{_xlabel}: %{{x:.3g}}<br>mean residual: %{{y:.3f}}<extra></extra>",
            )
        fig.add_hline(y=0, line_dash="dash", line_color=MUTED_INK, opacity=0.6)
        fig.update_layout(
            template="plotly_white",
            title=f"PDP: residual vs {xlabel}",
            height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            xaxis=dict(title=_xlabel, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK)),
            yaxis=dict(title="Mean residual (°C)", gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK)),
            margin=dict(t=60, b=50),
        )

        _series = _df[feature].drop_nulls()
        _sample = _series.sample(n=min(4999, _series.len()), seed=42)
        hist = go.Figure(go.Histogram(
            x=_sample.to_numpy(), nbinsx=hist_bins, marker_color=PALETTE["blue"], opacity=0.6, showlegend=False
        ))
        hist.update_layout(
            template="plotly_white",
            height=140,
            xaxis=dict(title=_xlabel, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK)),
            yaxis=dict(title="Count", gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK), title_font=dict(color=MUTED_INK)),
            margin=dict(t=10, b=50),
        )
        return fig, hist

    return (make_pdp_and_hist,)


@app.cell
def _(make_pdp_and_hist, mo, residuals_df_weighted):
    _specs = [
        ("station_celsius", "Station temp (°C)", False),
        ("tp", "Precipitation (m/day)", True),
        ("wind", "Wind speed (m/s)", False),
        ("ndvi", "NDVI", False),
        ("dist_to_sea_km", "Distance to sea (km)", False),
        ("elevation", "Elevation (m)", False),
    ]
    _blocks = []
    for _feature, _label, _log10 in _specs:
        _fig, _hist = make_pdp_and_hist(residuals_df_weighted, _feature, _label, log10=_log10)
        _blocks.extend([_fig, _hist])

    mo.vstack([
        mo.md(
            "## Partial Dependence Plots: Unweighted vs. GREG-Weighted\n\n"
            "Each panel overlays the raw (unweighted) mean residual per bin against "
            "the GREG-weighted mean, which reweights each observation toward the "
            "population-representative DEGURBA + distance-to-sea mix. Where the two "
            "curves track closely, the pattern is unlikely to be an artifact of "
            "station-network composition."
        ),
        *_blocks,
    ])
    return


@app.cell
def _(
    AXIS_COLOR,
    GRID_COLOR,
    MUTED_INK,
    PALETTE,
    go,
    itertools,
    make_subplots,
    np,
    pd,
    pdp,
):
    """
    2D binned heatmap over two continuous covariates, colored by a third variable
    (default: residual). Returns a side-by-side unweighted vs. GREG-weighted
    figure on a shared color scale, so the two panels are directly comparable.

    color_feat defaults to "residual" (diverging blue/red around 0). Pass a
    different color_feat for e.g. "mean NDVI per elevation x dist_to_sea cell";
    such magnitude variables should use diverging=False with a sequential scale.
    log10_color matches this codebase's existing convention of log10-transforming
    "tp" (precipitation) before averaging, since it's heavily right-skewed --
    pass it whenever color_feat is similarly skewed.
    """
    def make_cross_heatmap(
        df, feat_x, feat_y, xlabel, ylabel, n_bins=8, weight_col="greg_weight",
        color_feat="residual", color_title=None, diverging=True, sequential_hue="red",
        log10_color=False,
    ):
        import polars as _pl

        _df = df
        if log10_color:
            _df = _df.with_columns(_pl.col(color_feat).clip(lower_bound=1e-9).log(base=10).alias(color_feat))
        color_title = color_title or ("Mean residual (°C)" if color_feat == "residual" else f"Mean {color_feat}")
        if log10_color:
            color_title = f"{color_title} (log₁₀)"

        _df, bins_x = pdp.bin_features(_df, feat_x, n_bins=n_bins)
        _df = _df.rename({"bin": "bin_x"})
        _df, bins_y = pdp.bin_features(_df, feat_y, n_bins=n_bins)
        _df = _df.rename({"bin": "bin_y"})

        def _parse_edges(bins, dmin, dmax):
            out = []
            for b in bins:
                lo, hi = b.strip("(]").split(", ")
                out.append((dmin if lo == "-inf" else float(lo), dmax if hi == "inf" else float(hi)))
            return out

        edges_x = _parse_edges(bins_x, float(_df[feat_x].min()), float(_df[feat_x].max()))
        edges_y = _parse_edges(bins_y, float(_df[feat_y].min()), float(_df[feat_y].max()))
        x_labels = [f"{lo:.3g}–{hi:.3g}" for lo, hi in edges_x]
        y_labels = [f"{lo:.3g}–{hi:.3g}" for lo, hi in edges_y]

        full_grid = pd.DataFrame(list(itertools.product(bins_x, bins_y)), columns=["bin_x", "bin_y"])

        def _grid(weight):
            if weight is None:
                agg = _df.group_by(["bin_x", "bin_y"]).agg(_pl.col(color_feat).mean().alias("v"))
            else:
                agg = _df.group_by(["bin_x", "bin_y"]).agg(
                    ((_pl.col(color_feat) * _pl.col(weight)).sum() / _pl.col(weight).sum()).alias("v")
                )
            heat = full_grid.merge(agg.to_pandas(), on=["bin_x", "bin_y"], how="left")
            z = heat.pivot(index="bin_y", columns="bin_x", values="v").reindex(index=bins_y, columns=bins_x)
            return z.to_numpy()

        z_u = _grid(None)
        z_w = _grid(weight_col)
        _all = np.concatenate([z_u.flatten(), z_w.flatten()])

        if diverging:
            abs_max = np.nanmax(np.abs(_all))
            zmin, zmax = -abs_max, abs_max
            scale = [[0.0, PALETTE["blue"]], [0.5, "#f0efec"], [1.0, PALETTE["red"]]]
        else:
            zmin, zmax = float(np.nanmin(_all)), float(np.nanmax(_all))
            scale = [[0.0, "#fcfcfb"], [1.0, PALETTE[sequential_hue]]]

        fig = make_subplots(rows=1, cols=2, subplot_titles=["Unweighted", "GREG-weighted"], horizontal_spacing=0.15)
        for _col, _z in enumerate([z_u, z_w], start=1):
            fig.add_trace(
                go.Heatmap(
                    z=_z, x=x_labels, y=y_labels, zmin=zmin, zmax=zmax, colorscale=scale,
                    showscale=(_col == 2), colorbar=dict(title=color_title) if _col == 2 else None,
                    hovertemplate=f"{xlabel}: %{{x}}<br>{ylabel}: %{{y}}<br>{color_title}: %{{z:.3f}}<extra></extra>",
                ),
                row=1, col=_col,
            )
        fig.update_layout(
            template="plotly_white", height=420, width=900,
            title=f"{color_title} — {xlabel} × {ylabel}",
            margin=dict(t=70, b=90),
        )
        fig.update_xaxes(title=xlabel, tickangle=-40, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))
        fig.update_yaxes(title=ylabel, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))
        return fig

    return (make_cross_heatmap,)


@app.cell
def _(make_cross_heatmap, mo, residuals_df_weighted):
    _fig_a = make_cross_heatmap(residuals_df_weighted, "elevation", "dist_to_sea_km", "Elevation (m)", "Distance to sea (km)")
    _fig_b = make_cross_heatmap(residuals_df_weighted, "station_celsius", "wind", "Station temp (°C)", "Wind speed (m/s)")

    mo.vstack([
        mo.md(
            "## Cross Heatmaps: Unweighted vs. GREG-Weighted\n\n"
            "Same idea as the PDPs, in two dimensions. Neither axis below is a GREG "
            "calibration variable, so a shift between panels is a clean signal that "
            "station-network composition was affecting the raw pattern."
        ),
        _fig_a,
        _fig_b,
    ])
    return


@app.cell
def _(make_cross_heatmap, mo, residuals_df_weighted):
    """
    Same elevation x dist_to_sea grid as resid_analysis.py's 2x2 covariate panel,
    but colored by 4 different covariates instead of residual, each shown
    unweighted vs. GREG-weighted. Precipitation is log10'd before averaging,
    matching how it's treated everywhere else in this codebase (heavily
    right-skewed); the other three stay linear, same as resid_analysis.py.
    """
    _kw = dict(df=residuals_df_weighted, feat_x="elevation", feat_y="dist_to_sea_km",
               xlabel="Elevation (m)", ylabel="Distance to sea (km)", diverging=False)

    _fig_temp = make_cross_heatmap(**_kw, color_feat="station_celsius", sequential_hue="orange")
    _fig_ndvi = make_cross_heatmap(**_kw, color_feat="ndvi", sequential_hue="green")
    _fig_tp = make_cross_heatmap(**_kw, color_feat="tp", sequential_hue="blue", log10_color=True)
    _fig_wind = make_cross_heatmap(**_kw, color_feat="wind", sequential_hue="violet")

    mo.vstack([
        mo.md(
            "## Elevation × Distance to Sea, by Covariate: Unweighted vs. GREG-Weighted\n\n"
            "Same axes as the first heatmap above, but colored by mean station "
            "temperature, NDVI, precipitation (log₁₀), and wind speed instead of "
            "residual. These answer a different question than the residual "
            "heatmaps -- not \"is ERA5 biased here\" but \"what does this part of "
            "the covariate space actually look like\" -- and the same "
            "representativeness argument applies: a cell's raw mean can be skewed "
            "by which DEGURBA classes happen to be sampled within it."
        ),
        _fig_temp,
        _fig_ndvi,
        _fig_tp,
        _fig_wind,
    ])
    return


@app.cell
def _(
    AXIS_COLOR,
    DEGURBA_ORDER,
    GRID_COLOR,
    MUTED_INK,
    PALETTE,
    go,
    itertools,
    make_subplots,
    mo,
    np,
    pd,
    pdp,
    pl,
    residuals_df_weighted,
):
    """
    Mean residual by distance-to-sea bin (x) x DEGURBA class (y), unweighted vs.
    GREG-weighted.

    Caveat: both axes here are exactly what GREG calibrates on, so the weighted
    panel answers "which cells dominate the corrected national estimate", not
    "does the pattern change" -- that question is only clean when neither axis
    is a calibration variable, as in the two panels above.
    """
    _df = residuals_df_weighted.filter(pl.col("degurba_label").is_in(DEGURBA_ORDER))
    _df, _bins_dist = pdp.bin_features(_df, "dist_to_sea_km", n_bins=8)
    _df = _df.rename({"bin": "bin_dist"})

    def _parse(bins, dmin, dmax):
        out = []
        for b in bins:
            lo, hi = b.strip("(]").split(", ")
            out.append((dmin if lo == "-inf" else float(lo), dmax if hi == "inf" else float(hi)))
        return out

    _edges = _parse(_bins_dist, float(_df["dist_to_sea_km"].min()), float(_df["dist_to_sea_km"].max()))
    _x_labels = [f"{lo:.3g}–{hi:.3g}" for lo, hi in _edges]

    _full = pd.DataFrame(list(itertools.product(_bins_dist, DEGURBA_ORDER)), columns=["bin_dist", "degurba_label"])

    def _grid(weight):
        if weight is None:
            agg = _df.group_by(["bin_dist", "degurba_label"]).agg(pl.col("residual").mean().alias("v"))
        else:
            agg = _df.group_by(["bin_dist", "degurba_label"]).agg(
                ((pl.col("residual") * pl.col(weight)).sum() / pl.col(weight).sum()).alias("v")
            )
        heat = _full.merge(agg.to_pandas(), on=["bin_dist", "degurba_label"], how="left")
        z = heat.pivot(index="degurba_label", columns="bin_dist", values="v").reindex(index=DEGURBA_ORDER, columns=_bins_dist)
        return z.to_numpy()

    _z_u = _grid(None)
    _z_w = _grid("greg_weight")
    _abs_max = np.nanmax(np.abs(np.concatenate([_z_u.flatten(), _z_w.flatten()])))
    _scale = [[0.0, PALETTE["blue"]], [0.5, "#f0efec"], [1.0, PALETTE["red"]]]

    fig_dist_degurba = make_subplots(rows=1, cols=2, subplot_titles=["Unweighted", "GREG-weighted"], horizontal_spacing=0.2)
    for _col, _z in enumerate([_z_u, _z_w], start=1):
        fig_dist_degurba.add_trace(
            go.Heatmap(
                z=_z, x=_x_labels, y=DEGURBA_ORDER, zmin=-_abs_max, zmax=_abs_max, colorscale=_scale,
                showscale=(_col == 2), colorbar=dict(title="Mean residual (°C)") if _col == 2 else None,
                hovertemplate="dist: %{x}<br>%{y}<br>mean residual: %{z:.3f}<extra></extra>",
            ),
            row=1, col=_col,
        )
    fig_dist_degurba.update_layout(
        template="plotly_white", height=420, width=900,
        title="Distance to sea × DEGURBA class",
        margin=dict(t=70, b=60),
    )
    fig_dist_degurba.update_xaxes(title="Distance to sea (km)", tickangle=-40, gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))
    fig_dist_degurba.update_yaxes(gridcolor=GRID_COLOR, linecolor=AXIS_COLOR, tickfont=dict(color=MUTED_INK))

    mo.vstack([
        mo.md(
            "**Caveat**: both axes here are exactly what GREG calibrates on, so the "
            "weighted panel answers *which cells dominate the corrected national "
            "estimate*, not *does the pattern change* -- see the caveat above."
        ),
        fig_dist_degurba,
    ])
    return


if __name__ == "__main__":
    app.run()
