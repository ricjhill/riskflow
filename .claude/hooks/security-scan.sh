#!/bin/bash
# Run security scanners before git commit
# bandit: static analysis for Python security issues
# pip-audit: dependency vulnerability scanning
# semgrep: pattern-based security scanning (OWASP, FastAPI rules)
COMMAND=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only run on git commit
if ! echo "$COMMAND" | grep -q 'git commit'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

ERRORS=""

# 1. bandit — static analysis
OUTPUT=$(uv run bandit -r src/ -q 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="SECURITY: bandit found issues in source code:\n$OUTPUT\n"
  ERRORS+="FIX: Review each finding and fix or add #nosec with justification.\n\n"
fi

# 2. pip-audit — dependency vulnerabilities
# Uses --ignore-vuln for known CVEs with no available fix
KNOWN_IGNORES="--ignore-vuln CVE-2026-4539"
OUTPUT=$(uv run pip-audit $KNOWN_IGNORES 2>&1)
if [ $? -ne 0 ]; then
  ERRORS+="SECURITY: pip-audit found vulnerable dependencies:\n$OUTPUT\n"
  ERRORS+="FIX: Update the vulnerable package or add to --ignore-vuln if no fix available.\n\n"
fi

# 3. semgrep — pattern-based scanning (non-blocking, informational)
# semgrep is installed as a uv tool, not a project dep
if command -v semgrep &> /dev/null; then
  OUTPUT=$(semgrep scan --config auto --quiet src/ 2>&1)
  if [ $? -ne 0 ] && echo "$OUTPUT" | grep -q "Findings:"; then
    ERRORS+="SECURITY: semgrep found potential issues:\n$OUTPUT\n"
    ERRORS+="FIX: Review each finding — false positives can be ignored with nosemgrep comment.\n\n"
  fi
fi

if [ -n "$ERRORS" ]; then
  echo -e "Security scan failures:\n" >&2
  echo -e "$ERRORS" >&2
  exit 2
fi

exit 0
