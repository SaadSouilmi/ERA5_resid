# Cleanup

Source scope: the new station-window preprocessing pipeline and figures generated
from its sample, including the calculations behind those figures.

## Kept

- All `py.preprocessing` stages, including source/window evidence and hourly weather.
- `py.load_data`, shared inference, raster sampling and figure export helpers.
- All fourteen `analysis_*.py` entry points and their shared helpers.
- Current profiles, interactions, DEGURBA, source map, bootstrap plot and styles.
- Restyling the saved figures without recalculating their statistics.
- The working manuscript, selected publication snapshots, current result files,
  window documentation, plotting skill and Codespaces configuration.

The Plotly/OpenStreetMap station renderer moved from `paper_charts.py` to
`py.scripts.plot_station_map`. It now groups the current sample by actual source
location. The requested redesign adds a clean atlas view with cached Natural
Earth boundaries, EPSG:3035, a horizontal legend, a square panel and PNG/PDF
exports. The original Plotly/OpenStreetMap renderer remains available through
`--style original`. Both use the same source means and ±3°C colour limits.

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

The final source-only pass also archives `geographic_map.py`, `analysis_catalog.py`,
`build_numerical_note.py`, `build_paper_tables.py` and `sync_paper_figures.py`.
Its verified snapshot, including the current uncommitted source, is at:

`/home2/lobib/research-reports/saad.souilmi/archives/figure_source_scope_20261119_231941/`

Unused report paths, Markdown formatting, generic publication wrappers and unused
palette entries were removed. The figure runner keeps the fourteen analyses and
their CSV/results/manifests, and ends without manuscript or note export. Existing
documentation and manuscript snapshots stay available; they are outside the
retained source's output workflow.

`data2/cleaning_audit/source_scope.json` records the retained entry points and
their complete dependency set: all 52 remaining Python modules are reachable.
Import, runner-dispatch, isolated figure-export, unchanged estimator/style,
dataset hash, lint, lockfile and shell checks pass. No tests were added to `src`.

Raw data, rasters, existing releases, credentials, local environments, the
registered `report/` worktree and the running `hourly-weather` job were preserved.
Some historical audit snapshots remain alongside the historical local release;
they are not inputs to the current analysis loader. Current rules and evidence
remain under `data2/cleaning_audit/`.

## Figure paths

Current figures and source tables live in `figures/analysis/`, configured by
`py.paths.ANALYSIS_FIGURES_DIRECTORY`. Plotters, saved result paths and dependent
metadata hashes use this location. The earlier migration also updated the
now-archived note and manuscript exporters.
The move preserves all figures and numerical CSV contents. The migration record
is `data2/cleaning_audit/figure_path_migration.json`; original generation code
hashes remain unchanged. Historical inventory and publication audit snapshots
retain their original paths and are not active result manifests.

Migration checks passed: 57 module imports, eight saved-result/table checksum
chains, publication source resolution, note generation, local links, isolated
profile/interaction/Altair exports and Ruff. All 124 non-JSON artifacts are
byte-identical. The Plotly export check encounters the same Chrome startup failure
with both the previous and renamed exporter; its PDF rendering remains unverified
in the current environment. The running hourly-weather job was preserved and its
queued plotters read the new path.

## Publication status

The queued weather aggregation and full numerical rerun must finish before current
weather plots and tables can be exported. The manuscript's existing assets and
numerical prose still describe the earlier release; see [paper/README.md](../paper/README.md).
No numerical values were refreshed as part of this cleanup.

## Validation

- Before test removal, all 60 Python files imported and current and queued command
  help worked. Weather tests: 5 passed; numerical-method tests: 6 passed.
- Raster sampling, profile bins, means and seeded bootstrap intervals match the
  archived implementations on the comparison cases.
- The temperature file's SHA-256 remains
  `a794e06dc13336388d4fd89645271facb1d6fe4fadf128e029670cb344fccb74`.
  The loader preserves all 6,726,213 temperature rows and their order.
- The initial cleanup preserved all 148 current figure, source-table and note
  assets. The later path migration updates metadata as documented above.
- Ruff, offline lockfile validation, shell syntax, documentation links and
  `git diff --check` pass. Logs are saved with the archive.
