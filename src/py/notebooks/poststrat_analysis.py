import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    import itertools as Itertools
    from pathlib import Path

    import geopandas as Gpd
    import marimo as Mo
    import numpy as Np
    import pandas as Pd
    import plotly.express as Px
    import plotly.graph_objects as Go
    import polars as Pl
    import rasterio as Rasterio
    from plotly.subplots import make_subplots as MakeSubplots
    from pyproj import Transformer
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    from sklearn.linear_model import LinearRegression

    from py import pdp as Pdp
    from py.cleaning import FeatureRows, LoadResiduals

    return (
        FeatureRows,
        LoadResiduals,
        LinearRegression,
        Path,
        Point,
        STRtree,
        Transformer,
        Go,
        Gpd,
        Itertools,
        MakeSubplots,
        Mo,
        Np,
        Pd,
        Pdp,
        Pl,
        Px,
        Rasterio,
    )


@app.cell
def _(Path):
    from py.paths import AnalysisDataDirectory, RawDataDirectory

    DegurbaTif = (
        AnalysisDataDirectory
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0"
        / "GHS_SMOD_E2020_GLOBE_R2023A_54009_1000_V2_0.tif"
    )
    EuropeGpkg = RawDataDirectory / "gadm_410_europe.gpkg"
    ResidualsParquet = AnalysisDataDirectory / "clean/analysis.parquet"

    # DEGURBA integer code → label (Water excluded from land analysis)
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
    # Land-only strata in urbanisation order
    DegurbaOrder = [
        "Very low density rural",
        "Low density rural",
        "Rural cluster",
        "Suburban",
        "Semi-dense urban cluster",
        "Dense urban cluster",
        "Urban centre",
    ]

    # Shared plotly_white chart chrome: validated categorical + diverging colors
    Palette = {
        "blue": "#2a78d6",
        "orange": "#eb6834",
        "aqua": "#1baf7a",
        "yellow": "#eda100",
        "magenta": "#e87ba4",
        "green": "#008300",
        "violet": "#4a3aa7",
        "red": "#e34948",
    }
    GridColor = "#e1e0d9"
    AxisColor = "#c3c2b7"
    MutedInk = "#898781"
    return (
        AxisColor,
        DegurbaLabels,
        DegurbaOrder,
        DegurbaTif,
        EuropeGpkg,
        GridColor,
        MutedInk,
        Palette,
        ResidualsParquet,
    )


@app.cell
def _(LoadResiduals, FeatureRows, Pl, Mo):
    ResidualsDf = FeatureRows(LoadResiduals(), ["dist_to_sea_km"])
    print(
        "Conservative screened dataset; global coastline distances and flagged seasonal NDVI extrapolation."
    )
    Mo.md(f"""## Post-stratification on the screened dataset

    {len(ResidualsDf):,} observations at {ResidualsDf["STAID"].n_unique():,} station IDs.
    NDVI includes {ResidualsDf["ndvi_is_extrapolated"].sum():,} explicitly labelled seasonal
    extrapolations. The sample retains mixed observation-day windows.

    These are exploratory estimates using the existing post-stratification method.
    Population domains and calibration-weight consistency remain under review.
    Source covariates can vary within station IDs; station summaries use the first
    available source for elevation, coast distance and DEGURBA.
    See the [dataset methods](clean_dataset.html) and [methodology audit](data_cleaning.html).
    """)
    return (ResidualsDf,)


@app.cell
def _(
    AxisColor,
    DegurbaOrder,
    GridColor,
    MutedInk,
    Palette,
    Go,
    Mo,
    Pl,
    ResidualsDf,
):
    StationDf = ResidualsDf.group_by("STAID").agg(
        Pl.col("residual").mean(),
        Pl.col("elevation").first(),
        Pl.col("dist_to_sea_km").first(),
        Pl.col("degurba_label").first(),
        Pl.col("degurba").first(),
        Pl.col("ndvi").mean(),
        Pl.col("lat").first(),
        Pl.col("lon").first(),
        Pl.col("country").first(),
        Pl.len().alias("n_obs"),
    )
    print(f"Station-level dataframe: {len(StationDf)} stations")

    _Order = ["Water"] + DegurbaOrder
    _Colors = [
        Palette["blue"],
        Palette["orange"],
        Palette["aqua"],
        Palette["yellow"],
        Palette["magenta"],
        Palette["green"],
        Palette["violet"],
        Palette["red"],
    ]
    _Pct = (
        StationDf["degurba_label"]
        .value_counts(normalize=True)
        .to_pandas()
        .set_index("degurba_label")["proportion"]
    )
    _Y = [float(_Pct.get(Lbl, 0.0)) for Lbl in _Order]

    FigDegurbaDist = Go.Figure(
        Go.Bar(
            x=_Order,
            y=_Y,
            marker_color=_Colors,
            hovertemplate="%{x}<br>%{y:.2%}<extra></extra>",
        )
    )
    FigDegurbaDist.update_layout(
        template="plotly_white",
        title="Station distribution across DEGURBA classes",
        width=800,
        height=520,
        xaxis=dict(
            title="DEGURBA class",
            tickangle=-35,
            gridcolor=GridColor,
            linecolor=AxisColor,
            tickfont=dict(color=MutedInk),
            title_font=dict(color=MutedInk),
        ),
        yaxis=dict(
            title="Share of stations",
            tickformat=".0%",
            gridcolor=GridColor,
            linecolor=AxisColor,
            tickfont=dict(color=MutedInk),
            title_font=dict(color=MutedInk),
        ),
        margin=dict(t=60, b=110),
    )
    Mo.vstack([FigDegurbaDist])
    return (StationDf,)


@app.cell
def _(DegurbaLabels, DegurbaOrder, DegurbaTif, Transformer, Np, Rasterio):
    """
    Crop the GHS-SMOD raster to the European bounding box (lon -15→35, lat 34→72),
    extract all non-nodata pixels, and compute the proportion of land pixels per
    DEGURBA class. Water pixels (class 10) are excluded from the land proportions.
    """
    _Transformer = Transformer.from_crs("EPSG:4326", "ESRI:54009", always_xy=True)
    _XMin, _YMin = _Transformer.transform(-15.0, 34.0)
    _XMax, _YMax = _Transformer.transform(35.0, 72.0)

    with Rasterio.open(DegurbaTif) as _Src:
        from rasterio.windows import from_bounds as _FromBounds

        _Win = _FromBounds(_XMin, _YMin, _XMax, _YMax, _Src.transform)
        _WinInt = _Win.round_lengths().round_offsets()
        _Data = _Src.read(1, window=_WinInt)
        _Nodata = _Src.nodata

    _Flat = _Data.flatten()
    _Valid = _Flat[_Flat != _Nodata].astype(int)
    print(f"Valid GHS pixels in European bbox: {len(_Valid):,}")

    _UniqueVals, _Counts = Np.unique(_Valid, return_counts=True)
    _PixelCounts = dict(zip(_UniqueVals.tolist(), _Counts.tolist()))
    print("Pixel counts per class:")
    for _V, _C in sorted(_PixelCounts.items()):
        print(f"  {_V:2d}  {DegurbaLabels.get(_V, '?'):30s}: {_C:>9,}")

    # Land-only proportions (exclude Water class 10)
    _LandCounts = {K: V for K, V in _PixelCounts.items() if K != 10}
    _TotalLand = sum(_LandCounts.values())
    PopDegurba = {
        DegurbaLabels[K]: V / _TotalLand for K, V in _LandCounts.items() if K in DegurbaLabels
    }
    print("\nPopulation proportions (land only):")
    for _Label in DegurbaOrder:
        print(f"  {_Label:30s}: {PopDegurba.get(_Label, 0):.4f}")
    return (PopDegurba,)


