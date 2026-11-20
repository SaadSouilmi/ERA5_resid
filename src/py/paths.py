"""Shared repository and output paths."""

from pathlib import Path

ProjectRoot = Path(__file__).resolve().parents[2]
RawDataDirectory = ProjectRoot / "data/main"
AnalysisDataDirectory = ProjectRoot / "data2"
ANALYSIS_FIGURES_DIRECTORY = ProjectRoot / "figures/analysis"
