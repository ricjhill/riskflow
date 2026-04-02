#!/bin/bash
# Hook: check-runtime-deps
# Runs on: PreToolUse (Bash) — only triggers on git commit
# Purpose: Verify every third-party import in src/ has a matching
#          runtime dependency in [project].dependencies.
#
# Catches: imports that only work because a dev dep (like streamlit)
# transitively installs them. These fail in production containers
# built with uv sync --no-dev.

COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only run on git commit
if [[ ! "$COMMAND" =~ ^git\ commit ]]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Run the runtime dependency check test
OUTPUT=$(uv run pytest tests/unit/test_runtime_deps.py::TestRuntimeDependenciesComplete::test_all_imports_have_runtime_deps -x -q 2>&1)
if [ $? -ne 0 ]; then
  echo "Blocked: runtime dependency check failed" >&2
  echo "" >&2
  echo "$OUTPUT" | grep -E "import '|Fix:" >&2
  echo "" >&2
  echo "FIX: uv add <package> to add missing packages to [project].dependencies" >&2
  exit 2
fi

exit 0