@app.cell
def _(EuropeGpkg, Point, STRtree, Gpd, Np):
    """
    Sample 20,000 random points from the European land polygon (EPSG:3035),
    compute distance to coastline for each, and return a numpy array of km values.
    This constitutes the reference population distribution of dist_to_sea.
    """
    _NSample = 20_000
    _RngSeed = 42
    import shapely as _Shapely

    print("Loading Europe polygon…")
    _EuropeGdf = Gpd.read_file(EuropeGpkg)
    _Europe3035 = _EuropeGdf.dissolve().to_crs("EPSG:3035")
    _EuropeGeom = _Europe3035.geometry.iloc[0]
    _Shapely.prepare(_EuropeGeom)

    print("Extracting and simplifying coastline…")
    _Coastline = _EuropeGeom.boundary.simplify(1000)

    print(f"Sampling {_NSample:,} random land points…")
    _Rng = Np.random.default_rng(_RngSeed)
    _Minx, _Miny, _Maxx, _Maxy = _EuropeGeom.bounds
    _Pts = []
    _Attempts = 0
    while len(_Pts) < _NSample:
        _Bx = _Rng.uniform(_Minx, _Maxx, _NSample * 4)
        _By = _Rng.uniform(_Miny, _Maxy, _NSample * 4)
        _Attempts += len(_Bx)
        for _X, _Y in zip(_Bx, _By):
            if _EuropeGeom.contains(Point(_X, _Y)):
                _Pts.append((_X, _Y))
                if len(_Pts) >= _NSample:
                    break
    print(f"  Accepted {len(_Pts)} points from {_Attempts:,} attempts")

    # STRtree on coastline segments (MultiLineString → iterate geoms)
    _Segments = (
        list(_Coastline.geoms) if _Coastline.geom_type == "MultiLineString" else [_Coastline]
    )
    _Tree = STRtree(_Segments)
    _SamplePts = [Point(X, Y) for X, Y in _Pts]
    _SampleArr = _Shapely.from_wkt([P.wkt for P in _SamplePts])
    _NearestIdx = _Tree.nearest(_SampleArr)
    _NearestSegs = Np.array(_Segments, dtype=object)[_NearestIdx]
    _DistsM = _Shapely.distance(_SampleArr, _NearestSegs)
    RefDistToSeaKm = _DistsM / 1000.0
    print(
        f"Reference dist_to_sea: mean={RefDistToSeaKm.mean():.1f} km, "
        f"median={Np.median(RefDistToSeaKm):.1f} km"
    )
    return (RefDistToSeaKm,)


@app.cell
def _(
    AxisColor,
    DegurbaOrder,
    GridColor,
    MutedInk,
    Palette,
    Go,
    Mo,
    Np,
    Pl,
    PopDegurba,
    RefDistToSeaKm,
    StationDf,
):
    """
    Three charts showing how weather stations differ from the true European
    land population:
      A) DEGURBA class distribution (stations vs. GHS-SMOD population)
      B) dist_to_sea distribution (stations vs. random land sample)
      C) Elevation distribution (stations only — no population DEM available)
    """
    _MaxRows = 2499
    _AxisStyle = dict(
        gridcolor=GridColor,
        linecolor=AxisColor,
        tickfont=dict(color=MutedInk),
        title_font=dict(color=MutedInk),
    )
    _LegendStyle = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)

    # --- Panel A: DEGURBA grouped bar chart ---
    _NTotal = len(StationDf)
    _StationPctMap = (
        StationDf.filter(Pl.col("degurba_label") != "Water")
        .group_by("degurba_label")
        .agg(Pl.len().alias("count"))
        .with_columns((Pl.col("count") / _NTotal).alias("station_pct"))
        .to_pandas()
        .set_index("degurba_label")["station_pct"]
        .to_dict()
    )
    _PopPct = [PopDegurba.get(Lbl, 0.0) for Lbl in DegurbaOrder]
    _StationPct = [_StationPctMap.get(Lbl, 0.0) for Lbl in DegurbaOrder]

    FigDegurba = Go.Figure()
    FigDegurba.add_bar(
        name="Stations",
        x=DegurbaOrder,
        y=_StationPct,
        marker_color=Palette["blue"],
        hovertemplate="%{x}<br>Stations: %{y:.2%}<extra></extra>",
    )
    FigDegurba.add_bar(
        name="European land (GHS-SMOD)",
        x=DegurbaOrder,
        y=_PopPct,
        marker_color=Palette["orange"],
        hovertemplate="%{x}<br>Population: %{y:.2%}<extra></extra>",
    )
    FigDegurba.update_layout(
        template="plotly_white",
        title="A) DEGURBA class: stations vs. population",
        barmode="group",
        bargap=0.25,
        bargroupgap=0.05,
        height=340,
        legend=_LegendStyle,
        xaxis=dict(title="DEGURBA class", tickangle=-35, **_AxisStyle),
        yaxis=dict(title="Proportion", tickformat=".0%", **_AxisStyle),
        margin=dict(t=60, b=90),
    )

    # --- Panel B: dist_to_sea overlaid histograms ---
    _RngB = Np.random.default_rng(0)
    _StationDist = (
        StationDf.select(["dist_to_sea_km"])
        .sample(n=min(_MaxRows, len(StationDf)), seed=0)
        .to_pandas()["dist_to_sea_km"]
        .clip(upper=800)
    )
    _RefIdx = _RngB.choice(
        len(RefDistToSeaKm),
        size=min(_MaxRows, len(RefDistToSeaKm)),
        replace=False,
    )
    _RefDist = Np.clip(RefDistToSeaKm[_RefIdx], None, 800)

    FigDist = Go.Figure()
    FigDist.add_histogram(
        name="Stations",
        x=_StationDist,
        nbinsx=40,
        marker_color=Palette["blue"],
        opacity=0.55,
    )
    FigDist.add_histogram(
        name="European land (random sample)",
        x=_RefDist,
        nbinsx=40,
        marker_color=Palette["orange"],
        opacity=0.55,
    )
    FigDist.update_layout(
        template="plotly_white",
        title="B) Distance to sea: stations vs. land sample",
        barmode="overlay",
        bargap=0.05,
        height=340,
        legend=_LegendStyle,
        xaxis=dict(title="Distance to sea (km, clipped at 800)", **_AxisStyle),
        yaxis=dict(title="Count", **_AxisStyle),
        margin=dict(t=60, b=60),
    )

    # --- Panel C: Elevation (stations only) ---
    _Elev = (
        StationDf.filter(Pl.col("elevation") > -9000)
        .select(["elevation"])
        .sample(n=min(_MaxRows, len(StationDf)), seed=0)
        .to_pandas()["elevation"]
    )

    FigElev = Go.Figure()
    FigElev.add_histogram(
        x=_Elev,
        nbinsx=40,
        marker_color=Palette["blue"],
        showlegend=False,
        hovertemplate="Elevation: %{x} m<br>Count: %{y}<extra></extra>",
    )
    FigElev.update_layout(
        template="plotly_white",
        title="C) Elevation: stations only (no population DEM reference)",
        bargap=0.05,
        height=320,
        xaxis=dict(title="Elevation (m)", **_AxisStyle),
        yaxis=dict(title="Count", **_AxisStyle),
        margin=dict(t=60, b=60),
    )

    Mo.vstack(
        [
            Mo.md(
                "## Representativeness Analysis\n\n"
                "Weather stations are **not** a random sample of European land. "
                "Panel A shows suburban and low-density rural classes are over-represented "
                "relative to the GHS-SMOD land pixel distribution. "
                "Panel B confirms stations cluster close to coasts. "
                "These biases motivate post-stratification and GREG weighting."
            ),
            FigDegurba,
            FigDist,
            FigElev,
        ]
    )
    return


