import math as Math

import numpy as Np
import polars as Pl

from py import pdp as Pdp
from py.scripts.build_paper_figures import BinFeature, FeatureFrame, Summarize

from .check import Expect, ExpectClose, ExpectEqual, Run


def StationData():
    return Pl.DataFrame(
        {
            "STAID": [1, 1, 1, 2],
            "residual": [1.0, 1.0, 1.0, 5.0],
            "group": ["rural"] * 4,
            "weight": [1.0, 1.0, 1.0, 3.0],
        }
    )


def ObservationWeightedMean():
    Means, Low, High = Pdp.PdpClusterBootstrap(
        StationData(), "group", ["rural"], NBoot=1000, Rng=Np.random.default_rng(42)
    )
    ExpectClose(Means[0], 2.0)
    ExpectClose(Low[0], 1.0)
    ExpectClose(High[0], 5.0)


def WeightedStationBootstrap():
    Means, _, _ = Pdp.PdpClusterBootstrap(
        StationData(),
        "group",
        ["rural"],
        NBoot=1000,
        Rng=Np.random.default_rng(42),
        WeightCol="weight",
    )
    ExpectClose(Means[0], 3.0)
    Count = 10000
    Samples, _, _ = Pdp.ClusterBootstrapCi(
        StationData(),
        "group",
        ["rural"],
        NBoot=Count,
        Rng=Np.random.default_rng(42),
        WeightCol="weight",
    )
    # Two equally sampled stations give values 1, 3, 3, 5; variance is 2.
    Sigma = Math.sqrt(2 / Count)
    Expect(abs(Samples.mean() - 3.0) < 5 * Sigma, "bootstrap mean outside five sigmas")


def PublicationBootstrapIsReproducible():
    Forward = Summarize(StationData(), "group", ["rural"], 1000, 42)
    Reverse = Summarize(StationData().reverse(), "group", ["rural"], 1000, 42)
    Expect(Forward.equals(Reverse), "row order changed the publication estimates")
    ExpectClose(Forward["mean"][0], 2.0)
    ExpectEqual(Forward["n_observations"][0], 4)
    ExpectEqual(Forward["n_stations"][0], 2)


def QuantilesHandleTiesAndFiniteEndpoints():
    Frame = Pl.DataFrame({"feature": [0.0, 0.0, 0.0, 1.0]})
    _, Bins = BinFeature(Frame, "feature", 10)
    Centers = Pdp.BinCenters(Bins, 0.0, 1.0)
    Expect(all(Math.isfinite(Value) for Value in Centers), "non-finite bin center")
    Expect(all(0 <= Value <= 1 for Value in Centers), "bin center outside input range")


def ElevationCodesAreExcludedLocally():
    Frame = Pl.DataFrame({"elevation": [-9999, -999, -10, 500], "wind": [1.0, 2.0, 3.0, 4.0]})
    ExpectEqual(FeatureFrame(Frame, ["elevation"])["elevation"].to_list(), [-10, 500])
    ExpectEqual(FeatureFrame(Frame, ["wind"]).height, 4)


def Main():
    Run(ObservationWeightedMean)
    Run(WeightedStationBootstrap)
    Run(PublicationBootstrapIsReproducible)
    Run(QuantilesHandleTiesAndFiniteEndpoints)
    Run(ElevationCodesAreExcludedLocally)
