"""Raster covariates with explicit seasonal NDVI extrapolation provenance."""

from datetime import date as Date

import numpy as Np
import polars as Pl
import rasterio as Rasterio
from rasterio.warp import transform as Transform

from py.paths import RawDataDirectory


def NdviPeriods(Dates, Directory):
    Available = []
    for File in sorted(Directory.glob("ndvi_*.tif")):
        Start, End = [
            Date.fromisoformat(Part) for Part in File.stem.removeprefix("ndvi_").split("_")
        ]
        if End <= Start:
            raise ValueError(f"Invalid NDVI interval: {File.name}")
        Available.append((Start, End, File.name))
    if not Available:
        raise ValueError("No NDVI rasters found")
    Rows = []
    for Day in sorted(set(Dates)):
        Month = 12 if Day.month in (1, 2, 12) else ((Day.month // 3) * 3)
        Year = Day.year - (Day.month < 3)
        Target = Date(Year, Month, 1)
        Current = [Item for Item in Available if Item[0] <= Day < Item[1]]
        if len(Current) > 1:
            raise ValueError(f"Overlapping NDVI rasters for {Day}")
        Candidates = Current or [
            Item for Item in Available if Item[0].month == Month and Item[0] < Target
        ]
        Source = max(Candidates) if Candidates else (None, None, None)
        Rows.append(
            {
                "ndvi_observation_date": Day,
                "ndvi_source_start": Source[0],
                "ndvi_source_end": Source[1],
                "ndvi_source_file": Source[2],
                "ndvi_years_extrapolated": Target.year - Source[0].year if Source[0] else None,
            }
        )
    return Pl.DataFrame(
        Rows,
        schema_overrides={
            "ndvi_observation_date": Pl.Date,
            "ndvi_source_start": Pl.Date,
            "ndvi_source_end": Pl.Date,
            "ndvi_source_file": Pl.String,
            "ndvi_years_extrapolated": Pl.Int32,
        },
    )


def SampleRaster(File, Stations):
    with Rasterio.open(File) as Source:
        if Source.crs is None:
            raise ValueError(f"Raster CRS missing: {File}")
        Xs, Ys = Transform(
            "EPSG:4326", Source.crs, Stations["lon"].to_list(), Stations["lat"].to_list()
        )
        Rows, Columns = Rasterio.transform.rowcol(Source.transform, Xs, Ys)
        Valid = (
            (Np.asarray(Rows) >= 0)
            & (Np.asarray(Rows) < Source.height)
            & (Np.asarray(Columns) >= 0)
            & (Np.asarray(Columns) < Source.width)
        )
        Values = Np.full(len(Stations), Np.nan)
        Indices = Np.flatnonzero(Valid)
        for Index, Sample in zip(
            Indices,
            Source.sample([(Xs[Item], Ys[Item]) for Item in Indices], indexes=1, masked=True),
        ):
            if not Np.ma.is_masked(Sample[0]):
                Values[Index] = float(Sample[0])
        return Values


def AddSeasonalNdvi(
    Frame,
    Directory=RawDataDirectory / "sentinel2_ndvi",
    IdColumn="STAID",
    Coordinates=("lat", "lon"),
):
    Stations = (
        Frame.select(
            Pl.col(IdColumn).alias("STAID"),
            Pl.col(Coordinates[0]).alias("lat"),
            Pl.col(Coordinates[1]).alias("lon"),
        )
        .unique()
        .sort("STAID")
    )
    if Stations["STAID"].n_unique() != len(Stations):
        raise ValueError("Station coordinates change within the input table")
    Periods = NdviPeriods(Frame["date"].dt.date().unique().to_list(), Directory)
    Samples = []
    for File in Periods["ndvi_source_file"].drop_nulls().unique().sort():
        Values = SampleRaster(Directory / File, Stations)
        Values = Np.where((Values >= 0) & (Values <= 254), Values / 254 * 2 - 1, Np.nan)
        Samples.append(
            Stations.select("STAID").with_columns(
                Pl.lit(File).alias("ndvi_source_file"), Pl.Series("ndvi", Values).fill_nan(None)
            )
        )
        print(f"NDVI sampled: {File}", flush=True)
    Lookup = (
        Pl.concat(Samples)
        if Samples
        else Pl.DataFrame(
            schema={
                "STAID": Frame.schema[IdColumn],
                "ndvi_source_file": Pl.String,
                "ndvi": Pl.Float64,
            }
        )
    )
    Existing = [Name for Name in Frame.columns if Name.startswith("ndvi")]
    Result = (
        Frame.drop(Existing)
        .with_columns(Pl.col("date").dt.date().alias("ndvi_observation_date"))
        .join(
            Periods, on="ndvi_observation_date", how="left", validate="m:1", maintain_order="left"
        )
        .join(
            Lookup.rename({"STAID": IdColumn}),
            on=[IdColumn, "ndvi_source_file"],
            how="left",
            validate="m:1",
            maintain_order="left",
        )
    )
    return Result.with_columns(
        (Pl.col("ndvi").is_not_null() & (Pl.col("ndvi_years_extrapolated") > 0))
        .fill_null(False)
        .alias("ndvi_is_extrapolated"),
        Pl.when(Pl.col("ndvi").is_null())
        .then(Pl.lit("missing"))
        .when(Pl.col("ndvi_years_extrapolated") > 0)
        .then(Pl.lit("previous_same_season"))
        .otherwise(Pl.lit("observed_season"))
        .alias("ndvi_method"),
    ).drop("ndvi_observation_date")


def CoastDistances(Stations, CoastFile):
    from py.preprocessing.coastal_distance import coast_distances

    return coast_distances(Stations, CoastFile, latitude="lat", longitude="lon").select(
        "STAID", "dist_to_sea_km"
    )
