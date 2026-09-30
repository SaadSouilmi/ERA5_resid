# Repository guidance

This project studies ERA5-Land temperature residuals against European weather
stations. Residual means station temperature minus ERA5 temperature.

All active Python source belongs under `src/py`, the `py` package. Analysis
modules live directly in that directory. Scripts and Marimo notebooks live in
`py.scripts` and `py.notebooks`. Use `uv` for environments and Python execution.
Use `py.paths` for repository paths. Run computational work in a dedicated tmux
session and remove the session when the command finishes.

The old Jupyter notebooks under `notebooks/` are historical records. Do not
rewrite their analyses or regenerate their outputs during routine refactoring.
The last pre-refactor state is commit `5ee9293`.

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
