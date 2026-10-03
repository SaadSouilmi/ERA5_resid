from datetime import date as Date, datetime as Datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import geopandas as Gpd
import numpy as Np
import pandas as Pd
import polars as Pl
import rasterio as Rasterio
from rasterio.transform import from_origin as FromOrigin
from shapely.geometry import Point

from py.cleaning import AttachStationDistances, CleanResiduals, FeatureRows
from py.covariates import AddSeasonalNdvi, NdviPeriods
from py.temperature_quality import (
    AttachSourceMetadata,
    SelectTemperaturePairs,
    SourceTemperatureEvidence,
    TemperatureEvidence,
)

from .check import Expect, ExpectEqual, ExpectRaises, Run


def Fixture():
    return Pl.DataFrame(
        {
            "STAID": [1, 2, 3, 4],
            "date": [
                Datetime(2021, 7, 1),
                Datetime(2024, 7, 1),
                Datetime(2021, 7, 1),
                Datetime(2021, 7, 1),
            ],
            "lat": [50.0, 50.0, 80.0, 50.0],
            "lon": [10.0] * 4,
            "country": ["Germany"] * 4,
            "station_celsius": [20.0, 20.0, 20.0, 59.9],
            "era5_celsius": [19.0] * 4,
            "residual": [1.0, 1.0, 1.0, 40.9],
            "elevation": [-9999, -10, 10, -999],
            "ndvi": [0.4] * 4,
            "tp": [0.01] * 4,
            "wind": [2.0] * 4,
            "dist_to_sea_km": [50.0] * 4,
        }
    )


def MissingCovariatesDoNotDropOtherAnalyses():
    with TemporaryDirectory() as Directory:
        (Path(Directory) / "ndvi_2021-06-01_2021-09-01.tif").touch()
        Clean = CleanResiduals(Fixture(), Path(Directory))
    ExpectEqual(Clean["STAID"].to_list(), [1, 2, 4])
    ExpectEqual(Clean["elevation"].to_list(), [None, -10, None])
    ExpectEqual(Clean["ndvi"].to_list(), [0.4, None, 0.4])
    ExpectEqual(Clean["ndvi_previous_year_proxy"].to_list(), [False, True, False])
    ExpectEqual(len(FeatureRows(Clean, ["wind"])), 3)
    ExpectEqual(len(FeatureRows(Clean, ["ndvi"])), 2)
    ExpectEqual(Clean["temperature_review_required"].to_list(), [False, False, True])
    ExpectEqual(Clean["station_celsius"][-1], 59.9)


def DuplicateDaysAndWrongResidualsFail():
    Frame = Fixture()
    ExpectRaises(ValueError, CleanResiduals, Pl.concat([Frame, Frame.head(1)]))
    ExpectRaises(
        ValueError, CleanResiduals, Frame.with_columns((-Pl.col("residual")).alias("residual"))
    )


def DistancesFollowStationIdsAndCoordinates():
    Stations = Gpd.GeoDataFrame(
        {"STAID": [2, 1]}, geometry=[Point(20, 50), Point(10, 50)], crs="EPSG:4326"
    )
    Cache = Pd.DataFrame(
        {
            "STAID": [1, 2],
            "lat": [50.0, 50.0],
            "lon": [10.0, 20.0],
            "dist_to_sea_km": [100.0, 200.0],
        }
    )
    Result = AttachStationDistances(Stations, Cache)
    ExpectEqual(Result["dist_to_sea_km"].tolist(), [200.0, 100.0])
    ExpectEqual(Result["STAID"].tolist(), [2, 1])
    Cache.loc[0, "lat"] = 51.0
    ExpectRaises(ValueError, AttachStationDistances, Stations, Cache)
    Expect(Stations.crs is not None, "station geometry metadata was lost")