@app.cell
def _(DegurbaOrder, Mo, Pl, PopDegurba, StationDf):
    """
    Post-stratified estimator (Lehalle 2023 / Zhang 2000):
        ȳ_PS = Σ_s  p_s^{pop} · ȳ_s

    where p_s^{pop} is the GHS-SMOD land proportion and ȳ_s is the mean
    residual among stations in stratum s.

    Per-station weight: w_s = p_s^{pop} / p_s^{sample}
    """
    # Exclude water stations from land analysis
    _StationLand = StationDf.filter(Pl.col("degurba_label") != "Water")
    _NStations = len(_StationLand)

    _SampleCounts = (
        _StationLand.group_by("degurba_label")
        .agg(Pl.len().alias("n_s"))
        .to_pandas()
        .set_index("degurba_label")["n_s"]
        .to_dict()
    )

    _StratumMeans = (
        _StationLand.group_by("degurba_label")
        .agg(Pl.col("residual").mean().alias("mean_resid"))
        .to_pandas()
        .set_index("degurba_label")["mean_resid"]
        .to_dict()
    )

    # Naive unweighted mean and post-stratified mean
    YNaive = float(_StationLand["residual"].mean())
    YPoststrat = sum(PopDegurba.get(S, 0.0) * _StratumMeans.get(S, 0.0) for S in DegurbaOrder)

    # Per-stratum weights
    StrataWeights = {}
    for _S in DegurbaOrder:
        _PPop = PopDegurba.get(_S, 0.0)
        _PSample = _SampleCounts.get(_S, 0) / _NStations
        StrataWeights[_S] = _PPop / _PSample if _PSample > 0 else 0.0

    # Attach per-station weights
    _WeightMap = Pl.DataFrame(
        {
            "degurba_label": list(StrataWeights.keys()),
            "ps_weight": list(StrataWeights.values()),
        }
    )
    StationDfWeighted = _StationLand.join(_WeightMap, on="degurba_label", how="left")

    print(f"Naive mean residual:           {YNaive:+.4f} °C")
    print(f"Post-stratified mean residual: {YPoststrat:+.4f} °C")
    print(f"Correction:                    {YPoststrat - YNaive:+.4f} °C")
    print()
    print(f"{'Stratum':35s} {'p_pop':>7} {'p_sample':>9} {'weight':>7} {'ȳ_s':>8} {'n_s':>6}")
    for _S in DegurbaOrder:
        _Pp = PopDegurba.get(_S, 0.0)
        _Ps = _SampleCounts.get(_S, 0) / _NStations
        _W = StrataWeights[_S]
        _Ym = _StratumMeans.get(_S, float("nan"))
        _N = _SampleCounts.get(_S, 0)
        print(f"  {_S:33s} {_Pp:7.4f} {_Ps:9.4f} {_W:7.4f} {_Ym:8.4f} {_N:6d}")

    Mo.md(f"""
    ### Post-stratification by DEGURBA class

    | Estimator | Mean residual (°C) |
    |-----------|-------------------|
    | Naive (unweighted station mean) | **{YNaive:+.4f}** |
    | Post-stratified (DEGURBA weights) | **{YPoststrat:+.4f}** |
    | Correction | **{YPoststrat - YNaive:+.4f}** |

    Post-stratification re-weights each stratum so the weighted sample matches the
    GHS-SMOD land pixel distribution. Strata with more land pixels than station
    coverage receive higher weights.
    """)
    return StationDfWeighted, StrataWeights, YNaive, YPoststrat


