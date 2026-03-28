# Harness Engineering: Building Software by Asking Better Questions

**Duration:** 45 minutes
**Audience:** Engineering team
**Project:** RiskFlow — Reinsurance Data Mapper

---

## 1. The Problem (3 min)

- Show a messy bordereaux spreadsheet
- "We need to map this to a standard schema. An AI agent can do it — but how do we trust the output?"
- "The answer isn't better prompts. It's better constraints."

---

## 2. Live Demo (3 min)

```bash
curl -F "file=@tests/fixtures/sample_bordereaux.csv" localhost:8000/upload | python3 -m json.tool
```

- Show the response: 6 mapped fields, confidence scores, valid/invalid rows
- "Zero lines of manual code. 148 tests. 5 security hooks. Built in one session."
- "Let me show you how we got here — through questions, not code."

---

## 3. "Which rules can be converted to hooks?" (5 min)

*The first question: what can be automated?*

- Started with `agent.py.md` — 236 lines of instructions telling the agent what to do
- Asked: which of these are just words vs which can be enforced mechanically?
- **Before:** "Run mypy before committing" (advisory — the agent can ignore it)
- **After:** `pre-commit.sh` blocks the commit if mypy fails (enforced — the agent can't ignore it)
- Converted 5 rules to hooks: pre-commit quality gate, auto-format on edit, file protection, boundary check, security scan

**Principle: If a rule matters, make it a hook. If it's just a suggestion, delete it.**

---

## 4. "How can we make CLAUDE.md better?" (5 min)

*Refining the instructions: less is more*

- Reviewed against Anthropic best practices — CLAUDE.md should be under 200 lines
- Found: redundancy between CLAUDE.md and agent.py.md, stale architecture tree, an incomplete sentence on line 1
- **Before:** 107 lines + 236 lines across two files, conflicting folder structures
- **After:** 78 lines in one file, domain rules moved to path-scoped `.claude/rules/reinsurance.md`
- Path scoping: reinsurance rules only load when editing `src/domain/` or `src/adapters/slm/` — no context wasted on irrelevant rules

**Principle: The agent follows shorter instructions better. Prune ruthlessly, scope precisely.**

---

## 5. "Are the tests weak?" (7 min)

*Challenging quality — the harness must test the harness*

- Loop 1: wrote domain models with 10 tests. Asked: "Are these weak?"
- Answer: yes. Only happy path + one negative case per field.
- **Before:** `test_rejects_invalid_currency` tested one bad value ("DOLLARS")
- **After:** `@pytest.mark.parametrize("currency", ["DOLLARS", "usd", "Us", "", "AUD"])` — five bad values, one test result each
- Missing: boundary values (0.0, 1.0), target field validation (accepted any string), date ordering, empty Policy_ID, duplicate mappings
- Added `ColumnMapping.target_field` validation — without this, the SLM could return `"Amount"` instead of `"Sum_Insured"` and we'd silently accept it
- Created `.claude/rules/testing.md` with layer-specific test depth guidance
- Saved feedback to memory: "Tests must cover boundaries, edge cases, invalid input"
- Tests went from 10 to 37 for the same models

**Principle: Review your tests the way you'd review the code. Ask "what input would break this but still pass?"**

---

## 6. "How do we know this code runs?" (5 min)

*The gap between "tests pass" and "it works"*

- After Loop 9: 128 tests passing, mypy clean, all hooks green
- Asked: "How do we know this actually runs?"
- Answer: we don't. Everything was tested with mocks. The SLM was never called for real.
- Ran the smoke test:
  - `/health` -> 200 OK
  - Upload without API key -> 503 (correct)
  - Upload with API key -> 503: `"model llama-3.1-70b-versatile has been decommissioned"`
- **No unit test would have caught this.** The model was deprecated by Groq between when we wrote the code and when we ran it.
- Fixed: updated to `llama-3.3-70b-versatile`, uploaded again -> 200 OK, all 6 fields mapped correctly

**Principle: Mocked tests prove logic. Smoke tests prove the system works. You need both.**

---

## 7. "Review our way of working" (5 min)

*Iterating on the process itself*

- After several loops, reviewed the workflow
- Found: too much ceremony (asked "yes" 15 times for routine steps), loops too granular for some phases
- **Before:** commit -> "want me to push?" -> "yes" -> push -> "want me to PR?" -> "yes" -> PR -> "want me to merge?" -> "yes"
- **After:** commit -> push -> PR -> merge automatically. Only ask on risky actions (force push, architecture changes)
- Saved as feedback memory — the agent never asked again
- Also improved: commit messages went from one-line summaries to multi-paragraph design explanations, PRs got a full template with test inventory

**Principle: The process is part of the harness. Review it like code — prune what's slow, automate what's routine.**

---

## 8. "How do we stop regressions?" (5 min)

*Sustainability — the harness must outlive the session*

- After all loops complete, asked: what prevents this from breaking tomorrow?
- Current protection: pre-commit hooks (local only)
- Gap: if someone pushes directly to GitHub, no hooks fire
- The question led to: "Can we add security scanning?"
- Added bandit (Python security), pip-audit (dependency CVEs), semgrep (OWASP patterns)
- First scan caught: `pygments` CVE (no fix available — documented in `--ignore-vuln`)
- **Before:** 3 pre-commit hooks (quality, boundaries, file protection)
- **After:** 4 pre-commit hooks + security scanning
- Agent-readable errors: "VIOLATION: domain/ cannot import from adapters/. FIX: Define a Protocol in src/ports/output/"

**Principle: Every gap you find is a hook you're missing. The harness grows by learning from failures.**

---

## 9. The Full Harness (3 min)

The complete `.claude/` directory and what each piece does:

```
.claude/
  hooks/
    pre-commit.sh          <- mypy, pytest, ruff (blocks commit)
    post-edit-lint.sh      <- auto-format on every .py edit
    protect-files.sh       <- blocks edits to .env, uv.lock
    check-boundaries.sh   <- blocks cross-layer imports
    security-scan.sh       <- bandit, pip-audit, semgrep
  rules/
    reinsurance.md         <- domain rules (path-scoped to domain/ and slm/)
    testing.md             <- test quality standards (path-scoped to tests/)
    operating-principles.md <- agent-driven development philosophy
  skills/
    create-pr/SKILL.md    <- standardized PR template
  settings.json            <- permissions, hook wiring
```

---

## 10. By the Numbers (2 min)

| Metric | Value |
|--------|-------|
| Questions that shaped the harness | 10 |
| Hooks | 5 |
| Rules | 3 |
| Tests | 148 |
| PRs | 15 |
| Lines of source code | ~900 |
| Lines of manual code | 0 |
| Security findings | 0 |
| Bugs caught by smoke test | 1 (model deprecation) |
| Bugs caught by test review | 5+ (weak validation) |

---

## 11. Takeaway (2 min)

Harness engineering isn't about the tools — it's about asking the right questions in the right order:

1. **What can be automated?** -> Hooks
2. **What instructions does the agent actually need?** -> Pruned CLAUDE.md
3. **Are the tests strong enough?** -> Testing rules
4. **Does it actually run?** -> Smoke tests
5. **How do we keep it working?** -> Security scanning, CI

Each question tightened the constraints. Each constraint improved the output. The agent didn't get smarter — the harness got better.

---

## 12. Q&A (2 min remaining)

---

## Appendix A: Session 2 — Closing the Gaps

After the initial build session, we ran a second session to close open items. This demonstrated the harness working in maintenance mode, not just greenfield development.

### Tasks completed

| Task | Result |
|------|--------|
| Smoke test row validation (real SLM) | Pass — uploaded bordereaux CSV to Groq Llama 3.3, got 5 validated RiskRecords with full ProcessingResult response |
| Smoke test Redis caching | Skipped — no Docker installed on dev machine |
| Docker build test | Skipped — no Docker installed |
| GitHub Actions CI | Added — two jobs (quality + security). Code-reviewer agent caught: missing `needs:` dependency between jobs, undocumented CVE ignore. Both fixed before merge. |
| Run /doc-gardener | Found 9 stale items across 5 files on a codebase only two days old |
| Run /cleanup fixes | Fixed all 9 items: wrong entity names in CLAUDE.md, phantom Validator in README diagram, unused stdlib logging import, empty mocks/ directory, misleading hook claim |

### Key insight: documentation rots in days, not months

The doc-gardener found 9 stale items in a codebase that was **two days old** with only **~900 lines of code**. Examples:
- CLAUDE.md still said "IngestorInterface" from the initial scaffold — Loop 2 renamed it to "IngestorPort"
- README mermaid diagram had a "Validator" component from the plan — Loop 12 implemented validation inline
- `src/mocks/` was listed in the architecture tree but was empty and unused — tests use `unittest.mock`

This validates the doc-gardening pattern: if you don't scan for drift regularly, your docs mislead the agent, and the agent generates code based on wrong assumptions.

### Agent-to-agent review in action

The code-reviewer agent reviewed 3 PRs in this session:
1. **Cleanup skill** — approved with advisory note to invoke `check-boundaries.sh` directly (fixed)
2. **Doc-gardener agent** — approved, incorrectly flagged one path as wrong (we verified and overrode)
3. **CI workflow** — caught two real issues: missing job dependency and undocumented CVE ignore (both fixed)

The reviewer isn't perfect (it made one false positive), but it caught issues a human would likely miss in a quick review.

### Final numbers

| Metric | After Session 1 | After Session 2 |
|--------|-----------------|-----------------|
| PRs merged | 19 | 21 |
| Tests | 148 | 148 |
| Hooks | 5 | 5 |
| Agents | 2 | 2 |
| Skills | 2 | 2 |
| CI | None | GitHub Actions (quality + security) |
| Doc drift items found | Unknown | 9 (all fixed) |
| Open items | 5 | 2 (Redis + Docker, need Docker installed) |

---

## Appendix B: Session 3 Results (2026-03-28)

Session 3 shifted from harness building to feature development — with two harness improvements driven by bugs we found along the way.

### Features built (Loops 13–16)

| Loop | PR | Feature | Tests added |
|------|-----|---------|------------|
| 13 | #24 | Cache hit/miss logging + Docker Compose Redis fix | +2 |
| 14 | #25 | Structured error responses (error_code, message, suggestion) | +5 |
| 15 | #26 | Multi-sheet Excel support (`?sheet_name=Claims`) | +8 |
| 16 | #29 | Confidence report (min/avg/low-confidence/missing fields) | +9 |

### Bugs found and fixed

| Bug | How found | Fix |
|-----|-----------|-----|
| Docker Compose: REDIS_URL=localhost inside container | Smoke test — Redis unreachable | Added `environment:` override in docker-compose.yml |
| Docker .venv: host bind mount overwrites container's venv | Repeated Permission denied after `docker compose up` | Added anonymous volume `/app/.venv` to isolate |
| Sheet name 400 error: nonexistent sheet returned 500 | PR #26 review — traced error path and found ValueError had no handler | Added `except ValueError` handler returning 400 INVALID_SHEET (#27) |

### Harness improvements driven by bugs

**1. PR description accuracy verification (PR #28)**

PR #26 claimed "Raises 400 with descriptive error if the named sheet doesn't exist" but the code actually returned 500. The ValueError from the adapter had no handler in the route — it fell through to the generic Exception handler.

This was caught during manual review, not by the harness. To prevent future occurrences:
- Extended the code-reviewer agent with a "PR Description Accuracy" blocking category
- Reordered `/create-pr` skill: draft PR body (Phase 2) → agent reviews both code AND text (Phase 3)
- The reviewer now traces error paths, verifies behavior claims, and checks mechanism explanations

**2. Commit message accuracy (feedback memory)**

The Docker anonymous volume commit described the wrong direction of interference ("host's root-owned copy overwriting the container's" instead of the bidirectional bind mount issue). Led to a feedback memory: trace actual step-by-step mechanics before writing commit explanations.

### Key insight: inaccurate documentation is worse than missing documentation

A PR that says "returns 400" when the code returns 500 is actively harmful — it gives future readers (human or agent) false confidence that a path is handled. The fix isn't just "be more careful" — it's adding a second agent that cross-references claims against code, the same way we added hooks to enforce code quality.

### Docker smoke test results

| Test | Result |
|------|--------|
| `/health` | 200 OK |
| Upload CSV (Groq Llama 3.3) | All 6 fields mapped, 5 valid records, 0 errors |
| Redis cache miss | 1,306ms |
| Redis cache hit | 1ms (1,306x speedup) |

### Final numbers

| Metric | After Session 1 | After Session 2 | After Session 3 |
|--------|-----------------|-----------------|-----------------|
| PRs merged | 19 | 22 | 29 |
| Tests | 148 | 148 | 165 |
| Hooks | 5 | 5 | 5 |
| Agents | 2 | 2 | 2 (reviewer now checks PR text) |
| Skills | 2 | 3 | 3 (create-pr now has 4 phases) |
| Features | Health + upload | + logging, row validation | + structured errors, multi-sheet, confidence report |
| Bugs found by review | 0 | 0 | 2 (sheet 400, commit accuracy) |

---

## Appendix C: Question Arc

The full sequence of questions across all three sessions:

| # | Question | What it changed |
|---|----------|----------------|
| 1 | "Which rules can be converted to hooks?" | Created 5 automated hooks from manual rules |
| 2 | "How can we make CLAUDE.md better?" | Pruned from 107 to 78 lines, moved domain rules to scoped files |
| 3 | "Do we use hooks to ensure a venv is used?" | Learned limits of hooks — some things are instructions, not gates |
| 4 | "Review this project using Anthropic guidelines" | Found architecture/instruction conflicts, missing .env.example |
| 5 | "Should we make a plan?" | Designed 10-loop TDD implementation plan before writing code |
| 6 | "Are the tests weak?" | Added parametrize, boundary values, target field validation |
| 7 | "How do we know this code runs?" | Smoke test found deprecated SLM model |
| 8 | "Review our way of working" | Automated commit/push/PR/merge, improved commit messages |
| 9 | "How do we stop regressions?" | Added security scanning hooks |
| 10 | "Can we add security scanning?" | bandit + pip-audit + semgrep pre-commit gate |
| 11 | "Which OpenAI practices are we missing?" | Agent-to-agent review, /cleanup skill, doc-gardener agent |
| 12 | "How is drift defined?" | Clarified six categories of drift, built /cleanup to detect them |
| 13 | "Run the doc-gardener" | Found 9 stale items in a 2-day-old codebase — proved the tool's value |
| 14 | "How can I fix Docker push?" | Led to Docker Compose Redis fix and .dockerignore |
| 15 | "Why were these commit messages wrong?" | Feedback memory: trace mechanisms step-by-step before writing |
| 16 | "Review the last PR for accuracy" | Found PR #26 claimed 400 but code returned 500 — a real bug |
| 17 | "How can we stop hallucinations on PRs?" | Extended code-reviewer to verify PR text, reordered /create-pr phases |
| 18 | "Do we have subagents or hooks that can help?" | Chose to extend existing code-reviewer rather than add new tooling |
| 19 | "Confirm this is correct" | Caught inaccurate Docker volume explanation — corrected on PR #24 |
