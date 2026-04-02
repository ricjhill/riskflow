# Harness Engineering Part 2: Shipping Features with the Harness

**Duration:** 45 minutes
**Audience:** Engineering team
**Project:** RiskFlow — Reinsurance Data Mapper
**Prerequisite:** Part 1 (Building the Constraints)

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | Recap: The Harness So Far | 2 min |
| 2 | "How do we stop hallucinations on PRs?" | 7 min |
| 3 | Configurable Schema — The "Expand and Contract" Pattern | 8 min |
| 4 | The Feedback Loop — Correction Cache | 7 min |
| 5 | Testing Strategy & CI/CD Pipeline | 8 min |
| 6 | By the Numbers | 3 min |
| 7 | The Question Arc | 5 min |
| 8 | Takeaway & Q&A | 5 min |

---

## 1. Recap: The Harness So Far (2 min)

From Part 1, we built:

- **5 hooks** — pre-commit (mypy/pytest/ruff), auto-format, file protection, boundary check, security scan
- **3 rules** — reinsurance domain, testing standards, operating principles
- **2 agents** — code-reviewer, doc-gardener
- **2 skills** — create-pr (4-phase), cleanup (drift detection)

Now we use this harness to build features — and improve it when we find gaps.

---

## 2. "How do we stop hallucinations on PRs?" (7 min)

*Accuracy enforcement — the harness must check its own output*

- PR #26 claimed "Raises 400" but the code returned 500 — a ValueError had no handler
- **Before:** manual review caught it. No mechanical enforcement.
- **After:** Extended code-reviewer agent with "PR Description Accuracy" blocking category
- The reviewer now traces error paths, verifies behavior claims, checks mechanism explanations against the actual code
- Reordered `/create-pr` skill: draft PR body (Phase 2) → agent reviews both code AND text (Phase 3)
- Also added commit message accuracy feedback: trace actual step-by-step mechanics before writing

**Principle: If the harness can generate wrong documentation about correct code, add a second agent to cross-reference claims against the diff.**

---

## 3. Configurable Schema — The "Expand and Contract" Pattern (8 min)

*Swapping the engine while the harness keeps running*

### The Problem

Hardcoded 6-field schema (Policy_ID, Sum_Insured, etc.) limits the tool to one shape of bordereaux data.

### The Solution

Configurable TargetSchema loaded from YAML, with a dynamic Pydantic model factory.

### The Migration Strategy

| Phase | What | Tests broken |
|-------|------|-------------|
| 1 | Build new code alongside old code (TargetSchema, build_record_model) | Zero |
| 2 | Add optional `schema` parameter with DEFAULT_TARGET_SCHEMA default | Zero |
| 3 | Equivalence test proves dynamic model matches hardcoded RiskRecord | Zero |
| 4 | Wire in, relax ColumnMapping validator, switch ProcessingResult to dict | Zero |

### Safety Nets

- **Equivalence tests (Loop 7):** 18 tests feeding identical inputs to both models — if the dynamic model ever disagrees with the hardcoded one, the test catches it
- **Schema fingerprint (blake2b)** in cache keys prevents poisoned data across schema changes
- **Self-validating schema:** constraint-type safety, cross-field rule validation, SLM hint integrity all checked at parse time
- "A broken YAML config is a fatal startup error — the app refuses to boot"

**Principle: When replacing a foundation, build the new one next to the old one, prove they're identical, then switch. The harness validates both at every step.**

---

## 4. The Feedback Loop — Correction Cache (7 min)

*Human corrections improve future mappings automatically*

### The Problem

When the SLM maps wrong, there's no way to correct it and have the correction persist.

### The Solution

`POST /corrections` stores `(cedent_id, source_header) → target_field` in Redis.

### How It Works

On subsequent uploads with `?cedent_id=ABC`:

1. Check corrections for this cedent's headers
2. Corrected headers get confidence 1.0 — skip the SLM entirely
3. Only uncorrected headers go to the SLM
4. All headers corrected? SLM never called

### Implementation Details

- Redis hash per cedent: `HMGET` for batch lookup (one round-trip for all headers)
- Invalid corrections (target field not in schema) rejected with `InvalidCorrectionError` → 422
- Graceful degradation: Redis down → NullCorrectionCache → pure SLM path

