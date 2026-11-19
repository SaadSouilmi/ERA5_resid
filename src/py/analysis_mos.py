"""Five-fold held-out-source bias-correction benchmark and saved fold models."""

import argparse
import gzip
import pickle
import time

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, SplineTransformer, StandardScaler

from py import analysis_common as common

MODEL_NAMES = [
    "raw_era5",
    "constant_offset",
    "additive_spline",
    "gradient_boosting",
    "gradient_boosting_relative_elevation",
]


def feature_matrix(data, relative=False):
    frame = data
    if relative:
        lookup = pl.read_parquet(
            common.DATA_DIRECTORY / "numerical_analysis/relative_elevation.parquet",
            columns=["SOUID", "relative_elevation_25km"],
        )
        frame = frame.join(lookup, on="SOUID", how="left", validate="m:1", maintain_order="left")
    features = [
        "era5_celsius",
        "wind",
        "elevation",
        "dist_to_sea_km",
        "degurba",
        "log10_tp",
        "ndvi",
        "sin_doy",
        "cos_doy",
    ]
    if relative:
        features.insert(3, "relative_elevation_25km")
    day = 2 * np.pi * pl.col("date").dt.ordinal_day() / 365.25
    frame = frame.with_columns(
        pl.when(pl.col("tp") >= 0)
        .then(pl.col("tp").clip(lower_bound=1e-9).log10())
        .otherwise(None)
        .alias("log10_tp"),
        day.sin().alias("sin_doy"),
        day.cos().alias("cos_doy"),
    )
    return frame.select(pl.col(features).cast(pl.Float32)).to_numpy(), features


def spline_model():
    return Pipeline(
        [
            (
                "prepare",
                ColumnTransformer(
                    [
                        (
                            "splines",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(strategy="median")),
                                    ("spline", SplineTransformer(n_knots=5, degree=3)),
                                ]
                            ),
                            [0, 1, 2, 3],
                        ),
                        ("categories", OneHotEncoder(handle_unknown="ignore"), [4]),
                        (
                            "linear",
                            Pipeline(
                                [
                                    ("impute", SimpleImputer(strategy="median")),
                                    ("scale", StandardScaler()),
                                ]
                            ),
                            [5, 6, 7, 8],
                        ),
                    ]
                ),
            ),
            ("ridge", Ridge(alpha=100)),
        ]
    )


def evaluate(prediction, era5, station, groups):
    corrected = era5.astype(float) + prediction
    error = station.astype(float) - corrected
    per_source = (
        pl.DataFrame({"SOUID": groups, "error": error})
        .group_by("SOUID")
        .agg(pl.col("error").mean().alias("bias"))
    )
    result = {
        "mean_bias_celsius": float(error.mean()),
        "mae_celsius": float(np.abs(error).mean()),
        "rmse_celsius": float(np.sqrt(np.mean(error**2))),
        "median_source_abs_bias_celsius": per_source["bias"].abs().median(),
        "sources_abs_bias_above_1c_percent": 100 * (per_source["bias"].abs() > 1).mean(),
    }
    for threshold in [30, 35]:
        hot, predicted_hot = station > threshold, corrected > threshold
        both = int((hot & predicted_hot).sum())
        result.update(
            {
                f"hot{threshold}_mean_bias_celsius": float(error[hot].mean())
                if hot.any()
                else None,
                f"hot{threshold}_mae_celsius": float(np.abs(error[hot]).mean())
                if hot.any()
                else None,
                f"hot{threshold}_recall_percent": 100 * both / hot.sum() if hot.any() else None,
                f"hot{threshold}_precision_percent": 100 * both / predicted_hot.sum()
                if predicted_hot.any()
                else None,
                f"hot{threshold}_predicted_to_observed_count": float(
                    predicted_hot.sum() / hot.sum()
                )
                if hot.any()
                else None,
            }
        )
    return result


