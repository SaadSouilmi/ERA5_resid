#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

case "${1:-}" in
    "")
        mkdir -p data2
        tmux new-session -d -s station-preprocessing -c "$PWD" \
            'bash ./run.sh --inside-tmux > data2/preprocessing.log 2>&1'
        printf 'Started tmux session: station-preprocessing\nLog: data2/preprocessing.log\nStatus: data2/preprocessing.status (0 means success)\n'
        exit 0
        ;;
    --inside-tmux) ;;
    --help|-h)
        printf 'Usage: ./run.sh\nRuns station selection, ERA5 temperature matching, covariate preparation and hourly weather retrieval/aggregation in a dedicated tmux session.\n'
        exit 0
        ;;
    *) printf 'Usage: ./run.sh\n' >&2; exit 2 ;;
esac

printf 'running\n' > data2/preprocessing.status
trap 'printf "%s\n" "$?" > data2/preprocessing.status' EXIT
export POLARS_MAX_THREADS="${POLARS_MAX_THREADS:-8}"

uv run python -m py.preprocessing
