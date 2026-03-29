#!/bin/bash
# Enforce hexagonal architecture: dependencies only point inward
# domain/ <- ports/ <- adapters/ <- entrypoint/
# Uses the AST-based Python linter for accurate detection (no false
# positives from comments/strings, catches relative imports).
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only run on git commit
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Run the AST-based hexagonal linter
OUTPUT=$(/usr/bin/python3 tools/hexagonal_linter.py 2>&1)
if [ $? -ne 0 ]; then
  echo -e "Hexagonal boundary violations found:\n" >&2
  echo "$OUTPUT" >&2
  echo -e "\nAllowed dependency direction: domain/ <- ports/ <- adapters/ <- entrypoint/" >&2
  exit 2
fi

exit 0
