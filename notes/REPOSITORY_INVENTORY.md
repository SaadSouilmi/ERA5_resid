# Repository inventory

This is the pre-cleanup snapshot. Implemented decisions and the recovery archive are recorded in [CLEANUP.md](CLEANUP.md).

Figure paths below are historical. Current outputs live in `figures/analysis/`.

Snapshot: **19 November 2026, 12:54 UTC**, branch `dev`, commit `9baa91c`.
Inventory only. Existing source files, datasets and outputs were not changed or deleted.

The current workflow builds `data2/station_era5_clean.parquet` and analyses its **6,726,213 source-days** through `py.load_data`. The older workflow uses `data2/clean/analysis.parquet`, **6,958,414 observations**. Both remain in the tree.

## 1. Working tree

| Item | Count |
|:---|---:|
| Tracked paths | 270 |
| Tracked paths already deleted in the working tree | 65 |
| Modified tracked files | 16 |
| Untracked files before adding this inventory | 304 |
| Python files under `src/py` | 90 |

Most pending deletions are the earlier duplicate figure trees under `paper/figures/`; the old root `tests/run.sh` is also already deleted. These changes predate this inventory. Many untracked files are current analyses, audit evidence and figures that should be reviewed for inclusion.

| Python group | Files, including package initializers |
|:---|---:|
| `src/py/preprocessing/` | 21 |
| `src/py/analysis_*.py` | 16: fourteen analyses and two shared files |
| `src/py/scripts/` | 30 |
| `src/py/notebooks/` | 6 Python files: five Marimo apps and an initializer |
| `src/py/tests/` | 3 Python files; shell runner also present |
| Other modules directly under `src/py` | 14 |

Import tracing from the current preprocessing, analysis, plotting and restyling entry points reaches **56 modules**, including package initializers. The three test modules are separately retained. The remaining **31 modules** belong to additional workflows or research features requiring a scope decision. An absent import does not establish that a command-line tool is unused.

## 2. Keep as the current project

| Paths | Purpose |
|:---|:---|
| `src/py/preprocessing/`, `run.sh` | Station selection, verified UTC windows, ERA5 matching, temperature pairs and covariates |
| `src/py/load_data.py`, `paths.py` | Current input loader and repository paths |
| `src/py/analysis_*.py` | The fourteen current numerical analysis entry points and their shared definitions |
| Current plotting, note/table builders and numerical runners in `src/py/scripts/` | Profiles, interactions, DEGURBA, numerical note and manuscript tables |
| `restyle_note_figures.py`, `plot_bootstrap_means.py`, `plot_style.py`, `scientific_style.py` | Approved plotting styles, restyling and bootstrap-distribution preview |
| `pdp.py`, `publication.py`, `geographic_map.py` | Shared inference, exports and study-area map |
| `src/py/tests/` | Weather-window and numerical-method checks |
| `notes/PREPROCESSING.md`, `OBSERVATION_WINDOWS.md`, `NUMERICAL_ANALYSIS.md` | Current methods, provider evidence and numerical results |
| `skills/seaborn-paper-style/` | Project plotting instructions and references |
| `paper/paper.tex`, current selected figure copies and tables | Working manuscript and publication inputs |
| Current source tables, manifests, PNG/PDF figures under `figures/notebooks/` | Reproducible results and note figures |
| `.devcontainer/`, `pyproject.toml`, `uv.lock`, `.python-version` | Codespaces and environment setup |
| Stable audit CSV/JSON files | Selection decisions, UTC rules, coverage and input/output hashes |

Keep `.venv/` locally and ignored. Its configured interpreter is managed by uv outside this repository.

## 3. First cleanup candidates

| Paths | Finding | Recommendation |
|:---|:---|:---|
| `configuration-metrics.csv`, `configuration_results.csv` | Option-pricing/Heston/hedging results; unrelated to the climate analysis | Move to their own project or a personal archive; exclude from this push |
| `.venv.before-cleanup/` | Old environment, **2.72 GB** | Remove after confirming no notebook kernel still uses it |
| `.python-install/` | Old bundled Python, **0.10 GB**; targeted by the backup environment | Remove with the old environment if no longer used |
| `.ruff_cache/`, `__pycache__/`, `.virtual_documents/`, `.ipynb_checkpoints/` | Generated caches or notebook checkpoints | Clear regenerable caches; review checkpoints before discarding |
| `src/era5_analysis/` | Retired package directory containing bytecode and two checkpoint scripts | Review the checkpoints, then remove the obsolete directory |
| `ERA5_resid_v3_code.zip` | Original supplied code/reference archive, **6.24 MB** | Preserve as a reference archive outside the active source tree; it is not a runtime dependency |
| `docs/docs_from_teams.tgz` | Ignored reference bundle, **176 MB** | Keep archived if useful; it does not need to accompany the active code |
| `skills/crandom-blog-style/` | HTML/blog presentation skill, outside the numerical pipeline | Keep only if the repository will retain that reporting feature |

The old environment and bundled interpreter account for approximately **2.82 GB**. These and the large datasets are already ignored by Git; clearing them affects local storage rather than the proposed commit.

