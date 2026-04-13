#!/bin/bash
# Block direct `gh pr create` — must use /create-pr skill instead.
# Also validates that the PR body contains all required template sections.
#
# Bypass: if the PR body contains "Generated with [Claude Code]" it
# came from the /create-pr skill (which embeds that footer). This
# lets the skill's own gh pr create call pass through — but only if
# the required sections are present.
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

if echo "$COMMAND" | grep -q 'gh pr create'; then
  # Block if missing the /create-pr skill footer
  if ! echo "$COMMAND" | grep -q 'Generated with \[Claude Code\]'; then
    echo "Blocked: use /create-pr instead of gh pr create directly." >&2
    echo "The /create-pr skill enforces code review, full PR template, and accuracy checks." >&2
    exit 2
  fi

  # Validate required PR template sections are present
  MISSING=""
  for section in "## Summary" "## Agent Review" "## Loop context" "## TDD cycles" "## Checks" "## Known limitations"; do
    if ! echo "$COMMAND" | grep -q "$section"; then
      MISSING="$MISSING  - $section\n"
    fi
  done

  if [ -n "$MISSING" ]; then
    echo "Blocked: PR body is missing required template sections:" >&2
    echo -e "$MISSING" >&2
    echo "Every PR must use the full /create-pr template. Use 'N/A' for sections that don't apply." >&2
    exit 2
  fi
fi

exit 0
