#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
if [[ "${1:-}" != --inside-tmux ]]; then
    tmux new-session -d -s numerical-analysis -c "$PWD" \
        'bash src/py/scripts/run_numerical_analysis.sh --inside-tmux > data2/numerical_analysis.log 2>&1'
    printf 'Started numerical-analysis; log: data2/numerical_analysis.log\n'
    exit 0
fi
shift
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/era5-uv-cache}"
export POLARS_MAX_THREADS="${POLARS_MAX_THREADS:-8}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-2}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"
export MPLBACKEND=Agg
printf 'running\n' > data2/numerical_analysis.status
trap 'printf "%s\n" "$?" > data2/numerical_analysis.status' EXIT
uv run python -m py.scripts.run_numerical_analysis "$@"
