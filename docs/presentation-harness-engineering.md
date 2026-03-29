# Harness Engineering: Building Software by Asking Better Questions

**Duration:** 90 minutes
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
- "Zero lines of manual code. 406 tests. 5 hooks. 63 PRs. Built across three sessions."
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

## 9. The Full Harness — Break (5 min)

*Take a breather. Walk through the harness layout on screen.*

```
.claude/
  hooks/
    pre-commit.sh          <- mypy, pytest, ruff (blocks commit)
    post-edit-lint.sh      <- auto-format on every .py edit
    protect-files.sh       <- blocks edits to .env, uv.lock
    check-boundaries.sh    <- blocks cross-layer imports
    security-scan.sh       <- bandit, pip-audit, semgrep
  rules/
    reinsurance.md         <- domain rules (path-scoped to domain/ and slm/)
    testing.md             <- test quality standards (path-scoped to tests/)
    operating-principles.md <- agent-driven development philosophy
  agents/
    code-reviewer.md       <- reviews code + PR text accuracy before merge
    doc-gardener.md        <- scans for stale documentation
  skills/
    create-pr/SKILL.md     <- 4-phase PR: draft, review code, verify claims, publish
    cleanup/SKILL.md       <- garbage collection for pattern drift
    commit/SKILL.md        <- TDD-aware commit with message standards
  settings.json            <- permissions, hook wiring
```

- 5 hooks (mechanical gates)
- 3 rules (scoped instructions)
- 2 agents (agent-to-agent review)
- 3 skills (standardized workflows)
- "Every piece was added because we found a gap. None were planned upfront."

---

---

## 10. "How do we stop hallucinations on PRs?" (7 min)
*Accuracy enforcement — the harness must check its own output*

- PR #26 claimed "Raises 400" but the code returned 500 — a ValueError had no handler
- **Before:** manual review caught it. No mechanical enforcement.
- **After:** Extended code-reviewer agent with "PR Description Accuracy" blocking category
- The reviewer now traces error paths, verifies behavior claims, checks mechanism explanations against the actual code
- Reordered `/create-pr` skill: draft PR body (Phase 2) → agent reviews both code AND text (Phase 3)
- Also added commit message accuracy feedback: trace actual step-by-step mechanics before writing
- **Principle: If the harness can generate wrong documentation about correct code, add a second agent to cross-reference claims against the diff.**

---

## 11. Configurable Schema — The "Expand and Contract" Pattern (10 min)
*Swapping the engine while the harness keeps running*

- Problem: hardcoded 6-field schema (Policy_ID, Sum_Insured, etc.) limits the tool to one shape of bordereaux data
- Solution: configurable TargetSchema loaded from YAML, with a dynamic pydantic model factory
- **The migration strategy:**
  - Phase 1: Build new code alongside old code (TargetSchema, build_record_model) — zero existing tests broken
  - Phase 2: Add optional `schema` parameter with DEFAULT_TARGET_SCHEMA default — existing callers unchanged
  - Phase 3: Equivalence test proves dynamic model matches hardcoded RiskRecord for all inputs
  - Phase 4: Wire in, relax ColumnMapping validator, switch ProcessingResult to dict
- **Safety nets:**
  - Loop 7 equivalence tests: 18 tests feeding identical inputs to both models
  - Schema fingerprint (blake2b) in cache keys prevents poisoned data across schema changes
  - Self-validating schema: constraint-type safety, cross-field rule validation, SLM hint integrity all checked at parse time
- "A broken YAML config is a fatal startup error — the app refuses to boot"
- **Principle: When replacing a foundation, build the new one next to the old one, prove they're identical, then switch. The harness validates both at every step.**

---

## 12. The Feedback Loop — Correction Cache (7 min)
*Human corrections improve future mappings automatically*

- Problem: when the SLM maps wrong, there's no way to correct it and have the correction persist
- Solution: `POST /corrections` stores `(cedent_id, source_header) → target_field` in Redis
- On subsequent uploads with `?cedent_id=ABC`:
  1. Check corrections for this cedent's headers
  2. Corrected headers get confidence 1.0 — skip the SLM entirely
  3. Only uncorrected headers go to the SLM
  4. All headers corrected? SLM never called
- Redis hash per cedent: `HMGET` for batch lookup (one round-trip for all headers)
- Invalid corrections (target field not in schema) rejected with `InvalidCorrectionError` → 422
- Graceful degradation: Redis down → NullCorrectionCache → pure SLM path
- **Principle: Build feedback loops into the domain, not as afterthoughts. Corrections are a first-class port with their own adapter, not a patch on the mapper.**

---

## 13. Testing Strategy & CI/CD Pipeline (10 min)
*Three tiers, five CI jobs, zero manual gates*

### Three-tier test taxonomy
| Tier | Count | What | External deps | When |
|------|-------|------|---------------|------|
| Unit | 376 | Isolated components, all mocked | None | Every PR |
| Integration | 25 | Full pipeline, SLM mocked | None | Every PR |
| E2E | 5 | Real Groq API, nothing mocked | GROQ_API_KEY | Push to main only |

