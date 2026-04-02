#!/bin/bash
# Auto-format Python files after editing (style only, no lint fixes).
#
# Runs ruff format but NOT ruff check --fix. The check --fix was
# stripping imports that appeared "unused" between incremental edits
# (add import → next edit adds usage). Lint rules including unused
# import detection (F401) run at commit time via pre-commit.sh.
FILE=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# Only check Python files
if [ -z "$FILE" ] || [[ "$FILE" != *.py ]]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Auto-format only — no lint fixes (preserves imports during incremental edits)
uv run ruff format "$FILE" 2>&1

exit 0