@app.cell
def _(
    DegurbaOrder,
    LinearRegression,
    Mo,
    Np,
    Pd,
    Pl,
    PopDegurba,
    RefDistToSeaKm,
    StationDfWeighted,
    YNaive,
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
    _StationPd = StationDfWeighted.to_pandas()

    # Design matrix
    _Dummies = Pd.get_dummies(
        _StationPd["degurba_label"].astype(Pd.CategoricalDtype(DegurbaOrder)),
        prefix="deg",
        dtype=float,
    )
    _DistMean = _StationPd["dist_to_sea_km"].mean()
    _DistStd = _StationPd["dist_to_sea_km"].std()
    _DistStdCol = (_StationPd["dist_to_sea_km"] - _DistMean) / _DistStd
    _XSample = Np.hstack([_Dummies.values, _DistStdCol.values.reshape(-1, 1)])
    _YSample = _StationPd["residual"].values

    # Population means for each auxiliary variable
    _PopDegMeans = Np.array([PopDegurba.get(S, 0.0) for S in DegurbaOrder])
    _PopDistStdMean = (RefDistToSeaKm.mean() - _DistMean) / _DistStd
    _XPopBar = Np.concatenate([_PopDegMeans, [_PopDistStdMean]])
    _XBarSample = _XSample.mean(axis=0)

    # WLS regression weighted by n_obs (more observations = more reliable station mean)
    _NObsWeights = _StationPd["n_obs"].values.astype(float)
    _Reg = LinearRegression(fit_intercept=False)
    _Reg.fit(_XSample, _YSample, sample_weight=_NObsWeights)
    _Beta = _Reg.coef_

    # GREG point estimate
    YGreg = float(YNaive + (_XPopBar - _XBarSample) @ _Beta)

    # Per-station calibration weights: w_i = 1 + (X̄_pop − x̄)ᵀ V̂⁻¹ x_i
    _VHat = (_XSample.T @ _XSample) / len(_XSample)
    _VHatReg = _VHat + 1e-8 * Np.eye(_VHat.shape[0])
    _Diff = _XPopBar - _XBarSample
    _GregWeightsRaw = 1.0 + _XSample @ Np.linalg.solve(_VHatReg, _Diff)

    StationDfGreg = StationDfWeighted.with_columns(
        Pl.Series("greg_weight", _GregWeightsRaw.tolist())
    )

    print(f"Naive mean:          {YNaive:+.4f} °C")
    print(f"GREG mean:           {YGreg:+.4f} °C")
    print(f"Correction vs naive: {YGreg - YNaive:+.4f} °C")
    print("\nGREG β̂:")
    for _Col, _B in zip(list(_Dummies.columns) + ["dist_std"], _Beta):
        print(f"  {_Col:35s}: {_B:+.4f}")

    Mo.md(f"""
    ### GREG Calibration (DEGURBA + distance to sea)

    $$\\hat{{y}}_{{GREG}} = \\bar{{y}} + (\\bar{{X}}_{{pop}} - \\bar{{x}}_{{sample}})^\\top \\hat{{\\beta}}$$

    | Estimator | Mean residual (°C) |
    |-----------|-------------------|
    | Naive | **{YNaive:+.4f}** |
    | GREG (DEGURBA + dist_to_sea) | **{YGreg:+.4f}** |

    Population mean dist_to_sea (reference): **{RefDistToSeaKm.mean():.1f} km**
    Sample mean dist_to_sea (stations): **{_DistMean:.1f} km**

    Stations are on average closer to the coast than the European land average,
    so the GREG correction adjusts for this spatial concentration bias.
    """)
    return StationDfGreg, YGreg


@app.cell
def _(
    DegurbaOrder,
    LinearRegression,
    Mo,
    Np,
    Pd,
    PopDegurba,
    RefDistToSeaKm,
    StationDfGreg,
    YGreg,
    YNaive,
    YPoststrat,
):
    """
    Bootstrap (B=1000) by resampling stations with replacement.
    Provides 95% percentile CIs for naive, post-stratified, and GREG estimators.
    """
    _BootstrapCount = 1000
    _Alpha = 0.05
    _RngSeed = 0

    _StationPdBs = StationDfGreg.to_pandas().copy()
    _N = len(_StationPdBs)
    _Rng = Np.random.default_rng(_RngSeed)

    # Pre-compute dist_to_sea standardisation constants (keep consistent with cell 8)
    _DistMeanBs = _StationPdBs["dist_to_sea_km"].mean()
    _DistStdBs = _StationPdBs["dist_to_sea_km"].std()
    _PopDistStdMeanBs = (RefDistToSeaKm.mean() - _DistMeanBs) / _DistStdBs
    _PopDegMeansBs = Np.array([PopDegurba.get(S, 0.0) for S in DegurbaOrder])

    _BootNaive = Np.empty(_BootstrapCount)
    _BootPs = Np.empty(_BootstrapCount)
    _BootGreg = Np.empty(_BootstrapCount)

    for _B in range(_BootstrapCount):
        _Idx = _Rng.integers(0, _N, size=_N)
        _S = _StationPdBs.iloc[_Idx]

        # Naive
        _BootNaive[_B] = _S["residual"].mean()

        # Post-stratified
        _PsVal = 0.0
        for _Stratum in DegurbaOrder:
            _Rows = _S[_S["degurba_label"] == _Stratum]
            if len(_Rows) > 0:
                _PsVal += PopDegurba.get(_Stratum, 0.0) * _Rows["residual"].mean()
        _BootPs[_B] = _PsVal

        # GREG
        _DummiesB = Pd.get_dummies(
            _S["degurba_label"].astype(Pd.CategoricalDtype(DegurbaOrder)),
            prefix="deg",
            dtype=float,
        )
        _DistStdB = (_S["dist_to_sea_km"] - _DistMeanBs) / _DistStdBs
        _Xb = Np.hstack([_DummiesB.values, _DistStdB.values.reshape(-1, 1)])
        _Yb = _S["residual"].values
        _Wb = _S["n_obs"].values.astype(float)
        _XPopB = Np.concatenate([_PopDegMeansBs, [_PopDistStdMeanBs]])
        _XBarB = _Xb.mean(axis=0)
        _RegB = LinearRegression(fit_intercept=False)
        _RegB.fit(_Xb, _Yb, sample_weight=_Wb)
        _BootGreg[_B] = _BootNaive[_B] + (_XPopB - _XBarB) @ _RegB.coef_

    _CiNaive = Np.percentile(_BootNaive, [100 * _Alpha / 2, 100 * (1 - _Alpha / 2)])
    _CiPs = Np.percentile(_BootPs, [100 * _Alpha / 2, 100 * (1 - _Alpha / 2)])
    _CiGreg = Np.percentile(_BootGreg, [100 * _Alpha / 2, 100 * (1 - _Alpha / 2)])

    BootstrapResults = {
        "Naive": {
            "mean": float(YNaive),
            "ci_lo": float(_CiNaive[0]),
            "ci_hi": float(_CiNaive[1]),
        },
        "Post-stratified": {
            "mean": float(YPoststrat),
            "ci_lo": float(_CiPs[0]),
            "ci_hi": float(_CiPs[1]),
        },
        "GREG": {
            "mean": float(YGreg),
            "ci_lo": float(_CiGreg[0]),
            "ci_hi": float(_CiGreg[1]),
        },
    }

    print("Bootstrap 95% CIs (B=1000, station-level resampling):")
    for _Est, _Vals in BootstrapResults.items():
        print(
            f"  {_Est:20s}: {_Vals['mean']:+.4f}  "
            f"95% CI [{_Vals['ci_lo']:+.4f}, {_Vals['ci_hi']:+.4f}]"
        )

    Mo.md(f"""
    ### Bootstrap Confidence Intervals (B=1,000, station resampling)

    | Estimator | Mean (°C) | 95% CI |
    |-----------|-----------|--------|
    | Naive | **{YNaive:+.4f}** | [{_CiNaive[0]:+.4f}, {_CiNaive[1]:+.4f}] |
    | Post-stratified | **{YPoststrat:+.4f}** | [{_CiPs[0]:+.4f}, {_CiPs[1]:+.4f}] |
    | GREG | **{YGreg:+.4f}** | [{_CiGreg[0]:+.4f}, {_CiGreg[1]:+.4f}] |

    **Interpretation**: A positive residual means *station > ERA5*, i.e. ERA5
    under-estimates surface temperature. Post-stratification and GREG correct for the
    over-representation of suburban and near-coast stations.
    """)
    return (BootstrapResults,)


@app.cell
def _(
    AxisColor,
    GridColor,
    MutedInk,
    Palette,
    BootstrapResults,
    Go,
    Mo,
    Np,
    StationDfGreg,
):
    """
    Visual summary of point estimates and 95% bootstrap CIs.
    Also reports effective sample size for each estimator.
    """
    _EstOrder = ["Naive", "Post-stratified", "GREG"]
    _Colors = [Palette["blue"], Palette["orange"], Palette["aqua"]]
    _Means = [BootstrapResults[E]["mean"] for E in _EstOrder]
    _CiLo = [BootstrapResults[E]["ci_lo"] for E in _EstOrder]
    _CiHi = [BootstrapResults[E]["ci_hi"] for E in _EstOrder]
    _ErrPlus = [Hi - M for Hi, M in zip(_CiHi, _Means)]
    _ErrMinus = [M - Lo for M, Lo in zip(_Means, _CiLo)]

    ResultsChart = Go.Figure(
        Go.Bar(
            x=_EstOrder,
            y=_Means,
            marker_color=_Colors,
            width=0.5,
            error_y=dict(
                type="data",
                symmetric=False,
                array=_ErrPlus,
                arrayminus=_ErrMinus,
                color=MutedInk,
                thickness=1.5,
                width=6,
            ),
            hovertemplate="%{x}<br>mean %{y:+.4f}<extra></extra>",
        )
    )
    ResultsChart.update_layout(
        template="plotly_white",
        title="ERA5 temperature bias estimates with 95% bootstrap CI",
        showlegend=False,
        height=380,
        width=420,
        xaxis=dict(title=None, linecolor=AxisColor, tickfont=dict(color=MutedInk, size=13)),
        yaxis=dict(
            title="Mean residual (°C)",
            gridcolor=GridColor,
            linecolor=AxisColor,
            tickfont=dict(color=MutedInk),
            title_font=dict(color=MutedInk),
            zeroline=False,
        ),
        margin=dict(t=60, b=40),
    )

    # Effective sample size: n_eff = (Σ w_i)² / Σ w_i²
    def _EffN(W: Np.ndarray) -> float:
        return float(W.sum() ** 2 / (W**2).sum())

    _PsW = StationDfGreg["ps_weight"].to_numpy()
    _GrW = StationDfGreg["greg_weight"].to_numpy()
    _NTotal = len(_PsW)
    _NEffPs = _EffN(_PsW)
    _NEffGr = _EffN(_GrW)

    print(f"n               : {_NTotal}")
    print(f"n_eff (post-strat): {_NEffPs:.0f}  ({100 * _NEffPs / _NTotal:.1f}% of n)")
    print(f"n_eff (GREG)      : {_NEffGr:.0f}  ({100 * _NEffGr / _NTotal:.1f}% of n)")

    Mo.vstack(
        [
            ResultsChart,
            Mo.md(f"""
    | Estimator | n stations | n_eff |
    |-----------|-----------|-------|
    | Naive | {_NTotal} | {_NTotal} (100%) |
    | Post-stratified | {_NTotal} | {_NEffPs:.0f} ({100 * _NEffPs / _NTotal:.1f}%) |
    | GREG | {_NTotal} | {_NEffGr:.0f} ({100 * _NEffGr / _NTotal:.1f}%) |

    n_eff decreases when weights are unequal. Upweighted strata contribute more
    variance, which is the price of correcting the sampling bias.
        """),
        ]
    )
    return


@app.cell
def _(
    AxisColor,
    DegurbaOrder,
    GridColor,
    MutedInk,
    Palette,
    Go,
    Mo,
    PopDegurba,
    StrataWeights,
):
    """
    Two charts:
      1) Grouped bar: population proportion vs station proportion per stratum
      2) Bar chart of post-stratification weights w_s with w=1 reference line
    """
    _AxisStyle = dict(
        gridcolor=GridColor,
        linecolor=AxisColor,
        tickfont=dict(color=MutedInk),
        title_font=dict(color=MutedInk),
    )
    _LegendStyle = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)

    _PPop = [PopDegurba.get(S, 0.0) for S in DegurbaOrder]
    _Weights = [StrataWeights.get(S, 0.0) for S in DegurbaOrder]
    _PSample = [Pp / W if W > 0 else 0.0 for Pp, W in zip(_PPop, _Weights)]

    # Chart 1: population vs sample proportions
    FigProp = Go.Figure()
    FigProp.add_bar(
        name="GHS population",
        x=DegurbaOrder,
        y=_PPop,
        marker_color=Palette["blue"],
        hovertemplate="%{x}<br>Population: %{y:.2%}<extra></extra>",
    )
    FigProp.add_bar(
        name="Station sample",
        x=DegurbaOrder,
        y=_PSample,
        marker_color=Palette["orange"],
        hovertemplate="%{x}<br>Stations: %{y:.2%}<extra></extra>",
    )
    FigProp.update_layout(
        template="plotly_white",
        title="Population vs. sample proportions per DEGURBA class",
        barmode="group",
        bargap=0.25,
        bargroupgap=0.05,
        height=340,
        legend=_LegendStyle,
        xaxis=dict(title="DEGURBA class", tickangle=-35, **_AxisStyle),
        yaxis=dict(title="Proportion", tickformat=".0%", **_AxisStyle),
        margin=dict(t=60, b=90),
    )

    # Chart 2: weights, colored by over-/under-representation, w=1 reference line
    _BarColors = [Palette["red"] if W > 1.0 else Palette["blue"] for W in _Weights]
    FigWeights = Go.Figure()
    FigWeights.add_bar(
        x=DegurbaOrder,
        y=_Weights,
        marker_color=_BarColors,
        showlegend=False,
        customdata=list(zip(_PPop, _PSample)),
        hovertemplate=(
            "%{x}<br>weight %{y:.3f}<br>p_pop %{customdata[0]:.3f}"
            "<br>p_sample %{customdata[1]:.3f}<extra></extra>"
        ),
    )
    FigWeights.add_hline(
        y=1.0,
        line_dash="dash",
        line_color=MutedInk,
        opacity=0.8,
        annotation_text="w = 1",
        annotation_position="top right",
        annotation_font_color=MutedInk,
    )
    FigWeights.update_layout(
        template="plotly_white",
        title="Post-stratification weights (w_s = p_pop / p_sample)",
        bargap=0.25,
        height=340,
        xaxis=dict(title="DEGURBA class", tickangle=-35, **_AxisStyle),
        yaxis=dict(title="Post-stratification weight w_s", rangemode="tozero", **_AxisStyle),
        margin=dict(t=60, b=90),
    )

    Mo.vstack(
        [
            Mo.md("""## Weight Analysis

    **Blue bars** (w < 1): stratum is over-represented in stations — downweighted.
    **Red bars** (w > 1): stratum is under-represented — upweighted.
    A perfectly representative sample would have w = 1 for all strata (dashed line).
        """),
            FigProp,
            FigWeights,
        ]
    )
    return


