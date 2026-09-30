import marimo

__generated_with = "0.23.8"
app = marimo.App(width="medium")


@app.cell
def _():
    from pathlib import Path

    import altair as alt
    import numpy as np
    import pandas as pd
    import plotly.express as px
    import polars as pl

    from era5_analysis import pdp

    return Path, alt, np, pd, pdp, pl, px


@app.cell
def _(Path):
    DATA2 = Path("/home2/lobib/gen_hack/data2")
    return (DATA2,)


@app.cell
def _(DATA2, pl):
    residuals_df = pl.read_parquet(DATA2 / "residuals.parquet").drop_nulls()
    print(f"{len(residuals_df):,} rows · {residuals_df['STAID'].n_unique()} stations")
    return (residuals_df,)


@app.cell
def _(pl, px, residuals_df):
    _station_mean = residuals_df.group_by("STAID").agg(
        pl.col("residual").mean(),
        pl.col("lon").first(),
        pl.col("lat").first(),
        pl.col("place").first(),
        pl.col("country").first(),
    )

    _fig = px.scatter_map(
        _station_mean,
        lat="lat",
        lon="lon",
        color="residual",
        color_continuous_scale="RdBu_r",
        range_color=[-3, 3],
        zoom=3,
        center={"lat": 50, "lon": 10},
        hover_data=["STAID", "place", "country", "residual"],
        title="Mean residual per station (°C) — station minus ERA5",
    )
    _fig.update_traces(marker=dict(size=6))
    _fig.update_layout(
        height=700,
        template="plotly_white",
        coloraxis_colorbar_title="WS − ERA5 (°C)",
        map_style="open-street-map",
    )
    _fig
    return


@app.cell
def _(alt, np, pd, pdp):
    def make_pdp_and_hist(
        residuals_df,
        feature,
        xlabel,
        color="#4C78A8",
        n_bins=10,
        hist_bins=50,
        log10=False,
    ):
        import polars as _pl

        rng = np.random.default_rng(1337)
        if log10:
            residuals_df = residuals_df.with_columns(
                _pl.col(feature).clip(lower_bound=1e-9).log(base=10).alias(feature)
            )
        df_binned, bins = pdp.bin_features(residuals_df, feature, n_bins=n_bins)
        means, ci_lo, ci_hi = pdp.pdp_cluster_bootstrap(
            df_binned, "bin", bins, rng=rng
        )
        centers = pdp.bin_centers(
            bins, df_binned[feature].min(), df_binned[feature].max()
        )

        feat_min = float(residuals_df[feature].min())
        feat_max = float(residuals_df[feature].max())
        x_scale = alt.Scale(domain=[feat_min, feat_max], nice=False, zero=False)
        if log10:
            xlabel = f"{xlabel} (log₁₀)"

        pdp_df = pd.DataFrame(
            {"x": centers, "mean": means, "ci_lo": ci_lo, "ci_hi": ci_hi}
        )

        zero_rule = (
            alt.Chart(pd.DataFrame({"y": [0]}))
            .mark_rule(strokeDash=[4, 4], color="grey", opacity=0.5)
            .encode(y="y:Q")
        )

        band = alt.Chart(pdp_df).mark_area(opacity=0.15, color=color).encode(
            x=alt.X("x:Q", title=xlabel, scale=x_scale),
            y=alt.Y("ci_lo:Q", title="Mean residual (°C)"),
            y2=alt.Y2("ci_hi:Q"),
        )

        line = alt.Chart(pdp_df).mark_line(color=color, strokeWidth=2).encode(
            x=alt.X("x:Q", scale=x_scale),
            y="mean:Q",
        )

        points = (
            alt.Chart(pdp_df)
            .mark_point(color=color, size=70, filled=True)
            .encode(
                x=alt.X("x:Q", scale=x_scale),
                y="mean:Q",
                tooltip=[
                    alt.Tooltip("x:Q", title=xlabel, format=".3f"),
                    alt.Tooltip("mean:Q", title="Mean residual (°C)", format=".3f"),
                    alt.Tooltip("ci_lo:Q", title="CI low", format=".3f"),
                    alt.Tooltip("ci_hi:Q", title="CI high", format=".3f"),
                ],
            )
        )

        pdp_chart = (zero_rule + band + line + points).properties(
            width=560, height=220
        )

        # Sample to stay under Altair's row limit; same x domain as PDP
        _series = residuals_df[feature].drop_nulls()
        _sample = _series.sample(n=min(4999, _series.len()), seed=42)
        hist_df = pd.DataFrame({"val": _sample.to_numpy()})

        hist_chart = (
            alt.Chart(hist_df)
            .mark_bar(color=color, opacity=0.6)
            .encode(
                alt.X("val:Q", bin=alt.Bin(maxbins=hist_bins), title=xlabel, scale=x_scale),
                alt.Y("count()", title="Count"),
            )
            .properties(width=560, height=100)
        )

        return alt.vconcat(pdp_chart, hist_chart, spacing=4)

    return (make_pdp_and_hist,)


