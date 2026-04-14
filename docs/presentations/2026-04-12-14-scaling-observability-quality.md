# Scaling, Observability & Quality

**RiskFlow Engineering Session — 12-14 April 2026**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Did | 5 min |
| 2 | Scaling to 5 Users | 10 min |
| 3 | Observability & Logging | 5 min |
| 4 | Bug Fix: SLM Confidence Anchoring | 5 min |
| 5 | Harness Improvements | 5 min |
| 6 | Test Quality | 3 min |
| 7 | By the Numbers | 2 min |
| 8 | What's Next | 2 min |

---

## 1. What We Did (5 min)

20 PRs merged across 3 days, closing 15 issues. Three workstreams: scaling the app to 5 concurrent users, fixing a bug that made confidence scores meaningless, and improving test quality.

| PR | Title |
|----|-------|
| #132 | Add duration_ms to SLM calls and cache lookups |
| #133 | Add job file metadata and GET /jobs list endpoint |
| #134 | Fix 14 stale documentation items from doc-gardener scan |
| #147 | Add configurable LOG_LEVEL and worker_pid in logs |
| #148 | Add RedisJobStore adapter for persistent job tracking |
| #149 | Add concurrent background processing with ASYNC_BACKEND |
| #150 | Add coverage delta hook to block untested production code |
| #152 | Add Groq semaphore rate limiting with SLM_CONCURRENCY |
| #154 | Add 12 April session presentation |
| #155 | Move coverage delta check from pre-commit to CI |
| #156 | Add asyncio.Lock to schema registry for concurrency safety |
| #157 | Add Docker multi-worker and log rotation |
| #158 | Add DEBUG-level observability events for scaling |
| #159 | Add performance guardrails for scaling |
| #160 | Add integration and load tests for scaling |
| #161 | Add CI concurrency job + update scaling roadmap |
| #162 | Upgrade pygments + fix CI concurrency-test permissions |
| #163 | Fix SLM confidence anchoring on literal 0.95 |
| #165 | Add test docstrings to D/C/B-grade files |
| #166 | Add CSV test fixtures for confidence variance testing |

---

## 2. Scaling to 5 Users (10 min)

### The problem

RiskFlow ran as a single Uvicorn process with in-memory job storage. Under 5 concurrent users:
- InMemoryJobStore had race conditions and lost data on restart
- BackgroundTasks ran sequentially (5 uploads × 5s = 25s serial)
- No limit on simultaneous Groq API calls (risk of 429 rate limits)
- Schema registry had race conditions on concurrent POST /schemas

### What we built (10 issues, 41 TDD loops)

| Component | Fix | PR |
|-----------|-----|-----|
| Job persistence | RedisJobStore adapter | #148 |
| Concurrent tasks | `asyncio.create_task()` | #149 |
| API rate limiting | `asyncio.Semaphore` on GroqMapper | #152 |
| Schema safety | `asyncio.Lock` on create/delete | #156 |
| Multi-worker | `--workers 2` in Dockerfile | #157 |

### Rollback via env vars — no code changes, no redeploy

| Var | Default | Rollback |
|-----|---------|----------|
| `JOB_STORE` | `redis` | `memory` |
| `ASYNC_BACKEND` | `tasks` | `background` |
| `SLM_CONCURRENCY` | `3` | `0` (disabled) |
| `LOG_LEVEL` | `INFO` | `DEBUG` |

### Proof: CI concurrency test

The `concurrency-test` CI job runs 5 Locust users against the real Docker stack (multi-worker Uvicorn + Redis) for 30 seconds. Results from the first passing run:

- 94 requests completed, 3.32 RPS
- Zero unexpected errors (503s on /upload are expected with dummy Groq key)
- All non-SLM endpoints (health, schemas, jobs, async upload) handled 5 users with zero failures

### Known limitations

