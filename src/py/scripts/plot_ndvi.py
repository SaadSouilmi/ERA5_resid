"""Plot existing and newly retrieved NDVI as a preview without changing the release."""

import hashlib as Hashlib
import json as Json
import math as Math
from datetime import date as Date

import altair as Alt
import polars as Pl

from py.paths import AnalysisDataDirectory, NotebookFiguresDirectory
from py.publication import PaperStyle, SaveFigure

Origins = ["Old observed", "Old carried forward", "New satellite pilot", "Missing"]
Colors = ["#0072B2", "#D98B23", "#008A70", "#B8B8B8"]
Cutoff = Date(2023, 12, 1)


def Data(Frame):
    return Alt.Data(values=Json.loads(Frame.write_json()))


def OriginColor(Legend=True):
    return Alt.Color(
        "origin:N",
        scale=Alt.Scale(domain=Origins, range=Colors),
        legend=Alt.Legend(title=None, orient="top", columns=4) if Legend else None,
    )


def Load(Directory):
    Input = AnalysisDataDirectory / "clean/analysis.parquet"
    PilotDirectory = AnalysisDataDirectory / "ndvi_observed/sentinel2_missing_pilot_v1"
    Manifest = Json.loads((PilotDirectory / "manifest.json").read_text())
    with Input.open("rb") as Stream:
        InputHash = Hashlib.file_digest(Stream, "sha256").hexdigest()
    if InputHash != Manifest["input_sha256"]:
        raise ValueError("Pilot and current release hashes differ")
    Sources = Pl.read_csv(PilotDirectory / "selected_sources.csv")
    CandidateFile = PilotDirectory / "source_season_ndvi.parquet"
    Candidates = Pl.read_parquet(CandidateFile).rename({"ndvi_observed": "new_ndvi"})
    if Candidates.select("SOUID", "season_start").n_unique() != len(Candidates):
        raise ValueError("Duplicate candidate source-seasons")
    Seasons = (
        Pl.scan_parquet(Input)
        .with_columns(
            Pl.col("date")
            .dt.offset_by("1mo")
            .dt.truncate("1q")
            .dt.offset_by("-1mo")
            .dt.date()
            .alias("season_start")
        )
        .group_by("SOUID", "season_start")
        .agg(
            Pl.col("ndvi").first().alias("old_ndvi"),
            Pl.col("ndvi_method").first(),
            Pl.col("ndvi").n_unique().alias("values_per_season"),
            Pl.col("ndvi_method").n_unique().alias("methods_per_season"),
            Pl.len().alias("station_days"),
        )
        .collect()
    )
    if Seasons["values_per_season"].max() != 1 or Seasons["methods_per_season"].max() != 1:
        raise ValueError("NDVI or provenance changes within a source-season")
    Combined = (
        Seasons.join(
            Candidates.select(
                "SOUID", "season_start", "new_ndvi", "status", "valid_months", "valid_dates"
            ),
            on=["SOUID", "season_start"],
            how="left",
            validate="1:1",
        )
        .with_columns(
            (Pl.col("new_ndvi").is_not_null() & (Pl.col("ndvi_method") != "observed_season")).alias(
                "use_candidate"
            )
        )
        .with_columns(
            Pl.when(Pl.col("use_candidate"))
            .then(Pl.col("new_ndvi"))
            .otherwise(Pl.col("old_ndvi"))
            .alias("preview_ndvi"),
            Pl.when(Pl.col("use_candidate"))
            .then(Pl.lit(Origins[2]))
            .when(Pl.col("old_ndvi").is_null())
            .then(Pl.lit(Origins[3]))
            .when(Pl.col("ndvi_method") == "observed_season")
            .then(Pl.lit(Origins[0]))
            .otherwise(Pl.lit(Origins[1]))
            .alias("origin"),
        )
    )
    if len(Combined) != len(Seasons):
        raise ValueError("Preview join changed sample membership")
    Summary = (
        Combined.group_by("season_start")
        .agg(
            Pl.col("old_ndvi").mean().alias("current_mean"),
            Pl.col("preview_ndvi").mean().alias("preview_mean"),
            Pl.col("old_ndvi").count().alias("current_available"),
            Pl.col("preview_ndvi").count().alias("preview_available"),
            Pl.col("use_candidate").sum().alias("new_source_seasons"),
            Pl.len().alias("active_sources"),
        )
        .sort("season_start")
    )
    Coverage = (
        Combined.group_by("season_start", "origin")
        .agg(
            Pl.len().alias("source_seasons"),
            Pl.col("station_days").sum(),
        )
        .with_columns(Pl.col("origin").replace_strict(dict(zip(Origins, range(4)))).alias("order"))
    )
    Values = Combined.filter(Pl.col("preview_ndvi").is_not_null())
    if Values["preview_ndvi"].min() < -1 or Values["preview_ndvi"].max() > 1:
        raise ValueError("NDVI outside physical bounds")
    Histogram = (
        Values.with_columns(
            ((Pl.col("preview_ndvi") / 0.05).floor().clip(-20, 19) * 0.05).alias("bin_start")
        )
        .group_by("bin_start", "origin")
        .agg(Pl.len().alias("source_seasons"))
        .with_columns(
            (Pl.col("bin_start") + 0.05).alias("bin_end"),
            Pl.col("origin").replace_strict(dict(zip(Origins, range(4)))).alias("order"),
        )
        .sort("bin_start", "order")
    )
    Starts = Summary.select("season_start")
    Pilot = (
        Sources.select("SOUID", "country")
        .join(Starts, how="cross")
        .join(
            Seasons.select("SOUID", "season_start", "old_ndvi", "ndvi_method", "station_days"),
            on=["SOUID", "season_start"],
            how="left",
            validate="1:1",
        )
        .join(
            Candidates.select(
                "SOUID", "season_start", "new_ndvi", "status", "valid_months", "valid_dates"
            ),
            on=["SOUID", "season_start"],
            how="left",
            validate="1:1",
        )
        .with_columns(
            (Pl.col("country") + " · " + Pl.col("SOUID").cast(Pl.String)).alias("source_label")
        )
        .sort("country", "SOUID", "season_start")
    )
    for Name, Frame in [
        ("seasonal_summary", Summary),
        ("coverage", Coverage),
        ("distribution", Histogram),
        ("pilot_values", Pilot),
    ]:
        Frame.write_csv(Directory / f"{Name}.csv")
    Matched = Combined.filter(Pl.col("use_candidate"))
    Metadata = {
        "input_sha256": InputHash,
        "candidate_sha256": Hashlib.sha256(CandidateFile.read_bytes()).hexdigest(),
        "status": "Preview only; analysis.parquet is unchanged",
        "unit": "One row per source ID and meteorological season with retained temperature observations; means give each available source equal weight",
        "candidate_source_seasons": len(Candidates),
        "usable_candidate_source_seasons": Candidates["new_ndvi"].count(),
        "candidate_sources": Candidates["SOUID"].n_unique(),
        "new_source_seasons_in_preview": len(Matched),
        "new_station_days_in_preview": Matched["station_days"].sum(),
        "new_replacing_carried_source_seasons": Matched.filter(
            Pl.col("ndvi_method") == "previous_same_season"
        ).height,
        "new_filling_missing_source_seasons": Matched.filter(Pl.col("old_ndvi").is_null()).height,
        "all_source_seasons": len(Combined),
        "all_station_days": Combined["station_days"].sum(),
        "maximum_change_in_seasonal_mean": (Summary["preview_mean"] - Summary["current_mean"])
        .abs()
        .max(),
        "origin_counts": Combined.group_by("origin")
        .agg(Pl.len().alias("source_seasons"), Pl.col("station_days").sum())
        .sort("origin")
        .to_dicts(),
        "notes": [
            "Only qualified missing-season candidates replace carried or missing values in this preview",
            "Historical 2023 validation candidates are excluded; existing observed values remain the historical series",
            "The number and composition of active sources changes by season; this is not a balanced-panel trend",
            "Pilot panels include all retrieved pilot values, including source-seasons without retained temperature observations",
            "Lines connect seasonal estimates for readability; they do not represent daily measurements",
            "Grey crosses in pilot panels mark candidate retrievals that failed the three-month coverage rule",
        ],
    }
    (Directory / "manifest.json").write_text(Json.dumps(Metadata, indent=2) + "\n")
    return Summary, Coverage, Histogram, Pilot, Metadata


