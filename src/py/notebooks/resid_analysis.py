import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import altair as Alt
    import marimo as Mo
    import numpy as Np
    import pandas as Pd
    import polars as Pl

    from py import pdp as Pdp
    from py.cleaning import FeatureRows, LoadResiduals
    from py.publication import ExportNotebookFigure

    return Path, Alt, Mo, Np, Pd, Pdp, Pl, FeatureRows, LoadResiduals, ExportNotebookFigure


@app.cell
def _(Path):
    from py.paths import AnalysisDataDirectory

    return (AnalysisDataDirectory,)


@app.cell
def _(LoadResiduals):
    ResidualsDf = LoadResiduals()
    print(f"{len(ResidualsDf):,} rows · {ResidualsDf['STAID'].n_unique()} stations")
    print("Conservative station screening and source-observation deduplication applied.")
    print("NDVI includes explicitly flagged extrapolation from the latest matching season.")
    return (ResidualsDf,)


@app.cell
def _(Mo, ResidualsDf):
    Mo.md(f"""## Residual analysis

    {len(ResidualsDf):,} observations at {ResidualsDf["STAID"].n_unique():,} stations,
    after conservative temperature screening. Residual = station daily
    maximum minus ERA5-Land daily maximum temperature.

    Each figure uses available values for its own covariates. NDVI uses observed seasonal
    rasters through November 2023 and carries the latest matching season forward when
    unavailable. {ResidualsDf["ndvi_is_extrapolated"].sum():,} rows contain extrapolated NDVI.
    Precipitation is the supplied proxy in metres, and wind is the magnitude of
    the daily mean vector.

    Observation-day windows differ across sources; the dataset also provides a documented
    UTC-day subset. Large ERA5 residuals remain diagnostic flags and are not clipped.
    See the [clean dataset methods](clean_dataset.html) before finalizing paper results.
    """)
    return


@app.cell
async def _(ResidualsDf):
    from py.paper_charts import ExportNotebookStationMap as _ExportNotebookStationMap

    _Fig = await _ExportNotebookStationMap(ResidualsDf)
    _Fig
    return


@app.cell
def _(Alt, Np, Pd, Pdp, FeatureRows):
    def MakePdpAndHist(
        ResidualsDf,
        Feature,
        Xlabel,
        Color="#4C78A8",
        NBins=10,
        HistBins=50,
        Log10=False,
    ):
        import polars as _Pl

        ResidualsDf = FeatureRows(ResidualsDf, [Feature])
        Rng = Np.random.default_rng(1337)
        if Log10:
            ResidualsDf = ResidualsDf.with_columns(
                _Pl.col(Feature).clip(lower_bound=1e-9).log(base=10).alias(Feature)
            )
        DfBinned, Bins = Pdp.BinFeatures(ResidualsDf, Feature, NBins=NBins)
        Means, CiLo, CiHi = Pdp.PdpClusterBootstrap(DfBinned, "bin", Bins, Rng=Rng)
        Centers = Pdp.BinCenters(Bins, DfBinned[Feature].min(), DfBinned[Feature].max())

        FeatMin = float(ResidualsDf[Feature].min())
        FeatMax = float(ResidualsDf[Feature].max())
        XScale = Alt.Scale(domain=[FeatMin, FeatMax], nice=False, zero=False)
        if Log10:
            Xlabel = f"{Xlabel} (log₁₀)"

        PdpDf = Pd.DataFrame({"x": Centers, "mean": Means, "ci_lo": CiLo, "ci_hi": CiHi})

        ZeroRule = (
            Alt.Chart(Pd.DataFrame({"y": [0]}))
            .mark_rule(strokeDash=[4, 4], color="grey", opacity=0.5)
            .encode(y="y:Q")
        )

        Band = (
            Alt.Chart(PdpDf)
            .mark_area(opacity=0.15, color=Color)
            .encode(
                x=Alt.X("x:Q", title=Xlabel, scale=XScale),
                y=Alt.Y("ci_lo:Q", title="Mean residual (°C)"),
                y2=Alt.Y2("ci_hi:Q"),
            )
        )

        Line = (
            Alt.Chart(PdpDf)
            .mark_line(color=Color, strokeWidth=2)
            .encode(
                x=Alt.X("x:Q", scale=XScale),
                y="mean:Q",
            )
        )

        Points = (
            Alt.Chart(PdpDf)
            .mark_point(color=Color, size=70, filled=True)
            .encode(
                x=Alt.X("x:Q", scale=XScale),
                y="mean:Q",
                tooltip=[
                    Alt.Tooltip("x:Q", title=Xlabel, format=".3f"),
                    Alt.Tooltip("mean:Q", title="Mean residual (°C)", format=".3f"),
                    Alt.Tooltip("ci_lo:Q", title="CI low", format=".3f"),
                    Alt.Tooltip("ci_hi:Q", title="CI high", format=".3f"),
                ],
            )
        )

        PdpChart = (ZeroRule + Band + Line + Points).properties(width=560, height=220)

        # Sample to stay under Altair's row limit; same x domain as PDP
        _Series = ResidualsDf[Feature].drop_nulls()
        _Sample = _Series.sample(n=min(4999, _Series.len()), seed=42)
        HistDf = Pd.DataFrame({"val": _Sample.to_numpy()})

        HistChart = (
            Alt.Chart(HistDf)
            .mark_bar(color=Color, opacity=0.6)
            .encode(
                Alt.X("val:Q", bin=Alt.Bin(maxbins=HistBins), title=Xlabel, scale=XScale),
                Alt.Y("count()", title="Count"),
            )
            .properties(width=560, height=100)
        )

        return Alt.vconcat(PdpChart, HistChart, spacing=4)

    return (MakePdpAndHist,)


