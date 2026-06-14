#!/usr/bin/env bash
# Simple wrapper for the Python smoke test
set -euo pipefail

TICKER=${1:-AAPL}
PYTHON=${PYTHON:-python}

echo "Running smoke test for ${TICKER}"
${PYTHON} scripts/smoke_test.py --ticker "${TICKER}"
