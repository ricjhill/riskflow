#!/bin/bash
# Block edits to protected files
FILE=$(/usr/bin/python3 -c "import json,sys; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

if [ -z "$FILE" ]; then
  exit 0
fi

# Protected file patterns
case "$FILE" in
  */uv.lock)
    echo "Blocked: do not edit uv.lock manually — use uv add/remove" >&2
    exit 2
    ;;
  */.env|*/.env.*)
    echo "Blocked: do not edit .env files via Claude — manage secrets manually" >&2
    exit 2
    ;;
  */.claude/settings.json)
    echo "Blocked: do not edit .claude/settings.json directly — use /update-config" >&2
    exit 2
    ;;
  */pyproject.toml)
    echo "Blocked: do not edit pyproject.toml directly — use uv add/remove for deps, or ask to modify config sections" >&2
    exit 2
    ;;
esac

exit 0