@app.cell
def _(MakePdpAndHist, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakePdpAndHist(ResidualsDf, "station_celsius", "Station temp (°C)", Color="#E8851A"),
        Notebook="resid_analysis",
        Name="pdp_station_celsius",
    )
    return


@app.cell
def _(MakePdpAndHist, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakePdpAndHist(ResidualsDf, "tp", "Precipitation proxy (m)", Color="#1E90FF", Log10=True),
        Notebook="resid_analysis",
        Name="pdp_tp",
    )
    return


@app.cell
def _(MakePdpAndHist, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakePdpAndHist(ResidualsDf, "wind", "Magnitude of daily mean wind (m/s)", Color="#9370DB"),
        Notebook="resid_analysis",
        Name="pdp_wind",
    )
    return


@app.cell
def _(MakePdpAndHist, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakePdpAndHist(ResidualsDf, "ndvi", "NDVI (incl. extrapolation)", Color="#228B22"),
        Notebook="resid_analysis",
        Name="pdp_ndvi",
    )
    return


@app.cell
def _(MakePdpAndHist, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakePdpAndHist(ResidualsDf, "dist_to_sea_km", "Distance to sea (km)", Color="#4682B4"),
        Notebook="resid_analysis",
        Name="pdp_dist_to_sea_km",
    )
    return


@app.cell
def _(MakePdpAndHist, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakePdpAndHist(ResidualsDf, "elevation", "Elevation (m)", Color="#8B4513"),
        Notebook="resid_analysis",
        Name="pdp_elevation",
    )
    return


