#!/bin/bash
# Hook: post-failure-context
# Runs on: PostToolUse (Bash) — only triggers on failed uv run pytest/mypy/ruff
# Purpose: When a test/lint command fails, parse the output and inject a
#          structured diagnostic (failed test names, error lines, suggested
#          action) so the agent can diagnose without re-reading raw output.
#
# Non-blocking — always exits 0. Outputs hookSpecificOutput JSON on failure.
#
# Triggered by: back-and-forth increases when test failures produce long
# output that the agent needs to manually parse.

# Read all of stdin (PostToolUse sends tool_input + tool_output as JSON)
INPUT=$(cat)

# Delegate all parsing and analysis to Python
/usr/bin/python3 -c "
import json, sys, re

raw = sys.argv[1]
try:
    data = json.loads(raw)
except (json.JSONDecodeError, TypeError):
    sys.exit(0)

command = data.get('tool_input', {}).get('command', '')
output = data.get('tool_output', '')

# Future-proof: if tool_output is a dict, extract stdout/stderr
if isinstance(output, dict):
    output = str(output.get('stdout', '')) + '\n' + str(output.get('stderr', ''))

# --- Gate 1: Only trigger on target commands ---
tool = None
if re.match(r'uv run pytest\b', command):
    tool = 'pytest'
elif re.match(r'uv run mypy\b', command):
    tool = 'mypy'
elif re.match(r'uv run ruff check\b', command):
    tool = 'ruff'

if tool is None:
    sys.exit(0)

lines = output.splitlines()

# --- Gate 2: Only trigger on failures (content-based detection) ---
if tool == 'pytest':
    has_failure = any('short test summary info' in l for l in lines)
    if not has_failure:
        has_failure = any(
            re.search(r'=+ .*(failed|error).*=+', l, re.IGNORECASE)
            for l in lines[-5:]
        )
    if not has_failure:
        sys.exit(0)

elif tool == 'mypy':
    if not any(re.search(r'Found \d+ error', l) for l in lines):
        sys.exit(0)

elif tool == 'ruff':
    if not any(re.search(r'Found \d+ error', l) for l in lines):
        sys.exit(0)

# --- Extract diagnostic output ---
diagnostic_lines = []
failed_tests = []

if tool == 'pytest':
    # Find the 'short test summary info' section
    summary_start = None
    for i, l in enumerate(lines):
        if 'short test summary info' in l:
            summary_start = i
            break

    if summary_start is not None:
        diagnostic_lines = lines[summary_start:]
    else:
        diagnostic_lines = lines[-40:]

    # Extract FAILED lines for structured section
    failed_tests = [l.strip() for l in lines if l.strip().startswith('FAILED ')]

elif tool == 'mypy':
    diagnostic_lines = [l for l in lines if ': error:' in l or re.search(r'Found \d+ error', l)]
    diagnostic_lines = diagnostic_lines[-30:]

elif tool == 'ruff':
    # Full format: rule line 'F401 [*] ...' + ' --> file:line:col'
    # Concise format: 'file:line:col: F401 ...'
    diagnostic_lines = [
        l for l in lines
        if re.match(r'[A-Z]\d+\s', l)
        or re.search(r'-->\s+.+:\d+:\d+', l)
        or re.match(r'.+:\d+:\d+:', l)
        or re.search(r'Found \d+ error', l)
    ]
    diagnostic_lines = diagnostic_lines[-30:]

# --- Build context message ---
parts = []
parts.append(f'FAILURE DIAGNOSTIC: {tool} failed')
parts.append(f'Command: {command}')
parts.append('')

if tool == 'pytest' and failed_tests:
    parts.append('Failed tests:')
    for ft in failed_tests[:15]:
        parts.append(f'  {ft}')
    parts.append('')

parts.append(f'Error output ({len(diagnostic_lines)} lines):')
for dl in diagnostic_lines[-40:]:
    parts.append(f'  {dl}')

if tool == 'pytest':
    parts.append('')
    parts.append('Action: Read the failing test(s) and the source they exercise. Fix the assertion or the source code.')
elif tool == 'mypy':
    parts.append('')
    parts.append('Action: Read each file:line listed above. Add type annotations or fix type mismatches.')
elif tool == 'ruff':
    parts.append('')
    parts.append('Action: Read each file:line listed above. Apply the fix for each rule code (e.g. F401=unused import).')

context = '\n'.join(parts)

# --- Output hookSpecificOutput JSON ---
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PostToolUse',
        'additionalContext': context
    }
}))
" "$INPUT"
