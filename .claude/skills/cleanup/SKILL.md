---
name: cleanup
description: Scan the codebase for pattern drift, dead code, stale docs, and architectural decay. Opens a fix-up PR if issues are found.
---

Scan the RiskFlow codebase for entropy and open a cleanup PR if needed. This is the garbage collection process — run it periodically to prevent drift from compounding.

## Checks to run (in order)

### 1. Dead code detection
- Grep for unused imports: `uv run ruff check src/ --select F401`
- Check for empty `__init__.py` files that could have `__all__` exports but don't need them
- Check for empty placeholder files that were never populated

### 2. Architectural drift
- Run `echo '{"tool_input":{"command":"git commit"}}' | bash .claude/hooks/check-boundaries.sh` to invoke the boundary checker directly
- Check that all files in `src/domain/` have zero imports from `src/adapters/` or `src/entrypoint/`
- Check that no adapter reads environment variables directly
- Verify all port interfaces are `typing.Protocol`, not ABC

### 3. Test drift
- Run `uv run pytest --co -q tests/` and compare against source files
- For every `.py` file in `src/` that contains classes or functions, check that a corresponding test file exists
- Flag any source file with no test coverage

### 4. Dependency hygiene
- Run `uv run pip-audit --ignore-vuln CVE-2026-4539` for new CVEs
- Run `uv run bandit -r src/ -q` for new security findings
- Check for outdated packages: `uv pip list --outdated` if available

### 5. Documentation freshness
- Compare `CLAUDE.md` architecture tree against actual directory structure in `src/`
- Check that `README.md` getting started commands still work (do they reference files that exist?)
- Check `.env.example` matches env vars actually read in `src/entrypoint/main.py`

### 6. Stale patterns
- Check for `from typing import List, Dict, Optional` — should use `list`, `dict`, `X | None` (Python 3.12+)
- Check for `# TODO`, `# FIXME`, `# HACK` comments that were never resolved
- Check for commented-out code blocks

## Output

Report findings as a categorized list:

```
## Cleanup Report

### Dead Code
- <finding or "Clean">

### Architectural Drift
- <finding or "Clean">

### Test Drift
- <finding or "Clean">

### Dependency Hygiene
- <finding or "Clean">

### Documentation Freshness
- <finding or "Clean">

### Stale Patterns
- <finding or "Clean">

### Summary
<total findings> issues found. <N> need fixing, <N> are advisory.
```

## Action

If issues are found:
1. Create a `feature/cleanup` branch
2. Fix all non-advisory issues
3. Run `uv run pytest -x tests/` to verify nothing broke
4. Use `/create-pr` to open the cleanup PR (which triggers the code-reviewer agent)

If everything is clean, report "No drift detected" and do nothing.
