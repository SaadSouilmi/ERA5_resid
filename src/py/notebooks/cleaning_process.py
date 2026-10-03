import marimo

__generated_with = "0.23.8"
app = marimo.App(width="full")


@app.cell
def _():
    import hashlib as Hashlib
    import html as Html
    import json as Json

    import altair as Alt
    import marimo as Mo
    import polars as Pl

    from py.cleaning import FeatureRows
    from py.paths import AnalysisDataDirectory
    from py.publication import ExportNotebookFigure, PaperStyle

    return (
        Alt,
        AnalysisDataDirectory,
        ExportNotebookFigure,
        FeatureRows,
        Hashlib,
        Html,
        Json,
        Mo,
        PaperStyle,
        Pl,
    )


@app.cell
def _(AnalysisDataDirectory, Hashlib, Json, Pl):
    CleanDirectory = AnalysisDataDirectory / "clean"
    AuditDirectory = AnalysisDataDirectory / "cleaning_audit"
    Summary = Json.loads((CleanDirectory / "summary.json").read_text())
    Audit = Json.loads((AuditDirectory / "summary.json").read_text())
    Clean = Pl.scan_parquet(CleanDirectory / "analysis.parquet")
    Exclusions = Pl.read_csv(CleanDirectory / "exclusion_counts.csv")
    EraChecks = Pl.read_csv(CleanDirectory / "era5_full_checks.csv")
    Windows = Pl.read_csv(CleanDirectory / "observation_windows.csv")
    Review = Pl.read_csv(CleanDirectory / "temperature_review.csv")
    StationQuality = Pl.read_csv(CleanDirectory / "station_quality.csv")

    def Digest(File):
        with File.open("rb") as Stream:
            return Hashlib.file_digest(Stream, "sha256").hexdigest()

    assert Digest(CleanDirectory / "analysis.parquet") == Summary["cleaned_data_sha256"]
    assert Digest(AnalysisDataDirectory / "residuals.parquet") == Summary["raw_input_sha256"]
    assert Digest(AnalysisDataDirectory / "residuals_cleaned.parquet") == Summary["input_sha256"]
    assert Summary["raw_input_sha256"] == Audit["input_sha256"]
    assert Summary["input_sha256"] == Audit["cleaned_data_sha256"]
    return (
        Audit,
        Clean,
        CleanDirectory,
        EraChecks,
        Exclusions,
        Review,
        StationQuality,
        Summary,
        Windows,
    )


@app.cell
def _(Html, Mo):
    def Table(Frame):
        def Format(Value):
            if Value is None:
                return ""
            if isinstance(Value, bool):
                return str(Value)
            if isinstance(Value, int):
                return f"{Value:,}"
            if isinstance(Value, float):
                return f"{Value:.6g}"
            return Html.escape(str(Value))

        Header = "".join(f"<th>{Html.escape(Name)}</th>" for Name in Frame.columns)
        Rows = "".join(
            "<tr>" + "".join(f"<td>{Format(Value)}</td>" for Value in Row) + "</tr>"
            for Row in Frame.iter_rows()
        )
        return Mo.Html(
            f'<table class="oddeven"><thead><tr>{Header}</tr></thead><tbody>{Rows}</tbody></table>'
        )

    return (Table,)


@app.cell
def _(Audit, Mo, Summary):
    Mo.md(f"""
    # How the station–ERA5 dataset was cleaned

    The current release contains **{Summary["cleaned_rows"]:,} station-day pairs at
    {Summary["cleaned_stations"]:,} nominal station IDs**, starting from
    {Audit["input_rows"]:,} pairs at {Audit["input_stations"]:,} IDs.
    A residual is **station daily maximum temperature minus ERA5-Land daily maximum
    temperature**, in °C. Positive residuals mean ERA5 is cooler.

    This notebook documents the implemented decisions, shows their effect in order,
    and checks the saved release. Its numbers come from the audit CSV/JSON files and
    the actual cleaned Parquet file. It does not rerun or overwrite the raw-data build.
    The input hashes are verified when the notebook runs.

    “Clean” means this explicit conservative selection policy has been applied.
    Station screening remains provisional. Mixed observation-day windows, source
    blending, and the limitations of the covariates remain relevant to interpretation.
    """)
    return