def Overview(Summary, Coverage):
    MeanRows = Summary.unpivot(
        on=["current_mean", "preview_mean"],
        index=["season_start", "current_available", "preview_available", "new_source_seasons"],
        variable_name="series",
        value_name="ndvi",
    ).filter((Pl.col("series") == "current_mean") | (Pl.col("season_start") >= Cutoff))
    MeanRows = MeanRows.with_columns(
        Pl.col("series").replace(
            {
                "current_mean": "Current analysis",
                "preview_mean": "Preview with new pilot values",
            }
        )
    )
    X = Alt.X(
        "season_start:T", title=None, axis=Alt.Axis(format="%Y", tickCount="year", grid=False)
    )
    Boundary = (
        Alt.Chart(Alt.Data(values=[{"season_start": Cutoff.isoformat()}]))
        .mark_rule(
            color="#777777",
            strokeDash=[4, 4],
            strokeWidth=1,
        )
        .encode(x=X)
    )
    Mean = (
        Alt.Chart(Data(MeanRows))
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=X,
            y=Alt.Y("ndvi:Q", title="Mean NDVI", scale=Alt.Scale(zero=False)),
            color=Alt.Color(
                "series:N",
                scale=Alt.Scale(
                    domain=["Current analysis", "Preview with new pilot values"],
                    range=["#555555", Colors[2]],
                ),
                legend=Alt.Legend(title=None, orient="top"),
            ),
            strokeDash=Alt.StrokeDash(
                "series:N",
                scale=Alt.Scale(
                    domain=["Current analysis", "Preview with new pilot values"],
                    range=[[1, 0], [5, 3]],
                ),
                legend=None,
            ),
            tooltip=[
                "season_start:T",
                "series:N",
                Alt.Tooltip("ndvi:Q", format=".5f"),
                "new_source_seasons:Q",
            ],
        )
    )
    Top = (Mean + Boundary).properties(
        width=880,
        height=245,
        title=Alt.TitleParams(
            "A. Seasonal NDVI across the full retained sample",
            subtitle=[
                "Equal weight per active observation source. The two means nearly overlap.",
                "Dashed vertical line: December 2023, the first missing raster season.",
            ],
        ),
    )
    Bars = (
        Alt.Chart(Data(Coverage))
        .mark_bar(size=26)
        .encode(
            x=X,
            y=Alt.Y("source_seasons:Q", stack="zero", title="Active sources"),
            color=OriginColor(),
            order=Alt.Order("order:Q", sort="ascending"),
            tooltip=["season_start:T", "origin:N", "source_seasons:Q", "station_days:Q"],
        )
    )
    Labels = (
        Alt.Chart(Data(Summary.filter(Pl.col("new_source_seasons") > 0)))
        .mark_text(
            dy=-9,
            color=Colors[2],
            fontSize=11,
        )
        .encode(x=X, y=Alt.Y("active_sources:Q"), text=Alt.Text("new_source_seasons:Q"))
    )
    Bottom = (Bars + Labels + Boundary).properties(
        width=880,
        height=245,
        title=Alt.TitleParams(
            "B. Where the preview values come from",
            subtitle=[
                "New pilot values replace eligible carried or missing values only in this preview.",
                "Green numbers give the new source-season count; narrow green segments are to scale.",
            ],
        ),
    )
    return PaperStyle(Alt.vconcat(Top, Bottom, spacing=32).resolve_scale(color="independent"))


