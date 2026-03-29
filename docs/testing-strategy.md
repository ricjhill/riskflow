# RiskFlow Testing Strategy & CI/CD

## Overview

RiskFlow uses a three-tier testing strategy aligned with the hexagonal architecture. Each tier serves a distinct purpose, runs at a different stage of the pipeline, and catches a different class of defect.

| Tier | Marker | Count | What it tests | External deps | When it runs |
|------|--------|-------|---------------|---------------|-------------|
| Unit | `@pytest.mark.unit` | 431 | Isolated components with all deps mocked | None | Every PR, every push to main |
| Integration | `@pytest.mark.integration` | 25 | Full pipeline through TestClient, SLM mocked | None | Every PR, every push to main |
| E2E | `@pytest.mark.e2e` | 5 | Real Groq API, real parsing, nothing mocked | Groq API | Push to main only |

**Total: 461 tests**

---

## Tier 1: Unit Tests

**Directory:** `tests/unit/`
**Marker:** `@pytest.mark.unit`
**Run with:** `uv run pytest tests/unit/`

### Purpose
Verify individual components in isolation. Every dependency is mocked. A unit test failure means the logic inside a single class or function is wrong.

### Coverage by layer

| Layer | Test file | What it covers |
|-------|-----------|---------------|
| Domain models | `test_schema.py` | RiskRecord validation (currencies, dates, amounts), ColumnMapping, MappingResult, ConfidenceReport |
| Domain models | `test_dynamic_schema.py` | TargetSchema self-validation, build_record_model (types, constraints, cross-field rules, optional fields), equivalence with RiskRecord |
| Domain models | `test_correction_model.py` | Correction validation (non-empty fields, special characters) |
| Domain models | `test_job_model.py` | Job state machine (PENDING → PROCESSING → COMPLETE/FAILED) |
| Domain models | `test_errors.py` | Error hierarchy (all errors inherit from RiskFlowError) |
| Domain service | `test_mapping_service.py` | Orchestration: cache hit/miss, confidence threshold, correction cache integration, partial mapping, custom schema |
| Ports | `test_ports.py` | Protocol satisfaction: IngestorPort, MapperPort, CachePort, CorrectionCachePort |
| Adapters | `test_ingestor_adapter.py` | PolarsIngestor: CSV/Excel parsing, headers, preview, sheet names, missing files |
| Adapters | `test_slm_adapter.py` | GroqMapper: prompt construction, response parsing, error wrapping |
| Adapters | `test_cache_adapter.py` | RedisCache + NullCache: get/set, TTL, connection errors |
| Adapters | `test_correction_cache_adapter.py` | RedisCorrectionCache + NullCorrectionCache: HMGET/HSET, connection errors |
| Adapters | `test_job_store.py` | InMemoryJobStore: save/get, nonexistent ID |
| Adapters | `test_schema_loader.py` | YamlSchemaLoader: valid YAML, malformed YAML, invalid schema, missing file, unicode, permissions |
| HTTP | `test_http_adapter.py` | Routes: status codes, error mapping, file validation, sheet_name, cedent_id, corrections endpoint |
| HTTP | `test_async_upload.py` | Async upload: 202 response, job polling, 404 |
| Entrypoint | `test_entrypoint.py` | Composition root: app creation, cache wiring, correction cache wiring |
| Infrastructure | `test_imports.py` | All packages importable |
| Infrastructure | `test_logging.py` | structlog JSON output |
| Infrastructure | `test_hexagonal_linter.py` | AST linter: boundary violations, allowed imports, error messages |
| Row validation | `test_row_validation.py` | ProcessingResult with valid/invalid rows, RowError |
| Schema wiring | `test_schema_wiring.py` | Composition root loads schema from YAML, SCHEMA_PATH env var, error paths |
| Schema selection | `test_schema_selection.py` | ?schema= query param, GET /schemas, path traversal rejection |
| Cache keys | `test_cache_key_fingerprint.py` | Schema fingerprint in cache key, different schemas = different keys |
| SLM prompt | `test_schema_aware_prompt.py` | Dynamic prompt from schema fields and hints, no hardcoded leakage |
| Equivalence | `test_equivalence.py` | Dynamic model matches RiskRecord for all valid/invalid inputs |
| Shadow deployment | `test_shadow_deployment.py` | Full pipeline: CSV → both models → byte-identical JSON output |

