"""Station-only screening and traceable ECA&D observation provenance."""

import hashlib as Hashlib
import warnings as Warnings

import numpy as Np
import pandas as Pd
import polars as Pl
from scipy.spatial import cKDTree as Tree

from py.paths import RawDataDirectory


def DecimalDegrees(Value):
    Parts = str(Value).strip().split(":")
    Sign = -1 if Parts[0].startswith("-") else 1
    return Sign * (abs(float(Parts[0])) + float(Parts[1]) / 60 + float(Parts[2]) / 3600)


def AttachSourceMetadata(Observations, Directory=RawDataDirectory / "ECA_blend_tx"):
    Metadata = Pd.read_fwf(
        Directory / "sources.txt",
        skiprows=25,
        header=None,
        colspecs=[(0, 5), (6, 12), (57, 66), (67, 77), (78, 82), (83, 87)],
        names=["STAID", "SOUID", "LAT", "LON", "HGHT", "ELEI"],
    )
    Metadata["source_lat"] = Metadata["LAT"].map(DecimalDegrees)
    Metadata["source_lon"] = Metadata["LON"].map(DecimalDegrees)
    Metadata["source_elevation"] = Metadata["HGHT"].replace([-999, -9999], Np.nan)
    Metadata["observation_window"] = Metadata["ELEI"].str.strip()
    Metadata = (
        Pl.from_pandas(Metadata)
        .select(
            "STAID", "SOUID", "source_lat", "source_lon", "source_elevation", "observation_window"
        )
        .unique()
        .rename({"SOUID": "source_metadata_id"})
    )
    Candidates = Pl.concat(
        [
            Metadata.with_columns(
                Pl.col("source_metadata_id").alias("SOUID"),
                Pl.lit(0).alias("source_metadata_id_offset"),
            ),
            Metadata.filter(Pl.col("source_metadata_id") < 900000).with_columns(
                (Pl.col("source_metadata_id") - 100000).alias("SOUID"),
                Pl.lit(100000).alias("source_metadata_id_offset"),
            ),
        ]
    ).join(Observations.select("STAID", "SOUID").unique(), on=["STAID", "SOUID"], how="semi")
    if Candidates.select(Pl.struct("STAID", "SOUID").is_duplicated().any()).item():
        raise ValueError("Ambiguous observation-to-metadata source identifiers")
    return Observations.join(Candidates, on=["STAID", "SOUID"], how="left", validate="m:1")


def ObservationSources(Frame, Output, Directory=RawDataDirectory / "ECA_blend_tx"):
    Groups = (
        Frame.select("STAID", "date", "station_celsius")
        .with_columns(Pl.col("date").dt.strftime("%Y%m%d").cast(Pl.Int64).alias("DATE"))
        .partition_by("STAID", as_dict=True)
    )
    Chunks, Files = [], []
    for Index, ((Staid,), Group) in enumerate(Groups.items()):
        File = Directory / f"TX_STAID{Staid:06d}.txt"
        Raw = Pd.read_csv(File, skiprows=20, skipinitialspace=True)
        Raw = Raw[Raw.DATE.between(Group["DATE"].min(), Group["DATE"].max())]
        Joined = Group.join(Pl.from_pandas(Raw), on=["STAID", "DATE"], how="left", validate="1:1")
        if Joined.filter(
            Pl.col("Q_TX").is_null()
            | (Pl.col("Q_TX") != 0)
            | (Pl.col("TX") == -9999)
            | ((Pl.col("TX") / 10 - Pl.col("station_celsius")).abs() > 1e-8)
        ).height:
            raise ValueError(f"Source mismatch at station {Staid}")
        Chunks.append(Joined.select("STAID", "date", "SOUID", "Q_TX"))
        Files.append({"file": str(File), "sha256": Hashlib.sha256(File.read_bytes()).hexdigest()})
        if Index % 500 == 0:
            print(f"Observation provenance: {Index + 1}/{len(Groups)} stations", flush=True)
    Files.append(
        {
            "file": str(Directory / "sources.txt"),
            "sha256": Hashlib.sha256((Directory / "sources.txt").read_bytes()).hexdigest(),
        }
    )
    Pl.DataFrame(Files).write_csv(Output / "station_source_files.csv")
    return AttachSourceMetadata(Pl.concat(Chunks), Directory)


