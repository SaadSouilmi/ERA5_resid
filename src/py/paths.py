"""Shared repository and output paths."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIRECTORY = PROJECT_ROOT / "data/main"
ANALYSIS_DATA_DIRECTORY = PROJECT_ROOT / "data2"
ANALYSIS_FIGURES_DIRECTORY = PROJECT_ROOT / "figures/analysis"
