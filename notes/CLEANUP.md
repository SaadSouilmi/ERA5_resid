# Cleanup

Scope: the current station-window selection and every analysis run on that sample.
The previous workflow is retired from active source.

## Kept

- All `py.preprocessing` stages, including source/window evidence and hourly weather.
- `py.load_data`, shared inference, raster sampling, geography and publication exports.
- All fourteen `analysis_*.py` entry points and their shared catalogue/helpers.
- Current profiles, interactions, DEGURBA, styles and note/table builders.
- The working manuscript, selected publication snapshots, current result files,
  window documentation, plotting skill and Codespaces configuration.

The Plotly/OpenStreetMap station renderer moved from `paper_charts.py` to
`py.scripts.plot_station_map`. It now groups the current sample by actual source
location. The renderer keeps the square panel, fitted extent, attribution, colour
scale and 900 dpi PDF export.

`covariates.py` now contains only raster sampling. `pdp.py` filters finite feature
values directly. Elevation preparation no longer extracts the old daily weather.
Hourly temperature retrieval uses an explicit period and the supplied grid,
without loading the earlier residual sample or running the hourly-station pilot.

## Archived

The verified snapshot is outside the repository:

`/home2/lobib/research-reports/saad.souilmi/archives/cleanup_20261119_132351/`

`before_cleanup.tar.gz` contains 518 files, including untracked work, with SHA-256
hashes in `manifest.json`. `tracked_changes.patch` and `git_status.txt` record the
starting state; `removed_paths.json` lists the initial removals. Ignored files
encountered in removed directories are preserved under `local_leftovers/`.
That directory also holds the retired `src/era5_analysis/` checkpoints and unused
Latin Modern font assets.

Removed from active source: earlier sample builders and audits, Jupyter/Marimo
notebooks, post-stratification, metadata comparison, website and composite-report
exporters, separate NDVI acquisition/benchmark tools, and the hourly-station pilot.
Their corresponding legacy result folders were archived. The supplied ZIP,
comparison manuscript, previous draft and unrelated option-pricing CSVs are also
in the snapshot.

The `src/py/tests/` package and its runner were subsequently removed at the user's
request. All four source files remain recoverable from the verified snapshot.

Raw data, rasters, existing releases, credentials, local environments, the
registered `report/` worktree and the running `hourly-weather` job were preserved.
Some historical audit snapshots remain alongside the historical local release;
they are not inputs to the current analysis loader. Current rules and evidence
remain under `data2/cleaning_audit/`.

## Publication and Git status

The queued weather aggregation and full numerical rerun must finish before current
weather plots and tables can be exported. The manuscript's existing assets and
numerical prose still describe the earlier release; see [paper/README.md](../paper/README.md).
No numerical values were refreshed as part of this cleanup.

The requested branch name is `cleanup`. Creating it failed because this session
mounts `.git` read-only. These are uncommitted working-tree changes; no commit or
push was made. From a writable Git session, run `git switch -c cleanup` to carry
all current changes onto the requested branch before staging the reviewed files.

## Validation

- Before test removal, all 60 Python files imported and current and queued command
  help worked. Weather tests: 5 passed; numerical-method tests: 6 passed.
- Raster sampling, profile bins, means and seeded bootstrap intervals match the
  archived implementations on the comparison cases.
- The temperature file's SHA-256 remains
  `a794e06dc13336388d4fd89645271facb1d6fe4fadf128e029670cb344fccb74`.
  The loader preserves all 6,726,213 temperature rows and their order.
- All 148 retained current figure, source-table and note assets are unchanged.
- Ruff, offline lockfile validation, shell syntax, documentation links and
  `git diff --check` pass. Logs are saved with the archive.