**Principle: Build feedback loops into the domain, not as afterthoughts. Corrections are a first-class port with their own adapter, not a patch on the mapper.**

---

## 5. Testing Strategy & CI/CD Pipeline (8 min)

*Three tiers, five CI jobs, zero manual gates*

### Test Taxonomy

| Tier | Count | What | External deps | When |
|------|-------|------|---------------|------|
| Unit | 456 | Isolated components, all mocked | None | Every PR |
| Integration | 39 | Full pipeline, SLM mocked + testcontainers Redis | Docker (optional) | Every PR |
| E2E | 5 | Real Groq API, nothing mocked | GROQ_API_KEY | Push to main only |
| Contract | 11 | API response shape verification | None | Every PR |
| Benchmark | 28 | Performance guardrails, TTFB, memory endurance | None | Every PR |
| Load | 1 | Locust CI assertions (error rate, P95) | None | Every PR |

### CI Pipeline

```
PR → quality (unit + integration + contract + benchmarks + load + mypy + ruff + hex linter)
   → boot-test (Docker build + /health, if app code changed)
   → security (bandit + pip-audit)
Merge → e2e (real Groq API)
      → CD (Docker build → ghcr.io with :latest and :sha tags)
```

### Why E2E Runs After Merge, Not Before

- PRs use mocked tests — fast, free, never blocked by Groq outages
- Post-merge e2e catches model deprecation and API drift
- If e2e fails, the code is correct — the external dependency changed. Fix forward.

### Test Artifacts

- JUnit XML reports uploaded as 30-day artifacts
- `dorny/test-reporter` renders results as PR check annotations — test names and pass/fail visible in the PR Checks tab without opening logs

### The Hexagonal Linter

- AST-based Python linter that enforces `domain ← ports ← adapters ← entrypoint`
- Runs in CI alongside ruff and mypy
- Agent-readable error messages: "VIOLATION: Layer 'domain' cannot import 'adapters'. FIX: Define a Protocol in src/ports/output/"
- 18 tests including a scan of the real codebase

---

## 6. By the Numbers (3 min)

| Metric | Session 1 | Session 2 | Session 3 |
|--------|-----------|-----------|-----------|
| PRs merged | 19 | 22 | 73 |
| Tests | 148 | 148 | 461 |
| Hooks | 5 | 5 | 5 |
| Agents | 2 | 2 | 2 (reviewer checks PR text + accuracy) |
| Skills | 2 | 3 | 2 (create-pr has 4 phases, cleanup) |
| CI jobs | 0 | 2 | 5 (quality, boot-test, security, e2e, CD) |
| Source files | 25 | 25 | 21 |
| Manual code written | 0 | 0 | 0 |
| Endpoints | 2 | 2 | 7 (health, upload, upload/async, jobs, sheets, corrections, schemas) |

### Session 2: Closing the Gaps

After the initial build session, we ran a second session to close open items — demonstrating the harness in maintenance mode:

| Task | Result |
|------|--------|
| Smoke test row validation (real SLM) | Pass — 5 validated RiskRecords |
| GitHub Actions CI | Added — two jobs (quality + security) |
| Run /doc-gardener | Found 9 stale items in a 2-day-old codebase |
| Run /cleanup fixes | Fixed all 9 items |

**Key insight: documentation rots in days, not months.** The doc-gardener found 9 stale items in a codebase that was two days old with only ~900 lines of code.

### Session 3: Features Built (Loops 13-23)

| Loop | Feature | Tests added |
|------|---------|------------|
| 13 | Cache hit/miss logging + Docker Compose Redis fix | +2 |
| 14 | Structured error responses (error_code, message, suggestion) | +5 |
| 15 | Multi-sheet Excel support | +8 |
| 16 | Confidence report (min/avg/low-confidence/missing) | +9 |
| 17 | Partial mapping (proved it already worked) | +3 |
| 18 | Async upload with job tracking | +19 |
| 19 | List sheet names | +7 |
| 20-22 | Configurable target schema (YAML, dynamic models, loader) | +88 |
| 23 | Wire dynamic schema, relax ColumnMapping | +8 |
| CC 1-8 | Correction cache feedback loop | +46 |

