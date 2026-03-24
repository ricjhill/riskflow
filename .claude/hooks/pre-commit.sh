#!/bin/bash
# Block git commit unless mypy, pytest, and ruff all pass
COMMAND=$(jq -r '.tool_input.command' 2>/dev/null)

# Only intercept git commit commands
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Ensure venv tools are used
export PATH="$CLAUDE_PROJECT_DIR/.venv/bin:$PATH"

ERRORS=""

# 1. mypy
OUTPUT=$(mypy src/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="mypy failed:\n$OUTPUT\n\n"
fi

# 2. pytest
OUTPUT=$(pytest -x -v tests/unit/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="pytest failed:\n$OUTPUT\n\n"
fi

# 3. ruff check
OUTPUT=$(ruff check src/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="ruff check failed:\n$OUTPUT\n\n"
fi

# 4. ruff format
OUTPUT=$(ruff format --check src/ 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="ruff format check failed:\n$OUTPUT\n\n"
fi

if [ -n "$ERRORS" ]; then
  echo -e "$ERRORS" >&2
  echo "Fix the above before committing." >&2
  exit 2
fi

exit 0