def Distribution(Histogram):
    return PaperStyle(
        Alt.Chart(Data(Histogram))
        .mark_bar()
        .encode(
            x=Alt.X("bin_start:Q", bin="binned", title="NDVI", scale=Alt.Scale(domain=[-1, 1])),
            x2="bin_end:Q",
            y=Alt.Y("source_seasons:Q", stack="zero", title="Source-seasons"),
            color=OriginColor(),
            order=Alt.Order("order:Q", sort="ascending"),
            tooltip=["origin:N", Alt.Tooltip("bin_start:Q", format=".2f"), "source_seasons:Q"],
        )
        .properties(
            width=880,
            height=330,
            title=Alt.TitleParams(
                "NDVI distribution with the pilot values included",
                subtitle=[
                    "One value per active source-season; bin width 0.05. Missing values are excluded.",
                    "New values contribute only a small fraction of the full distribution. Preview, not an adopted release.",
                ],
            ),
        )
    )


def PilotFigure(Pilot):
    Rows = []
    for Row in Pilot.iter_rows(named=True):
        Base = {Key: Row[Key] for Key in ["SOUID", "source_label", "season_start"]}
        Base["season_start"] = Base["season_start"].isoformat()
        if Row["season_start"] < Cutoff:
            Rows.append({**Base, "origin": Origins[0], "ndvi": Row["old_ndvi"]})
        else:
            Rows.append({**Base, "origin": Origins[1], "ndvi": Row["old_ndvi"]})
            Rows.append({**Base, "origin": Origins[2], "ndvi": Row["new_ndvi"]})
            if Row["status"] == "insufficient_month_coverage":
                Rows.append({**Base, "origin": Origins[3], "ndvi": None})
    Valid = [Row["ndvi"] for Row in Rows if Row["ndvi"] is not None]
    Lower = min(0, Math.floor(min(Valid) * 10) / 10)
    AxisFloor = Lower - 0.08
    Base = Alt.Chart(Alt.Data(values=Rows))
    X = Alt.X(
        "season_start:T", title=None, axis=Alt.Axis(format="%Y", tickCount="year", grid=False)
    )
    Y = Alt.Y("ndvi:Q", title="NDVI", scale=Alt.Scale(domain=[AxisFloor, 1]))
    Lines = (
        Base.transform_filter(Alt.datum.origin != Origins[3])
        .mark_line(
            point=Alt.OverlayMarkDef(size=25, filled=True),
            strokeWidth=1.8,
            invalid="break-paths-show-domains",
        )
        .encode(
            x=X,
            y=Y,
            color=OriginColor(),
            strokeDash=Alt.StrokeDash(
                "origin:N",
                scale=Alt.Scale(
                    domain=Origins,
                    range=[[1, 0], [4, 3], [1, 0], [1, 0]],
                ),
                legend=None,
            ),
            tooltip=[
                "source_label:N",
                "season_start:T",
                "origin:N",
                Alt.Tooltip("ndvi:Q", format=".3f"),
            ],
        )
    )
    Missing = (
        Base.transform_filter(Alt.datum.origin == Origins[3])
        .mark_point(
            shape="cross",
            size=35,
            color=Colors[3],
            strokeWidth=1.5,
        )
        .encode(x=X, y=Alt.YDatum(AxisFloor + 0.025))
    )
    Cut = (
        Base.transform_aggregate(groupby=["source_label"])
        .transform_calculate(cutoff="datetime(2023, 11, 1)")
        .mark_rule(color="#999999", strokeDash=[3, 3], strokeWidth=0.8)
        .encode(x=Alt.X("cutoff:T"))
    )
    Facets = (
        (Lines + Missing + Cut)
        .properties(width=275, height=155)
        .facet(
            facet=Alt.Facet(
                "source_label:N", title=None, sort=sorted(Pilot["source_label"].unique())
            ),
            columns=3,
        )
        .properties(
            title=Alt.TitleParams(
                "Old and new NDVI at the same 12 pilot locations",
                subtitle=[
                    "Blue: original observed seasons. Orange dashed: values currently carried forward. Green: new satellite estimates.",
                    "Grey crosses at the bottom mark failed candidate coverage, not NDVI = 0. Gaps remain gaps.",
                    "Vertical lines mark December 2023. These are pilot estimates; the analysis release is unchanged.",
                ],
            )
        )
    )
    return PaperStyle(Facets).configure_header(
        labelFontSize=12, labelFontWeight="normal", labelPadding=7
    )