def run(train_limit=800_000, max_iter=200):
    data = common.load_sample(weather=True)
    x, features = feature_matrix(data)
    extended, extended_features = feature_matrix(data, relative=True)
    y = data["residual_celsius"].to_numpy().astype(np.float32)
    era5, station = (data[name].to_numpy() for name in ["era5_celsius", "station_celsius"])
    groups = data["SOUID"].to_numpy()
    predictions = {name: np.zeros(len(y), dtype=np.float32) for name in MODEL_NAMES}
    folds = np.empty(len(y), dtype=np.uint8)
    rows, artifacts, fold_metrics = [], [], []
    directory = common.DATA_DIRECTORY / "numerical_analysis/models"
    directory.mkdir(parents=True, exist_ok=True)
    for fold, (train, test) in enumerate(GroupKFold(n_splits=5).split(x, y, groups=groups)):
        started = time.monotonic()
        folds[test] = fold
        predictions["constant_offset"][test] = y[train].mean(dtype=np.float64)
        sampled = np.random.default_rng(1337 + fold).choice(
            train, min(train_limit, len(train)), replace=False
        )
        spline = spline_model()
        spline.fit(x[sampled], y[sampled])
        predictions["additive_spline"][test] = spline.predict(x[test])
        for name, matrix, names in [
            ("gradient_boosting", x, features),
            ("gradient_boosting_relative_elevation", extended, extended_features),
        ]:
            model = HistGradientBoostingRegressor(
                max_iter=max_iter,
                learning_rate=0.08,
                max_leaf_nodes=63,
                min_samples_leaf=200,
                categorical_features=[names.index("degurba")],
                random_state=1337 + fold,
            )
            model.fit(matrix[sampled], y[sampled])
            predictions[name][test] = model.predict(matrix[test])
            path = directory / f"{name}_fold{fold}.pkl.gz"
            with gzip.open(path, "wb") as output:
                pickle.dump(
                    {"model": model, "features": names, "fold": fold},
                    output,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )
            artifacts.append(
                {"model": name, "fold": fold, "file": str(path), "sha256": common.sha256(path)}
            )
        for name in MODEL_NAMES:
            fold_metrics.append(
                {
                    "fold": fold,
                    "model": name,
                    "train_sources": int(np.unique(groups[train]).size),
                    "test_sources": int(np.unique(groups[test]).size),
                    "training_rows_used": int(len(sampled))
                    if name not in ("raw_era5", "constant_offset")
                    else int(len(train)),
                    **evaluate(predictions[name][test], era5[test], station[test], groups[test]),
                }
            )
        print(f"MOS fold {fold + 1}/5 completed in {time.monotonic() - started:.1f}s", flush=True)
    for name in MODEL_NAMES:
        improvement = (
            pl.DataFrame(
                {
                    "SOUID": groups,
                    "improvement": np.abs(station - era5)
                    - np.abs(station - era5 - predictions[name]),
                }
            )
            .group_by("SOUID")
            .agg(pl.col("improvement").sum(), pl.len().alias("observations"))
            .sort("SOUID")
        )
        interval = common.bootstrap_ratio(improvement["improvement"], improvement["observations"])
        rows.append(
            {
                "model": name,
                **evaluate(predictions[name], era5, station, groups),
                "mae_improvement_celsius": interval["estimate"],
                "mae_improvement_ci_low": interval["ci_low"],
                "mae_improvement_ci_high": interval["ci_high"],
            }
        )
    output = common.DATA_DIRECTORY / "numerical_analysis/mos_predictions.parquet"
    data.select("observation_id", "SOUID", "DATE").with_columns(
        pl.Series("fold", folds), *[pl.Series(name, values) for name, values in predictions.items()]
    ).write_parquet(output, compression="zstd")
    metrics = pl.DataFrame(rows)
    common.setup_plotting()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    positions = np.arange(len(MODEL_NAMES))
    labels = ["Raw ERA5", "Constant", "Spline", "Boosting", "Boosting + neighbours"]
    for index, (field, label) in enumerate([("mae_celsius", "MAE"), ("rmse_celsius", "RMSE")]):
        axes[0].bar(
            positions + (index - 0.5) * 0.35,
            metrics[field],
            width=0.35,
            label=label,
            color=common.COLORS[index],
        )
    axes[0].set(ylabel="Held-out-source error (°C)")
    axes[0].legend()
    for index, threshold in enumerate([30, 35]):
        axes[1].plot(
            positions,
            metrics[f"hot{threshold}_recall_percent"],
            "o-",
            label=f">{threshold}°C",
            color=common.COLORS[index + 2],
        )
    axes[1].set_ylabel("Hot-day recall (%)")
    axes[1].legend()
    for ax in axes:
        ax.set_xticks(positions, labels, rotation=25, ha="right")
        ax.grid(True)
    common.save_plot(fig, "mos", "held_out_source_performance")
    common.finish(
        "mos",
        data,
        {
            "metrics": metrics,
            "fold_metrics": pl.DataFrame(fold_metrics),
            "models": pl.DataFrame(artifacts),
        },
        {
            "folds": 5,
            "train_limit": train_limit,
            "max_iter": max_iter,
            "base_features": features,
            "extended_features": extended_features,
            "predictions_file": str(output),
            "predictions_sha256": common.sha256(output),
        },
        "Five GroupKFold splits by SOUID, covering every retained row out of fold. Raw ERA5, training-mean offset, additive spline ridge, histogram gradient boosting, and boosting plus neighbour-source relative elevation. Learned models share up to 800,000 sampled training rows per fold, seed 1337+fold. Imputation and spline transforms fit training rows only. No station temperature, midpoint or residual-derived feature enters predictors. Missing covariates remain missing for imputation/native tree handling; negative rain totals become missing log precipitation. These are source holdouts over mixed dates, not independent spatial or future-year validation. MAE-improvement intervals use paired SOUID bootstrap draws.",
        weather=True,
        extra_inputs=[
            common.DATA_DIRECTORY / "numerical_analysis/relative_elevation.parquet",
            common.OUTPUT_DIRECTORY / "relative_elevation/manifest.json",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-limit", type=int, default=800_000)
    parser.add_argument("--max-iter", type=int, default=200)
    args = parser.parse_args()
    run(args.train_limit, args.max_iter)


if __name__ == "__main__":
    main()
