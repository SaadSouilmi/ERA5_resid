# Repository guidance

This project compares European ECA&D daily maximum temperatures with hourly
ERA5-Land maxima over verified provider UTC windows. Residual means station minus
ERA5-Land temperature, in °C.

All active Python belongs under `src/py`, the `py` package. Preprocessing lives in
`py.preprocessing`, analyses directly in `py` and commands in `py.scripts`.
Use `uv` for environments and Python execution, and `py.paths` for
repository paths. Run computational work in a dedicated tmux session and remove
the session when the command finishes. Simple file reads and documentation edits
do not need tmux.

Historical notebooks, earlier sample builders, website exports and separate NDVI
acquisition experiments have been retired. Recover them from the archive recorded
in `notes/CLEANUP.md` or Git history; commit `5ee9293` preserves the pre-refactor
workflow. Do not restore old outputs as current results. README.md lists active
entry points. Preserve `.devcontainer/` for Codespaces and the registered `report/`
worktree. Do not delete ignored datasets or environments during source cleanup.

## Python naming and implementation

Use idiomatic Python naming: `snake_case` for functions, parameters, variables,
modules and packages, `UPPER_CASE` for constants and `PascalCase` for classes.
Prefer familiar aliases such as `np`, `pd`, `pl` and `xr`. Existing PascalCase APIs
may remain for compatibility; do not rename unrelated code for style. External
API names, data columns, serialized keys and command-line flags retain their
required spelling.

Use small plain functions and direct code. Avoid unnecessary classes, speculative
error handling, redundant checks, exception wrappers and cleanup machinery for
routine operations. Let library exceptions surface naturally. Validate concrete
requirements and scientific assumptions; do not repeat checks the library makes.

## Current data

The current temperature input is `data2/station_era5_clean.parquet`, built by
`py.preprocessing` or `./run.sh`. `notes/PREPROCESSING.md` documents the selection
in execution order; `notes/OBSERVATION_WINDOWS.md` records provider evidence.
Use `py.load_data.load_data()` for analyses and `include_weather=True` when needed.
Keep temperature pairs separate from covariates and preserve row membership,
source identifiers, UTC-window metadata and the exact 24-hour UTC subset.

Selection uses provider quality, European geography, an isolated spike filter,
−60°C to 50°C bounds and the study period. Retained source-days have resolved
provider windows, complete hourly ERA5 coverage and unique `(SOUID, DATE)` keys.
Temperature maxima include both boundary samples. Resolved 12-hour and DST
23/25-hour windows remain included. Do not select by residual magnitude or
silently clip flagged temperatures. Use actual source coordinates; no land-cell
fallback or interpolation.

The user authorizes original seasonal NDVI carry-forward: use each source
location's latest earlier valid value across missing seasons, retaining source
dates, lag and an extrapolation flag. Spatial nodata within an existing season
stays missing. The earlier `data2/clean/analysis.parquet` release used a different
selection and same-season NDVI policy; it is historical local data.

Weather covariates come from hourly ERA5-Land over the saved station windows.
Wind is the magnitude of the time-mean vector; precipitation uses de-accumulated
hourly amounts. Preserve negative precipitation flags and missing-hour metadata.
Missing covariates do not remove temperature pairs; analyses select availability
explicitly. Cluster inference on `SOUID` and keep per-analysis sample counts.

The `hourly-weather` job queues aggregation, figure export and all numerical
analyses. Preserve its paths and helper APIs during refactors. Do not launch
competing rebuilds or downloads. Do not print or commit CDS credentials.

## Reports and figures

Use the project plotting skill at `skills/seaborn-paper-style/SKILL.md`. Preserve
the approved bar/curve styles and red/green paired palette; use the STIX/SciencePlots
variant only for whisker/box plots. Preserve the separately approved DEGURBA
figure when restyling other figures. Preserve estimates when changing presentation.

Default exports are PNG/PDF. Do not generate new SVG files unless explicitly
requested. Saved Altair specifications remain supported for figures using Altair.
The station map keeps the original Plotly/OpenStreetMap style and attribution,
with a 900 dpi square panel fitted to all sources with a small margin; preserve
its Plotly specification.

Exports and source tables live in `figures/notebooks/`; retain this output path
for compatibility. Manuscript PDFs live in `paper/figures/`, source data and tables
in `paper/tables/`. `py.scripts.sync_paper_figures` copies the selected current
figures and provenance; `py.scripts.build_paper_tables` refreshes numerical tables.
Require matching input hashes. `paper/paper.tex` is the working draft; its existing
text and assets await reconciliation with the new release, and the bibliography
is missing. Do not present the old publication assets as current results.

Keep large datasets, rasters, models and live progress local and ignored. Commit
compact scientific evidence, source tables, manifests and figures. Generated HTML
reports go in `/home2/lobib/research-reports/saad.souilmi` unless specified otherwise;
read `~/.codex/html_reports_style.md` before generating HTML.
