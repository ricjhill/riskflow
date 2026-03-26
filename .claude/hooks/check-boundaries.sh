#!/bin/bash
# Enforce hexagonal architecture: domain must not import from adapters or entrypoint
COMMAND=$(jq -r '.tool_input.command' 2>/dev/null)

# Only run on git commit
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

ERRORS=""

# domain/ must not import from adapters/ or entrypoint/
VIOLATIONS=$(grep -rn "from src\.\(adapters\|entrypoint\)\|import src\.\(adapters\|entrypoint\)" src/domain/ 2>/dev/null)
if [ -n "$VIOLATIONS" ]; then
  ERRORS+="domain/ imports from adapters/ or entrypoint/:\n$VIOLATIONS\n\n"
fi

# ports/ must not import from adapters/ or entrypoint/
VIOLATIONS=$(grep -rn "from src\.\(adapters\|entrypoint\)\|import src\.\(adapters\|entrypoint\)" src/ports/ 2>/dev/null)
if [ -n "$VIOLATIONS" ]; then
  ERRORS+="ports/ imports from adapters/ or entrypoint/:\n$VIOLATIONS\n\n"
fi

# adapters/ must not import from entrypoint/
VIOLATIONS=$(grep -rn "from src\.entrypoint\|import src\.entrypoint" src/adapters/ 2>/dev/null)
if [ -n "$VIOLATIONS" ]; then
  ERRORS+="adapters/ imports from entrypoint/:\n$VIOLATIONS\n\n"
fi

if [ -n "$ERRORS" ]; then
  echo -e "Hexagonal boundary violations:\n$ERRORS" >&2
  exit 2
fi

exit 0