def FocusedComparison(Pilot, Directory):
    Matched = Pilot.filter(
        (Pl.col("season_start") >= Cutoff)
        & Pl.col("station_days").is_not_null()
        & Pl.col("old_ndvi").is_not_null()
        & Pl.col("new_ndvi").is_not_null()
    )
    Means = (
        Matched.group_by("season_start")
        .agg(
            Pl.col("old_ndvi").mean(),
            Pl.col("new_ndvi").mean(),
            Pl.len().alias("sources"),
        )
        .sort("season_start")
    )
    Series = ["OLD: carried-forward values", "NEW: satellite observations"]
    Rows, Labels = [], []
    for Row in Means.iter_rows(named=True):
        Start = Row["season_start"]
        Season = {3: "Spring", 6: "Summer", 9: "Autumn", 12: "Winter"}[Start.month]
        Year = f"{Start.year}/{str(Start.year + 1)[2:]}" if Start.month == 12 else str(Start.year)
        Label = f"{Season} {Year}|{Row['sources']} sources"
        Labels.append(Label)
        for Name, Column in zip(Series, ["old_ndvi", "new_ndvi"]):
            Rows.append(
                {
                    "season_start": Start.isoformat(),
                    "season": Label,
                    "series": Name,
                    "mean_ndvi": Row[Column],
                    "sources": Row["sources"],
                }
            )
    Means.write_csv(Directory / "focused_comparison.csv")
    Matched.write_csv(Directory / "matched_source_seasons.csv")
    Base = Alt.Chart(Alt.Data(values=Rows)).encode(
        x=Alt.X(
            "season:N",
            sort=Labels,
            title=None,
            axis=Alt.Axis(
                labelAngle=0,
                labelExpr="split(datum.label, '|')",
                labelLineHeight=15,
            ),
        ),
        xOffset=Alt.XOffset("series:N", sort=Series),
        y=Alt.Y(
            "mean_ndvi:Q", title="Mean NDVI at matched locations", scale=Alt.Scale(domain=[0, 1])
        ),
    )
    Bars = Base.mark_bar(size=42).encode(
        color=Alt.Color(
            "series:N",
            scale=Alt.Scale(domain=Series, range=[Colors[1], Colors[2]]),
            legend=Alt.Legend(title=None, orient="top", symbolSize=160),
        ),
        tooltip=["season:N", "series:N", Alt.Tooltip("mean_ndvi:Q", format=".3f"), "sources:Q"],
    )
    Values = Base.mark_text(dy=-9, fontSize=12, color="#222222").encode(
        text=Alt.Text("mean_ndvi:Q", format=".3f")
    )
    Figure = (Bars + Values).properties(
        width=980,
        height=330,
        title=Alt.TitleParams(
            "New satellite NDVI versus the old carried-forward values",
            subtitle=[
                f"Green bars show only the new observations: {len(Matched)} matched source-seasons at {Matched['SOUID'].n_unique()} locations.",
                "Each orange/green pair uses exactly the same locations. Available locations differ between seasons.",
                "This is the pilot comparison; the main analysis dataset is unchanged.",
            ],
        ),
    )
    return PaperStyle(Figure)


def Main():
    Directory = NotebookFiguresDirectory / "ndvi_review"
    Directory.mkdir(parents=True, exist_ok=True)
    Summary, Coverage, Histogram, Pilot, Metadata = Load(Directory)
    for Name, Figure in [
        ("overview", Overview(Summary, Coverage)),
        ("distribution", Distribution(Histogram)),
        ("pilot_locations", PilotFigure(Pilot)),
        ("focused_comparison", FocusedComparison(Pilot, Directory)),
    ]:
        SaveFigure(Figure, Directory / Name, WidthMm=240, Dpi=150)
        print(f"Saved {Directory / Name}", flush=True)
    print(Json.dumps(Metadata, indent=2), flush=True)


if __name__ == "__main__":
    Main()
