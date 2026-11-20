# Project context

Follow AGENTS.md for conventions and README.md for commands.

The current temperature sample is `data2/station_era5_clean.parquet`.
Load it with `py.load_data.load_data()`; use `include_weather=True` for the saved
station-window wind/rain lookup. Read `figures/analysis/README.md` for current
results, CSV tables, plots and input manifests. Methods live in `notes/`;
`notes/NUMERICAL_ANALYSIS.md` is an older partial write-up, not current run status.

All active Python belongs in `src/py`. Use uv, snake_case, plain functions and
simple code. Run computational work in dedicated tmux sessions.

Earlier sample builders and notebooks are archived; do not restore their outputs
as current results. `paper/paper.tex` remains a draft awaiting numerical refresh.
