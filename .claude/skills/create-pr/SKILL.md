---
name: create-pr
description: Run agent-to-agent code review, then create a pull request with the full RiskFlow PR template including test inventory, TDD cycles, and loop context
---

Create a PR for the current branch. The code-reviewer agent must approve before the PR is created.

## Steps

### Phase 1: Agent review (blocking)

1. Launch the `code-reviewer` agent to review the changes on this branch
2. If the reviewer returns **BLOCK**: fix the issues it identified, then re-run the reviewer
3. If the reviewer returns **REVISE**: address the feedback, then re-run the reviewer
4. If the reviewer returns **APPROVE**: proceed to Phase 2
5. Include the reviewer's full output in the PR description

### Phase 2: Gather data

1. Run `git log --oneline main..HEAD` to get commits on this branch
2. Run `git diff main..HEAD --stat` to get changed files
3. Run `uv run pytest --co -q tests/` to get the full test inventory
4. Run `uv run pytest -v tests/ 2>&1 | tail -5` to get test results
5. Run `uv run mypy src/ 2>&1 | tail -1` for mypy status
6. Run `uv run ruff check src/ 2>&1 | tail -1` for ruff status

### Phase 3: Create PR

Create the PR using `gh pr create` with this template:

```
gh pr create --base main --title "<short title under 70 chars>" --body "$(cat <<'EOF'
## Summary

<2-4 paragraphs explaining what changed, why, and key design decisions or trade-offs made>

## Agent Review

<paste the full code-reviewer output here>

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

- **Never create a PR without an APPROVE from the code-reviewer agent**
- If the reviewer blocks, fix the code and re-run the reviewer — do not skip it
- Always run the data-gathering commands fresh — do not rely on earlier output
- The summary must explain WHY, not just WHAT
- Test inventory must be the complete output, not a subset
- Known limitations must be honest — do not hide gaps