- Per-process scope: `Semaphore(3)` with 2 workers = 6 total, not 3
- `asyncio.Lock` prevents races within a worker, not across workers
- No test with real Groq API under 5 concurrent users (tracked as #164)

---

## 3. Observability & Logging (5 min)

### Before this session

- LOG_LEVEL hardcoded to INFO — no way to switch to DEBUG without code changes
- No worker identity in logs — with `--workers 2`, can't tell which process handled a request
- No timing on the most expensive operations (SLM calls, cache lookups)

### After

Every log line now carries `worker_pid` and `request_id` automatically:

```json
{"event": "slm_call", "duration_ms": 1247, "request_id": "a1b2c3d4", "worker_pid": 42, "level": "info"}
```

**Event catalogue:**

| Event | Level | When |
|-------|-------|------|
| `slm_call` | INFO | After each Groq API call |
| `cache_lookup` | INFO | Cache hit or miss with duration |
| `task_started` | INFO | Background task begins |
| `task_completed` | INFO | Background task finishes with duration and status |
| `semaphore_wait` | DEBUG | Time waiting for Groq semaphore |
| `job_store_save` | DEBUG | Redis SETEX timing |
| `job_store_list` | DEBUG | Redis SCAN+GET timing |

**Querying:**
```bash
docker compose logs api --no-log-prefix | jq 'select(.event == "slm_call" and .duration_ms > 2000)'
docker compose logs api --no-log-prefix | jq 'select(.worker_pid == 42)'
LOG_LEVEL=DEBUG docker compose up  # surfaces semaphore and Redis timing
```

---

## 4. Bug Fix: SLM Confidence Anchoring (5 min)

### The bug (#135)

Every mapping returned `confidence: 0.95` — the exact value from the example JSON in the system prompt. The SLM (Llama 3.3) anchored on this literal and parroted it back for every mapping, making the confidence threshold feature useless.

### The fix (#163)

Replaced the literal `0.95` with a `<float>` placeholder and added explicit guidance:

```
- confidence is a float between 0.0 and 1.0 — estimate YOUR certainty:
  - 0.9-1.0: exact or near-exact name match
  - 0.7-0.9: strong match via known alias or clear context
  - 0.4-0.7: uncertain, plausible but ambiguous
  - below 0.4: guess, low certainty
- Do NOT default all confidences to the same value
```

### Verified with real uploads

| Header | Target | Before | After |
|--------|--------|--------|-------|
| Policy_ID | Policy_ID | 0.95 | **1.0** (exact match) |
| Amount | Sum_Insured | 0.95 | **0.9** (reasonable alias) |
| Effective | Inception_Date | 0.95 | **0.8** (plausible) |
| Random Column | unmapped | 0.95 | **unmapped** |

---

## 5. Harness Improvements (5 min)

### Coverage delta check

Added a `diff-cover` step to CI that blocks PRs where new `src/` lines in adapters/domain/ports have < 80% test coverage. Caught a real gap in PR #152 (entrypoint wiring lines).

Initially implemented as a pre-commit hook (PR #150) but moved to CI (PR #155) because it added 30s to every commit. Coverage enforcement is a branch-level concern, not a commit-level concern.

### PR template enforcement

The `enforce-create-pr.sh` hook now validates that all 6 required sections are present in the PR body: Summary, Agent Review, Loop context, TDD cycles, Checks, Known limitations. Missing sections are blocked with a specific list.

### Feedback memories saved

| Memory | Why |
|--------|-----|
| RED-first per loop | PR #149 shipped 4 loops without tests — caught by user review |
| Full PR template always | Multiple PRs skipped sections — "no small PR exception" |

---

## 6. Test Quality (3 min)

### Readability audit

Evaluated three approaches for test readability:
1. **BDD docstrings everywhere** — rejected (verbose for obvious tests, forced "so that" clauses, maintenance burden)
2. **Test helper refactoring** — rejected (risky to refactor 200+ working tests, shared helpers create coupling)
3. **Class docstrings + selective method docstrings** — chosen (zero risk, targeted value, low maintenance)

### What we added (#165)

- Class docstrings on all undocumented test classes across 6 files
- Method docstrings on edge case tests explaining the business rule
- Testing rule in `.claude/rules/testing.md`

### Standard

```python
class TestGracefulDegradation:
    """Redis failures degrade to no-op — the API stays up."""

    def test_get_returns_none_on_corrupt_data(self) -> None:
        """Corrupt Redis entry returns None instead of crashing the API."""
```

---

## 7. By the Numbers (2 min)

| Metric | Start of session | End of session |
|--------|-----------------|---------------|
| PRs merged (total) | 131 | 166 |
| Tests | ~840 | 959 |
| Coverage | 96.5% | 96.5% |
| Open issues | 2 (#116, #117) | 2 (#136, #164) |
| Scaling issues | 0 created | 10 created, 10 closed |
| Endpoints | 14 | 15 |
| Pre-commit hooks | 5 | 5 (coverage moved to CI) |
| CI jobs | 4 | 5 (+ concurrency-test) |
| Uvicorn workers | 1 | 2 |
| Version | v0.2.0 | v0.2.0 |

### Session output: 20 PRs in 3 days

- 10 scaling PRs (41 TDD loops)
- 1 bug fix (confidence anchoring)
- 3 harness improvements (coverage hook, PR template, CI fixes)
- 3 documentation PRs (doc gardener, presentations, test docstrings)
- 3 infrastructure PRs (CVE upgrades, CI permissions, test fixtures)

---

## 8. Lessons Learned (5 min)

### What went wrong

| Problem | Impact | Fix applied |
|---------|--------|-------------|
| **Skipped tests on 4 TDD loops** (PR #149) | Production code shipped untested — user caught it, not the harness | Added coverage delta check in CI; saved RED-first feedback memory |
| **Skipped PR template repeatedly** | Multiple PRs had minimal descriptions despite explicit rules | Added hook that validates 6 required sections in PR body |
| **CI broke 3 times after merge** | Shallow checkout, missing permissions, Locust exit code on 503s | Each was a trivial fix but showed CI changes weren't tested pre-merge |
| **Version didn't bump for 20 PRs** | New endpoint added in PR #133 but version stayed at 0.2.0 | Manual bump to v0.3.0; created issue #169 for /release skill |
| **Scaling proof is incomplete** | CI concurrency test uses dummy Groq key — proves infra, not full path | Tracked as issue #164 (concurrent e2e with real API) |
| **Plan took 6 review rounds** | 41-loop plan had dependency errors, missing tests, wrong granularity | Good investment — caught real gaps — but planning overhead was significant |
| **Test readability deferred too long** | 959 tests but 75% lacked docstrings after 160+ PRs | Retrofitted class docstrings; should have been enforced from the start |

### What should change

1. **Version bumps must be automated** — the /release skill (#169) should detect API changes and bump on merge, not rely on manual intervention
2. **CI changes need dry-run testing** — too many "fix CI" follow-up PRs. Consider a CI-testing workflow that validates workflow YAML before merge
3. **RED-first needs mechanical enforcement** — the feedback memory helps but discipline fails under time pressure. The coverage delta in CI catches it at PR level but not at commit level
4. **Session presentations should always include this section** — what went wrong is more valuable than what shipped

### What went well

- The scaling plan was thorough — 41 loops with explicit dependencies, rollback strategy, and observability
- Every scaling feature is reversible via env var — no redeploy needed to rollback
- The code-reviewer agent caught real issues in every PR it reviewed (test isolation, timer consistency, null-filename gaps, disjunctive assertions)
- The confidence bug was found, root-caused, fixed, and verified with real uploads in one session
- The harness got stronger — PR template enforcement, coverage delta in CI, test docstring standard

---

## 9. What's Next (2 min)

| # | Title | Type |
|---|-------|------|
| #136 | Confidence endpoint for human-provided mappings | Enhancement |
| #164 | Concurrent e2e test with real Groq API | Testing |
| #169 | /release skill for automated version bumps | Harness |

The scaling infrastructure is complete. The next step is proving it works with real Groq API calls under concurrency (#164), automating releases (#169), and building the confidence score endpoint for the interactive mapping workflow (#136).