### Bugs Found by the Harness

| Bug | How found | Fix |
|-----|-----------|-----|
| Docker Compose: REDIS_URL=localhost inside container | Smoke test | Added `environment:` override |
| Docker .venv: host bind mount overwrites container's venv | Repeated Permission denied | Added anonymous volume `/app/.venv` |
| Sheet name 400 error: nonexistent sheet returned 500 | PR review — code-reviewer traced error path | Added `except ValueError` handler |

### Docker Smoke Test Results

| Test | Result |
|------|--------|
| `/health` | 200 OK |
| Upload CSV (Groq Llama 3.3) | All 6 fields mapped, 5 valid records, 0 errors |
| Redis cache miss | 1,306ms |
| Redis cache hit | 1ms (1,306x speedup) |

---

## 7. The Question Arc (5 min)

The full sequence of questions across all sessions:

| # | Question | What it changed |
|---|----------|----------------|
| 1 | "Which rules can be converted to hooks?" | Created 5 automated hooks from manual rules |
| 2 | "How can we make CLAUDE.md better?" | Pruned from 107 to 96 lines, moved domain rules to scoped files |
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
| 13 | "Run the doc-gardener" | Found 9 stale items in a 2-day-old codebase |
| 14 | "How can I fix Docker push?" | Led to Docker Compose Redis fix and .dockerignore |
| 15 | "Why were these commit messages wrong?" | Feedback memory: trace mechanisms step-by-step before writing |
| 16 | "Review the last PR for accuracy" | Found PR #26 claimed 400 but code returned 500 — a real bug |
| 17 | "How can we stop hallucinations on PRs?" | Extended code-reviewer to verify PR text, reordered /create-pr phases |
| 18 | "Do we have subagents or hooks that can help?" | Chose to extend existing code-reviewer rather than add new tooling |
| 19 | "Confirm this is correct" | Caught inaccurate Docker volume explanation |
| 20 | "Have we got enough integration tests?" | Added 17 integration tests covering all Session 3 features |
| 21 | "Are our tests sufficient?" (TargetSchema) | Added 15 boundary/edge case tests before continuing |
| 22 | "Is test coverage sufficient?" (correction cache) | Created test coverage validation process |
| 23 | "Would it make sense to run integration tests before every PR?" | Split CI into unit + integration steps |
| 24 | "Would it make sense to provision via Docker Compose before each PR?" | Added Docker boot test to CI |
| 25 | "Which features are most useful for RiskFlow?" | Reprioritized: configurable schema first, then correction cache |
| 26 | "Can you plan implementation of configurable schema?" | 20-loop Expand and Contract migration plan |
| 27 | "Feedback Loop: Redis Correction Cache" | 9-loop plan for human-verified mapping corrections |

---

## 8. Takeaway & Q&A (5 min)

Harness engineering isn't about the tools — it's about asking the right questions in the right order:

1. **What can be automated?** → Hooks (5 mechanical gates)
2. **What instructions does the agent need?** → Pruned CLAUDE.md (96 lines, not 343)
3. **Are the tests strong enough?** → Testing rules + coverage validation before every TDD loop
4. **Does it actually run?** → Smoke tests, Docker boot test in CI
5. **Is the documentation accurate?** → Code-reviewer verifies PR text against the actual diff
6. **Can we swap the foundation safely?** → Expand and Contract with equivalence tests
7. **Do users get feedback?** → Correction cache with confidence 1.0 overrides
8. **How do we keep it working?** → CI/CD: 5 jobs, 461 tests, Docker image on every green merge
9. **How do we prevent drift?** → `/cleanup` skill, doc-gardener agent, hexagonal AST linter

Each question tightened the constraints. Each constraint improved the output. The agent didn't get smarter — the harness got better.

**The harness is the product.** The code is a side effect.

**What we'd do differently:** Start with hooks and CI from commit 1. The hardest bugs to find were the ones that mattered most — model deprecation, inaccurate PR claims, cross-layer imports. All were caught by mechanical checks, not by reading code.