def TemperatureEvidence(Frame):
    """Conservative review rules in degrees C; neither ERA5 nor residuals are used."""
    Stations = (
        Frame.group_by("STAID")
        .agg(*[Pl.col(Name).first() for Name in ["lat", "lon", "elevation"]])
        .sort("STAID")
    )
    Lat, Lon = Np.deg2rad(Stations["lat"].to_numpy()), Np.deg2rad(Stations["lon"].to_numpy())
    Xyz = Np.column_stack([Np.cos(Lat) * Np.cos(Lon), Np.cos(Lat) * Np.sin(Lon), Np.sin(Lat)])
    Dist, Neighbors = Tree(Xyz).query(Xyz, k=min(64, len(Stations)))
    Dist, Neighbors = (
        Np.reshape(Dist, (len(Stations), -1)),
        Np.reshape(Neighbors, (len(Stations), -1)),
    )
    Dist = 6371 * 2 * Np.arcsin(Np.minimum(Dist / 2, 1))
    Elev = Stations["elevation"].to_numpy()
    Valid = (Dist >= 15) & (Dist <= 100) & (Np.abs(Elev[Neighbors] - Elev[:, None]) <= 300)
    Start = Frame["date"].min().date()
    Days = (Frame["date"].max().date() - Start).days + 1
    Indexed = Frame.join(
        Stations.select("STAID").with_row_index("station_index"), on="STAID", validate="m:1"
    ).with_columns((Pl.col("date").dt.date() - Start).dt.total_days().alias("day_index"))
    Y, X = Indexed["day_index"].to_numpy(), Indexed["station_index"].to_numpy()
    Daily = Np.full((Days, len(Stations)), Np.nan)
    Daily[Y, X] = Indexed["station_celsius"].to_numpy()
    Median = Np.full_like(Daily, Np.nan)
    Count = Np.zeros(Daily.shape, dtype=Np.int16)
    Locations = list(zip(Stations["lat"].to_list(), Stations["lon"].to_list()))
    for Index in range(len(Stations)):
        Selected, Seen = [], set()
        for Neighbor in Neighbors[Index][Valid[Index]]:
            if Locations[Neighbor] not in Seen:
                Selected.append(Neighbor)
                Seen.add(Locations[Neighbor])
            if len(Selected) == 10:
                break
        if len(Selected) >= 3:
            Values = Daily[:, Selected]
            Count[:, Index] = Np.isfinite(Values).sum(axis=1)
            with Warnings.catch_warnings():
                Warnings.simplefilter("ignore", RuntimeWarning)
                Median[:, Index] = Np.nanmedian(Values, axis=1)
    Previous, Following = Np.full_like(Daily, Np.nan), Np.full_like(Daily, Np.nan)
    Previous[1:], Following[:-1] = Daily[:-1], Daily[1:]
    Evidence = Indexed.select("STAID", "date", "station_celsius").with_columns(
        Pl.Series("neighbor_median", Median[Y, X]).fill_nan(None),
        Pl.Series("neighbor_count", Count[Y, X]),
        Pl.Series("previous_day", Previous[Y, X]).fill_nan(None),
        Pl.Series("next_day", Following[Y, X]).fill_nan(None),
    )
    DeltaBefore = Pl.col("station_celsius") - Pl.col("previous_day")
    DeltaAfter = Pl.col("station_celsius") - Pl.col("next_day")
    return Evidence.with_columns(
        (~Pl.col("station_celsius").is_between(-60, 50)).alias("source_range_flag"),
        (
            (Pl.col("neighbor_count") >= 3)
            & ((Pl.col("station_celsius") - Pl.col("neighbor_median")).abs() > 20)
        )
        .fill_null(False)
        .alias("source_spatial_flag"),
        (((DeltaBefore > 20) & (DeltaAfter > 20)) | ((DeltaBefore < -20) & (DeltaAfter < -20)))
        .fill_null(False)
        .alias("source_spike_flag"),
    ).with_columns(
        Pl.any_horizontal("source_range_flag", "source_spatial_flag", "source_spike_flag").alias(
            "source_review_required"
        )
    )


def SourceTemperatureEvidence(Frame):
    Sources = (
        Frame.select(
            Pl.col("SOUID").alias("STAID"),
            "date",
            "station_celsius",
            Pl.col("source_lat").alias("lat"),
            Pl.col("source_lon").alias("lon"),
            Pl.col("source_elevation").alias("elevation"),
        )
        .unique()
        .sort("STAID", "date")
    )
    if Sources.select(Pl.struct("STAID", "date").is_duplicated().any()).item():
        raise ValueError("Conflicting measurements or metadata for a repeated source-day")
    return TemperatureEvidence(Sources).rename({"STAID": "SOUID"})


def SelectTemperaturePairs(Frame, SuspectStations):
    """Return accepted pairs and every rejected row with an explicit reason."""
    Frame = Frame.with_columns(
        Pl.when(Pl.col("era5_land_fallback").fill_null(True))
        .then(Pl.lit("era5_land_fallback"))
        .when(Pl.col("STAID").is_in(SuspectStations))
        .then(Pl.lit("station_series_quarantined"))
        .when(Pl.col("SOUID").is_null() | (Pl.col("Q_TX") != 0).fill_null(True))
        .then(Pl.lit("invalid_observation_source"))
        .when(~Pl.col("source_same_grid_cell").fill_null(False))
        .then(Pl.lit("source_location_grid_mismatch"))
        .otherwise(Pl.lit(""))
        .alias("exclusion_reason")
    ).sort("STAID", "date")
    Eligible = Frame.filter(Pl.col("exclusion_reason") == "").with_columns(
        Pl.struct("SOUID", "date").is_first_distinct().alias("first_source_observation")
    )
    Repeated = (
        Eligible.filter(~Pl.col("first_source_observation"))
        .drop("first_source_observation")
        .with_columns(Pl.lit("reused_source_observation").alias("exclusion_reason"))
    )
    Accepted = Eligible.filter(Pl.col("first_source_observation")).drop(
        "first_source_observation", "exclusion_reason"
    )
    Excluded = Pl.concat([Frame.filter(Pl.col("exclusion_reason") != ""), Repeated])
    return Accepted, Excluded
