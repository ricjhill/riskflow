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

  # Validate that each required section has actual content (>20 chars),
  # not just a header with nothing beneath it.
  EMPTY_SECTIONS=$(/usr/bin/python3 -c "
import sys, re

command = sys.stdin.read()
required = ['Summary', 'Agent Review', 'Loop context', 'TDD cycles', 'Checks', 'Known limitations']
empty = []
for req in required:
    # Capture lines after '## <name>' until the next '## ' header or end of string.
    # (?:(?!## ).*\n?)* matches consecutive lines that don't start with '## '.
    pattern = r'## ' + re.escape(req) + r'[^\n]*\n((?:(?!## ).*\n?)*)'
    m = re.search(pattern, command)
    if m:
        content = m.group(1)
        # Remove the /create-pr footer so it doesn't count as section content
        content = re.sub(r'.*Generated with \[Claude Code\].*', '', content)
        # Strip whitespace and markdown table decoration to measure real text
        cleaned = re.sub(r'[\s|+\-]', '', content)
        if len(cleaned) < 20:
            empty.append(req)
    else:
        # Section header not found — already caught by the grep check above,
        # but include here for completeness.
        empty.append(req)
if empty:
    print('\n'.join(empty))
" <<< "$COMMAND" 2>/dev/null)

  if [ -n "$EMPTY_SECTIONS" ]; then
    echo "Blocked: The following PR template sections have no meaningful content:" >&2
    while IFS= read -r section; do
      echo "  - ## $section" >&2
    done <<< "$EMPTY_SECTIONS"
    echo "Each section must contain at least 20 characters of content." >&2
    echo "Use the /create-pr skill to generate a complete PR body." >&2
    exit 2
  fi
fi

exit 0
