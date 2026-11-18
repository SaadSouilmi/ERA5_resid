"""Shared repository and output paths."""

import os as Os
from pathlib import Path

ProjectRoot = Path(__file__).resolve().parents[2]
RawDataDirectory = ProjectRoot / "data/main"
AnalysisDataDirectory = ProjectRoot / "data2"
FiguresDirectory = ProjectRoot / "figures/paper"
NotebookFiguresDirectory = ProjectRoot / "figures/notebooks"
ReportsDirectory = Path(
    Os.environ.get("ERA5_REPORTS_DIR", "/home2/lobib/research-reports/saad.souilmi")
).expanduser()
