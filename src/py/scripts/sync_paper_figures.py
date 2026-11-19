"""Copy the draft's selected current-sample PDFs, source tables and provenance."""

import argparse
import json
import re
import shutil

from py.paths import AnalysisDataDirectory, NotebookFiguresDirectory, ProjectRoot
from py.preprocessing.match_era5_grid import sha256


def figure_sources(name):
    directory = NotebookFiguresDirectory
    if name == "degurba.pdf":
        folder = directory / "partial_dependence"
        return folder / "degurba_seaborn.pdf", folder / "degurba_manifest.json", [
            *sorted((folder / "tables").glob("degurba*.csv"))
        ]
    if name.startswith("pdp_"):
        folder = directory / "partial_dependence"
        feature = name.removeprefix("pdp_").removesuffix(".pdf")
        return folder / name, folder / "manifest.json", [
            folder / "tables" / f"pdp_{feature}.csv",
            folder / "tables" / f"histogram_{feature}.csv",
        ]
    if name == "station_map.pdf":
        folder = directory / "station_map"
        return folder / name, folder / "manifest.json", [
            folder / "tables/source_means.csv", folder / "station_map.plotly.json"
        ]
    folder = directory / "interactions"
    stem = name.removesuffix(".pdf")
    return folder / name, folder / "manifest.json", [
        folder / "tables" / f"{stem}{suffix}.csv" for suffix in ["", "_hist_x", "_hist_y"]
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate sources without copying")
    args = parser.parse_args()
    paper = ProjectRoot / "paper"
    text = re.sub(r"(?<!\\)%[^\n]*", "", (paper / "paper.tex").read_text())
    names = list(dict.fromkeys(re.findall(
        r"\\includegraphics(?:\[[^\]]*\])?\{figures/([^{}]+\.pdf)\}", text
    )))
    if not names or any("/" in name for name in names):
        raise ValueError("Use explicit PDF filenames directly under paper/figures")
    temperature = AnalysisDataDirectory / "station_era5_clean.parquet"
    digest = sha256(temperature)
    sources = {}
    for name in names:
        source, manifest_path, tables = figure_sources(name)
        manifest = json.loads(manifest_path.read_text())
        if manifest["inputs"].get(str(temperature)) != digest:
            raise ValueError(f"Rebuild {source}: its temperature sample differs")
        if name.startswith("pdp_") and name[4:-4] not in manifest["features"]:
            raise ValueError(f"Rebuild {source}: feature absent from the current manifest")
        if source.parent.name == "interactions" and source.stem not in manifest["pairs"]:
            raise ValueError(f"Rebuild {source}: pair absent from the current manifest")
        if name in ["pdp_tp.pdf", "pdp_wind.pdf", "station_celsius_by_wind.pdf"]:
            weather = AnalysisDataDirectory / "station_hourly_weather.parquet"
            if manifest["inputs"].get(str(weather)) != sha256(weather):
                raise ValueError(f"Rebuild {source}: hourly weather differs")
        provenance = f"{source.parent.name}_{manifest_path.name}"
        files = {provenance: manifest_path, **{path.name: path for path in tables}}
        sources[name] = {
            "source": str(source.relative_to(ProjectRoot)),
            "sha256": sha256(source),
            "temperature_sha256": digest,
            "source_files": {
                target: {"source": str(path.relative_to(ProjectRoot)), "sha256": sha256(path)}
                for target, path in files.items()
            },
        }
    if not args.check:
        figures, tables = paper / "figures", paper / "tables"
        figures.mkdir(exist_ok=True)
        tables.mkdir(exist_ok=True)
        for name, record in sources.items():
            shutil.copy2(ProjectRoot / record["source"], figures / name)
            for target, item in record["source_files"].items():
                shutil.copy2(ProjectRoot / item["source"], tables / target)
        (tables / "figure_sources.json").write_text(json.dumps(sources, indent=2) + "\n")
    print(f"{'Validated' if args.check else 'Copied'} {len(sources)} current-sample figures")


if __name__ == "__main__":
    main()
