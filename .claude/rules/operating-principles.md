---
description: Core operating principles for agent-driven development
---

# Operating Principles

## Humans design constraints, agents generate code
- Humans steer via CLAUDE.md, rules, hooks, tests, and prompts.
- When an agent produces wrong code, fix the harness (add a test, tighten a rule, improve a prompt) — not the code directly.
- Exception: reviewing diffs, writing test fixtures, and editing configuration files are human tasks.

## Strict dependency direction
Dependencies only point inward. No layer may import from a layer above it.

```
domain/model/    ← domain/service/    ← ports/    ← adapters/    ← entrypoint/
(pure types)       (business logic)     (protocols)  (implementations)  (wiring)
```

Violations must be caught by review or linting before merge.

## Mechanical validation before merge
Every change must pass automated checks before human review:
- Pre-commit hook: mypy, pytest, ruff check, ruff format
- PR review: all checks green before merge
