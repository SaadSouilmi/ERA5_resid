"""Brute-force fitted-model partial dependence, averaged over all held-out-source folds."""

import argparse
import gzip
import json
import pickle
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import polars as pl

from py import analysis_common as common
from py.analysis_mos import feature_matrix
from py.preprocessing.land_cover import CLASSES


def run(background_per_fold=5000):
    data = common.load_sample(weather=True)
    mos_directory = common.OUTPUT_DIRECTORY / "mos"
    manifest = json.loads((mos_directory / "manifest.json").read_text())
    for filename, digest in manifest["inputs"].items():
        if common.sha256(Path(filename)) != digest:
            raise ValueError(f"MOS models used a different analysis input: {filename}")
    summary = json.loads((mos_directory / "results.json").read_text())["summary"]
    prediction_path = summary["predictions_file"]
    if common.sha256(Path(prediction_path)) != summary["predictions_sha256"]:
        raise ValueError("Saved out-of-fold predictions differ from the MOS run")
    folds = (
        data.select("observation_id")
        .join(
            pl.read_parquet(prediction_path, columns=["observation_id", "fold"]),
            on="observation_id",
            how="left",
            validate="1:1",
            maintain_order="left",
        )["fold"]
        .to_numpy()
    )
    artifacts = pl.read_csv(mos_directory / "tables/models.csv")
    backgrounds = {}
    for fold in range(5):
        indices = np.flatnonzero(folds == fold)
        backgrounds[fold] = np.random.default_rng(2026 + fold).choice(
            indices, min(background_per_fold, len(indices)), replace=False
        )
    sample = np.concatenate(list(backgrounds.values()))
    tables = {}
    common.setup_plotting()
    for relative in [False, True]:
        matrix, features = feature_matrix(data, relative)
        name = "gradient_boosting_relative_elevation" if relative else "gradient_boosting"
        selected = [
            feature
            for feature in features
            if feature in common.LABELS or feature in ["log10_tp", "degurba"]
        ]
        grids = {}
        for feature in selected:
            values = matrix[sample, features.index(feature)]
            finite = values[np.isfinite(values)]
            grids[feature] = (
                np.unique(finite)
                if feature == "degurba"
                else np.unique(np.quantile(finite, np.linspace(0.05, 0.95, 11)))
            )
        rows = []
        for artifact in artifacts.filter(pl.col("model") == name).iter_rows(named=True):
            path = Path(artifact["file"])
            if common.sha256(path) != artifact["sha256"]:
                raise ValueError(f"Saved fold model changed: {path}")
            with gzip.open(path, "rb") as source:
                fitted = pickle.load(source)
            if fitted["features"] != features:
                raise ValueError("Saved model feature order differs from current features")
            fold = artifact["fold"]
            original = matrix[backgrounds[fold]].copy()
            for feature in selected:
                modified = original.copy()
                for value in grids[feature]:
                    modified[:, features.index(feature)] = value
                    rows.append(
                        {
                            "model": name,
                            "fold": fold,
                            "feature": feature,
                            "x": float(value),
                            "mean_prediction": float(fitted["model"].predict(modified).mean()),
                            "background_rows": len(modified),
                            "held_out_rows": int((folds == fold).sum()),
                        }
                    )
        fold_profiles = pl.DataFrame(rows)
        curve = (
            fold_profiles.group_by("feature", "x")
            .agg(
                (
                    (pl.col("mean_prediction") * pl.col("held_out_rows")).sum()
                    / pl.col("held_out_rows").sum()
                ).alias("mean"),
                pl.col("mean_prediction").min().alias("fold_min"),
                pl.col("mean_prediction").max().alias("fold_max"),
            )
            .sort("feature", "x")
        )
        tables[f"{name}_fold_profiles"] = fold_profiles
        tables[f"{name}_profiles"] = curve
        fig, axes = plt.subplots(3, 3, figsize=(15, 10), layout="constrained")
        for ax, feature in zip(axes.flat, selected):
            part = curve.filter(pl.col("feature") == feature)
            color = common.COLORS[0]
            if feature == "degurba":
                positions = np.arange(part.height)
                ax.vlines(positions, part["fold_min"], part["fold_max"], color=color, linewidth=1)
                ax.plot(positions, part["mean"], "o", color=color, markerfacecolor="white")
            else:
                ax.plot(part["x"], part["mean"], "o-", color=color, markerfacecolor="white")
                ax.fill_between(
                    part["x"],
                    part["fold_min"],
                    part["fold_max"],
                    color=color,
                    alpha=0.15,
                    label="Fold range",
                )
            ax.set(
                xlabel=common.LABELS["tp"]
                if feature == "log10_tp"
                else common.LABELS.get(feature, "DEGURBA class"),
                ylabel="Predicted residual (°C)",
            )
            if feature == "degurba":
                ax.set_xticks(
                    positions,
                    [CLASSES[int(value)] for value in part["x"]],
                    rotation=45,
                    ha="right",
                    fontsize=8,
                )
            ax.grid(True)
        for ax in list(axes.flat)[len(selected) :]:
            ax.set_visible(False)
        axes.flat[0].legend(fontsize=9)
        common.save_plot(fig, "model_partial_dependence", name)
    common.finish(
        "model_partial_dependence",
        data,
        tables,
        {
            "background_per_fold": background_per_fold,
            "background_total": len(sample),
            "mos_results_sha256": common.sha256(mos_directory / "results.json"),
        },
        "Brute-force replacement of one feature at a time, averaging predictions over up to 5,000 held-out background rows per fold; seed 2026+fold. Grids use pooled background 5th–95th percentiles, or observed DEGURBA classes. Combine all five fitted folds with held-out-row weights; shading is the fold minimum–maximum range, not a confidence interval. Avoids the archive's recursion/NaN issue and final-fold-only interpretation. These average predictions on synthetic covariate combinations are model diagnostics, not causal effects.",
        weather=True,
        extra_inputs=[mos_directory / "results.json", mos_directory / "manifest.json"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--background-per-fold", type=int, default=5000)
    run(parser.parse_args().background_per_fold)


if __name__ == "__main__":
    main()