@app.cell
def _(Audit, Exclusions, Pl, Summary):
    _Counts = dict(Exclusions.select("exclusion_reason", "len").iter_rows())
    _Remaining = Audit["input_rows"]
    _Rows = [{"Step": "0. Supplied station–ERA5 pairs", "Removed": 0, "Retained": _Remaining}]
    _Rules = [
        ("1. Inside the ERA5 footprint", Audit["outside_grid_rows"]),
        ("2. No substituted land cell", _Counts.get("era5_land_fallback", 0)),
        ("3. Station series passes screening policy", _Counts.get("station_series_quarantined", 0)),
        ("4. Valid observation source", _Counts.get("invalid_observation_source", 0)),
        (
            "5. Source location selects the saved cell",
            _Counts.get("source_location_grid_mismatch", 0),
        ),
        ("6. One copy per source and date", _Counts.get("reused_source_observation", 0)),
    ]
    for _Label, _Removed in _Rules:
        _Remaining -= _Removed
        _Rows.append({"Step": _Label, "Removed": _Removed, "Retained": _Remaining})
    assert _Remaining == Summary["cleaned_rows"]
    assert Audit["cleaned_rows"] == Summary["input_rows"]
    Selection = Pl.DataFrame(_Rows).with_columns(
        (100 * Pl.col("Retained") / Audit["input_rows"]).alias("Percent of original")
    )
    return (Selection,)


@app.cell
def _(Mo, Selection, Table):
    Mo.vstack(
        [
            Mo.md("""
        ## Selection, in execution order

        These are **sequential, mutually exclusive removal counts**. A row that fails
        several rules is assigned the first applicable reason. They are not counts of
        how many rows would fail each rule independently. The original files remain intact.
        """),
            Table(Selection),
        ]
    )
    return


@app.cell
def _(Alt, ExportNotebookFigure, PaperStyle, Selection):
    _Chart = (
        Alt.Chart(Selection)
        .mark_bar(color="#0072B2")
        .encode(
            x=Alt.X("Retained:Q", title="Retained station-day pairs", axis=Alt.Axis(format="~s")),
            y=Alt.Y(
                "Step:N",
                sort=Selection["Step"].to_list(),
                title=None,
                axis=Alt.Axis(labelLimit=330),
            ),
            tooltip=[
                "Step:N",
                Alt.Tooltip("Retained:Q", format=","),
                Alt.Tooltip("Removed:Q", format=","),
            ],
        )
        .properties(width=480, height=230)
    )
    ExportNotebookFigure(PaperStyle(_Chart), "cleaning_process", "selection_counts")
    return


@app.cell
def _(Audit, Mo):
    Mo.md(f"""
    ## Before selection: validate values and identities

    The supplied table is `data2/residuals.parquet`. The first audit checks for duplicate
    `(STAID, date)` pairs, finite temperatures and coordinates, and
    `residual = station_celsius - era5_celsius`. There were
    **{Audit["duplicate_station_dates"]:,} duplicate station-days** in this input.

    Saved station temperatures are joined back to the ECA&D TX files using station ID
    and date. They must equal `TX / 10`, must not use the missing-value sentinel, and
    must have `Q_TX = 0`. A mismatch stops the build rather than silently correcting
    the observation. The saved source-quality audit found
    **{Audit["source_quality_mismatches"]:,} mismatches**.

    ECA&D blended series can borrow observations from another source. `STAID` is the
    nominal series; `SOUID` identifies the actual observation source. Source coordinates,
    elevation and observation-window code are attached to each observation. In this
    supplied release, participant source metadata IDs require an inferred +100000
    offset; synoptic IDs match directly. Both IDs and the offset are retained, and
    ambiguous matches stop the build. This mapping is reproducible but still merits
    confirmation from the provider.

    ## 1. Remove matches outside the supplied ERA5 grid

    Nearest-coordinate lookup otherwise snaps stations outside the downloaded region
    to a boundary cell. The footprint check uses the supplied 0.1° grid plus half a
    grid-cell margin: longitude −25.05° to 40.95°, latitude 34.95° to 69.95°.
    It removes **{Audit["outside_grid_rows"]:,} rows at
    {Audit["outside_grid_stations"]:,} station IDs**.

    `data2/residuals_cleaned.parquet` is the preserved intermediate result:
    **{Audit["cleaned_rows"]:,} rows at {Audit["cleaned_stations"]:,} station IDs**.
    At this stage invalid covariates are masked, not used to discard temperature pairs.
    The final build later recalculates the geographic and vegetation covariates.
    """)
    return