### Test quality rules

Defined in `.claude/rules/testing.md` and enforced by the test coverage validation process:

- **Happy path** — valid input produces expected output
- **Boundary values** — zero, empty string, exactly at limits (0.0, 1.0)
- **Invalid input** — wrong types, out-of-range, malformed
- **Edge cases** — duplicates, empty collections, special characters
- **Parametrize** — `@pytest.mark.parametrize` for multiple values of the same rule
- **Match error messages** — `pytest.raises(ValueError, match="field_name")` not just `pytest.raises(ValueError)`

### Test depth by layer

- **Domain models** — full edge case coverage (these are the core validation rules)
- **Ports** — structural only (verify Protocol satisfaction)
- **Adapters** — heavy edge cases (empty files, missing files, malformed input, API errors, connection failures)
- **Domain services** — orchestration with mocked ports (cache hit/miss, error propagation, threshold checks)
- **HTTP routes** — status codes, error mapping, request/response shapes

---

## Tier 2: Integration Tests

**Directory:** `tests/integration/`
**Marker:** `@pytest.mark.integration`
**Run with:** `uv run pytest tests/integration/`

### Purpose
Verify that components connect correctly through the full pipeline. Uses the real FastAPI app via TestClient with a real PolarsIngestor and NullCache, but mocks the GroqMapper to avoid external API calls.

### What it catches that unit tests miss
- Import errors and circular dependencies
- Incorrect wiring in the composition root
- Response serialization issues (pydantic model_dump → JSON)
- Middleware and error handler ordering
- File upload/temp file lifecycle

### Test classes

| Class | Tests | What it covers |
|-------|-------|---------------|
| TestEndToEnd | 5 | Upload CSV → mapping → response shape, headers, confidence |
| TestEdgeCases | 3 | Single column, all unmapped, empty CSV |
| TestRowValidation | 3 | Valid rows, invalid rows with errors, invalid_records |
| TestConfidenceReportE2E | 2 | Report present, missing fields for partial mapping |
| TestStructuredErrorsE2E | 3 | File type 400, oversized 400, SLM 503 with error_code |
| TestAsyncUploadE2E | 3 | 202 + job_id, job completes, 404 nonexistent |
| TestSheetNamesE2E | 2 | CSV returns empty, invalid file rejected |
| TestFileValidationE2E | 4 | Parametrized rejection of pdf/json/png, CSV accepted |

---

## Tier 3: E2E Tests

**Directory:** `tests/e2e/`
**Marker:** `@pytest.mark.e2e`
**Run with:** `GROQ_API_KEY=... uv run pytest -m e2e`

### Purpose
Verify the real external API works with our code. Nothing is mocked. These catch issues that are invisible to mocked tests: model deprecation, API changes, prompt regressions, response format drift.

### Why they're separate
- **Cost** — each run makes a real Groq API call
- **Flakiness** — if Groq is down, tests fail regardless of code quality
- **Speed** — ~5 seconds per run vs <1 second for mocked tests
- **Secrets** — requires GROQ_API_KEY (not available in all environments)

### Skip mechanism
```python
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("GROQ_API_KEY"),
        reason="GROQ_API_KEY not set — skipping e2e tests",
    ),
]
```

### Test cases

| Test | What it verifies |
|------|-----------------|
| test_health | App starts and serves /health |
| test_upload_maps_all_target_fields | Real SLM maps Policy_ID, Gross_Premium, Currency from bordereaux headers |
| test_confidence_scores_are_reasonable | Confidence >= 0.5 for obvious mappings |
| test_row_validation_produces_valid_records | Parsed records validate against schema |
| test_confidence_report_present | Response includes min/avg confidence and missing fields |

---

## CI/CD Pipeline

### Workflow: CI (`ci.yml`)

Triggers on every PR targeting main and every push to main.

