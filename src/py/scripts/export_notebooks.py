"""Execute active Marimo notebooks and export HTML, PDF charts and provenance."""

import argparse as Argparse
import hashlib as Hashlib
import html as Html
import json as Json
import subprocess as Subprocess

from pypdf import PdfWriter

from py.paths import (
    AnalysisDataDirectory,
    NotebookFiguresDirectory,
    ProjectRoot,
    RawDataDirectory,
    ReportsDirectory,
)
from py.report_style import StyleHtml

NotebookNames = (
    "cleaning_process",
    "temp_resid",
    "resid_analysis",
    "data_comparison",
    "poststrat_analysis",
)


def Main():
    Parser = Argparse.ArgumentParser(description=__doc__)
    Parser.add_argument("Name", nargs="?", default="all", choices=("all", *NotebookNames))
    Args = Parser.parse_args()
    Names = NotebookNames if Args.Name == "all" else (Args.Name,)
    Audit = Json.loads((AnalysisDataDirectory / "clean/summary.json").read_text())
    if (
        Hashlib.sha256((AnalysisDataDirectory / "residuals.parquet").read_bytes()).hexdigest()
        != Audit["raw_input_sha256"]
    ):
        raise ValueError("The raw data changed; rerun the cleaning audit before exporting")
    if (
        Hashlib.sha256((AnalysisDataDirectory / "clean/analysis.parquet").read_bytes()).hexdigest()
        != Audit["cleaned_data_sha256"]
    ):
        raise ValueError("The analysis data changed; rebuild the clean dataset before exporting")
    Output = ReportsDirectory / "era5-notebooks"
    Output.mkdir(parents=True, exist_ok=True)
    ManifestFile = Output / "exports.json"
    Manifest = Json.loads(ManifestFile.read_text()) if ManifestFile.exists() else {}
    for Name in Names:
        Source = ProjectRoot / "src/py/notebooks" / f"{Name}.py"
        Pending = Output / f"{Name}.pending.html"
        print(f"Executing {Name}...", flush=True)
        with (Output / f"{Name}.log").open("w") as Log:
            Subprocess.run(
                [
                    "uv",
                    "run",
                    "--no-sync",
                    "marimo",
                    "export",
                    "html",
                    str(Source),
                    "--no-include-code",
                    "--force",
                    "-o",
                    str(Pending),
                ],
                cwd=ProjectRoot,
                stdout=Log,
                stderr=Subprocess.STDOUT,
                check=True,
            )
        Pending.write_text(StyleHtml(Pending.read_text()))
        Target = Output / f"{Name}.html"
        Pending.replace(Target)
        Pdfs = sorted((NotebookFiguresDirectory / Name).glob("*.pdf"))
        Manifest = Json.loads(ManifestFile.read_text()) if ManifestFile.exists() else {}
        Manifest[Name] = {
            "html": str(Target),
            "pdfs": [str(File) for File in Pdfs],
            "notebook_sha256": Hashlib.sha256(Source.read_bytes()).hexdigest(),
            "raw_data_sha256": Audit["raw_input_sha256"],
            "cleaned_data": Audit["output"],
            "cleaned_data_sha256": Audit["cleaned_data_sha256"],
            "status": Audit["status"],
        }
        if Name == "data_comparison":
            for Key in ("raw_data_sha256", "cleaned_data", "cleaned_data_sha256"):
                Manifest[Name][Key] = None
            Manifest[Name]["station_metadata"] = {
                str(File): Hashlib.sha256(File.read_bytes()).hexdigest()
                for File in (
                    RawDataDirectory / "ECA_blend_tx/stations.txt",
                    AnalysisDataDirectory / "ECA_homblend_tx/stations.txt",
                )
            }
        if Name == "cleaning_process":
            Manifest[Name]["audit_files"] = {
                str(File.relative_to(ProjectRoot)): Hashlib.sha256(File.read_bytes()).hexdigest()
                for Directory in (
                    AnalysisDataDirectory / "clean",
                    AnalysisDataDirectory / "cleaning_audit",
                )
                for File in sorted(Directory.iterdir())
                if File.suffix in (".csv", ".json")
            }
        ManifestFile.write_text(Json.dumps(Manifest, indent=2) + "\n")
        print(f"Saved {Target}; {len(Pdfs)} figure PDFs", flush=True)
    with PdfWriter() as Book:
        for Record in Manifest.values():
            for File in Record["pdfs"]:
                Book.append(File)
        if Book.pages:
            Book.write(Output / "all_altair_figures.pdf")
    AuditHtml = Output / "data_cleaning.html"
    if "data:font/otf" not in AuditHtml.read_text():
        AuditHtml.write_text(StyleHtml(AuditHtml.read_text()))
    Index = '<!doctype html><html><head><meta charset="utf-8"><title>ERA5 notebooks</title></head><body><h1>ERA5 notebook exports</h1>'
    Index += '<p>Start with the <a href="cleaning_process.html">step-by-step cleaning notebook</a>. The <a href="clean_dataset.html">release summary</a> and <a href="data_cleaning.html">original processing audit</a> record the methods and limitations. The export manifest records the dataset used by each notebook.</p><ul>'
    Index += "".join(
        f'<li><a href="{Name}.html">{Html.escape(Name)}</a>: {len(Record["pdfs"])} figure PDFs</li>'
        for Name, Record in Manifest.items()
    )
    PdfLink = (
        '<p><a href="all_altair_figures.pdf">All notebook figures in one PDF</a></p>'
        if (Output / "all_altair_figures.pdf").exists()
        else ""
    )
    Index += (
        "</ul>"
        + PdfLink
        + "<p>PDFs and their Vega-Lite or Plotly specifications with plotted data are saved in <code>"
        + str(NotebookFiguresDirectory)
        + "</code>.</p></body></html>"
    )
    (Output / "index.html").write_text(StyleHtml(Index))


if __name__ == "__main__":
    Main()