## 4. Workflows requiring a decision

### Older screened-data workflow

These are the principal candidates to retire from the active workflow once their retained features have been accounted for:

| Files | Role |
|:---|:---|
| `scripts/audit_cleaning.py`, `build_clean_dataset.py` | Earlier screened sample and quality policy |
| `notebooks/cleaning_process.py`, `temp_resid.py`, `resid_analysis.py` | Earlier cleaning/rebuild/analysis workflow |
| `notebooks/poststrat_analysis.py` | Exploratory post-stratification and calibration |
| `notebooks/data_comparison.py` | Independent comparison of station metadata releases |
| `scripts/export_notebooks.py` | Exports those five Marimo apps against the earlier release |
| `scripts/build_paper_figures.py`, `build_pages.py` | Older publication composites and website |
| `scripts/audit_paper.py`, `sync_paper_figures.py` | Publication utilities needing adaptation to the new outputs |
| `temperature_quality.py`, `report_style.py`, parts of `paper_charts.py` | Older screening and reporting helpers |

Paths in this table are relative to `src/py/`. The current numerical runner does not invoke this older workflow. Retiring it should preserve the earlier release and its provenance separately.

**Preserve the station map:** `paper_charts.py` still contains the approved Plotly/OpenStreetMap renderer. Extract or port that feature before retiring the module.

**Shared files need function-level cleanup:**

- `cleaning.py` is still imported by `pdp.py` for `FeatureRows`.
- `covariates.py` supplies `SampleRaster` to the current NDVI, land-cover and DEGURBA code. Its older seasonal-NDVI policy also remains in that file.
- `preprocessing/analysis_covariates.py` still supplies `build_source_elevation()` to the current pipeline; its standalone command also extracts the older daily weather covariates.
- `preprocessing/download_era5_hourly.py` supplies `expected_times`, `save_json` and `unpack` to the running weather downloader.
- `plot_style.py` and `scientific_style.py` serve different approved figure types; they are not interchangeable duplicates.

### NDVI research tools

The current analysis uses the original seasonal rasters with carry-forward. These **fourteen files** support the separate observed-NDVI experiments and acquisition archive:

```text
src/py/ndvi_observations.py
src/py/ndvi_fast.py
src/py/ndvi_acquisitions.py
src/py/scripts/fetch_ndvi.py
src/py/scripts/fetch_ndvi_gap.py
src/py/scripts/fetch_ndvi_acquisitions.py
src/py/scripts/resume_ndvi.py
src/py/scripts/plan_ndvi_acquisitions.py
src/py/scripts/benchmark_ndvi.py
src/py/scripts/benchmark_ndvi_archive.py
src/py/scripts/benchmark_ndvi_seasons.py
src/py/scripts/compare_ndvi_overlap.py
src/py/scripts/validate_ndvi.py
src/py/scripts/plot_ndvi.py
```

Recommendation: retain them as optional research work if NDVI development will continue, with their own documentation. Remove their commands from the default workflow documentation. Preserve already downloaded observations independently of any code cleanup.

`src/py/scripts/inspect_ghcnh.py` is another separate research tool: the hourly-station pilot. Its raw downloads are not inputs to the current temperature-pair loader. Keep compact observation-window evidence used by the current rules.

### Jupyter notebooks

| Notebook | Current role |
|:---|:---|
| `src/py/notebooks/preprocessing_walkthrough.ipynb` | Exploratory station selection and UTC-window walkthrough; stops before the current final sample |
| `src/py/notebooks/data_processing.ipynb` | Earlier screened-release walkthrough; code references the older release |

Recommendation: keep only a deliberately maintained walkthrough, or archive both now that the methods live in the notes and Python pipeline. Neither is needed by the current runners.

## 5. Manuscript and output consolidation

There are **three distinct draft files**, with different hashes:

| Path | Size | Role |
|:---|---:|:---|
| `paper/paper.tex` | 42.1 KB | Working draft designated by repository guidance |
| `paper/old_paper.tex` | 49.1 KB | Untracked previous draft; also differs from the manuscript at Git HEAD |
| `paper_new/main.tex` | 52.8 KB | Supplied comparison draft, including material to reconcile |

Keep `paper/paper.tex` as the working draft. Review or archive the other two before deleting anything; their filenames do not establish redundancy. The original ZIP is a separate reference source.

The draft references **`downscaling.bib`**, but no `.bib` file is present under `paper/` or `paper_new/`. A clean publication build still needs that bibliography.

The scan found **27 exact duplicate-content groups** among small visible assets, source tables and figures. Several are intentional:

- `paper/figures/` holds the selected manuscript PDFs.
- `paper/tables/` includes exact plotted-data/specification copies.
- `notes/assets/` holds the selected DEGURBA image, PDF, tables and provenance.
- Separate analysis directories can contain identical source tables while remaining independently reproducible.

Nine selected manuscript PDFs match the older `figures/notebooks/resid_analysis/` exports byte for byte. They should be refreshed deliberately from the new results when ready.