@app.cell
def _(EraChecks, Mo, Summary, Table):
    assert EraChecks["sampled_station_days"].sum() == Summary["input_rows"]
    assert all(
        EraChecks[Name].sum() == 0 for Name in EraChecks.columns if Name.endswith("mismatches")
    )
    Mo.vstack(
        [
            Mo.md(f"""
        ## Validate the ERA5 extraction on every in-grid pair

        The first audit sampled dates. The final build expanded that comparison to
        **all {Summary["input_rows"]:,} in-grid station-days** against the supplied daily
        NetCDF files: maximum temperature, mean-vector wind magnitude and precipitation proxy.
        Every stored value agrees; the table below is the full check, not the earlier sample.

        This verifies extraction, units and arithmetic against those files. It does not
        independently validate the instruments or the upstream daily-aggregation recipe.
        """),
            Table(EraChecks),
        ]
    )
    return


@app.cell
def _(Mo, Summary):
    Mo.md(f"""
    ## 2. Exclude substitutions of a different ERA5 land cell

    Some original matches replaced the nearest grid cell with a more distant land cell.
    The conservative baseline excludes `era5_land_fallback = True`, including a missing
    fallback flag. This avoids mixing two spatial-matching rules in the same baseline.
    It can reduce coastal and island coverage; exclusion does not mean the station is bad.

    ## 3. Quarantine suspect station series using station evidence

    Screening uses unique `(SOUID, date)` observations at their actual source locations.
    Copies borrowed by several station series do not count as independent evidence.
    An observation is flagged if any of the following holds:

    1. TX is outside **[−60, 50] °C**.
    2. TX is over **20 °C above both**, or over **20 °C below both**, adjacent calendar days.
       Both neighbours in time must exist; a gap is not treated as consecutive days.
    3. TX differs by over **20 °C** from the median of at least **three** available
       same-day neighbours. Candidates are 15–100 km away and within 300 m elevation.
       The code checks the nearest 64 candidates and keeps up to ten distinct locations.

    Missing neighbour coverage is recorded; it does not imply a passed spatial check.
    These deliberately conservative thresholds are **provisional review rules**, not a
    calibrated climatological QC algorithm. They flag
    **{Summary["source_flagged_observations"]:,} source-days** and quarantine
    **{Summary["quarantined_stations"]:,} nominal station series** that use any flagged source.
    Whole series are excluded, including their otherwise unflagged days. The sequential
    count above is smaller than an independent count because land substitutions were
    already excluded.

    **Neither ERA5 temperature nor residual magnitude is used for this selection.**
    Large station–ERA5 differences remain diagnostic flags, not exclusion thresholds.
    """)
    return


@app.cell
def _(Mo, Pl, Review, Table):
    _Unique = Review.unique(subset=["SOUID", "date"])
    _Flags = Pl.DataFrame(
        [
            {"Review rule": _Name, "Flagged source-days": _Unique[_Column].sum()}
            for _Name, _Column in [
                ("Range", "source_range_flag"),
                ("Neighbour disagreement", "source_spatial_flag"),
                ("Isolated temporal spike", "source_spike_flag"),
            ]
        ]
    )
    Mo.vstack(
        [
            Mo.md(
                "### Saved screening evidence\n\nRules can overlap, so these counts need not sum to the number of flagged source-days."
            ),
            Table(_Flags),
            Mo.md(
                "First eight flagged source-days, with the saved evidence; missing values indicate unavailable comparisons."
            ),
            Table(
                _Unique.sort("SOUID", "date")
                .select(
                    "SOUID",
                    "date",
                    "station_celsius",
                    "previous_day",
                    "next_day",
                    "neighbor_median",
                    "neighbor_count",
                )
                .head(8)
            ),
        ]
    )
    return