def NdviExtrapolationUsesPastMatchingSeason():
    with TemporaryDirectory() as Directory:
        Directory = Path(Directory)
        for Name in ["2021-12-01_2022-03-01", "2023-06-01_2023-09-01", "2023-09-01_2023-12-01"]:
            (Directory / f"ndvi_{Name}.tif").touch()
        Periods = NdviPeriods(
            [Date(2020, 7, 1), Date(2022, 1, 1), Date(2024, 1, 1), Date(2025, 7, 1)], Directory
        )
        ExpectEqual(Periods["ndvi_years_extrapolated"].to_list(), [None, 0, 2, 2])
        ExpectEqual(
            Periods["ndvi_source_start"].to_list(),
            [None, Date(2021, 12, 1), Date(2021, 12, 1), Date(2023, 6, 1)],
        )


def NdviRasterNodataAndProvenance():
    with TemporaryDirectory() as Directory:
        Directory = Path(Directory)
        File = Directory / "ndvi_2023-06-01_2023-09-01.tif"
        with Rasterio.open(
            File,
            "w",
            driver="GTiff",
            height=1,
            width=2,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=FromOrigin(10, 51, 1, 1),
            nodata=255,
        ) as Raster:
            Raster.write(Np.array([[127, 255]], dtype=Np.uint8), 1)
        Frame = Pl.DataFrame(
            {
                "STAID": [1, 1, 2, 3],
                "lat": [50.5] * 4,
                "lon": [10.5, 10.5, 11.5, 40.0],
                "date": [
                    Datetime(2023, 7, 1),
                    Datetime(2025, 7, 1),
                    Datetime(2025, 7, 1),
                    Datetime(2025, 7, 1),
                ],
            }
        )
        Result = AddSeasonalNdvi(Frame, Directory)
        ExpectEqual(Result["ndvi"].to_list(), [0.0, 0.0, None, None])
        ExpectEqual(Result["ndvi_is_extrapolated"].to_list(), [False, True, False, False])
        ExpectEqual(
            Result["ndvi_method"].to_list(),
            ["observed_season", "previous_same_season", "missing", "missing"],
        )


def ScreeningUsesStationEvidenceAndConsecutiveDates():
    Frame = Pl.DataFrame(
        {
            "STAID": [1] * 3,
            "date": [Datetime(2020, 1, Day) for Day in (1, 2, 3)],
            "station_celsius": [10.0, 45.0, 10.0],
            "lat": [50.0] * 3,
            "lon": [10.0] * 3,
            "elevation": [100.0] * 3,
        }
    )
    Result = TemperatureEvidence(Frame)
    ExpectEqual(Result["source_spike_flag"].to_list(), [False, True, False])
    ExpectEqual(Result["source_spatial_flag"].to_list(), [False] * 3)
    Changed = TemperatureEvidence(
        Frame.with_columns(Pl.lit(1000.0).alias("era5_celsius"), Pl.lit(-1000.0).alias("residual"))
    )
    Expect(Result.equals(Changed), "temperature screening depends on ERA5")
    Gapped = Frame.with_columns(Pl.Series("date", [Datetime(2020, 1, Day) for Day in (1, 3, 5)]))
    ExpectEqual(TemperatureEvidence(Gapped)["source_spike_flag"].sum(), 0)


def BlendedCopiesAreOneSourceForScreening():
    Frame = Pl.DataFrame(
        {
            "STAID": [1] * 3,
            "SOUID": [100] * 3,
            "date": [Datetime(2020, 1, Day) for Day in (1, 2, 3)],
            "station_celsius": [10.0, 45.0, 10.0],
            "source_lat": [50.0] * 3,
            "source_lon": [10.0] * 3,
            "source_elevation": [100.0] * 3,
        }
    )
    Copies = Pl.concat([Frame, Frame.with_columns(Pl.lit(2).cast(Pl.Int64).alias("STAID"))])
    Result = SourceTemperatureEvidence(Copies)
    ExpectEqual(len(Result), 3)
    ExpectEqual(Result["source_spike_flag"].sum(), 1)
    Conflict = Frame.head(1).with_columns(Pl.lit(20.0).alias("station_celsius"))
    ExpectRaises(ValueError, SourceTemperatureEvidence, Pl.concat([Copies, Conflict]))


