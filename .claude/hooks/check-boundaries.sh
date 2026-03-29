#!/bin/bash
# Enforce hexagonal architecture: dependencies only point inward
# domain/ <- ports/ <- adapters/ <- entrypoint/
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only run on git commit
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

ERRORS=""

# domain/ must not import from adapters/ or entrypoint/
VIOLATIONS=$(grep -rn "from src\.\(adapters\|entrypoint\)\|import src\.\(adapters\|entrypoint\)" src/domain/ 2>/dev/null)
if [ -n "$VIOLATIONS" ]; then
  ERRORS+="VIOLATION: domain/ cannot import from adapters/ or entrypoint/\n"
  ERRORS+="$VIOLATIONS\n"
  ERRORS+="FIX: Define a Protocol in src/ports/output/ and have the adapter implement it.\n"
  ERRORS+="     domain/ may only import from: src.domain, src.ports\n\n"
fi

# ports/ must not import from adapters/ or entrypoint/
VIOLATIONS=$(grep -rn "from src\.\(adapters\|entrypoint\)\|import src\.\(adapters\|entrypoint\)" src/ports/ 2>/dev/null)
if [ -n "$VIOLATIONS" ]; then
  ERRORS+="VIOLATION: ports/ cannot import from adapters/ or entrypoint/\n"
  ERRORS+="$VIOLATIONS\n"
  ERRORS+="FIX: Ports define interfaces only. They must not reference implementations.\n"
  ERRORS+="     ports/ may only import from: src.domain, src.ports\n\n"
fi

# adapters/ must not import from entrypoint/
VIOLATIONS=$(grep -rn "from src\.entrypoint\|import src\.entrypoint" src/adapters/ 2>/dev/null)
if [ -n "$VIOLATIONS" ]; then
  ERRORS+="VIOLATION: adapters/ cannot import from entrypoint/\n"
  ERRORS+="$VIOLATIONS\n"
  ERRORS+="FIX: Adapters are wired by entrypoint/, not the other way around.\n"
  ERRORS+="     adapters/ may only import from: src.domain, src.ports, src.adapters\n\n"
fi

if [ -n "$ERRORS" ]; then
  echo -e "Hexagonal boundary violations found:\n" >&2
  echo -e "$ERRORS" >&2
  echo -e "Allowed dependency direction: domain/ <- ports/ <- adapters/ <- entrypoint/" >&2
  exit 2
fi

exit 0