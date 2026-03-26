---
name: create-pr
description: Create a pull request with the full RiskFlow PR template including test inventory, TDD cycles, and loop context
---

Create a PR for the current branch using this template. Gather all data before creating the PR.

## Steps

1. Run `git log --oneline main..HEAD` to get commits on this branch
2. Run `git diff main..HEAD --stat` to get changed files
3. Run `uv run pytest --co -q tests/unit/` to get the full test inventory
4. Run `uv run pytest -v tests/unit/ 2>&1 | tail -5` to get test results
5. Run `uv run mypy src/ 2>&1 | tail -1` for mypy status
6. Run `uv run ruff check src/ 2>&1 | tail -1` for ruff status
7. Create the PR using `gh pr create` with this template:

```
gh pr create --base main --title "<short title under 70 chars>" --body "$(cat <<'EOF'
## Summary

<2-4 paragraphs explaining what changed, why, and key design decisions or trade-offs made>

## Loop context

- **Loop:** <number> — <name>
- **Depends on:** Loop <N> (<what it provided>)
- **Unblocks:** Loop <N> (<what it enables>)

## TDD cycles

1. **RED:** <what test was written and how it failed>
2. **GREEN:** <what was implemented to make it pass>
3. <repeat for each cycle>

## Test inventory

<paste full output of pytest --co -q>

## Checks

| Check | Result |
|-------|--------|
| pytest | <N> passed |
| mypy | <clean or errors> |
| ruff check | <clean or errors> |
| ruff format | <clean or errors> |

## Known limitations

- <what this doesn't handle yet>
- <follow-up work for later loops>

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## Rules

- Always run the data-gathering commands fresh — do not rely on earlier output
- The summary must explain WHY, not just WHAT
- Test inventory must be the complete output, not a subset
- Known limitations must be honest — do not hide gaps