def CovariatesFollowObservationSourceCoordinates():
    with TemporaryDirectory() as Directory:
        Directory = Path(Directory)
        File = Directory / "ndvi_2023-06-01_2023-09-01.tif"
        with Rasterio.open(
            File,
            "w",
            driver="GTiff",
            height=1,
            width=2,
            count=1,
            dtype="uint8",
            crs="EPSG:4326",
            transform=FromOrigin(10, 51, 1, 1),
            nodata=255,
        ) as Raster:
            Raster.write(Np.array([[0, 254]], dtype=Np.uint8), 1)
        Frame = Pl.DataFrame(
            {
                "STAID": [1, 1],
                "SOUID": [100, 200],
                "date": [Datetime(2023, 7, 1), Datetime(2023, 7, 2)],
                "lat": [50.5] * 2,
                "lon": [10.5] * 2,
                "source_lat": [50.5] * 2,
                "source_lon": [10.5, 11.5],
            }
        )
        Result = AddSeasonalNdvi(
            Frame, Directory, IdColumn="SOUID", Coordinates=("source_lat", "source_lon")
        )
        ExpectEqual(Result["ndvi"].to_list(), [-1.0, 1.0])


def ConservativeSelectionDoesNotTrimResiduals():
    Frame = Pl.DataFrame(
        {
            "STAID": [2, 1, 3, 4, 5, 6],
            "SOUID": [100, 100, 101, 102, 103, 104],
            "date": [Datetime(2020, 1, 1)] * 6,
            "Q_TX": [0] * 6,
            "era5_land_fallback": [False, False, True, False, False, False],
            "source_same_grid_cell": [True, True, True, True, False, True],
            "residual": [1.0, 1.0, 1.0, 1.0, 1.0, 40.0],
        }
    )
    Accepted, Excluded = SelectTemperaturePairs(Frame, [4])
    ExpectEqual(Accepted["STAID"].to_list(), [1, 6])
    ExpectEqual(len(Excluded), 4)
    ExpectEqual(
        set(Excluded["exclusion_reason"].to_list()),
        {
            "era5_land_fallback",
            "station_series_quarantined",
            "source_location_grid_mismatch",
            "reused_source_observation",
        },
    )


def SourceMetadataHandlesCommasAndRecordsOffsets():
    with TemporaryDirectory() as Directory:
        Directory = Path(Directory)
        Row = (
            f"{2:5d},{136438:6d},{'FALUN, OBS':40s},SE,+60:37:00,+015:37:00,{160:4d},{'TX2':>4s}\n"
        )
        (Directory / "sources.txt").write_text("\n" * 25 + Row)
        Observations = Pl.DataFrame({"STAID": [2], "SOUID": [36438]})
        Result = AttachSourceMetadata(Observations, Directory)
        ExpectEqual(Result["source_metadata_id"].item(), 136438)
        ExpectEqual(Result["source_metadata_id_offset"].item(), 100000)
        ExpectEqual(Result["observation_window"].item(), "TX2")
        Other = Row.replace("136438", " 36438")
        (Directory / "sources.txt").write_text("\n" * 25 + Row + Other)
        ExpectRaises(ValueError, AttachSourceMetadata, Observations, Directory)


def Main():
    Run(MissingCovariatesDoNotDropOtherAnalyses)
    Run(DuplicateDaysAndWrongResidualsFail)
    Run(DistancesFollowStationIdsAndCoordinates)
    Run(NdviExtrapolationUsesPastMatchingSeason)
    Run(NdviRasterNodataAndProvenance)
    Run(ScreeningUsesStationEvidenceAndConsecutiveDates)
    Run(ConservativeSelectionDoesNotTrimResiduals)
    Run(SourceMetadataHandlesCommasAndRecordsOffsets)
    Run(BlendedCopiesAreOneSourceForScreening)
    Run(CovariatesFollowObservationSourceCoordinates)
