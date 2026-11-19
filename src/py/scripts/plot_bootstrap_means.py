"""Preview source-bootstrap distributions of the observation-window mean residuals."""

import json
from datetime import datetime, time, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from py import analysis_common as common
from py.scripts.scientific_style import COLORS, percentile_boxes, save_scientific_figure


def main():
    directory = common.OUTPUT_DIRECTORY / "utc_windows"
    source_manifest = json.loads((directory / "manifest.json").read_text())
    input_path = common.DATA_DIRECTORY / "station_era5_clean.parquet"
    input_hash = common.sha256(input_path)
    assert input_hash == source_manifest["inputs"][str(input_path)]
    data = pl.read_parquet(
        input_path,
        columns=["SOUID", "residual_celsius", "window_hours", "window_start_utc", "window_end_utc"],
    )
    data = data.with_columns(
        (
            (pl.col("window_hours") == 24)
            & (pl.col("window_start_utc").dt.time() == time(0))
            & (pl.col("window_end_utc").dt.time() == time(0))
        ).alias("utc_day_aligned")
    )
    subsets = {
        "full": data,
        "utc_midnight": data.filter("utc_day_aligned"),
        "other_resolved": data.filter(~pl.col("utc_day_aligned")),
    }
    saved = pl.read_csv(directory / "tables/summary.csv")
    samples, tables, quantiles = [], [], []
    for name, frame in subsets.items():
        groups = (
            frame.group_by("SOUID")
            .agg(pl.col("residual_celsius").sum().alias("total"), pl.len().alias("count"))
            .sort("SOUID")
        )
        draws = common.bootstrap_ratio_draws(groups["total"], groups["count"], 1000, 1337)
        mean = groups["total"].sum() / groups["count"].sum()
        low, high = np.quantile(draws, [0.025, 0.975])
        original = saved.filter(pl.col("sample") == name).row(0, named=True)
        assert frame.height == original["observations"] and groups.height == original["sources"]
        assert np.allclose(
            [mean, low, high],
            [original["mean"], original["ci_low"], original["ci_high"]],
            rtol=0,
            atol=1e-12,
        ), "Bootstrap must reproduce the saved mean and interval"
        samples.append(draws)
        tables.append(
            pl.DataFrame(
                {
                    "sample": [name] * len(draws),
                    "draw": np.arange(len(draws)),
                    "mean_residual_celsius": draws,
                }
            )
        )
        quantiles.append(
            {
                "sample": name,
                "observations": frame.height,
                "sources": groups.height,
                "mean": mean,
                "ci_low": low,
                "ci_high": high,
                **{
                    f"p{int(q * 100):02d}": float(np.quantile(draws, q))
                    for q in [0.05, 0.25, 0.5, 0.75, 0.95]
                },
            }
        )
    common.setup_plotting(whiskers=True)
    fig, ax = plt.subplots(figsize=(6.5, 3.6), layout="constrained")
    percentile_boxes(ax, samples, np.arange(3), COLORS[:3])
    ax.set_xticks(
        np.arange(3), ["All resolved windows", "00–00 UTC, 24 h", "Other resolved windows"]
    )
    ax.set(xlim=(-0.5, 2.5), ylabel="Bootstrap mean residual (°C)")
    ax.margins(y=0.08)
    paths = save_scientific_figure(fig, directory / "window_bootstrap_means")
    plt.close(fig)
    draws_path = directory / "tables/bootstrap_mean_draws.csv"
    quantiles_path = directory / "tables/bootstrap_mean_quantiles.csv"
    pl.concat(tables).write_csv(draws_path)
    pl.DataFrame(quantiles).write_csv(quantiles_path)
    record = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "bootstrap": 1000,
        "seed": 1337,
        "unit": "SOUID, retaining all source-days within each draw",
        "estimator": "Observation-weighted mean residual within each window sample",
        "display": "25th–75th percentile boxes, median line, 5th–95th percentile whiskers of bootstrap means",
        "interpretation": "Uncertainty in the estimated mean; not the distribution of individual temperatures. Samples overlap, so these are not independent comparisons.",
        "validation": "Matches existing sample counts, means and 95% source-bootstrap intervals within 1e-12 °C",
        "inputs": {str(input_path): input_hash},
        "tables": {str(path): common.sha256(path) for path in [draws_path, quantiles_path]},
        "render_code_sha256": {
            str(path): common.sha256(path)
            for path in [
                Path(__file__),
                Path(common.__file__),
                Path(__file__).with_name("scientific_style.py"),
            ]
        },
        "outputs": [str(path) for path in paths],
    }
    (directory / "bootstrap_mean_manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        "Saved bootstrap mean distributions; verified all three existing estimates and intervals."
    )


if __name__ == "__main__":
    main()
