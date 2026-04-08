# RiskFlow: Reinsurance Data Mapper — Agent Instructions

## Project Context
A DevOps-oriented tool to automate the mapping of messy reinsurance spreadsheets (Bordereaux) to a standardized schema using SLMs (Groq/Llama 3.3).

## Stack
Python 3.12, FastAPI, Polars, Redis, Groq API, `uv` for dependency management

---

## Architecture: Hexagonal (Ports & Adapters)
The codebase is strictly organized into three zones. Dependencies only point inward.

```
src/
  entrypoint/        # main.py — wires FastAPI, Groq, Redis, and schema loader
  domain/
    model/           # TargetSchema, FieldDefinition, record_factory, ColumnMapping,
                     # MappingResult, ProcessingResult, ConfidenceReport,
                     # Correction, Job, RowError, DateOrderingRule, SLMHint, errors,
                     # MappingSession (interactive mapping workflow),
                     # date_format (column-level date format detection and parsing)
    service/         # MappingService — orchestrates mapping, corrections, and row validation
  ports/
    input/           # IngestorPort (how data enters the domain)
    output/          # MapperPort (SLM calls), CachePort (Redis),
                     # CorrectionCachePort, JobStorePort, SchemaLoaderPort,
                     # MappingSessionStorePort, SchemaStorePort
  adapters/
    http/            # FastAPI routes (/upload, /upload/async, /jobs, /sheets,
                     # /corrections, /schemas, /sessions),
                     # RequestIdMiddleware (request-scoped structlog context)
    slm/             # Groq API implementation
    storage/         # Redis cache, Redis correction cache, in-memory job store,
                     # Redis session store, Redis schema store
    parsers/         # Polars-based Excel/CSV readers, YAML schema loader
tests/
  unit/              # Domain and service tests — no I/O
  integration/       # Wiring tests — full pipeline with mocked SLM + testcontainers Redis
  e2e/               # Real Groq API tests — needs GROQ_API_KEY
  benchmark/         # Performance guardrails, pytest-benchmark suite, TTFB + memory tests
  contract/          # Consumer-driven contract tests for API response shapes
  load/              # Locust load tests (locustfile.py for manual, test_locust_ci.py for CI)
  fixtures/          # Sample bordereaux CSV for tests
schemas/
  standard_reinsurance.yaml  # Default 6-field reinsurance target schema
  marine_cargo.yaml          # 8-field marine cargo schema (demo + testing)
tools/
  export_openapi.py    # Export OpenAPI spec to openapi.json (no Redis/Groq needed)
  check_api_changes.py # Detect breaking vs non-breaking changes between two OpenAPI specs
  bump_version.py      # Semantic version bumping based on API change classification
  coverage_report.py   # Coverage measurement, baseline comparison, PR reporting
  hexagonal_linter.py  # AST-based architecture boundary checker
openapi.json           # Committed OpenAPI 3.1 spec — CI-enforced, auto-versioned
gui/
  app.py             # Streamlit dashboard (3 tabs: mapping, debugger, corrections)
  api_client.py      # Thin httpx wrapper — GUI talks to API via HTTP, not imports
  Dockerfile         # Separate image with dev deps (includes streamlit)
```

---

## Reinsurance Domain Rules
See `.claude/rules/reinsurance.md` — loads automatically when editing `src/domain/` or `src/adapters/slm/`.

---

## Permissions & Tools
- Use `polars` for all data manipulation (do not use `pandas`).
- Access Groq via the `openai` Python SDK (OpenAI-compatible).
- Use `pydantic` for data validation and schema enforcement.
- Do not modify `uv.lock` manually.

---

## Python Conventions
- Use `typing.Protocol` for port interfaces — not abstract base classes.
- Logger: `structlog` only — no stdlib `logging` or `loguru`. Pass via dependency injection.
- Define domain exceptions in `src/domain/model/errors.py`. Adapters map them to HTTP responses.
- Never leak infrastructure exceptions into the domain layer.
- Load environment variables only in `src/entrypoint/main.py` using `os.environ`. Required vars (like `GROQ_API_KEY`) should fail on first use; optional vars (`REDIS_URL`, `SCHEMA_PATH`, `DEFAULT_SCHEMA`) use sensible defaults.

---

## TDD Workflow
- Baseline: `uv run pytest -x -v tests/unit/`
- After green: `uv run mypy src/` then `uv run ruff check src/`
- Commit after every green cycle.

## Definition of Done
- `uv run mypy src/`
- `uv run pytest -x -v tests/unit/`
- `uv run ruff check src/`
- `uv run ruff format --check src/`

---

## Git
- Default branch: `main`. Always use `main` when initializing repos or referencing the default branch.
- Create a feature branch before writing code. Use the format: `feature/<short-description>`.
- Do not commit directly to `main`.
---

## Infrastructure (Docker Compose)
- **API:** Runs on port `8000`.
- **Redis:** Runs on port `6379`.
- **GUI:** Runs on port `8501` (Streamlit dashboard).
- Start everything: `docker compose up -d`
- Environment variables (`GROQ_API_KEY`) are loaded only in `src/entrypoint/main.py`.