@app.cell
def _(Mo):
    Mo.md("""
    ## 4. Require a valid observation source

    Source identity and `Q_TX = 0` are required. Missing or invalid provenance stops the
    production build before selection; the selection function also has a defensive
    exclusion rule. **No rows were removed by that rule in this release.**

    ## 5. Require the source location to select the saved ERA5 cell

    A nominal station can borrow a measurement from elsewhere. The actual source
    coordinates must select the same nearest ERA5 cell as the saved match and be within
    half a grid-cell spacing of it. Otherwise the pair is excluded. This prevents a
    borrowed temperature from being compared with a cell chosen for the nominal station.

    ## 6. Keep one copy of each source-day

    Among rows that survived the previous rules, keep each `(SOUID, date)` once.
    Sorting by `STAID` and date makes the choice deterministic: the smallest eligible
    nominal station ID is retained. This prevents the same source observation being
    counted several times through blending. Different source IDs can still refer to
    related instruments, so deduplication does not establish statistical independence.

    The builder saves every rejected row and its first exclusion reason in
    `excluded_pairs.parquet`. The accepted temperature-only table is
    `temperature_pairs.parquet`; adding covariates does not change its pair membership.
    """)
    return


@app.cell
def _(Mo, Summary, Table, Windows):
    Mo.vstack(
        [
            Mo.md(f"""
        ## Observation-day windows: an explicit optional subset

        The main screened dataset retains mixed daily observation windows. The separate
        `temperature_pairs_utc.parquet` keeps documented TX3/TX21 00–00 UTC windows:
        **{Summary["utc_aligned_rows"]:,} observations at
        {Summary["utc_aligned_stations"]:,} station IDs**. This restriction is not part
        of the main selection counts or the current main figures.

        Even aligned windows do not make sampling frequencies identical: ERA5 daily
        maxima use hourly samples, whereas station measurement frequencies differ.
        Station counts below can overlap when a nominal series changes source/window.
        """),
            Table(Windows.sort("observations", descending=True)),
        ]
    )
    return


@app.cell
def _(Mo):
    Mo.md("""
    ## Recalculate covariates after temperature selection

    Geographic covariates use **actual observation-source coordinates**, including
    borrowed observations. Nominal coordinates remain available separately. A station
    ID can therefore have covariates that change when its observation source changes.

    | Covariate | Computation and interpretation |
    |:---|:---|
    | Elevation | Source metadata height in metres; −999 and −9999 mean missing. The nominal height is preserved separately. |
    | DEGURBA | Sample the fixed 2020 GHS-SMOD raster after transforming source coordinates to its CRS. Unknown codes and raster nodata stay missing. This is not annually changing urbanization. |
    | Distance to sea | Nearest point on global Natural Earth 1:10 million coastline in EPSG:3035, followed by WGS84 geodesic distance. The Caspian ring is excluded. Generalized coastlines and omitted small islands limit fine coastal interpretation. |
    | Wind | `sqrt(mean(u10)^2 + mean(v10)^2)`, in m/s: magnitude of the daily mean vector, not mean hourly speed. |
    | Precipitation | Supplied daily-mean proxy in metres. The upstream accumulation recipe is unresolved, so it is not relabelled as mm/day or a daily total. |
    | NDVI | Observed seasonal raster where available; otherwise the latest earlier raster from the same seasonal quarter, explicitly flagged as extrapolated. |

    Missing covariates do not remove valid temperature pairs. Each figure selects only
    the finite covariates it uses; multivariate figures require their joint availability.
    """)
    return


@app.cell
def _(Mo, Summary):
    Mo.md(f"""
    ## Seasonal NDVI extrapolation and its limits

    An observation first uses the raster covering its actual season. If that seasonal
    file is unavailable, the latest **earlier** raster for the matching season is used.
    This carries a seasonal pattern forward; it neither interpolates between seasons
    nor uses future rasters. Spatial nodata is left missing rather than replaced with
    an older pixel. Each value retains `ndvi_source_file`, `ndvi_source_start`,
    `ndvi_source_end`, `ndvi_years_extrapolated`, `ndvi_is_extrapolated` and `ndvi_method`.

    The release contains **{Summary["ndvi_observed_rows"]:,} observed**, **{Summary["ndvi_extrapolated_rows"]:,}
    extrapolated** and **{Summary["ndvi_missing_rows"]:,} missing** NDVI values.
    Extrapolation assumes seasonal persistence; it does not claim that vegetation is
    exactly periodic or that those future values were measured.
    """)
    return