```
PR opened/updated
  ↓
quality job
  ├── Unit tests (376) → reports/unit.xml
  ├── Integration tests (25) → reports/integration.xml
  ├── mypy type check
  ├── ruff lint + format check
  ├── Hexagonal architecture linter (AST-based)
  ├── Upload JUnit XML artifacts (30-day retention)
  └── Publish test report (dorny/test-reporter → PR check annotations)
  ↓
boot-test job (PRs only, if src/ or Docker files changed)
  ├── docker compose up --build
  ├── curl /health with retries
  └── docker compose down
  ↓
security job
  ├── bandit static analysis
  └── pip-audit dependency CVE scan
  ↓
e2e job (push to main only)
  ├── Real Groq API tests (5) → reports/e2e.xml
  ├── Upload JUnit XML artifacts
  └── Publish e2e test report
```

### Workflow: CD (`cd.yml`)

Triggers after CI completes on main. Only runs if CI succeeded.

```
CI passes on main
  ↓
CD workflow (workflow_run trigger)
  ├── if: conclusion == 'success'
  ├── docker build
  ├── Tag with :latest and :sha
  └── Push to ghcr.io
```

### Why e2e runs after merge, not before

| Concern | PR (before merge) | Main (after merge) |
|---------|-------------------|-------------------|
| Code correctness | Unit + integration tests | Same |
| API compatibility | Not checked (mocked) | **E2E verifies real API** |
| Cost | Free (no API calls) | ~1 Groq call per merge |
| Blocking | Yes — gates the merge | No — fix forward if broken |
| Groq outage impact | None — PRs unblocked | E2E fails, CD still runs if quality passes |

E2E is a **post-merge validation**. It catches external changes (model deprecation, API drift) that affect main. If e2e fails, the code is still correct — the external dependency changed. Fix forward rather than blocking all PRs.

---

## Local Development

### Running tests

```bash
# All unit + integration tests (fast, no API key needed)
uv run pytest tests/unit/ tests/integration/

# Unit tests only
uv run pytest tests/unit/

# Integration tests only
uv run pytest tests/integration/

# E2E tests (requires GROQ_API_KEY in .env or environment)
uv run pytest -m e2e

# Everything except e2e
uv run pytest -m "not e2e"

# Specific test file
uv run pytest tests/unit/test_schema.py -v

# Specific test class
uv run pytest tests/unit/test_schema.py::TestRiskRecord -v
```

### Pre-commit checks (enforced by Claude Code hooks)

```bash
uv run mypy src/
uv run pytest -x -v tests/unit/
uv run ruff check src/
uv run ruff format --check src/
```

These run automatically before every `git commit` via `.claude/hooks/pre-commit.sh`. The commit is blocked if any check fails.

### Additional checks

```bash
# Hexagonal architecture boundary check
uv run python -m tools.hexagonal_linter

# Security scan
uv run bandit -r src/ -q
uv run pip-audit --ignore-vuln CVE-2026-4539
```

---

## Test Artifacts

### JUnit XML reports
- Generated by pytest `--junitxml=reports/{unit,integration,e2e}.xml`
- Uploaded as GitHub Actions artifacts with 30-day retention
- Rendered as PR check annotations by `dorny/test-reporter`

### Where to find results
1. **PR Checks tab** — "Test Results" check with pass/fail per test
2. **Actions tab** → workflow run → **Artifacts** section → download `test-results` zip
3. **Local** — `reports/` directory (gitignored)

---

## Adding New Tests

### Choosing the right tier

| Question | If yes → |
|----------|----------|
| Does it test a single class/function in isolation? | Unit test in `tests/unit/` |
| Does it test multiple components connected together? | Integration test in `tests/integration/` |
| Does it call a real external API? | E2E test in `tests/e2e/` with `@pytest.mark.e2e` |

### Test coverage validation process

Before writing tests for a new feature, run a coverage validation:

1. List planned tests
2. Check against testing rules (happy path, boundaries, invalid input, edge cases)
3. Check layer-specific depth requirements
4. Add missing tests before writing any code

This process is enforced by feedback memory and runs before every TDD loop.
