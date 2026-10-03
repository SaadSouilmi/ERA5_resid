import numpy as Np
import polars as Pl

from py.cleaning import FeatureRows


def ClusterBootstrapCi(
    Df: Pl.DataFrame,
    BinCol: str,
    Bins: list,
    NBoot=1000,
    Ci=95,
    Rng: Np.random.Generator = None,
    WeightCol: str = None,
):
    """Cluster bootstrap at station level: resample STAIDs, compute (weighted) mean residual per bin."""
    if WeightCol is None:
        StationBin = Df.group_by("STAID", BinCol).agg(
            Pl.col("residual").sum().alias("sum"), Pl.col("residual").count().alias("count")
        )
    else:
        StationBin = Df.group_by("STAID", BinCol).agg(
            (Pl.col("residual") * Pl.col(WeightCol)).sum().alias("sum"),
            Pl.col(WeightCol).sum().alias("count"),
        )

    NBins = len(Bins)
    BootMeans = Np.zeros((NBins, NBoot))

    for Index, B in enumerate(Bins):
        SubDf = StationBin.filter(StationBin[BinCol].eq(B))
        Arr = Np.zeros((SubDf["STAID"].n_unique(), 2))
        Arr[:, 0] = SubDf["sum"]
        Arr[:, 1] = SubDf["count"]

        Ids = Rng.choice(Np.arange(Arr.shape[0]), size=(NBoot, Arr.shape[0]), replace=True)
        Samples = Arr[Ids, :]
        Stats = Samples.sum(axis=1)
        BootMeans[Index] = Stats[:, 0] / Stats[:, 1]

    PctLo = (100 - Ci) / 2
    PctHi = 100 - PctLo
    CiHi = Np.percentile(BootMeans, PctHi, axis=1)
    CiLo = Np.percentile(BootMeans, PctLo, axis=1)

    return BootMeans, CiLo, CiHi


def BinCenters(Bins, DataMin, DataMax):
    Centers = []
    for B in Bins:
        Lo, Hi = B.strip("(]").split(", ")
        Lo = DataMin if Lo == "-inf" else float(Lo)
        Hi = DataMax if Hi == "inf" else float(Hi)
        Centers.append((Lo + Hi) / 2)

    return Centers


def BinFeatures(Df: Pl.DataFrame, Feature: str, NBins: int = 5):
    Df = FeatureRows(Df, [Feature])
    Df = Df.with_columns(Pl.col(Feature).qcut(NBins, allow_duplicates=True).alias("bin"))
    Bins = sorted(
        Df["bin"].drop_nulls().unique().to_list(),
        key=lambda B: float(B.strip("(]").split(", ")[0].replace("-inf", "-999999")),
    )

    return Df, Bins


def PdpClusterBootstrap(
    Df, BinCol, Bins, NBoot=1000, Ci=95, Rng: Np.random.Generator = None, WeightCol: str = None
):
    """Bin feature into quantiles, compute (weighted) mean residual + cluster bootstrap 95% CI."""
    if WeightCol is None:
        Means = Df.group_by(BinCol).agg(Pl.col("residual").mean())
    else:
        Means = Df.group_by(BinCol).agg(
            ((Pl.col("residual") * Pl.col(WeightCol)).sum() / Pl.col(WeightCol).sum()).alias(
                "residual"
            )
        )
    Means = Means.with_columns(Pl.col(BinCol).cast(Pl.Enum(Bins))).sort(BinCol)
    _, CiLo, CiHi = ClusterBootstrapCi(Df, BinCol, Bins, NBoot, Ci, Rng, WeightCol=WeightCol)

    return Means["residual"].to_numpy(), CiLo, CiHi