@app.cell
def _(make_pdp_and_hist, residuals_df):
    make_pdp_and_hist(
        residuals_df, "station_celsius", "Station temp (°C)", color="#E8851A"
    )
    return


@app.cell
def _(make_pdp_and_hist, residuals_df):
    make_pdp_and_hist(
        residuals_df, "tp", "Precipitation (m/day)", color="#1E90FF", log10=True
    )
    return


@app.cell
def _(make_pdp_and_hist, residuals_df):
    make_pdp_and_hist(residuals_df, "wind", "Wind speed (m/s)", color="#9370DB")
    return


@app.cell
def _(make_pdp_and_hist, residuals_df):
    make_pdp_and_hist(residuals_df, "ndvi", "NDVI", color="#228B22")
    return


@app.cell
def _(make_pdp_and_hist, residuals_df):
    make_pdp_and_hist(
        residuals_df, "dist_to_sea_km", "Distance to sea (km)", color="#4682B4"
    )
    return


@app.cell
def _(make_pdp_and_hist, residuals_df):
    make_pdp_and_hist(residuals_df, "elevation", "Elevation (m)", color="#8B4513")
    return


@app.cell
def _(alt, np, pd, pdp, pl, residuals_df):
    _degurba_order = [
        "Very low density rural",
        "Low density rural",
        "Rural cluster",
        "Suburban",
        "Semi-dense urban cluster",
        "Dense urban cluster",
        "Urban centre",
    ]
    _colors = [
        "#90EE90",
        "#228B22",
        "#006400",
        "#FFA500",
        "#FF8C00",
        "#DC143C",
        "#8B0000",
    ]

    _rng = np.random.default_rng(1337)
    _df_degurba = residuals_df.filter(pl.col("degurba_label").is_in(_degurba_order))
    _means, _ci_lo, _ci_hi = pdp.pdp_cluster_bootstrap(
        _df_degurba, "degurba_label", _degurba_order, rng=_rng
    )

    _pdp_df = pd.DataFrame(
        {
            "label": _degurba_order,
            "mean": _means,
            "ci_lo": _ci_lo,
            "ci_hi": _ci_hi,
            "color": _colors,
        }
    )

    _zero_rule = (
        alt.Chart(pd.DataFrame({"y": [0]}))
        .mark_rule(strokeDash=[4, 4], color="grey", opacity=0.5)
        .encode(y="y:Q")
    )

    _bars = (
        alt.Chart(_pdp_df)
        .mark_bar(opacity=0.8)
        .encode(
            x=alt.X(
                "label:N",
                sort=_degurba_order,
                title="DEGURBA class",
                axis=alt.Axis(labelAngle=-30),
            ),
            y=alt.Y("mean:Q", title="Mean residual (°C)"),
            color=alt.Color(
                "color:N", scale=None, legend=None
            ),
            tooltip=[
                alt.Tooltip("label:N", title="Class"),
                alt.Tooltip("mean:Q", title="Mean residual", format=".3f"),
                alt.Tooltip("ci_lo:Q", title="CI low", format=".3f"),
                alt.Tooltip("ci_hi:Q", title="CI high", format=".3f"),
            ],
        )
    )

    _errorbars = (
        alt.Chart(_pdp_df)
        .mark_errorbar(color="black", ticks=True)
        .encode(
            x=alt.X("label:N", sort=_degurba_order),
            y=alt.Y("ci_lo:Q"),
            y2=alt.Y2("ci_hi:Q"),
        )
    )

    # Histogram: station share per class
    _shares = (
        residuals_df.group_by("degurba_label")
        .agg(pl.len().alias("count"))
        .with_columns((pl.col("count") / pl.col("count").sum()).alias("share"))
        .to_pandas()
    )

    _hist = (
        alt.Chart(_shares)
        .mark_bar(opacity=0.6, color="#4C78A8")
        .encode(
            x=alt.X(
                "degurba_label:N",
                sort=_degurba_order,
                title="DEGURBA class",
                axis=alt.Axis(labelAngle=-30),
            ),
            y=alt.Y("share:Q", title="Obs share"),
            tooltip=[
                alt.Tooltip("degurba_label:N", title="Class"),
                alt.Tooltip("share:Q", title="Share", format=".1%"),
            ],
        )
        .properties(width=560, height=100)
    )

    alt.vconcat(
        (_zero_rule + _bars + _errorbars).properties(width=560, height=260),
        _hist,
        spacing=4,
    ).resolve_scale(x="shared")
    return


