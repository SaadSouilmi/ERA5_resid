"""Restyle saved numerical-note figures without rerunning statistical analyses."""

import importlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from py import analysis_common as common
from py.analysis_descriptive import residual_histogram
from py.paths import ANALYSIS_FIGURES_DIRECTORY as FIGURES_DIRECTORY, ProjectRoot as PROJECT_ROOT

ANALYSES = [
    "descriptive",
    "utc_windows",
    "heat_excess",
    "heatwaves",
    "fixed_effects",
    "ndvi_sensitivity",
    "geographic_deciles",
    "relative_elevation",
]


def main():
    tables_before = {
        str(path): common.sha256(path)
        for directory in [
            FIGURES_DIRECTORY / "partial_dependence",
            FIGURES_DIRECTORY / "interactions",
            common.OUTPUT_DIRECTORY,
        ]
        for path in directory.rglob("*.csv")
    }
    degurba = {
        str(path): common.sha256(path)
        for directory in [PROJECT_ROOT / "notes/assets", FIGURES_DIRECTORY / "partial_dependence"]
        for path in directory.glob("degurba*")
        if path.is_file()
    }
    for name in ANALYSES:
        directory = common.OUTPUT_DIRECTORY / name
        tables = {path.stem: pl.read_csv(path) for path in (directory / "tables").glob("*.csv")}
        if name == "descriptive" and "residual_histogram" not in tables:
            input_path = common.DATA_DIRECTORY / "station_era5_clean.parquet"
            manifest = json.loads((directory / "manifest.json").read_text())
            assert common.sha256(input_path) == manifest["inputs"][str(input_path)]
            values = pl.read_parquet(input_path, columns=["residual_celsius"])["residual_celsius"]
            tables["residual_histogram"] = residual_histogram(values.to_numpy())
            tables["residual_histogram"].write_csv(directory / "tables/residual_histogram.csv")
        importlib.import_module(f"py.analysis_{name}").plot(tables)
        print(f"Restyled {name}", flush=True)
    for module, directory, key in [
        ("plot_partial_dependence", "partial_dependence", "features"),
        ("plot_interactions", "interactions", "pairs"),
    ]:
        manifest = json.loads((FIGURES_DIRECTORY / directory / "manifest.json").read_text())
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-m",
                f"py.scripts.{module}",
                "--from-tables",
                f"--{key}",
                *manifest[key],
            ],
            check=True,
        )
    assert all(common.sha256(Path(path)) == digest for path, digest in tables_before.items())
    assert all(common.sha256(Path(path)) == digest for path, digest in degurba.items())
    code = [
        Path(__file__),
        PROJECT_ROOT / "src/py/analysis_common.py",
        PROJECT_ROOT / "src/py/scripts/scientific_style.py",
        PROJECT_ROOT / "src/py/scripts/plot_style.py",
        *[PROJECT_ROOT / f"src/py/analysis_{name}.py" for name in ANALYSES],
    ]
    record = {
        "restyled_utc": datetime.now(timezone.utc).isoformat(),
        "style": "Original bar/curve styles; STIX limited to whisker plots; red/green paired series",
        "statistics": "Original means, intervals, totals, samples and bin definitions preserved",
        "formats": ["PNG (300 or 600 dpi)", "vector PDF", "existing SVGs refreshed"],
        "source_tables_unchanged": tables_before,
        "degurba_unchanged": degurba,
        "render_code_sha256": {str(path): common.sha256(path) for path in code},
    }
    (common.OUTPUT_DIRECTORY / "restyle_manifest.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    print(
        f"Verified {len(tables_before)} unchanged source tables and all DEGURBA files.", flush=True
    )


if __name__ == "__main__":
    main()
