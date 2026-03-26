#!/bin/bash
# Block edits to protected files
FILE=$(jq -r '.tool_input.file_path // empty' 2>/dev/null)

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
esac

exit 0
