#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

usage() {
    printf 'Usage: ./run.sh <workflow>\n\nWorkflows:\n  preprocessing  Build station selection, ERA5 matches and covariates.\n'
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

case "$1" in
    preprocessing)
        mkdir -p data2
        printf 'running\n' > data2/preprocessing.status
        trap 'printf "%s\n" "$?" > data2/preprocessing.status' EXIT
        export POLARS_MAX_THREADS="${POLARS_MAX_THREADS:-8}"
        uv run python -u -m py.preprocessing 2>&1 | tee data2/preprocessing.log
        ;;
    --help|-h)
        usage
        ;;
    *)
        printf 'Unknown workflow: %s\n' "$1" >&2
        usage >&2
        exit 2
        ;;
esac
