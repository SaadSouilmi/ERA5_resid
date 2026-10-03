"""Explicit, non-destructive cleaning of the saved station-day table."""

from datetime import date as Date

import polars as Pl

from py.paths import AnalysisDataDirectory, RawDataDirectory

GridExtent = (-25.05, 40.95, 34.95, 69.95)
MissingElevation = (-9999, -999)


def InsideGrid(Extent=GridExtent):
    return Pl.col("lon").is_between(*Extent[:2]) & Pl.col("lat").is_between(*Extent[2:])


def FeatureRows(Frame, Features):
    Columns = list(dict.fromkeys(Features))
    return Frame.filter(Pl.all_horizontal(Pl.col(Name).is_finite() for Name in Columns))


def AttachStationDistances(Stations, Cached):
    """Join by identifier and reject stale coordinates or duplicated station IDs."""
    import numpy as Np

    Columns = ["STAID", "lat", "lon", "dist_to_sea_km"]
    Joined = Stations.merge(Cached[Columns], on="STAID", how="left", validate="one_to_one")
    if Joined[Columns].isna().any().any():
        raise ValueError("Missing cached station coordinates or coastal distances")
    if not (
        Np.allclose(Joined.geometry.y, Joined["lat"], atol=1e-6, rtol=0)
        and Np.allclose(Joined.geometry.x, Joined["lon"], atol=1e-6, rtol=0)
    ):
        raise ValueError("Cached coastal distances do not match station coordinates")
    return Joined.drop(columns=["lat", "lon"])


def CleanResiduals(Frame, NdviDirectory=RawDataDirectory / "sentinel2_ndvi"):
    if Frame.select(Pl.struct("STAID", "date").is_duplicated().any()).item():
        raise ValueError("Duplicate station-date records")
    Frame = FeatureRows(Frame, ["station_celsius", "era5_celsius", "residual", "lat", "lon"])
    if Frame.select(
        (
            (Pl.col("station_celsius") - Pl.col("era5_celsius") - Pl.col("residual")).abs() > 1e-6
        ).any()
    ).item():
        raise ValueError("Residual must equal station minus ERA5 temperature")
    Frame = Frame.filter(InsideGrid())
    Intervals = [
        tuple(Date.fromisoformat(Part) for Part in File.stem.removeprefix("ndvi_").split("_"))
        for File in NdviDirectory.glob("ndvi_*.tif")
    ]
    if not Intervals:
        raise ValueError("NDVI raster dates are required to establish temporal coverage")
    Contemporary = Pl.any_horizontal(
        (Pl.col("date").dt.date() >= Start) & (Pl.col("date").dt.date() < End)
        for Start, End in Intervals
    )
    BadCoast = (
        ((Pl.col("country") == "Türkiye") & (Pl.col("lon") > 29.1))
        | ((Pl.col("country") == "Russian Federation") & (Pl.col("lon") > 69.07))
        | ((Pl.col("country") == "Spain") & (Pl.col("lon") < -12))
        | Pl.col("country").is_in(["Israel", "Greenland"])
    )
    return Frame.with_columns(
        Pl.when(Pl.col("elevation").is_in(MissingElevation))
        .then(None)
        .otherwise(Pl.col("elevation"))
        .alias("elevation"),
        Pl.when(Contemporary & Pl.col("ndvi").is_between(-1, 1))
        .then(Pl.col("ndvi"))
        .otherwise(None)
        .alias("ndvi"),
        (~Contemporary & Pl.col("ndvi").is_not_null()).alias("ndvi_previous_year_proxy"),
        Pl.when(~BadCoast & Pl.col("dist_to_sea_km").is_finite() & (Pl.col("dist_to_sea_km") >= 0))
        .then(Pl.col("dist_to_sea_km"))
        .otherwise(None)
        .alias("dist_to_sea_km"),
        Pl.when(Pl.col("tp").is_finite() & (Pl.col("tp") >= 0))
        .then(Pl.col("tp"))
        .otherwise(None)
        .alias("tp"),
        Pl.when(Pl.col("wind").is_finite() & (Pl.col("wind") >= 0))
        .then(Pl.col("wind"))
        .otherwise(None)
        .alias("wind"),
        # Review flags are not automatic exclusions or corrections of observations.
        ((Pl.col("station_celsius") > 50) | (Pl.col("residual").abs() > 20)).alias(
            "temperature_review_required"
        ),
    )


def LoadResiduals():
    File = AnalysisDataDirectory / "clean/analysis.parquet"
    if not File.is_file() or not (File.parent / "summary.json").is_file():
        raise FileNotFoundError("Run uv run python -m py.scripts.build_clean_dataset first")
    return Pl.read_parquet(File)