@app.cell
def _(Alt, Np, Pd, Pdp, Pl, ResidualsDf, ExportNotebookFigure):
    _DegurbaOrder = [
        "Very low density rural",
        "Low density rural",
        "Rural cluster",
        "Suburban",
        "Semi-dense urban cluster",
        "Dense urban cluster",
        "Urban centre",
    ]
    _Colors = [
        "#90EE90",
        "#228B22",
        "#006400",
        "#FFA500",
        "#FF8C00",
        "#DC143C",
        "#8B0000",
    ]

    _Rng = Np.random.default_rng(1337)
    _DfDegurba = ResidualsDf.filter(Pl.col("degurba_label").is_in(_DegurbaOrder))
    _Means, _CiLo, _CiHi = Pdp.PdpClusterBootstrap(
        _DfDegurba, "degurba_label", _DegurbaOrder, Rng=_Rng
    )

    _PdpDf = Pd.DataFrame(
        {
            "label": _DegurbaOrder,
            "mean": _Means,
            "ci_lo": _CiLo,
            "ci_hi": _CiHi,
            "color": _Colors,
        }
    )

    _ZeroRule = (
        Alt.Chart(Pd.DataFrame({"y": [0]}))
        .mark_rule(strokeDash=[4, 4], color="grey", opacity=0.5)
        .encode(y="y:Q")
    )

    _Bars = (
        Alt.Chart(_PdpDf)
        .mark_bar(opacity=0.8)
        .encode(
            x=Alt.X(
                "label:N",
                sort=_DegurbaOrder,
                title="DEGURBA class",
                axis=Alt.Axis(labelAngle=-30),
            ),
            y=Alt.Y("mean:Q", title="Mean residual (°C)"),
            color=Alt.Color("color:N", scale=None, legend=None),
            tooltip=[
                Alt.Tooltip("label:N", title="Class"),
                Alt.Tooltip("mean:Q", title="Mean residual", format=".3f"),
                Alt.Tooltip("ci_lo:Q", title="CI low", format=".3f"),
                Alt.Tooltip("ci_hi:Q", title="CI high", format=".3f"),
            ],
        )
    )

    _Errorbars = (
        Alt.Chart(_PdpDf)
        .mark_errorbar(color="black", ticks=True)
        .encode(
            x=Alt.X("label:N", sort=_DegurbaOrder),
            y=Alt.Y("ci_lo:Q"),
            y2=Alt.Y2("ci_hi:Q"),
        )
    )

    # Observation shares retain the full-sample denominator.
    _Shares = (
        ResidualsDf.group_by("degurba_label")
        .agg(Pl.len().alias("count"))
        .with_columns((Pl.col("count") / Pl.col("count").sum()).alias("share"))
        .filter(Pl.col("degurba_label").is_in(_DegurbaOrder))
        .to_pandas()
    )

    _Hist = (
        Alt.Chart(_Shares)
        .mark_bar(opacity=0.6, color="#4C78A8")
        .encode(
            x=Alt.X(
                "degurba_label:N",
                sort=_DegurbaOrder,
                title="DEGURBA class",
                axis=Alt.Axis(labelAngle=-30),
            ),
            y=Alt.Y("share:Q", title="Obs share"),
            tooltip=[
                Alt.Tooltip("degurba_label:N", title="Class"),
                Alt.Tooltip("share:Q", title="Share", format=".1%"),
            ],
        )
        .properties(width=640, height=100)
    )

    ExportNotebookFigure(
        Alt.vconcat(
            (_ZeroRule + _Bars + _Errorbars).properties(width=640, height=260),
            _Hist,
            spacing=4,
        ).resolve_scale(x="shared"),
        Notebook="resid_analysis",
        Name="degurba",
    )
    return


