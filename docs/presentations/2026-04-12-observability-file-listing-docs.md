# Observability, File Listing & Documentation Gardening

**RiskFlow Engineering Session — 12 April 2026**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | What We Did | 3 min |
| 2 | Observability: Duration Logging | 5 min |
| 3 | Feature: Job File Metadata & GET /jobs | 8 min |
| 4 | Doc Gardener: 14 Stale Items | 5 min |
| 5 | Agent Workflow in Practice | 3 min |
| 6 | By the Numbers | 2 min |
| 7 | What's Next | 2 min |

---

## 1. What We Did (3 min)

Three PRs merged, closing all open issues and fixing all stale documentation:

| PR | Title | Issues |
|----|-------|--------|
| #132 | Add duration_ms to SLM calls and cache lookups | Closes #116, #117 |
| #133 | Add job file metadata and GET /jobs list endpoint | New feature |
| #134 | Fix 14 stale documentation items | Doc gardening |

**Starting state:** 2 open issues, 0 open PRs
**Ending state:** 0 open issues, 0 open PRs, docs clean

---

## 2. Observability: Duration Logging (5 min)

**Problem:** The two most expensive operations — SLM API calls (Groq) and Redis cache lookups — had no timing instrumentation. Slow calls were invisible in logs.

**Solution:**

```
# SLM call (mapper.py) — new event
{"event": "slm_call", "duration_ms": 1247, "model": "llama-3.3-70b-versatile", "headers_count": 6}

# Cache lookup (mapping_service.py) — enriched existing event
{"event": "cache_lookup", "result": "hit", "duration_ms": 1, "cache_key": "39fe3bc..."}
```

**Design decisions:**
- `time.monotonic()` everywhere — matches the existing `routes.py` convention (reviewer caught `perf_counter` inconsistency)
- Log only on success — API errors propagate `SLMUnavailableError` without partial timing
- structlog only, no stdlib logging

**Tests:** 9 new (5 SLM logging with parametrized boundaries, 2 cache hit/miss, plus structlog config teardown for test isolation)

**Code reviewer:** Approved after one REVISE round — fixed structlog config teardown, parametrized `headers_count` boundaries, switched `perf_counter` to `monotonic`

---

## 3. Feature: Job File Metadata & GET /jobs (8 min)

**Problem:** Users upload files via `POST /upload/async` but can't see what they uploaded or when. The Job model stored only `id`, `status`, `result`, `error`. Filename was logged but never persisted.

**Solution — 8 TDD loops across all hexagonal layers:**

| Loop | Layer | Change |
|------|-------|--------|
| 1 | Domain | `filename: str \| None` on Job (backward-compatible) |
| 2 | Domain | `created_at: datetime` (UTC, immutable across transitions) |
| 3 | Port | `list_all() -> list[Job]` on JobStorePort protocol |
| 4 | Adapter | `InMemoryJobStore.list_all()` sorted newest-first |
| 5 | HTTP | `GET /jobs` endpoint, `JobSummary`/`JobListResponse` models |
| 6 | HTTP | Wire `file.filename` into `Job.create()`, enrich `GET /jobs/{id}` |
| 7 | Contract | Provider + consumer tests for response shape |
| 8 | GUI | `list_jobs()` on RiskFlowClient |

**API response:**

```json
GET /jobs → 200
{
  "jobs": [
    {
      "job_id": "a1b2c3d4-...",
      "filename": "bordereaux_q1.csv",
      "created_at": "2026-04-12T10:30:00+00:00",
      "status": "complete"
    }
  ]
}
```

**Key design decisions:**
- `created_at` is `datetime.datetime` in the domain, serialized to ISO 8601 only at the HTTP boundary
- `GET /jobs` registered before `GET /jobs/{job_id}` for correct FastAPI path resolution
- `list_all()` sorts in Python, not by insertion order — resilient to future Redis-backed store
- `filename` defaults to `None` — all existing `Job.create()` callers unchanged

**Tests:** 30 new across all layers (including null-filename serialization and HTTP-layer sort order added during code review)

**Code reviewer:** Approved after one REVISE round — added null-filename tests, HTTP-layer sort order test, fixed import style

**OpenAPI spec:** Regenerated with new endpoint and models.

---

## 4. Doc Gardener: 14 Stale Items (5 min)

Ran the doc-gardener agent against the full codebase. Found 14 stale items across 9 files:

| Category | File | Issue |
|----------|------|-------|
| Wrong reference | `reinsurance.md` | `schemas/default.yaml` → `standard_reinsurance.yaml` |
| Wrong reference | `reinsurance.md` | `coerce_date()` → `parse_date()` |
| Missing content | `api.md` | `GET /jobs` endpoint entirely undocumented |
| Missing content | `README.md` | `GET /jobs` missing from endpoint table |
| Missing content | `api.md` | `filename` and `created_at` fields on `GET /jobs/{id}` |
| Missing content | `routes.py` docstring | `InvalidCorrectionError → 422` omitted |
| Wrong casing | `api.md` | Status values `COMPLETE` → `complete` |
| Wrong casing | `features.md` | Status values `PENDING` → `pending` |
| Wrong casing | `async-upload.md` | Status values uppercase throughout |
| Wrong count | `CLAUDE.md` | GUI "3 tabs" → "4 tabs" |
| Ambiguous | `CLAUDE.md` | `/jobs` route didn't distinguish list vs detail |
| Missing content | `features.md` | `GET /jobs` not in async feature or checklist |
| Missing content | `async-upload.md` | No "list all jobs" step |
| Fabricated | `cleanup/SKILL.md` | `CVE-2026-4539` doesn't exist |

**Key insight:** The uppercase/lowercase status casing issue appeared in 4 files. `JobStatus` is a `StrEnum` producing lowercase values, but all docs were written with uppercase. This drifted silently because no test ever compared doc examples against the enum values.

---

## 5. Agent Workflow in Practice (3 min)

Every feature PR followed the same mechanical pattern:

```
Plan → TDD loops (RED/GREEN/commit) → Code review → Fix REVISE feedback → APPROVE → PR → Merge
```

**Code reviewer caught real issues:**
- **PR #132:** structlog config mutation without teardown (test isolation), `perf_counter` vs `monotonic` inconsistency, missing parametrized boundaries
- **PR #133:** no test for `filename=null` serialization, sort order only tested at store level not HTTP, import inside method body

Both required one REVISE round. Neither would have been caught by mypy, ruff, or pytest alone — they were quality and coverage gaps that needed a second pair of eyes.

The doc-gardener agent was run separately to scan for drift, producing the 14-item report that became PR #134.

---

## 6. By the Numbers (2 min)

| Metric | Before session | After session |
|--------|---------------|--------------|
| Open issues | 2 | 0 |
| Open PRs | 0 | 0 |
| PRs merged (total) | 131 | 134 |
| Tests | ~840 | 876 |
| Coverage | 96.5% | 96.5% |
| Endpoints | 14 | 15 |
| Stale doc items | 14 | 0 |
| Version | v0.2.0 | v0.2.0 |

---

## 7. What's Next (2 min)

No open issues or PRs. Potential follow-ups:

| Item | Priority | Why |
|------|----------|-----|
| Pagination on `GET /jobs` | Medium | Will be needed at scale — limit/offset params |
| GUI "Recent Uploads" tab | Medium | The `list_jobs()` client method exists, tab does not |
| Redis-backed job store | Low | InMemoryJobStore loses data on restart |
| Sync upload tracking | Low | Only async uploads create Job records currently |
| Alerting thresholds | Low | `duration_ms` data exists; slow-query warnings do not |
