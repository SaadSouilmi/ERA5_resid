"""Generate figures and their supporting numerical results from the current sample."""

import argparse
import json
import subprocess
from datetime import datetime, timezone

from py.paths import AnalysisDataDirectory as DATA_DIRECTORY

ANALYSES = [
    "descriptive",
    "utc_windows",
    "exceedances",
    "heat_excess",
    "heatwaves",
    "seasonal",
    "fixed_effects",
    "multivariate",
    "covariate_tests",
    "ndvi_sensitivity",
    "geographic_deciles",
    "relative_elevation",
    "mos",
    "model_partial_dependence",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures-ready", action="store_true")
    args = parser.parse_args()
    progress_path = DATA_DIRECTORY / "numerical_analysis.progress.json"
    progress = {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "completed": [],
        "status": "running",
    }
    commands = [
        (name, ["uv", "run", "python", "-m", f"py.analysis_{name}"]) for name in ANALYSES
    ]
    initial = [("degurba", ["uv", "run", "python", "-m", "py.scripts.plot_degurba"])]
    if not args.figures_ready:
        initial += [
            (
                "profiles",
                [
                    "uv",
                    "run",
                    "python",
                    "-m",
                    "py.scripts.plot_partial_dependence",
                    "--features",
                    "station_celsius",
                    "tp",
                    "wind",
                    "ndvi",
                    "dist_to_sea_km",
                    "elevation",
                ],
            ),
            ("interactions", ["uv", "run", "python", "-m", "py.scripts.plot_interactions"]),
        ]
    for name, command in [*initial, *commands]:
        progress["current"] = name
        progress_path.write_text(json.dumps(progress, indent=2) + "\n")
        print(f"Running {name}", flush=True)
        subprocess.run(command, check=True)
        progress["completed"].append(name)
    progress.update(status="complete", completed_utc=datetime.now(timezone.utc).isoformat())
    progress_path.write_text(json.dumps(progress, indent=2) + "\n")


if __name__ == "__main__":
    main()