`sync_paper_figures.py` searches all notebook-output directories for a unique PDF filename and requires an Altair/Plotly specification. Current Seaborn outputs use CSV tables and manifests, and older/newer folders share filenames. Adapt this copier before using it for the new release. The existing paper audit likewise targets the earlier dataset.

The older `figures/paper/` composites and notebook exports can be archived when the website/Marimo decision is made. Avoid regenerating old results into directories presented as the current release.

## 6. Local data and protected state

Large datasets are already ignored. The inventory measured selected directories without recursively crawling `data2/ndvi_observed/` or the nested report worktree.

| Paths | Size at snapshot | Treatment |
|:---|---:|:---|
| `data2/era5_land_hourly/` | 9.95 GB | Keep: temperature extraction and weather-grid reference |
| `data2/era5_land_hourly_weather/` | 28.63 GB and growing | Keep: running download and queued aggregation |
| `data2/station_era5_clean.parquet` | 97.8 MB | Keep: current analysis parent |
| `data2/station_data.parquet` | 523.7 MB | Keep: raw station cache used by preprocessing |
| `selected_station_observations.parquet`, `selected_station_era5_grid.parquet`, `station_era5_monthly/` | Intermediate products | Keep through the current rebuild and validation |
| `station_coastal_distance.parquet`, `station_elevation.parquet`, `station_land_cover.parquet`, `station_ndvi.parquet` | Compact lookup tables | Keep: loader dependencies |
| `data2/cleaning_audit/verified_observation_window*.csv` | Compact evidence | Keep: direct preprocessing inputs |
| Other stable coverage, selection and provider-verification audits | About 7.8 MB directly under `cleaning_audit/` | Review as evidence; preserve what supports the release |
| `data2/clean/`, `residuals.parquet`, `residuals_cleaned.parquet` | Earlier sample and inputs | Preserve separately if retiring its workflow; ignored data cannot be recovered from Git |
| `data2/station_weather/` | 88.2 MB | Older date-labelled daily covariates; not the new hourly aggregates |
| `data2/ndvi_observed/`, `data2/ghcnh/` | Not recursively measured | Optional research data; retain pending a separate storage decision |
| Fifteen `data/main-*.zip` files | 21.48 GB | Original delivery archives; verify extraction completeness before removing |
| `data/main/ECA_blend_tx/`, `data2/ECA_blend_tx/` | Different source-metadata hashes | Treat as distinct releases until compared; not established duplicates |
| `data2/.cdsapirc` | Ignored local credential configuration | Keep private and preserve for the running download; contents were not inspected |
| `.venv/` | 1.41 GB | Current environment; keep ignored |

`data/main/sentinel2_ndvi/`, the 2020 GHS-SMOD raster and the source metadata remain required local inputs.

The `hourly-weather` tmux session is active. Its queued stages depend on the current source paths, environment, temperature reference grid, covariate lookups and verified rules. Keep that dependency chain intact during cleanup.

`report/3ca187f1d2ba22a5/` is a registered Git worktree on **`gh-pages`**, not an ordinary cache directory. Preserve it until the website decision is made. `.agents/`, `.aws/` and `.codex/` are environment-managed locations, outside the cleanup scope.

Historical recovery sources are present: Git commit `5ee9293`, the ignored `figures/archive/before_cleaned_graphs_20261003.tar.gz`, and `/home2/lobib/research-reports/saad.souilmi/archives/deprecated_repo_20261003.tar.gz`. These do not replace backing up newer untracked work.

Sizes above are apparent decimal sizes, not a complete measurement of all local storage.

## 7. Documentation and commit cleanup

- `CLAUDE.md` still identifies the earlier dataset as current and asks for PascalCase bindings. Align it with `AGENTS.md` and the current loader.
- `AGENTS.md` still includes an older “current analysis input” paragraph alongside the new workflow. Make the two releases' roles explicit.
- The README is about **38 KB** and mixes current commands, earlier notebooks, stopped NDVI retrieval and website publishing. Reduce it to the active entry points; move retained research instructions into focused notes.
- Resolve the export-format wording: repository guidance defaults to PNG/PDF, while the README/restyle tooling also describes refreshing SVGs.
- Keep permanent source manifests and scientific audits distinct from mutable download progress, logs and preview state. The blanket JSON/CSV exceptions currently expose live `hourly_weather_progress.json` to Git.
- Keep publication figures and paper tables identified by their input hashes. The full numerical rerun and table refresh are still queued behind the weather download.
- Prune dependencies after deciding which optional workflows remain. SciencePlots is currently used by the approved whisker style, and Plotly/Kaleido support the station map.

## 8. Suggested cleanup order

1. Move the two unrelated option-pricing CSVs out of the project; review old environment/checkpoint cleanup separately from source changes.
2. Make README and agent guidance describe the current pipeline consistently.
3. Decide whether to retain the old Marimo, post-stratification, website and metadata-comparison workflows. Preserve or port the station map and shared helpers before retirement.
4. Separate optional NDVI/GHCNh research tools and their instructions from the default analysis path.
5. Reconcile manuscript drafts, restore the bibliography, and adapt publication copying/auditing to the new figures and tables.
6. Finish the queued rerun, review the exact Git file list, and prepare focused cleanup commits with current results and provenance.