@app.cell
def _(alt, pd, pdp):
    import itertools as _itertools
    import polars as _pl

    def make_cross_heatmap(residuals_df, feat_x, feat_y, xlabel, ylabel, n_bins=8, title="",
                           color_x="#E8851A", color_y="#4682B4",
                           color_feat="residual", color_scheme="redblue", color_title="Mean residual (°C)",
                           diverging=True):
        W, H = 360, 300

        df, bins_x = pdp.bin_features(residuals_df, feat_x, n_bins=n_bins)
        df = df.rename({"bin": "bin_x"})
        df, bins_y = pdp.bin_features(df, feat_y, n_bins=n_bins)
        df = df.rename({"bin": "bin_y"})

        # Parse quantile bin edges so heatmap and histograms share the same domain
        def _parse_edges(bins, data_min, data_max):
            result = []
            for b in bins:
                lo, hi = b.strip("(]").split(", ")
                result.append((
                    float(data_min) if lo == "-inf" else float(lo),
                    float(data_max) if hi == "inf" else float(hi),
                ))
            return result

        edges_x = _parse_edges(bins_x, df[feat_x].min(), df[feat_x].max())
        edges_y = _parse_edges(bins_y, df[feat_y].min(), df[feat_y].max())
        x_domain = [edges_x[0][0], edges_x[-1][1]]
        y_domain = [edges_y[0][0], edges_y[-1][1]]
        x_scale = alt.Scale(domain=x_domain, nice=False, zero=False)
        y_scale = alt.Scale(domain=y_domain, nice=False, zero=False)

        # Complete grid
        full_grid = pd.DataFrame(
            list(_itertools.product(bins_x, bins_y)), columns=["bin_x", "bin_y"]
        )
        heat_df = (
            df.group_by(["bin_x", "bin_y"])
            .agg(
                _pl.col(color_feat).mean().alias("color_val"),
                _pl.len().alias("n"),
            )
            .to_pandas()
        )
        heat_df = full_grid.merge(heat_df, on=["bin_x", "bin_y"], how="left")
        heat_df["x_lo"] = heat_df["bin_x"].map({b: e[0] for b, e in zip(bins_x, edges_x)})
        heat_df["x_hi"] = heat_df["bin_x"].map({b: e[1] for b, e in zip(bins_x, edges_x)})
        heat_df["y_lo"] = heat_df["bin_y"].map({b: e[0] for b, e in zip(bins_y, edges_y)})
        heat_df["y_hi"] = heat_df["bin_y"].map({b: e[1] for b, e in zip(bins_y, edges_y)})

        if diverging:
            abs_max = heat_df["color_val"].abs().max()
            c_scale = alt.Scale(scheme=color_scheme, domain=[-abs_max, abs_max])
        else:
            c_scale = alt.Scale(scheme=color_scheme)

        heatmap = (
            alt.Chart(heat_df)
            .mark_rect()
            .encode(
                x=alt.X("x_lo:Q", title=xlabel, scale=x_scale),
                x2=alt.X2("x_hi"),
                y=alt.Y("y_lo:Q", title=ylabel, scale=y_scale),
                y2=alt.Y2("y_hi"),
                color=alt.Color(
                    "color_val:Q",
                    scale=c_scale,
                    title=color_title,
                    legend=alt.Legend(orient="bottom"),
                ),
                tooltip=[
                    alt.Tooltip("x_lo:Q", title=f"{xlabel} from", format=".3g"),
                    alt.Tooltip("x_hi:Q", title=f"{xlabel} to", format=".3g"),
                    alt.Tooltip("y_lo:Q", title=f"{ylabel} from", format=".3g"),
                    alt.Tooltip("y_hi:Q", title=f"{ylabel} to", format=".3g"),
                    alt.Tooltip("color_val:Q", title=color_title, format=".3f"),
                    alt.Tooltip("n:Q", title="Observations"),
                ],
            )
            .properties(width=W, height=H)
        )

        # Marginal histograms — sampled raw values, same domain as heatmap axes
        _nx = min(4999, residuals_df[feat_x].drop_nulls().len())
        _ny = min(4999, residuals_df[feat_y].drop_nulls().len())
        x_hist_df = pd.DataFrame({"val": residuals_df[feat_x].drop_nulls().sample(n=_nx, seed=42).to_numpy()})
        y_hist_df = pd.DataFrame({"val": residuals_df[feat_y].drop_nulls().sample(n=_ny, seed=42).to_numpy()})

        top_hist = (
            alt.Chart(x_hist_df)
            .mark_bar(color=color_x, opacity=0.75)
            .encode(
                alt.X("val:Q", bin=alt.Bin(maxbins=40), title=None, scale=x_scale,
                      axis=alt.Axis(labels=False, ticks=False)),
                alt.Y("count()", title="N", axis=alt.Axis(tickCount=3)),
            )
            .properties(width=W, height=70)
        )

        right_hist = (
            alt.Chart(y_hist_df)
            .mark_bar(color=color_y, opacity=0.75)
            .encode(
                alt.Y("val:Q", bin=alt.Bin(maxbins=40), title=None, scale=y_scale,
                      axis=alt.Axis(labels=False, ticks=False)),
                alt.X("count()", title="N", axis=alt.Axis(tickCount=3)),
            )
            .properties(width=70, height=H)
        )

        return (
            alt.vconcat(
                top_hist,
                alt.hconcat(heatmap, right_hist, spacing=4),
                spacing=2,
            )
            .properties(title=title)
        )

    return (make_cross_heatmap,)


