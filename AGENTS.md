# Repository guidance

This project studies ERA5-Land temperature residuals against European weather
stations. Residual means station temperature minus ERA5 temperature.

All active Python source belongs under `src/py`, the `py` package. Analysis
modules live directly in that directory. Scripts and Marimo notebooks live in
`py.scripts` and `py.notebooks`. Use `uv` for environments and Python execution.
Use `py.paths` for repository paths. Run computational work in a dedicated tmux
session and remove the session when the command finishes.

Historical Jupyter notebooks, Quarto reports and the duplicate standalone
post-stratification exporter have been retired. Recover historical analyses from
Git history; the last pre-refactor state is commit `5ee9293`. Do not restore old
outputs as current results. Active entry points are listed in README.md.

## Python naming

Use PascalCase for functions, arguments, variables, constants and import aliases
throughout `src/py`. Keep module and package filenames in snake_case. Preserve
Python special names and Marimo's generated `marimo`, `app`, `_` and
`__generated_with` names. Retain the leading underscore on private notebook
variables, for example `_Frame`. External API names, keyword arguments, data
columns, serialized keys and command-line flags retain their required spelling.

## Python tests

Tests live in `src/py/tests`. Use plain functions, explicit `Run(Fn)` calls and
`Expect*` helpers, with PascalCase test functions and local variables. Print each
result and a final passed/failed summary, green/red in terminals. Count failed
tests, not individual assertions. Exit with the failure count, capped at 255,
including suite errors. Do not use `unittest`, `pytest`, `numpy.testing` or
test-only dependencies. The harness uses the standard library; numerical cases
may use existing project dependencies. Fix seeds and state statistical tolerances
in sigmas. Run a suite with `tests/run.sh <name>`.

## Reports and figures

Publication figures use Altair, saved source tables and vector exports. Preserve
statistical estimates when changing presentation. Generated HTML reports go in
`/home2/lobib/research-reports/saad.souilmi` unless the user specifies another path.
For HTML reports, read `~/.codex/html_reports_style.md`.

`paper/paper.tex` is the working draft. The supplied comparison is ECA&D daily maximum
temperature versus ERA5-Land daily maximum temperature. The selected
`data2/residuals.parquet` input may be generated as `residuals_rebuilt.parquet`
by `py.notebooks.temp_resid` and adopted after review; the audited copy is
`data2/residuals_cleaned.parquet`.
`py.scripts.audit_cleaning` records unresolved quality and methodology issues in
`data2/cleaning_audit/`. `py.scripts.export_notebooks` exports the active notebooks
and their Altair PDFs. Treat these as review outputs until the audit's open
scientific questions are resolved; do not silently clip flagged temperatures.

The current analysis input is `data2/clean/analysis.parquet`, built by
`py.scripts.build_clean_dataset`. The conservative temperature baseline excludes
station series flagged by station-only screening, land-fallback matches,
source-location mismatches and repeated source observations. Screening thresholds
are provisional and explicit; do not select observations by ERA5 residual size.
The user authorizes seasonal NDVI extrapolation: use the latest earlier raster
from the same season, preserving source dates, lag and an extrapolation flag.
Keep temperature pairs separate from covariates, and preserve observation-window
metadata plus the UTC-window subset. Notebook and paper-figure exports use the
main screened sample with per-feature covariate availability; their manifests
identify the input hashes. Regenerate them after rebuilding the dataset.

`py.notebooks.cleaning_process` documents the selection in execution order and
checks the saved release. Export it with `py.scripts.export_notebooks cleaning_process`.
Large datasets and rasters stay local and ignored; commit compact audit CSV/JSON
files, source tables and vector figures. HTML outputs stay in ReportsDirectory.
