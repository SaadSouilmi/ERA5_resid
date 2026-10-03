# Project context

Read AGENTS.md for repository conventions and README.md for the current workflow.

This project compares European ECA&D daily maximum temperature with ERA5-Land
daily maximum temperature. Residual means station minus ERA5, in degrees Celsius.
The working draft is `paper.tex`.

The current analysis input is `data2/clean/analysis.parquet`, with its release
manifest in `data2/clean/summary.json`. The original `data2/residuals.parquet`
is preserved locally as an input, not used directly by current analyses.

Start with `src/py/notebooks/cleaning_process.py` for the implemented cleaning
policy, sequential selection counts, provenance checks and NDVI extrapolation.
All active notebooks are Marimo apps under `src/py/notebooks/`. Use `uv` and
PascalCase Python bindings as described in AGENTS.md.

Do not treat seasonal NDVI extrapolations as observed vegetation, the supplied
precipitation proxy as a daily total, or mixed observation windows as aligned.
Station screening is provisional. Post-stratification remains exploratory.

Deprecated notebooks and reports are available from Git history and a verified
local archive; they are not alternative active workflows.
