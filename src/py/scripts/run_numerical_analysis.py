"""Run the separate numerical analyses, then refresh tables and the numerical note."""

import argparse
import json
import subprocess
from datetime import datetime, timezone

from py.analysis_catalog import ANALYSES
from py.paths import AnalysisDataDirectory as DATA_DIRECTORY


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
        (name, ["uv", "run", "python", "-m", f"py.analysis_{name}"]) for name, *_ in ANALYSES
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
    for name, command in [
        *initial,
        *commands,
        ("paper_tables", ["uv", "run", "python", "-m", "py.scripts.build_paper_tables"]),
        (
            "numerical_note",
            ["uv", "run", "python", "-m", "py.scripts.build_numerical_note", "--require-complete"],
        ),
    ]:
        progress["current"] = name
        progress_path.write_text(json.dumps(progress, indent=2) + "\n")
        print(f"Running {name}", flush=True)
        subprocess.run(command, check=True)
        progress["completed"].append(name)
        if name != "numerical_note":
            subprocess.run(
                ["uv", "run", "python", "-m", "py.scripts.build_numerical_note"], check=True
            )
    progress.update(status="complete", completed_utc=datetime.now(timezone.utc).isoformat())
    progress_path.write_text(json.dumps(progress, indent=2) + "\n")


if __name__ == "__main__":
    main()
