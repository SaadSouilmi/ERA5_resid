"""Copy the manuscript's selected notebook PDFs and their exact plotted data."""

import argparse as Argparse
import hashlib as Hashlib
import json as Json
import re as Re
import shutil as Shutil

from py.paths import NotebookFiguresDirectory, ProjectRoot


def Main():
    Argparse.ArgumentParser(description=__doc__).parse_args()
    Paper = ProjectRoot / "paper"
    Text = Re.sub(r"(?<!\\)%[^\n]*", "", (Paper / "paper.tex").read_text())
    Names = Re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{figures/([^{}]+\.pdf)\}", Text)
    if not Names or any("/" in Name for Name in Names):
        raise ValueError("Use explicit PDF filenames directly under paper/figures")
    Figures, Tables = Paper / "figures", Paper / "tables"
    Figures.mkdir(exist_ok=True)
    Tables.mkdir(exist_ok=True)
    Sources = {}
    for Name in dict.fromkeys(Names):
        Matches = list(NotebookFiguresDirectory.glob(f"*/{Name}"))
        if len(Matches) != 1:
            raise ValueError(f"Expected one notebook export for {Name}, found {len(Matches)}")
        Source = Matches[0]
        Specs = [
            Source.with_suffix(Suffix)
            for Suffix in (".vl.json", ".plotly.json")
            if Source.with_suffix(Suffix).is_file()
        ]
        if len(Specs) != 1:
            raise ValueError(f"Expected one Altair or Plotly specification for {Source}")
        Sources[Name] = Source, Specs[0]
    Extra = {File.name for File in Figures.iterdir()} - set(Sources)
    if Extra:
        raise ValueError(f"Move unused assets out of paper/figures first: {sorted(Extra)}")
    Manifest = {}
    for Name, (Source, Spec) in Sources.items():
        Shutil.copy2(Source, Figures / Name)
        Shutil.copy2(Spec, Tables / Spec.name)
        for Suffix in (".vl.json", ".plotly.json"):
            Other = Tables / Source.with_suffix(Suffix).name
            if Other.name != Spec.name:
                Other.unlink(missing_ok=True)
        Manifest[Name] = {
            "source": str(Source.relative_to(ProjectRoot)),
            "sha256": Hashlib.sha256(Source.read_bytes()).hexdigest(),
            "source_specification": str(Spec.relative_to(ProjectRoot)),
            "specification": f"tables/{Spec.name}",
            "specification_sha256": Hashlib.sha256(Spec.read_bytes()).hexdigest(),
        }
    (Tables / "figure_sources.json").write_text(Json.dumps(Manifest, indent=2) + "\n")
    print(f"Copied {len(Sources)} notebook PDFs to {Figures}; source data in {Tables}")


if __name__ == "__main__":
    Main()
