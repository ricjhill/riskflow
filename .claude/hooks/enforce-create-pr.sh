#!/bin/bash
# Block direct `gh pr create` — must use /create-pr skill instead.
# The skill enforces: code review, full PR template, test inventory,
# and accuracy verification before the PR is created.
#
# Bypass: if the PR body contains "Generated with [Claude Code]" it
# came from the /create-pr skill (which embeds that footer). This
# lets the skill's own gh pr create call pass through.
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

if echo "$COMMAND" | grep -q 'gh pr create'; then
  # Allow if body contains the /create-pr skill footer
  if echo "$COMMAND" | grep -q 'Generated with \[Claude Code\]'; then
    exit 0
  fi
  echo "Blocked: use /create-pr instead of gh pr create directly." >&2
  echo "The /create-pr skill enforces code review, full PR template, and accuracy checks." >&2
  exit 2
fi

exit 0
