#!/usr/bin/env bash
# Coverage delta check: blocks commit if new src/ lines have < 80% coverage.
#
# How it works:
# 1. Runs pytest with coverage on unit tests (reuses the test run from pre-commit)
# 2. Generates coverage XML
# 3. Runs diff-cover to check only the lines being committed
# 4. Fails if new lines in src/ are below the threshold
#
# This hook catches the exact case where production code is committed
# without corresponding tests — the gap that mypy/pytest/ruff can't catch.

set -e

THRESHOLD=80

# Only run if src/ files are being committed
STAGED_SRC=$(git diff --cached --name-only --diff-filter=ACM -- 'src/*.py' 2>/dev/null || true)
if [ -z "$STAGED_SRC" ]; then
    exit 0
fi

# Generate coverage data (fast — unit tests already ran in the pytest hook)
uv run pytest tests/unit/ -q --benchmark-disable \
    --cov=src --cov-report=xml:.coverage-delta.xml \
    --no-header -q 2>/dev/null

# Check coverage on the diff
RESULT=$(uv run diff-cover .coverage-delta.xml \
    --compare-branch=HEAD \
    --fail-under="$THRESHOLD" \
    --diff-range-notation='..' \
    --quiet 2>&1) || {
    echo "COVERAGE DELTA CHECK FAILED"
    echo ""
    echo "$RESULT"
    echo ""
    echo "New lines in src/ must have >= ${THRESHOLD}% test coverage."
    echo "Write tests for the uncovered lines, then commit again."
    rm -f .coverage-delta.xml
    exit 1
}

rm -f .coverage-delta.xml
