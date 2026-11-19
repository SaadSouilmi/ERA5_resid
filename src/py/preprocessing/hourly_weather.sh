#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/era5-uv-cache}"
export POLARS_MAX_THREADS="${POLARS_MAX_THREADS:-8}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-2}"
printf 'downloading\n' > data2/hourly_weather.status
trap 'printf "%s\n" "$?" > data2/hourly_weather.status' EXIT
uv run python -m py.preprocessing.download_hourly_weather
printf 'aggregating\n' > data2/hourly_weather.status
uv run python -m py.preprocessing.hourly_weather
uv run python -m py.preprocessing.land_cover
printf 'plotting\n' > data2/hourly_weather.status
uv run python -m py.scripts.plot_partial_dependence --features station_celsius tp wind ndvi dist_to_sea_km elevation
uv run python -m py.scripts.plot_interactions
printf 'analysing\n' > data2/hourly_weather.status
bash src/py/scripts/run_numerical_analysis.sh --inside-tmux --figures-ready > data2/numerical_analysis.log 2>&1
