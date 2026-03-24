#!/bin/bash
# Run ruff check + ruff format after editing Python files
FILE=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)

# Only check Python files
if [ -z "$FILE" ] || [[ "$FILE" != *.py ]]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Ensure venv tools are used
export PATH="$CLAUDE_PROJECT_DIR/.venv/bin:$PATH"

# Auto-fix lint issues
ruff check --fix "$FILE" 2>&1

# Auto-format
ruff format "$FILE" 2>&1

exit 0
