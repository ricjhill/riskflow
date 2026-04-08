#!/bin/bash
# Block git commit unless mypy, pytest, and ruff all pass
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only intercept git commit commands
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

ERRORS=""

# 1. mypy
OUTPUT=$(uv run mypy src/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="mypy failed:\n$OUTPUT\n\n"
fi

# 2. pytest
PYTEST_OUTPUT=$(uv run pytest -x -v tests/unit/ --cov=src --cov-report=term-missing 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="pytest failed:\n$PYTEST_OUTPUT\n\n"
fi

# 3. ruff check
OUTPUT=$(uv run ruff check src/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="ruff check failed:\n$OUTPUT\n\n"
fi

# 4. ruff format
OUTPUT=$(uv run ruff format --check src/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="ruff format check failed:\n$OUTPUT\n\n"
fi

if [ -n "$ERRORS" ]; then
  echo -e "$ERRORS" >&2
  echo "Fix the above before committing." >&2
  exit 2
fi

# Show coverage summary (non-blocking, informational only)
COV_LINE=$(echo "$PYTEST_OUTPUT" | grep "^TOTAL" | head -1)
if [ -n "$COV_LINE" ]; then
  echo "Coverage: $COV_LINE" >&2
fi

exit 0