@app.cell
def _(make_cross_heatmap, residuals_df):
    make_cross_heatmap(
        residuals_df, "elevation", "dist_to_sea_km",
        "Elevation (m)", "Distance to sea (km)",
        title="Elevation x distance to sea",
        color_x="#8B4513", color_y="#4682B4",
    )
    return


@app.cell
def _(alt, pd, pdp, pl, residuals_df):
    import itertools as _it2

    _W, _H = 360, 300
    _degurba_order = [
        "Very low density rural", "Low density rural", "Rural cluster",
        "Suburban", "Semi-dense urban cluster", "Dense urban cluster", "Urban centre",
    ]
    _df = residuals_df.filter(pl.col("degurba_label").is_in(_degurba_order))
    _df, _bins_dist = pdp.bin_features(_df, "dist_to_sea_km", n_bins=8)
    _df = _df.rename({"bin": "bin_dist"})

    # Parse bin edges for dist_to_sea (quantitative x-axis)
    def _parse(bins, dmin, dmax):
        res = []
        for b in bins:
            lo, hi = b.strip("(]").split(", ")
            res.append((float(dmin) if lo == "-inf" else float(lo),
                        float(dmax) if hi == "inf" else float(hi)))
        return res

    _edges = _parse(_bins_dist, _df["dist_to_sea_km"].min(), _df["dist_to_sea_km"].max())
    _x_domain = [_edges[0][0], _edges[-1][1]]
    _x_scale = alt.Scale(domain=_x_domain, nice=False, zero=False)

    # Complete grid
    _full = pd.DataFrame(list(_it2.product(_bins_dist, _degurba_order)), columns=["bin_dist", "degurba_label"])
    _heat_df = (
        _df.group_by(["degurba_label", "bin_dist"])
        .agg(pl.col("residual").mean().alias("mean_residual"), pl.len().alias("n"))
        .to_pandas()
    )
    _heat_df = _full.merge(_heat_df, on=["bin_dist", "degurba_label"], how="left")
    _heat_df["x_lo"] = _heat_df["bin_dist"].map({b: e[0] for b, e in zip(_bins_dist, _edges)})
    _heat_df["x_hi"] = _heat_df["bin_dist"].map({b: e[1] for b, e in zip(_bins_dist, _edges)})
    _abs_max = _heat_df["mean_residual"].abs().max()

    _heatmap = (
        alt.Chart(_heat_df)
        .mark_rect()
        .encode(
            x=alt.X("x_lo:Q", title="Distance to sea (km)", scale=_x_scale),
            x2=alt.X2("x_hi"),
            y=alt.Y("degurba_label:O", sort=_degurba_order, title="DEGURBA class"),
            color=alt.Color(
                "mean_residual:Q",
                scale=alt.Scale(scheme="redblue", domain=[-_abs_max, _abs_max]),
                title="Mean residual (°C)",
                legend=alt.Legend(orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("degurba_label:O", title="DEGURBA"),
                alt.Tooltip("x_lo:Q", title="Dist from (km)", format=".3g"),
                alt.Tooltip("x_hi:Q", title="Dist to (km)", format=".3g"),
                alt.Tooltip("mean_residual:Q", title="Mean residual (°C)", format=".3f"),
                alt.Tooltip("n:Q", title="Observations"),
            ],
        )
        .properties(width=_W, height=_H)
    )

    # Top histogram: actual dist_to_sea distribution
    _n_dist = min(4999, residuals_df["dist_to_sea_km"].drop_nulls().len())
    _dist_hist_df = pd.DataFrame({"val": residuals_df["dist_to_sea_km"].drop_nulls().sample(n=_n_dist, seed=42).to_numpy()})
    _top_hist = (
        alt.Chart(_dist_hist_df)
        .mark_bar(color="#4682B4", opacity=0.75)
        .encode(
            alt.X("val:Q", bin=alt.Bin(maxbins=40), title=None, scale=_x_scale,
                  axis=alt.Axis(labels=False, ticks=False)),
            alt.Y("count()", title="N", axis=alt.Axis(tickCount=3)),
        )
        .properties(width=_W, height=70)
    )

    # Right histogram: degurba class counts with original PDP colors
    _degurba_colors = {
        "Very low density rural": "#90EE90",
        "Low density rural": "#228B22",
        "Rural cluster": "#006400",
        "Suburban": "#FFA500",
        "Semi-dense urban cluster": "#FF8C00",
        "Dense urban cluster": "#DC143C",
        "Urban centre": "#8B0000",
    }
    _degurba_counts = (
        _df.group_by("degurba_label")
        .agg(pl.len().alias("count"))
        .to_pandas()
    )
    _right_hist = (
        alt.Chart(_degurba_counts)
        .mark_bar(opacity=0.85)
        .encode(
            y=alt.Y("degurba_label:O", sort=_degurba_order, title=None,
                    axis=alt.Axis(labels=False, ticks=False)),
            x=alt.X("count:Q", title="N", axis=alt.Axis(tickCount=3)),
            color=alt.Color("degurba_label:N",
                            scale=alt.Scale(domain=list(_degurba_colors.keys()),
                                            range=list(_degurba_colors.values())),
                            legend=None),
        )
        .properties(width=70, height=_H)
    )

    alt.vconcat(
        _top_hist,
        alt.hconcat(_heatmap, _right_hist, spacing=4),
        spacing=2,
    ).properties(title="Distance to sea x urbanisation")
    return


@app.cell
def _(make_cross_heatmap, residuals_df):
    make_cross_heatmap(
        residuals_df, "station_celsius", "wind",
        "Station temp (°C)", "Wind speed (m/s)",
        title="Station temperature x wind speed",
        color_x="#E8851A", color_y="#9370DB",
    )
    return


@app.cell
def _(make_cross_heatmap, residuals_df):
    make_cross_heatmap(
        residuals_df, "elevation", "wind",
        "Elevation (m)", "Wind speed (m/s)",
        title="Elevation x wind speed",
        color_x="#8B4513", color_y="#9370DB",
    )
    return


@app.cell
def _(alt, make_cross_heatmap, residuals_df):
    _kw = dict(
        residuals_df=residuals_df,
        feat_x="elevation", feat_y="dist_to_sea_km",
        xlabel="Elevation (m)", ylabel="Distance to sea (km)",
        color_x="#8B4513", color_y="#4682B4",
        diverging=False,
    )
    alt.vconcat(
        alt.hconcat(
            make_cross_heatmap(**_kw, title="Mean station temperature",
                               color_feat="station_celsius", color_scheme="plasma",
                               color_title="Mean station temp (°C)"),
            make_cross_heatmap(**_kw, title="Mean NDVI",
                               color_feat="ndvi", color_scheme="greens",
                               color_title="Mean NDVI"),
            spacing=20,
        ).resolve_scale(color="independent"),
        alt.hconcat(
            make_cross_heatmap(**_kw, title="Mean precipitation",
                               color_feat="tp", color_scheme="blues",
                               color_title="Mean precipitation (m/day)"),
            make_cross_heatmap(**_kw, title="Mean wind speed",
                               color_feat="wind", color_scheme="purples",
                               color_title="Mean wind (m/s)"),
            spacing=20,
        ).resolve_scale(color="independent"),
        spacing=30,
    ).resolve_scale(color="independent")
    return


if __name__ == "__main__":
    app.run()