@app.cell
def _(Alt, ExportNotebookFigure, PaperStyle, Pl, Summary):
    _Coverage = Pl.DataFrame(
        {
            "NDVI availability": ["Observed season", "Earlier matching season", "Missing"],
            "Observations": [
                Summary["ndvi_observed_rows"],
                Summary["ndvi_extrapolated_rows"],
                Summary["ndvi_missing_rows"],
            ],
        }
    )
    _Chart = (
        Alt.Chart(_Coverage)
        .mark_bar(color="#0072B2")
        .encode(
            x=Alt.X("Observations:Q", axis=Alt.Axis(format="~s")),
            y=Alt.Y(
                "NDVI availability:N", sort=_Coverage["NDVI availability"].to_list(), title=None
            ),
            tooltip=["NDVI availability:N", Alt.Tooltip("Observations:Q", format=",")],
        )
        .properties(width=480, height=110)
    )
    ExportNotebookFigure(PaperStyle(_Chart), "cleaning_process", "ndvi_coverage")
    return


@app.cell
def _(CleanDirectory, Mo, Pl, Table):
    Mo.vstack(
        [
            Mo.md("""
        ### Check the persistence assumption where observations exist

        The saved backtest compares observed NDVI at source-seasons with the same source
        and season one or two years earlier. Errors are observed minus carried values.
        This measures historical carry-forward error, not uncertainty coverage or proof
        that the same error applies to the missing years. The two lag samples differ.
        """),
            Table(Pl.read_csv(CleanDirectory / "ndvi_backtest.csv")),
            Mo.md("""
        The sensitivity table compares observed-only and observed-plus-extrapolated
        binned residual means. Differences also include changes in years and sample
        composition, so they cannot be attributed only to NDVI imputation.
        """),
            Table(Pl.read_csv(CleanDirectory / "ndvi_sensitivity.csv")),
        ]
    )
    return


@app.cell
def _(Clean, FeatureRows, Mo, Pl, Table):
    _Rows = []
    for _Feature in ["station_celsius", "tp", "wind", "ndvi", "dist_to_sea_km", "elevation"]:
        _Sample = (
            FeatureRows(Clean, [_Feature])
            .select(Pl.len().alias("Observations"), Pl.col("STAID").n_unique().alias("Station IDs"))
            .collect()
            .row(0, named=True)
        )
        _Rows.append({"Covariate": _Feature, **_Sample})
    Mo.vstack(
        [
            Mo.md(
                "## Sample sizes available to individual figures\n\nThese counts are recomputed from `analysis.parquet`, before any figure-specific grouping or urbanization-class selection."
            ),
            Table(Pl.DataFrame(_Rows)),
        ]
    )
    return