@app.cell
def _(Alt, Pd, Pdp, FeatureRows):
    import itertools as _Itertools

    import polars as _Pl

    def MakeCrossHeatmap(
        ResidualsDf,
        FeatX,
        FeatY,
        Xlabel,
        Ylabel,
        NBins=8,
        Title="",
        ColorX="#E8851A",
        ColorY="#4682B4",
        ColorFeat="residual",
        ColorScheme="redblue",
        ColorTitle="Mean residual (°C)",
        Diverging=True,
    ):
        W, H = 360, 300
        ResidualsDf = FeatureRows(ResidualsDf, [FeatX, FeatY, ColorFeat])

        Df, BinsX = Pdp.BinFeatures(ResidualsDf, FeatX, NBins=NBins)
        Df = Df.rename({"bin": "bin_x"})
        Df, BinsY = Pdp.BinFeatures(Df, FeatY, NBins=NBins)
        Df = Df.rename({"bin": "bin_y"})

        # Parse quantile bin edges so heatmap and histograms share the same domain
        def _ParseEdges(Bins, DataMin, DataMax):
            Result = []
            for B in Bins:
                Lo, Hi = B.strip("(]").split(", ")
                Result.append(
                    (
                        float(DataMin) if Lo == "-inf" else float(Lo),
                        float(DataMax) if Hi == "inf" else float(Hi),
                    )
                )
            return Result

        EdgesX = _ParseEdges(BinsX, Df[FeatX].min(), Df[FeatX].max())
        EdgesY = _ParseEdges(BinsY, Df[FeatY].min(), Df[FeatY].max())
        XDomain = [EdgesX[0][0], EdgesX[-1][1]]
        YDomain = [EdgesY[0][0], EdgesY[-1][1]]
        XScale = Alt.Scale(domain=XDomain, nice=False, zero=False)
        YScale = Alt.Scale(domain=YDomain, nice=False, zero=False)

        # Complete grid
        FullGrid = Pd.DataFrame(list(_Itertools.product(BinsX, BinsY)), columns=["bin_x", "bin_y"])
        HeatDf = (
            Df.group_by(["bin_x", "bin_y"])
            .agg(
                _Pl.col(ColorFeat).mean().alias("color_val"),
                _Pl.len().alias("n"),
            )
            .to_pandas()
        )
        HeatDf = FullGrid.merge(HeatDf, on=["bin_x", "bin_y"], how="left")
        HeatDf["x_lo"] = HeatDf["bin_x"].map({B: E[0] for B, E in zip(BinsX, EdgesX)})
        HeatDf["x_hi"] = HeatDf["bin_x"].map({B: E[1] for B, E in zip(BinsX, EdgesX)})
        HeatDf["y_lo"] = HeatDf["bin_y"].map({B: E[0] for B, E in zip(BinsY, EdgesY)})
        HeatDf["y_hi"] = HeatDf["bin_y"].map({B: E[1] for B, E in zip(BinsY, EdgesY)})

        if Diverging:
            AbsMax = HeatDf["color_val"].abs().max()
            CScale = Alt.Scale(scheme=ColorScheme, domain=[-AbsMax, AbsMax])
        else:
            CScale = Alt.Scale(scheme=ColorScheme)

        Heatmap = (
            Alt.Chart(HeatDf)
            .mark_rect()
            .encode(
                x=Alt.X("x_lo:Q", title=Xlabel, scale=XScale),
                x2=Alt.X2("x_hi"),
                y=Alt.Y("y_lo:Q", title=Ylabel, scale=YScale),
                y2=Alt.Y2("y_hi"),
                color=Alt.Color(
                    "color_val:Q",
                    scale=CScale,
                    title=ColorTitle,
                    legend=Alt.Legend(orient="bottom"),
                ),
                tooltip=[
                    Alt.Tooltip("x_lo:Q", title=f"{Xlabel} from", format=".3g"),
                    Alt.Tooltip("x_hi:Q", title=f"{Xlabel} to", format=".3g"),
                    Alt.Tooltip("y_lo:Q", title=f"{Ylabel} from", format=".3g"),
                    Alt.Tooltip("y_hi:Q", title=f"{Ylabel} to", format=".3g"),
                    Alt.Tooltip("color_val:Q", title=ColorTitle, format=".3f"),
                    Alt.Tooltip("n:Q", title="Observations"),
                ],
            )
            .properties(width=W, height=H)
        )

        # Marginal histograms — sampled raw values, same domain as heatmap axes
        _Nx = min(4999, ResidualsDf[FeatX].drop_nulls().len())
        _Ny = min(4999, ResidualsDf[FeatY].drop_nulls().len())
        XHistDf = Pd.DataFrame(
            {"val": ResidualsDf[FeatX].drop_nulls().sample(n=_Nx, seed=42).to_numpy()}
        )
        YHistDf = Pd.DataFrame(
            {"val": ResidualsDf[FeatY].drop_nulls().sample(n=_Ny, seed=42).to_numpy()}
        )

        TopHist = (
            Alt.Chart(XHistDf)
            .mark_bar(color=ColorX, opacity=0.75)
            .encode(
                Alt.X(
                    "val:Q",
                    bin=Alt.Bin(maxbins=40),
                    title=None,
                    scale=XScale,
                    axis=Alt.Axis(labels=False, ticks=False),
                ),
                Alt.Y("count()", title="N", axis=Alt.Axis(tickCount=3)),
            )
            .properties(width=W, height=70)
        )

        RightHist = (
            Alt.Chart(YHistDf)
            .mark_bar(color=ColorY, opacity=0.75)
            .encode(
                Alt.Y(
                    "val:Q",
                    bin=Alt.Bin(maxbins=40),
                    title=None,
                    scale=YScale,
                    axis=Alt.Axis(labels=False, ticks=False),
                ),
                Alt.X("count()", title="N", axis=Alt.Axis(tickCount=3)),
            )
            .properties(width=70, height=H)
        )

        return Alt.vconcat(
            TopHist,
            Alt.hconcat(Heatmap, RightHist, spacing=4),
            spacing=2,
        ).properties(title=Title)

    return (MakeCrossHeatmap,)


