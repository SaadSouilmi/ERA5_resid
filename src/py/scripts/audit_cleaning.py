"""Audit the saved data, preserve the input, and write a processing-cleaned copy."""

import argparse as Argparse
import hashlib as Hashlib
import html as Html
import json as Json
from pathlib import Path

import numpy as Np
import pandas as Pd
import polars as Pl
import xarray as Xr
from pyproj import Geod

from py.cleaning import CleanResiduals, FeatureRows, GridExtent, InsideGrid
from py.paths import AnalysisDataDirectory, RawDataDirectory, ReportsDirectory
from py.report_style import StyleHtml


def VerifySources(Frame):
    Groups = (
        Frame.select("STAID", "date", "station_celsius")
        .with_columns(Pl.col("date").dt.strftime("%Y%m%d").cast(Pl.Int64).alias("DATE"))
        .partition_by("STAID", as_dict=True)
    )
    Rows = []
    for Index, ((Staid,), Group) in enumerate(Groups.items()):
        File = RawDataDirectory / "ECA_blend_tx" / f"TX_STAID{Staid:06d}.txt"
        Raw = Pd.read_csv(File, skiprows=20, skipinitialspace=True)
        Raw = Raw[Raw.DATE.between(Group["DATE"].min(), Group["DATE"].max())]
        Joined = Group.join(Pl.from_pandas(Raw), on=["STAID", "DATE"], how="left", validate="1:1")
        Bad = Joined.filter(
            Pl.col("Q_TX").is_null()
            | (Pl.col("Q_TX") != 0)
            | ((Pl.col("TX") / 10 - Pl.col("station_celsius")).abs() > 1e-8)
        )
        Rows.append({"STAID": Staid, "saved_rows": len(Group), "mismatch_rows": len(Bad)})
        if Index % 500 == 0:
            print(f"Source checks: {Index + 1}/{len(Groups)} stations", flush=True)
    return Pl.DataFrame(Rows)


def StationMatches(Stations):
    File = (
        RawDataDirectory / "derived-era5-land-daily-statistics/2020_2m_temperature_daily_maximum.nc"
    )
    with Xr.open_dataset(File) as Ds:
        Lat, Lon = Ds.latitude.values, Ds.longitude.values
        ActualExtent = [Lon.min() - 0.05, Lon.max() + 0.05, Lat.min() - 0.05, Lat.max() + 0.05]
        if not Np.allclose(ActualExtent, GridExtent):
            raise ValueError("ERA5 grid changed; review the cleaning footprint")
        Y = Ds.indexes["latitude"].get_indexer(Stations["lat"].to_numpy(), method="nearest")
        X = Ds.indexes["longitude"].get_indexer(Stations["lon"].to_numpy(), method="nearest")
        Sample = Ds.t2m.isel(valid_time=0).values
        Fallback = ~Np.isfinite(Sample[Y, X])
        LandY, LandX = Np.where(Np.isfinite(Sample))
        for Index in Np.flatnonzero(Fallback):
            Closest = Np.argmin(
                (Lat[LandY] - Stations["lat"][int(Index)]) ** 2
                + (Lon[LandX] - Stations["lon"][int(Index)]) ** 2
            )
            Y[Index], X[Index] = LandY[Closest], LandX[Closest]
        _, _, Distance = Geod(ellps="WGS84").inv(
            Stations["lon"].to_numpy(), Stations["lat"].to_numpy(), Lon[X], Lat[Y]
        )
        return Stations.with_columns(
            Pl.Series("era5_lat", Lat[Y]),
            Pl.Series("era5_lon", Lon[X]),
            Pl.Series("era5_distance_km", Distance / 1000),
            Pl.Series("era5_land_fallback", Fallback),
            InsideGrid().alias("inside_era5_grid"),
        )