### CI pipeline
```
PR → quality (unit + integration + mypy + ruff + hex linter)
   → boot-test (Docker build + /health, if app code changed)
   → security (bandit + pip-audit)
Merge → e2e (real Groq API)
      → CD (Docker build → ghcr.io with :latest and :sha tags)
```

### Why e2e runs after merge, not before
- PRs use mocked tests — fast, free, never blocked by Groq outages
- Post-merge e2e catches model deprecation and API drift
- If e2e fails, the code is correct — the external dependency changed. Fix forward.

### Test artifacts
- JUnit XML reports uploaded as 30-day artifacts
- `dorny/test-reporter` renders results as PR check annotations — test names and pass/fail visible in the PR Checks tab without opening logs

### The hexagonal linter
- AST-based Python linter that enforces `domain ← ports ← adapters ← entrypoint`
- Runs in CI alongside ruff and mypy
- Agent-readable error messages: "VIOLATION: Layer 'domain' cannot import 'adapters'. FIX: Define a Protocol in src/ports/output/"
- 18 tests including a scan of the real codebase

---

## 14. By the Numbers (3 min)

| Metric | Session 1 | Session 2 | Session 3 |
|--------|-----------|-----------|-----------|
| PRs merged | 19 | 22 | 63 |
| Tests | 148 | 148 | 406 |
| Hooks | 5 | 5 | 5 |
| Agents | 2 | 2 | 2 (reviewer checks PR text + accuracy) |
| Skills | 2 | 3 | 3 (create-pr now has 4 phases) |
| CI jobs | 0 | 2 | 5 (quality, boot-test, security, e2e, CD) |
| Source files | 25 | 25 | 21 |
| Manual code written | 0 | 0 | 0 |
| Endpoints | 2 | 2 | 7 (health, upload, upload/async, jobs, sheets, corrections, confidence) |
| Features | Upload + health | + logging, validation | + configurable schema, correction cache, async upload, sheets, confidence report, structured errors |

---

## 15. Takeaway (3 min)

Harness engineering isn't about the tools — it's about asking the right questions in the right order:

1. **What can be automated?** → Hooks (5 mechanical gates)
2. **What instructions does the agent need?** → Pruned CLAUDE.md (78 lines, not 343)
3. **Are the tests strong enough?** → Testing rules + coverage validation before every TDD loop
4. **Does it actually run?** → Smoke tests, Docker boot test in CI
5. **Is the documentation accurate?** → Code-reviewer verifies PR text against the actual diff
6. **Can we swap the foundation safely?** → Expand and Contract with equivalence tests
7. **Do users get feedback?** → Correction cache with confidence 1.0 overrides
8. **How do we keep it working?** → CI/CD: 5 jobs, 406 tests, Docker image on every green merge
9. **How do we prevent drift?** → `/cleanup` skill, doc-gardener agent, hexagonal AST linter

Each question tightened the constraints. Each constraint improved the output. The agent didn't get smarter — the harness got better.

**The harness is the product.** The code is a side effect.

**What we'd do differently:** Start with hooks and CI from commit 1. The hardest bugs to find were the ones that mattered most — model deprecation, inaccurate PR claims, cross-layer imports. All were caught by mechanical checks, not by reading code.

---

## 16. Q&A (5 min)

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
| 17 | #31 | Partial mapping (already worked — added tests to prove it) | +3 |
| 18 | #32 | Async upload with job tracking (`POST /upload/async`, `GET /jobs/{id}`) | +19 |
| 19 | #33 | List sheet names (`POST /sheets`) | +7 |
| 20-22 | #34,#38 | Configurable target schema (TargetSchema, build_record_model, YAML loader) | +88 |
| 23 | #40 | Wire dynamic schema into MappingService, relax ColumnMapping | +8 |
| CC 1-8 | #41-#48 | Correction cache feedback loop (Correction model, Redis hash, service integration, HTTP endpoint, wiring) | +46 |

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
| PRs merged | 19 | 22 | 49 |
| Tests | 148 | 148 | 383 |
| Hooks | 5 | 5 | 5 |
| Agents | 2 | 2 | 2 (reviewer now checks PR text + accuracy) |
| Skills | 2 | 3 | 3 (create-pr now has 4 phases) |
| CI jobs | None | quality + security | + integration tests + Docker boot test |
| Features | Health + upload | + logging, row validation | + structured errors, multi-sheet, confidence report, async upload, sheet names, configurable schema, correction cache |
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
| 20 | "Have we got enough integration tests?" | Added 17 integration tests covering all Session 3 features |
| 21 | "Are our tests sufficient?" (TargetSchema) | Added 15 boundary/edge case tests before continuing |
| 22 | "Is test coverage sufficient?" (correction cache) | Created test coverage validation process — now runs before every TDD loop |
| 23 | "Would it make sense to run integration tests before every PR?" | Split CI into unit + integration steps |
| 24 | "Would it make sense to provision via Docker Compose before each PR?" | Added Docker boot test to CI for app code changes |
| 25 | "Which features are most useful for RiskFlow?" | Reprioritized: configurable schema first (foundation), then correction cache (feedback loop) |
| 26 | "Can you plan implementation of configurable schema?" | 20-loop Expand and Contract migration plan with safety nets |
| 27 | "Feedback Loop: Redis Correction Cache" | 9-loop plan for human-verified mapping corrections |