@app.cell
def _(Clean, CleanDirectory, Exclusions, Mo, Pl, StationQuality, Summary, Table):
    _Quarantined = StationQuality.filter(Pl.col("quarantined"))["STAID"].to_list()
    _Actual = (
        Clean.select(
            Pl.len().alias("rows"),
            Pl.col("STAID").n_unique().alias("stations"),
            Pl.struct("SOUID", "date").n_unique().alias("source_days"),
            (Pl.col("Q_TX") != 0).sum().alias("invalid_quality"),
            Pl.col("SOUID").null_count().alias("missing_source"),
            Pl.col("era5_land_fallback").sum().alias("land_fallback"),
            (~Pl.col("source_same_grid_cell")).sum().alias("wrong_grid"),
            Pl.col("STAID").is_in(_Quarantined).sum().alias("quarantined"),
            (Pl.col("residual") - (Pl.col("station_celsius") - Pl.col("era5_celsius")))
            .abs()
            .max()
            .alias("residual_error"),
            Pl.col("ndvi_is_extrapolated").sum().alias("ndvi_extrapolated"),
            Pl.col("ndvi").null_count().alias("ndvi_missing"),
            Pl.col("temperature_review_required").sum().alias("residual_review_flags"),
        )
        .collect()
        .row(0, named=True)
    )
    assert _Actual["rows"] == _Actual["source_days"] == Summary["cleaned_rows"]
    assert _Actual["stations"] == Summary["cleaned_stations"]
    assert all(
        _Actual[Name] == 0
        for Name in [
            "invalid_quality",
            "missing_source",
            "land_fallback",
            "wrong_grid",
            "quarantined",
        ]
    )
    assert _Actual["residual_error"] < 1e-6
    assert _Actual["ndvi_extrapolated"] == Summary["ndvi_extrapolated_rows"]
    assert _Actual["ndvi_missing"] == Summary["ndvi_missing_rows"]
    _Rejected = (
        Pl.scan_parquet(CleanDirectory / "excluded_pairs.parquet")
        .group_by("exclusion_reason")
        .len()
        .collect()
    )
    assert dict(_Rejected.iter_rows()) == dict(Exclusions.iter_rows())
    _Core = Pl.scan_parquet(CleanDirectory / "temperature_pairs.parquet").select(
        "STAID", "SOUID", "date"
    )
    _Keys = Clean.select("STAID", "SOUID", "date")
    assert (
        _Core.join(_Keys, on=["STAID", "SOUID", "date"], how="anti")
        .select(Pl.len())
        .collect()
        .item()
        == 0
    )
    assert (
        _Keys.join(_Core, on=["STAID", "SOUID", "date"], how="anti")
        .select(Pl.len())
        .collect()
        .item()
        == 0
    )
    Mo.vstack(
        [
            Mo.md(f"""
        ## Release checks executed by this notebook

        The assertions passed: hashes match the saved release; row and station counts
        reconcile; source-days are unique; no quarantined station, land substitution or
        wrong source cell remains; residual arithmetic agrees; NDVI counts match; and
        the rejection table reproduces the sequential exclusion totals. Temperature-only
        and covariate-enriched tables contain the same pair keys.

        **{_Actual["residual_review_flags"]:,} temperature/residual diagnostic flags remain**
        in the final data. Their presence is intentional: residual size is not a cleaning rule.
        """),
            Table(
                Pl.DataFrame(
                    {"Check": list(_Actual), "Value": [str(Value) for Value in _Actual.values()]}
                )
            ),
        ]
    )
    return


@app.cell
def _(Mo, Summary):
    Mo.md(f"""
    ## Files, provenance and reproduction

    | File under `data2/` | Role |
    |:---|:---|
    | `residuals.parquet` | Preserved supplied input. |
    | `residuals_cleaned.parquet` | Intermediate processing audit output. |
    | `clean/temperature_pairs.parquet` | Main screened temperature pairs. |
    | `clean/temperature_pairs_utc.parquet` | Optional aligned-window subset. |
    | `clean/analysis.parquet` | Main pairs with recalculated covariates. |
    | `clean/excluded_pairs.parquet` | Every exclusion with its first reason. |
    | `clean/observation_sources.parquet` | Observation-to-source provenance. |
    | `clean/temperature_review.csv`, `clean/station_quality.csv` | Screening evidence and quarantined series. |
    | `clean/*_source_files.csv` | Hashes of station, ERA5 and covariate source files. |
    | `clean/summary.json` | Release counts, policy limitations and output hashes. |

    Cleaned input SHA-256:
    `{Summary["cleaned_data_sha256"]}`

    The implementation is in `py.cleaning`, `py.temperature_quality`, `py.covariates`,
    `py.scripts.audit_cleaning` and `py.scripts.build_clean_dataset`. Run computational
    commands in a dedicated tmux session and remove it when done:

    ```bash
    uv run python -m py.scripts.audit_cleaning
    uv run python -m py.scripts.build_clean_dataset
    uv run python -m py.scripts.export_notebooks cleaning_process
    uv run python -m py.scripts.build_paper_figures
    ```

    Rebuilding the dataset requires the original station files, daily ERA5 NetCDFs,
    NDVI rasters and DEGURBA raster. Reading this notebook requires the saved audit
    products and Parquet files. Source code, compact evidence tables and figure sources
    belong in Git; large datasets remain local. Re-export analyses after rebuilding data.

    For the figures, see the [notebook index](index.html). Post-stratification remains
    exploratory: population domains, source aggregation and calibration-weight consistency
    need separate methodological review. Cleaning alone does not resolve those choices
    or automatically update the numerical claims in `paper.tex`.
    """)
    return


if __name__ == "__main__":
    app.run()