@app.cell
def _(Palette, Mo, Px, StationDfGreg):
    """
    Plotly scatter_map coloured by post-stratification weight.
    High-weight stations (red) belong to under-represented strata and receive
    more weight in the corrected estimator; their geographic pattern reveals
    where the station network is thin relative to the land population.
    """
    _MapPd = StationDfGreg.select(
        ["lat", "lon", "ps_weight", "degurba_label", "residual", "country", "STAID"]
    ).to_pandas()

    _DivergingScale = [
        [0.0, Palette["blue"]],
        [0.5, "#f0efec"],
        [1.0, Palette["red"]],
    ]

    _Fig = Px.scatter_map(
        _MapPd,
        lat="lat",
        lon="lon",
        color="ps_weight",
        color_continuous_scale=_DivergingScale,
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
    _Fig.update_traces(marker=dict(size=6, opacity=0.8))
    _Fig.update_layout(
        height=700,
        template="plotly_white",
        coloraxis_colorbar=dict(title="w_s", tickformat=".2f"),
    )

    Mo.vstack(
        [
            Mo.md("""## Geographic Pattern of the Sampling Correction

    Stations in very-low-density rural and urban-centre areas receive the highest
    weights (red) because those land types are under-represented in the station
    network. Dense suburban clusters (blue) are downweighted. The spatial pattern
    of weights reveals which parts of Europe are statistically thin relative to
    their land area in the GHS-SMOD reference.
        """),
            _Fig,
        ]
    )
    return


@app.cell
def _(ResidualsDf, StationDfGreg):
    """
    Attach each station's ps_weight / greg_weight onto the observation-level
    residuals_df, so the PDPs and cross-heatmaps below can compare an unweighted
    mean against the population-representative (GREG-calibrated) mean.

    Inner join: station_df_greg only has land stations (Water excluded during
    post-stratification), so Water-labelled stations drop out of this weighted
    view — consistent with the rest of this notebook's land-only scope.
    """
    ResidualsDfWeighted = ResidualsDf.join(
        StationDfGreg.select(["STAID", "ps_weight", "greg_weight"]),
        on="STAID",
        how="inner",
    )
    print(
        f"{len(ResidualsDfWeighted):,} rows with weights attached "
        f"({ResidualsDfWeighted['STAID'].n_unique()} stations)"
    )
    return (ResidualsDfWeighted,)


@app.cell
def _(AxisColor, GridColor, MutedInk, Palette, Go, Np, Pdp, FeatureRows):
    """
    PDP: mean residual vs. a binned covariate, cluster-bootstrap 95% CI band.
    Overlays the unweighted (raw sample) curve against the GREG-weighted
    (population-representative) curve, plus a raw-value histogram below.
    """

    def _HexToRgba(HexColor, Alpha):
        H = HexColor.lstrip("#")
        R, G, B = (int(H[Index : Index + 2], 16) for Index in (0, 2, 4))
        return f"rgba({R},{G},{B},{Alpha})"

    def MakePdpAndHist(
        Df, Feature, Xlabel, NBins=10, HistBins=50, Log10=False, WeightCol="greg_weight"
    ):
        import polars as _Pl

        _Df = FeatureRows(Df, [Feature, WeightCol])
        if Log10:
            _Df = _Df.with_columns(
                _Pl.col(Feature).clip(lower_bound=1e-9).log(base=10).alias(Feature)
            )

        DfBinned, Bins = Pdp.BinFeatures(_Df, Feature, NBins=NBins)
        MeansU, LoU, HiU = Pdp.PdpClusterBootstrap(
            DfBinned, "bin", Bins, Rng=Np.random.default_rng(1337)
        )
        MeansW, LoW, HiW = Pdp.PdpClusterBootstrap(
            DfBinned, "bin", Bins, Rng=Np.random.default_rng(1337), WeightCol=WeightCol
        )
        Centers = Pdp.BinCenters(Bins, DfBinned[Feature].min(), DfBinned[Feature].max())
        _Xlabel = f"{Xlabel} (log₁₀)" if Log10 else Xlabel

        Fig = Go.Figure()
        for _Name, _Means, _Lo, _Hi, _Color in [
            ("Unweighted", MeansU, LoU, HiU, Palette["blue"]),
            ("GREG-weighted", MeansW, LoW, HiW, Palette["orange"]),
        ]:
            Fig.add_scatter(
                x=Centers + Centers[::-1],
                y=list(_Hi) + list(_Lo[::-1]),
                fill="toself",
                fillcolor=_HexToRgba(_Color, 0.15),
                line=dict(color="rgba(255,255,255,0)"),
                hoverinfo="skip",
                showlegend=False,
            )
            Fig.add_scatter(
                x=Centers,
                y=_Means,
                mode="lines+markers",
                name=_Name,
                line=dict(color=_Color, width=2),
                marker=dict(size=7),
                hovertemplate=f"{_Name}<br>{_Xlabel}: %{{x:.3g}}<br>mean residual: %{{y:.3f}}<extra></extra>",
            )
        Fig.add_hline(y=0, line_dash="dash", line_color=MutedInk, opacity=0.6)
        Fig.update_layout(
            template="plotly_white",
            title=f"PDP: residual vs {Xlabel}",
            height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            xaxis=dict(
                title=_Xlabel,
                gridcolor=GridColor,
                linecolor=AxisColor,
                tickfont=dict(color=MutedInk),
                title_font=dict(color=MutedInk),
            ),
            yaxis=dict(
                title="Mean residual (°C)",
                gridcolor=GridColor,
                linecolor=AxisColor,
                tickfont=dict(color=MutedInk),
                title_font=dict(color=MutedInk),
            ),
            margin=dict(t=60, b=50),
        )

        _Series = _Df[Feature].drop_nulls()
        _Sample = _Series.sample(n=min(4999, _Series.len()), seed=42)
        Hist = Go.Figure(
            Go.Histogram(
                x=_Sample.to_numpy(),
                nbinsx=HistBins,
                marker_color=Palette["blue"],
                opacity=0.6,
                showlegend=False,
            )
        )
        Hist.update_layout(
            template="plotly_white",
            height=140,
            xaxis=dict(
                title=_Xlabel,
                gridcolor=GridColor,
                linecolor=AxisColor,
                tickfont=dict(color=MutedInk),
                title_font=dict(color=MutedInk),
            ),
            yaxis=dict(
                title="Count",
                gridcolor=GridColor,
                linecolor=AxisColor,
                tickfont=dict(color=MutedInk),
                title_font=dict(color=MutedInk),
            ),
            margin=dict(t=10, b=50),
        )
        return Fig, Hist

    return (MakePdpAndHist,)


@app.cell
def _(MakePdpAndHist, Mo, ResidualsDfWeighted):
    _Specs = [
        ("station_celsius", "Station temp (°C)", False),
        ("tp", "Precipitation proxy (m)", True),
        ("wind", "Magnitude of daily mean wind (m/s)", False),
        ("ndvi", "NDVI (incl. extrapolation)", False),
        ("dist_to_sea_km", "Distance to sea (km)", False),
        ("elevation", "Elevation (m)", False),
    ]
    _Blocks = []
    for _Feature, _Label, _Log10 in _Specs:
        _Fig, _Hist = MakePdpAndHist(ResidualsDfWeighted, _Feature, _Label, Log10=_Log10)
        _Blocks.extend([_Fig, _Hist])

    Mo.vstack(
        [
            Mo.md(
                "## Partial Dependence Plots: Unweighted vs. GREG-Weighted\n\n"
                "Each panel overlays the raw (unweighted) mean residual per bin against "
                "the GREG-weighted mean, which reweights each observation toward the "
                "population-representative DEGURBA + distance-to-sea mix. Where the two "
                "curves track closely, the pattern is unlikely to be an artifact of "
                "station-network composition."
            ),
            *_Blocks,
        ]
    )
    return


@app.cell
def _(
    AxisColor,
    GridColor,
    MutedInk,
    Palette,
    Go,
    Itertools,
    MakeSubplots,
    Np,
    Pd,
    Pdp,
    FeatureRows,
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

    def MakeCrossHeatmap(
        Df,
        FeatX,
        FeatY,
        Xlabel,
        Ylabel,
        NBins=8,
        WeightCol="greg_weight",
        ColorFeat="residual",
        ColorTitle=None,
        Diverging=True,
        SequentialHue="red",
        Log10Color=False,
    ):
        import polars as _Pl

        _Df = FeatureRows(Df, [FeatX, FeatY, ColorFeat, WeightCol])
        if Log10Color:
            _Df = _Df.with_columns(
                _Pl.col(ColorFeat).clip(lower_bound=1e-9).log(base=10).alias(ColorFeat)
            )
        ColorTitle = ColorTitle or (
            "Mean residual (°C)" if ColorFeat == "residual" else f"Mean {ColorFeat}"
        )
        if Log10Color:
            ColorTitle = f"{ColorTitle} (log₁₀)"

        _Df, BinsX = Pdp.BinFeatures(_Df, FeatX, NBins=NBins)
        _Df = _Df.rename({"bin": "bin_x"})
        _Df, BinsY = Pdp.BinFeatures(_Df, FeatY, NBins=NBins)
        _Df = _Df.rename({"bin": "bin_y"})

        def _ParseEdges(Bins, Dmin, Dmax):
            Out = []
            for B in Bins:
                Lo, Hi = B.strip("(]").split(", ")
                Out.append(
                    (Dmin if Lo == "-inf" else float(Lo), Dmax if Hi == "inf" else float(Hi))
                )
            return Out

        EdgesX = _ParseEdges(BinsX, float(_Df[FeatX].min()), float(_Df[FeatX].max()))
        EdgesY = _ParseEdges(BinsY, float(_Df[FeatY].min()), float(_Df[FeatY].max()))
        XLabels = [f"{Lo:.3g}–{Hi:.3g}" for Lo, Hi in EdgesX]
        YLabels = [f"{Lo:.3g}–{Hi:.3g}" for Lo, Hi in EdgesY]

        FullGrid = Pd.DataFrame(list(Itertools.product(BinsX, BinsY)), columns=["bin_x", "bin_y"])

        def _Grid(Weight):
            if Weight is None:
                Agg = _Df.group_by(["bin_x", "bin_y"]).agg(_Pl.col(ColorFeat).mean().alias("v"))
            else:
                Agg = _Df.group_by(["bin_x", "bin_y"]).agg(
                    ((_Pl.col(ColorFeat) * _Pl.col(Weight)).sum() / _Pl.col(Weight).sum()).alias(
                        "v"
                    )
                )
            Heat = FullGrid.merge(Agg.to_pandas(), on=["bin_x", "bin_y"], how="left")
            Z = Heat.pivot(index="bin_y", columns="bin_x", values="v").reindex(
                index=BinsY, columns=BinsX
            )
            return Z.to_numpy()

        ZU = _Grid(None)
        ZW = _Grid(WeightCol)
        _All = Np.concatenate([ZU.flatten(), ZW.flatten()])

        if Diverging:
            AbsMax = Np.nanmax(Np.abs(_All))
            Zmin, Zmax = -AbsMax, AbsMax
            Scale = [[0.0, Palette["blue"]], [0.5, "#f0efec"], [1.0, Palette["red"]]]
        else:
            Zmin, Zmax = float(Np.nanmin(_All)), float(Np.nanmax(_All))
            Scale = [[0.0, "#fcfcfb"], [1.0, Palette[SequentialHue]]]

        Fig = MakeSubplots(
            rows=1, cols=2, subplot_titles=["Unweighted", "GREG-weighted"], horizontal_spacing=0.15
        )
        for _Col, _Z in enumerate([ZU, ZW], start=1):
            Fig.add_trace(
                Go.Heatmap(
                    z=_Z,
                    x=XLabels,
                    y=YLabels,
                    zmin=Zmin,
                    zmax=Zmax,
                    colorscale=Scale,
                    showscale=(_Col == 2),
                    colorbar=dict(title=ColorTitle) if _Col == 2 else None,
                    hovertemplate=f"{Xlabel}: %{{x}}<br>{Ylabel}: %{{y}}<br>{ColorTitle}: %{{z:.3f}}<extra></extra>",
                ),
                row=1,
                col=_Col,
            )
        Fig.update_layout(
            template="plotly_white",
            height=420,
            width=900,
            title=f"{ColorTitle} — {Xlabel} × {Ylabel}",
            margin=dict(t=70, b=90),
        )
        Fig.update_xaxes(
            title=Xlabel,
            tickangle=-40,
            gridcolor=GridColor,
            linecolor=AxisColor,
            tickfont=dict(color=MutedInk),
        )
        Fig.update_yaxes(
            title=Ylabel, gridcolor=GridColor, linecolor=AxisColor, tickfont=dict(color=MutedInk)
        )
        return Fig

    return (MakeCrossHeatmap,)


@app.cell
def _(MakeCrossHeatmap, Mo, ResidualsDfWeighted):
    _FigA = MakeCrossHeatmap(
        ResidualsDfWeighted,
        "elevation",
        "dist_to_sea_km",
        "Elevation (m)",
        "Distance to sea (km)",
    )
    _FigB = MakeCrossHeatmap(
        ResidualsDfWeighted,
        "station_celsius",
        "wind",
        "Station temp (°C)",
        "Mean wind vector (m/s)",
    )

    Mo.vstack(
        [
            Mo.md(
                "## Cross Heatmaps: Unweighted vs. GREG-Weighted\n\n"
                "Same idea as the PDPs, in two dimensions. Neither axis below is a GREG "
                "calibration variable, so a shift between panels is a clean signal that "
                "station-network composition was affecting the raw pattern."
            ),
            _FigA,
            _FigB,
        ]
    )
    return


@app.cell
def _(MakeCrossHeatmap, Mo, ResidualsDfWeighted):
    """
    Same elevation x dist_to_sea grid as resid_analysis.py's 2x2 covariate panel,
    but colored by 4 different covariates instead of residual, each shown
    unweighted vs. GREG-weighted. Precipitation is log10'd before averaging,
    matching how it's treated everywhere else in this codebase (heavily
    right-skewed); the other three stay linear, same as resid_analysis.py.
    """
    _Kw = dict(
        Df=ResidualsDfWeighted,
        FeatX="elevation",
        FeatY="dist_to_sea_km",
        Xlabel="Elevation (m)",
        Ylabel="Distance to sea (km)",
        Diverging=False,
    )

    _FigTemp = MakeCrossHeatmap(**_Kw, ColorFeat="station_celsius", SequentialHue="orange")
    _FigNdvi = MakeCrossHeatmap(**_Kw, ColorFeat="ndvi", SequentialHue="green")
    _FigTp = MakeCrossHeatmap(**_Kw, ColorFeat="tp", SequentialHue="blue", Log10Color=True)
    _FigWind = MakeCrossHeatmap(**_Kw, ColorFeat="wind", SequentialHue="violet")

    Mo.vstack(
        [
            Mo.md(
                "## Elevation × Distance to Sea, by Covariate: Unweighted vs. GREG-Weighted\n\n"
                "Same axes as the first heatmap above, but colored by mean station "
                "temperature, NDVI, precipitation (log₁₀), and wind speed instead of "
                "residual. These answer a different question than the residual "
                'heatmaps -- not "is ERA5 biased here" but "what does this part of '
                'the covariate space actually look like" -- and the same '
                "representativeness argument applies: a cell's raw mean can be skewed "
                "by which DEGURBA classes happen to be sampled within it."
            ),
            _FigTemp,
            _FigNdvi,
            _FigTp,
            _FigWind,
        ]
    )
    return


@app.cell
def _(
    AxisColor,
    DegurbaOrder,
    GridColor,
    MutedInk,
    Palette,
    Go,
    Itertools,
    MakeSubplots,
    Mo,
    Np,
    Pd,
    Pdp,
    Pl,
    ResidualsDfWeighted,
):
    """
    Mean residual by distance-to-sea bin (x) x DEGURBA class (y), unweighted vs.
    GREG-weighted.

    Caveat: both axes here are exactly what GREG calibrates on, so the weighted
    panel answers "which cells dominate the corrected national estimate", not
    "does the pattern change" -- that question is only clean when neither axis
    is a calibration variable, as in the two panels above.
    """
    _Df = ResidualsDfWeighted.filter(Pl.col("degurba_label").is_in(DegurbaOrder))
    _Df, _BinsDist = Pdp.BinFeatures(_Df, "dist_to_sea_km", NBins=8)
    _Df = _Df.rename({"bin": "bin_dist"})

    def _Parse(Bins, Dmin, Dmax):
        Out = []
        for B in Bins:
            Lo, Hi = B.strip("(]").split(", ")
            Out.append((Dmin if Lo == "-inf" else float(Lo), Dmax if Hi == "inf" else float(Hi)))
        return Out

    _Edges = _Parse(
        _BinsDist, float(_Df["dist_to_sea_km"].min()), float(_Df["dist_to_sea_km"].max())
    )
    _XLabels = [f"{Lo:.3g}–{Hi:.3g}" for Lo, Hi in _Edges]

    _Full = Pd.DataFrame(
        list(Itertools.product(_BinsDist, DegurbaOrder)), columns=["bin_dist", "degurba_label"]
    )

    def _Grid(Weight):
        if Weight is None:
            Agg = _Df.group_by(["bin_dist", "degurba_label"]).agg(
                Pl.col("residual").mean().alias("v")
            )
        else:
            Agg = _Df.group_by(["bin_dist", "degurba_label"]).agg(
                ((Pl.col("residual") * Pl.col(Weight)).sum() / Pl.col(Weight).sum()).alias("v")
            )
        Heat = _Full.merge(Agg.to_pandas(), on=["bin_dist", "degurba_label"], how="left")
        Z = Heat.pivot(index="degurba_label", columns="bin_dist", values="v").reindex(
            index=DegurbaOrder, columns=_BinsDist
        )
        return Z.to_numpy()

    _ZU = _Grid(None)
    _ZW = _Grid("greg_weight")
    _AbsMax = Np.nanmax(Np.abs(Np.concatenate([_ZU.flatten(), _ZW.flatten()])))
    _Scale = [[0.0, Palette["blue"]], [0.5, "#f0efec"], [1.0, Palette["red"]]]

    FigDistDegurba = MakeSubplots(
        rows=1, cols=2, subplot_titles=["Unweighted", "GREG-weighted"], horizontal_spacing=0.2
    )
    for _Col, _Z in enumerate([_ZU, _ZW], start=1):
        FigDistDegurba.add_trace(
            Go.Heatmap(
                z=_Z,
                x=_XLabels,
                y=DegurbaOrder,
                zmin=-_AbsMax,
                zmax=_AbsMax,
                colorscale=_Scale,
                showscale=(_Col == 2),
                colorbar=dict(title="Mean residual (°C)") if _Col == 2 else None,
                hovertemplate="dist: %{x}<br>%{y}<br>mean residual: %{z:.3f}<extra></extra>",
            ),
            row=1,
            col=_Col,
        )
    FigDistDegurba.update_layout(
        template="plotly_white",
        height=420,
        width=900,
        title="Distance to sea × DEGURBA class",
        margin=dict(t=70, b=60),
    )
    FigDistDegurba.update_xaxes(
        title="Distance to sea (km)",
        tickangle=-40,
        gridcolor=GridColor,
        linecolor=AxisColor,
        tickfont=dict(color=MutedInk),
    )
    FigDistDegurba.update_yaxes(
        gridcolor=GridColor, linecolor=AxisColor, tickfont=dict(color=MutedInk)
    )

    Mo.vstack(
        [
            Mo.md(
                "**Caveat**: both axes here are exactly what GREG calibrates on, so the "
                "weighted panel answers *which cells dominate the corrected national "
                "estimate*, not *does the pattern change* -- see the caveat above."
            ),
            FigDistDegurba,
        ]
    )
    return


if __name__ == "__main__":
    app.run()