def VerifyGridValues(Frame, Matches, AllDates=False):
    """Check supplied ERA5 values on sampled dates, or every observed date."""
    Lats = Xr.DataArray(Matches["era5_lat"].to_numpy(), dims="station")
    Lons = Xr.DataArray(Matches["era5_lon"].to_numpy(), dims="station")
    Rows = []
    for Year in range(Frame["date"].min().year, Frame["date"].max().year + 1):
        Values, Dates = {}, None
        for Variable, Suffix in [
            ("t2m", "2m_temperature_daily_maximum"),
            ("u10", "10m_u_component_of_wind_daily_mean"),
            ("v10", "10m_v_component_of_wind_daily_mean"),
            ("tp", "total_precipitation_daily_mean"),
        ]:
            File = RawDataDirectory / "derived-era5-land-daily-statistics" / f"{Year}_{Suffix}.nc"
            with Xr.open_dataset(File) as Ds:
                if Dates is None:
                    Available = Ds.valid_time.values
                    Available = Available[Available <= Np.datetime64(Frame["date"].max())]
                    Dates = (
                        Available
                        if AllDates
                        else Available[Np.unique(Np.linspace(0, len(Available) - 1, 8, dtype=int))]
                    )
                Values[Variable] = (
                    Ds[Variable]
                    .sel(valid_time=Dates)
                    .load()
                    .sel(latitude=Lats, longitude=Lons, method="nearest")
                    .values
                )
        Actual = Pl.DataFrame(
            {
                "STAID": Np.tile(Matches["STAID"].to_numpy(), len(Dates)),
                "date": Np.repeat(Dates, len(Matches)),
                "grid_temperature": (Values["t2m"] - 273.15).ravel(),
                "grid_wind": Np.sqrt(Values["u10"] ** 2 + Values["v10"] ** 2).ravel(),
                "grid_tp": Values["tp"].ravel(),
            }
        ).join(
            Frame.select("STAID", "date", "era5_celsius", "wind", "tp"),
            on=["STAID", "date"],
            how="inner",
            validate="1:1",
        )
        Result = {"year": Year, "sampled_station_days": len(Actual)}
        for Name, Stored, Tolerance in [
            ("temperature", "era5_celsius", 1e-4),
            ("wind", "wind", 1e-5),
            ("tp", "tp", 1e-10),
        ]:
            Errors = Actual.select((Pl.col("grid_" + Name) - Pl.col(Stored)).abs())["grid_" + Name]
            Result[Name + "max_absolute_error"] = Errors.max()
            Result[Name + "_mismatches"] = (
                int((Errors > Tolerance).sum()) + Errors.null_count() + int(Errors.is_nan().sum())
            )
        Rows.append(Result)
        print(f"ERA5 value checks: {Result}", flush=True)
    Checks = Pl.DataFrame(Rows)
    if any(Value for Row in Rows for Key, Value in Row.items() if Key.endswith("mismatches")):
        raise ValueError("Saved ERA5 values disagree with reconstructed grid matches")
    return Checks


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument(
        "--source-check",
        dest="SourceCheck",
        type=Path,
        help="Reuse a completed station-by-station source audit CSV",
    )
    Args = Parser.parse_args()
    Source = AnalysisDataDirectory / "residuals.parquet"
    if not Source.is_file():
        Parser.error(
            f"required input is missing: {Source}\n"
            "Generate data2/residuals_rebuilt.parquet with the temp_resid notebook, review "
            "its export, then copy it to data2/residuals.parquet as described in README.md."
        )
    Output = ReportsDirectory / "era5-notebooks"
    Output.mkdir(parents=True, exist_ok=True)
    Audit = AnalysisDataDirectory / "cleaning_audit"
    Audit.mkdir(parents=True, exist_ok=True)
    Frame = Pl.read_parquet(Source)
    Quality = Pl.read_csv(Args.SourceCheck) if Args.SourceCheck else VerifySources(Frame)
    Expected = Frame.group_by("STAID").len().rename({"len": "expected_rows"})
    Checked = Expected.join(Quality, on="STAID", how="left", validate="1:1")
    if (
        Checked["saved_rows"].null_count()
        or Checked.filter(
            (Pl.col("saved_rows") != Pl.col("expected_rows")) | (Pl.col("mismatch_rows") != 0)
        ).height
    ):
        raise ValueError("Source audit failed or does not cover this saved dataset")
    Quality.write_csv(Audit / "source_quality.csv")
    Stations = (
        Frame.group_by("STAID")
        .agg(
            Pl.len().alias("observations"),
            *[
                Pl.col(Name).first()
                for Name in ["country", "lat", "lon", "elevation", "dist_to_sea_km"]
            ],
        )
        .sort("STAID")
    )
    Matches = StationMatches(Stations)
    Matches.write_csv(Audit / "station_grid_matches.csv")
    GridChecks = VerifyGridValues(Frame, Matches)
    GridChecks.write_csv(Audit / "era5_value_checks.csv")
    Clean = CleanResiduals(Frame).join(
        Matches.select("STAID", "era5_lat", "era5_lon", "era5_distance_km", "era5_land_fallback"),
        on="STAID",
        how="left",
        validate="m:1",
        maintain_order="left",
    )
    Clean.write_parquet(AnalysisDataDirectory / "residuals_cleaned.parquet")
    Review = Clean.filter(Pl.col("temperature_review_required"))
    Review.write_csv(Audit / "temperature_review.csv")
    Counts = []
    for Name in ["station_celsius", "tp", "wind", "ndvi", "dist_to_sea_km", "elevation"]:
        Subset = FeatureRows(Clean, [Name])
        Counts.append(
            {
                "feature": Name,
                "observations": len(Subset),
                "stations": Subset["STAID"].n_unique(),
                "first_date": str(Subset["date"].min()),
                "last_date": str(Subset["date"].max()),
            }
        )
    Pl.DataFrame(Counts).write_csv(Audit / "feature_samples.csv")
    Summary = {
        "input": str(Source),
        "input_sha256": Hashlib.sha256(Source.read_bytes()).hexdigest(),
        "output": str(AnalysisDataDirectory / "residuals_cleaned.parquet"),
        "cleaned_data_sha256": Hashlib.sha256(
            (AnalysisDataDirectory / "residuals_cleaned.parquet").read_bytes()
        ).hexdigest(),
        "input_rows": len(Frame),
        "input_stations": Frame["STAID"].n_unique(),
        "duplicate_station_dates": len(Frame) - Frame.select("STAID", "date").unique().height,
        "source_quality_mismatches": int(Quality["mismatch_rows"].sum()),
        "era5_checked_station_days": int(GridChecks["sampled_station_days"].sum()),
        "era5_value_mismatches": 0,
        "outside_grid_rows": Frame.filter(~InsideGrid()).height,
        "outside_grid_stations": Matches.filter(~Pl.col("inside_era5_grid")).height,
        "outside_grid_complete_case_rows": Frame.drop_nulls().filter(~InsideGrid()).height,
        "missing_elevation_rows": Frame.filter(Pl.col("elevation").is_in([-999, -9999])).height,
        "previous_year_ndvi_rows_input": Frame.filter(
            (Pl.col("date").dt.date() >= Pd.Timestamp("2023-12-01").date())
            & Pl.col("ndvi").is_not_null()
        ).height,
        "previous_year_ndvi_rows_retained_as_missing": int(Clean["ndvi_previous_year_proxy"].sum()),
        "cleaned_rows": len(Clean),
        "cleaned_stations": Clean["STAID"].n_unique(),
        "temperature_review_rows": len(Review),
        "temperature_review_stations": Review["STAID"].n_unique(),
        "retained_matches_over_25km_stations": Matches.filter(
            InsideGrid() & (Pl.col("era5_distance_km") > 25)
        ).height,
        "original_complete_case_mean": Frame.drop_nulls()["residual"].mean(),
        "cleaned_mean": Clean["residual"].mean(),
        "cleaned_mean_without_review_flags_sensitivity_only": Clean.filter(
            ~Pl.col("temperature_review_required")
        )["residual"].mean(),
        "feature_samples": Counts,
        "status": "Processing fixes applied; source-temperature and spatial-representativeness review remains open.",
    }
    (Audit / "summary.json").write_text(Json.dumps(Summary, indent=2) + "\n")
    Notes = [
        "The input parquet is preserved. No station temperatures were clipped, sign-flipped or silently discarded using ERA5 residuals. Review flags use temperature >50°C or |residual| >20°C as screening rules, not validated quality-control exclusions.",
        "Both temperature series are daily maxima: ECA&D TX (tenths of °C, Q_TX=0) and 0.1° ERA5-Land daily maximum of hourly 2 m temperature (Kelvin minus 273.15). The provider guide and NetCDF history identify these products; they are not daily mean temperatures or a separately bias-adjusted Kayrros temperature product.",
        "The ERA5 centre grid runs from 25°W to 40.9°E and 35°N to 69.9°N. Stations beyond its half-cell footprint were previously snapped to an edge or distant land point; those rows are now excluded. Reconstructed legacy grid locations and geodesic distances are saved for review. In-domain land fallback can still be distant and used Euclidean degrees; coastal representativeness needs sensitivity analysis.",
        "Elevation -9999 and -999 are now missing. Analyses select finite values only for the covariates they need. Previously, drop_nulls() removed rows solely because NDVI was unavailable and retained numeric elevation sentinels.",
        "Only the NDVI raster covering the observation's actual quarter is used. Supplied rasters cover December 2019 through November 2023. Values copied from an earlier year are now missing rather than presented as contemporaneous measurements; later temperature observations remain available to other plots. NDVI scaling 0..254 to -1..1 and nodata=255 agree with the provider guide.",
        "Saved station coastal distances match the cache by STAID. The raw pipeline's positional assignment was fragile and is replaced with an ID join plus coordinate checks. Distances from the truncated GADM Europe polygon are missing for known unsupported territories. Polygon boundaries may also include inland water or truncation edges, so this is not a fully validated ocean-coast distance product.",
        "The files label precipitation in metres, and the provider guide describes daily mean hourly precipitation. Their metadata does not establish an unambiguous daily accumulation window. The plots now label it a precipitation proxy in metres; a mm/day claim needs the original accumulation/deaccumulation recipe. No factor of 24 or date shift was guessed.",
        "Wind is sqrt(mean(u10)^2 + mean(v10)^2), the magnitude of the daily mean vector. It is not the daily mean of hourly wind-speed magnitudes. Plot labels now distinguish these quantities.",
        "All saved TX records were checked against the original source values and valid quality flags. Yet stations 25881 and 26079 contain repeated values near 59.9°C, and station 25885 contains negative summer readings in Italy. These examples persist in the newer release. They require source-series review, not residual-based automatic trimming. The WMO verified continental record is 48.8°C in Sicily in 2021.",
        "The draft's numerical tables and claims describe the previous analysis and must be refreshed after quality review. It also describes wind terciles although the active notebook shows joint quantile heatmaps; its calm/strong-wind numerical example contradicts its prose. Station clustering preserves within-station records, but does not model correlation between distinct nearby stations. Binned conditional means are descriptive associations, not model-based partial dependence or causal effects.",
        "ECA&D observation-day windows differ by source. ERA5 metadata uses a zero-hour shift, so calendar-date joins alone do not prove matching 24-hour windows. Blended series can also borrow observations from nearby stations; SOUID provenance matters for interpreting station-cluster uncertainty.",
        "Post-stratification is exploratory: the DEGURBA pixel crop, GADM land population and station footprint differ. Its GREG point estimate uses observation-count-weighted regression while displayed calibration weights follow an unweighted matrix formula. This audit does not establish that they target one consistent estimator.",
    ]
    Summary["findings"] = Notes
    (Audit / "summary.json").write_text(Json.dumps(Summary, indent=2) + "\n")
    Rows = "".join(
        f"<tr><th>{Html.escape(Key)}</th><td>{Html.escape(str(Value))}</td></tr>"
        for Key, Value in Summary.items()
        if not isinstance(Value, (list, dict))
    )
    Sources = [
        (
            "ECA&D observation elements and day windows",
            "https://www.ecad.eu/dailydata/datadictionaryelement.php",
        ),
        ("ECA&D blended-series provenance", "https://www.ecad.eu/helptext/blending_help.html"),
        (
            "ERA5-Land accumulation conventions",
            "https://confluence.ecmwf.int/pages/viewpage.action?pageId=462906181",
        ),
        (
            "WMO verification of the European temperature record",
            "https://wmo.int/media/news/wmo-confirms-verification-of-new-continental-european-temperature-record",
        ),
    ]
    Document = '<!doctype html><html><head><meta charset="utf-8"><title>ERA5 data-cleaning audit</title></head><body><h1>ERA5 data-cleaning audit</h1>'
    Document += "<p><strong>Processing corrections are complete. Scientific quality review remains open.</strong></p>"
    Document += "<table>" + Rows + "</table><h2>Findings</h2><ol>"
    Document += "".join(f"<li><p>{Html.escape(Note)}</p></li>" for Note in Notes)
    Document += (
        "</ol><h2>Source documentation</h2><ul>"
        + "".join(f'<li><a href="{Url}">{Title}</a></li>' for Title, Url in Sources)
        + "</ul></body></html>"
    )
    (Output / "data_cleaning.html").write_text(StyleHtml(Document))
    print(
        Json.dumps(
            {
                Key: Value
                for Key, Value in Summary.items()
                if Key not in {"findings", "feature_samples"}
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    Main()
