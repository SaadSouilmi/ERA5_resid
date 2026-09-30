#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")/.."
exec uv run python -m py.tests.run "$@"