@app.cell
def _(MakeCrossHeatmap, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakeCrossHeatmap(
            ResidualsDf,
            "elevation",
            "dist_to_sea_km",
            "Elevation (m)",
            "Distance to sea (km)",
            Title="Elevation x distance to sea",
            ColorX="#8B4513",
            ColorY="#4682B4",
        ),
        Notebook="resid_analysis",
        Name="elevation_by_dist_to_sea_km",
    )
    return


@app.cell
def _(Alt, Pd, Pdp, Pl, ResidualsDf, ExportNotebookFigure):
    import itertools as _It2

    _W, _H = 360, 300
    _DegurbaOrder = [
        "Very low density rural",
        "Low density rural",
        "Rural cluster",
        "Suburban",
        "Semi-dense urban cluster",
        "Dense urban cluster",
        "Urban centre",
    ]
    _Df = ResidualsDf.filter(Pl.col("degurba_label").is_in(_DegurbaOrder))
    _Df, _BinsDist = Pdp.BinFeatures(_Df, "dist_to_sea_km", NBins=8)
    _Df = _Df.rename({"bin": "bin_dist"})

    # Parse bin edges for dist_to_sea (quantitative x-axis)
    def _Parse(Bins, Dmin, Dmax):
        Res = []
        for B in Bins:
            Lo, Hi = B.strip("(]").split(", ")
            Res.append(
                (
                    float(Dmin) if Lo == "-inf" else float(Lo),
                    float(Dmax) if Hi == "inf" else float(Hi),
                )
            )
        return Res

    _Edges = _Parse(_BinsDist, _Df["dist_to_sea_km"].min(), _Df["dist_to_sea_km"].max())
    _XDomain = [_Edges[0][0], _Edges[-1][1]]
    _XScale = Alt.Scale(domain=_XDomain, nice=False, zero=False)

    # Complete grid
    _Full = Pd.DataFrame(
        list(_It2.product(_BinsDist, _DegurbaOrder)), columns=["bin_dist", "degurba_label"]
    )
    _HeatDf = (
        _Df.group_by(["degurba_label", "bin_dist"])
        .agg(Pl.col("residual").mean().alias("mean_residual"), Pl.len().alias("n"))
        .to_pandas()
    )
    _HeatDf = _Full.merge(_HeatDf, on=["bin_dist", "degurba_label"], how="left")
    _HeatDf["x_lo"] = _HeatDf["bin_dist"].map({B: E[0] for B, E in zip(_BinsDist, _Edges)})
    _HeatDf["x_hi"] = _HeatDf["bin_dist"].map({B: E[1] for B, E in zip(_BinsDist, _Edges)})
    _AbsMax = _HeatDf["mean_residual"].abs().max()

    _Heatmap = (
        Alt.Chart(_HeatDf)
        .mark_rect()
        .encode(
            x=Alt.X("x_lo:Q", title="Distance to sea (km)", scale=_XScale),
            x2=Alt.X2("x_hi"),
            y=Alt.Y("degurba_label:O", sort=_DegurbaOrder, title="DEGURBA class"),
            color=Alt.Color(
                "mean_residual:Q",
                scale=Alt.Scale(scheme="redblue", domain=[-_AbsMax, _AbsMax]),
                title="Mean residual (°C)",
                legend=Alt.Legend(orient="bottom"),
            ),
            tooltip=[
                Alt.Tooltip("degurba_label:O", title="DEGURBA"),
                Alt.Tooltip("x_lo:Q", title="Dist from (km)", format=".3g"),
                Alt.Tooltip("x_hi:Q", title="Dist to (km)", format=".3g"),
                Alt.Tooltip("mean_residual:Q", title="Mean residual (°C)", format=".3f"),
                Alt.Tooltip("n:Q", title="Observations"),
            ],
        )
        .properties(width=_W, height=_H)
    )

    # Top histogram: actual dist_to_sea distribution
    _NDist = min(4999, ResidualsDf["dist_to_sea_km"].drop_nulls().len())
    _DistHistDf = Pd.DataFrame(
        {"val": ResidualsDf["dist_to_sea_km"].drop_nulls().sample(n=_NDist, seed=42).to_numpy()}
    )
    _TopHist = (
        Alt.Chart(_DistHistDf)
        .mark_bar(color="#4682B4", opacity=0.75)
        .encode(
            Alt.X(
                "val:Q",
                bin=Alt.Bin(maxbins=40),
                title=None,
                scale=_XScale,
                axis=Alt.Axis(labels=False, ticks=False),
            ),
            Alt.Y("count()", title="N", axis=Alt.Axis(tickCount=3)),
        )
        .properties(width=_W, height=70)
    )

    # Right histogram: degurba class counts with original PDP colors
    _DegurbaColors = {
        "Very low density rural": "#90EE90",
        "Low density rural": "#228B22",
        "Rural cluster": "#006400",
        "Suburban": "#FFA500",
        "Semi-dense urban cluster": "#FF8C00",
        "Dense urban cluster": "#DC143C",
        "Urban centre": "#8B0000",
    }
    _DegurbaCounts = _Df.group_by("degurba_label").agg(Pl.len().alias("count")).to_pandas()
    _RightHist = (
        Alt.Chart(_DegurbaCounts)
        .mark_bar(opacity=0.85)
        .encode(
            y=Alt.Y(
                "degurba_label:O",
                sort=_DegurbaOrder,
                title=None,
                axis=Alt.Axis(labels=False, ticks=False),
            ),
            x=Alt.X("count:Q", title="N", axis=Alt.Axis(tickCount=3)),
            color=Alt.Color(
                "degurba_label:N",
                scale=Alt.Scale(
                    domain=list(_DegurbaColors.keys()), range=list(_DegurbaColors.values())
                ),
                legend=None,
            ),
        )
        .properties(width=70, height=_H)
    )

    ExportNotebookFigure(
        Alt.vconcat(
            _TopHist,
            Alt.hconcat(_Heatmap, _RightHist, spacing=4),
            spacing=2,
        ).properties(title="Distance to sea x urbanisation"),
        Notebook="resid_analysis",
        Name="distance_by_degurba",
    )
    return


