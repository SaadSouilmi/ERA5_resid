import math

import numpy as np
import polars as pl

from py import pdp
from py.scripts.build_paper_figures import bin_feature, feature_frame, summarize

from .check import Expect, ExpectClose, ExpectEqual, Run


def StationData():
    return pl.DataFrame(
        {
            "STAID": [1, 1, 1, 2],
            "residual": [1.0, 1.0, 1.0, 5.0],
            "group": ["rural"] * 4,
            "weight": [1.0, 1.0, 1.0, 3.0],
        }
    )


def ObservationWeightedMean():
    Means, Low, High = pdp.pdp_cluster_bootstrap(
        StationData(), "group", ["rural"], n_boot=1000, rng=np.random.default_rng(42)
    )
    ExpectClose(Means[0], 2.0)
    ExpectClose(Low[0], 1.0)
    ExpectClose(High[0], 5.0)


def WeightedStationBootstrap():
    Means, _, _ = pdp.pdp_cluster_bootstrap(
        StationData(),
        "group",
        ["rural"],
        n_boot=1000,
        rng=np.random.default_rng(42),
        weight_col="weight",
    )
    ExpectClose(Means[0], 3.0)
    Count = 10000
    Samples, _, _ = pdp.cluster_bootstrap_ci(
        StationData(),
        "group",
        ["rural"],
        n_boot=Count,
        rng=np.random.default_rng(42),
        weight_col="weight",
    )
    # Two equally sampled stations give values 1, 3, 3, 5; variance is 2.
    Sigma = math.sqrt(2 / Count)
    Expect(abs(Samples.mean() - 3.0) < 5 * Sigma, "bootstrap mean outside five sigmas")


def PublicationBootstrapIsReproducible():
    Forward = summarize(StationData(), "group", ["rural"], 1000, 42)
    Reverse = summarize(StationData().reverse(), "group", ["rural"], 1000, 42)
    Expect(Forward.equals(Reverse), "row order changed the publication estimates")
    ExpectClose(Forward["mean"][0], 2.0)
    ExpectEqual(Forward["n_observations"][0], 4)
    ExpectEqual(Forward["n_stations"][0], 2)


def QuantilesHandleTiesAndFiniteEndpoints():
    Frame = pl.DataFrame({"feature": [0.0, 0.0, 0.0, 1.0]})
    _, Bins = bin_feature(Frame, "feature", 10)
    Centers = pdp.bin_centers(Bins, 0.0, 1.0)
    Expect(all(math.isfinite(Value) for Value in Centers), "non-finite bin center")
    Expect(all(0 <= Value <= 1 for Value in Centers), "bin center outside input range")


def ElevationCodesAreExcludedLocally():
    Frame = pl.DataFrame({"elevation": [-9999, -999, -10, 500], "wind": [1.0, 2.0, 3.0, 4.0]})
    ExpectEqual(feature_frame(Frame, ["elevation"])["elevation"].to_list(), [-10, 500])
    ExpectEqual(feature_frame(Frame, ["wind"]).height, 4)


def Main():
    Run(ObservationWeightedMean)
    Run(WeightedStationBootstrap)
    Run(PublicationBootstrapIsReproducible)
    Run(QuantilesHandleTiesAndFiniteEndpoints)
    Run(ElevationCodesAreExcludedLocally)
