#!/bin/bash
# Advisory: remind to update docs when API-facing files change without docs.
#
# Triggers on git commit. Checks if staged files include route definitions,
# response models, or OpenAPI tooling — but no docs/ files. If so, prints
# a non-blocking reminder. Never blocks the commit (always exits 0).
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only check on git commit
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Files that signal an API surface change
API_PATTERNS="src/adapters/http/routes.py|src/entrypoint/main.py|openapi.json|tools/check_api_changes.py|tools/bump_version.py|tools/export_openapi.py"

# Check staged files
STAGED=$(git diff --cached --name-only 2>/dev/null)
if [ -z "$STAGED" ]; then
  exit 0
fi

HAS_API_CHANGE=$(echo "$STAGED" | grep -E "$API_PATTERNS" | head -1)
HAS_DOCS_CHANGE=$(echo "$STAGED" | grep -E "^docs/" | head -1)

if [ -n "$HAS_API_CHANGE" ] && [ -z "$HAS_DOCS_CHANGE" ]; then
  echo "Reminder: API-facing files changed ($HAS_API_CHANGE) but no docs/ updated." >&2
  echo "Consider updating docs/reference/api.md, docs/reference/openapi.md, or docs/reference/versioning.md." >&2
fi

# Always allow — this is advisory only
exit 0