@app.cell
def _(MakeCrossHeatmap, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakeCrossHeatmap(
            ResidualsDf,
            "station_celsius",
            "wind",
            "Station temp (°C)",
            "Mean wind vector (m/s)",
            Title="Station temperature x mean wind vector",
            ColorX="#E8851A",
            ColorY="#9370DB",
        ),
        Notebook="resid_analysis",
        Name="station_celsius_by_wind",
    )
    return


@app.cell
def _(MakeCrossHeatmap, ResidualsDf, ExportNotebookFigure):
    ExportNotebookFigure(
        MakeCrossHeatmap(
            ResidualsDf,
            "elevation",
            "wind",
            "Elevation (m)",
            "Mean wind vector (m/s)",
            Title="Elevation x mean wind vector",
            ColorX="#8B4513",
            ColorY="#9370DB",
        ),
        Notebook="resid_analysis",
        Name="elevation_by_wind",
    )
    return


@app.cell
def _(Alt, MakeCrossHeatmap, ResidualsDf, ExportNotebookFigure):
    _Kw = dict(
        ResidualsDf=ResidualsDf,
        FeatX="elevation",
        FeatY="dist_to_sea_km",
        Xlabel="Elevation (m)",
        Ylabel="Distance to sea (km)",
        ColorX="#8B4513",
        ColorY="#4682B4",
        Diverging=False,
    )
    ExportNotebookFigure(
        Alt.vconcat(
            Alt.hconcat(
                MakeCrossHeatmap(
                    **_Kw,
                    Title="Mean station temperature",
                    ColorFeat="station_celsius",
                    ColorScheme="plasma",
                    ColorTitle="Mean station temp (°C)",
                ),
                MakeCrossHeatmap(
                    **_Kw,
                    Title="Mean NDVI",
                    ColorFeat="ndvi",
                    ColorScheme="greens",
                    ColorTitle="Mean NDVI",
                ),
                spacing=20,
            ).resolve_scale(color="independent"),
            Alt.hconcat(
                MakeCrossHeatmap(
                    **_Kw,
                    Title="Mean precipitation",
                    ColorFeat="tp",
                    ColorScheme="blues",
                    ColorTitle="Mean precipitation proxy (m)",
                ),
                MakeCrossHeatmap(
                    **_Kw,
                    Title="Mean wind-vector magnitude",
                    ColorFeat="wind",
                    ColorScheme="purples",
                    ColorTitle="Mean wind (m/s)",
                ),
                spacing=20,
            ).resolve_scale(color="independent"),
            spacing=30,
        ).resolve_scale(color="independent"),
        Notebook="resid_analysis",
        Name="geography_covariates",
    )
    return


if __name__ == "__main__":
    app.run()
