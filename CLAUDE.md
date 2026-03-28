# RiskFlow: Reinsurance Data Mapper — Agent Instructions

## Project Context
A DevOps-oriented tool to automate the mapping of messy reinsurance spreadsheets (Bordereaux) to a standardized schema using SLMs (Groq/Llama 3.1).

## Stack
Python 3.12, FastAPI, Polars, Redis, Groq API, `uv` for dependency management

---

## Architecture: Hexagonal (Ports & Adapters)
The codebase is strictly organized into three zones. Dependencies only point inward.

```
src/
  entrypoint/        # main.py — wires FastAPI, Groq, and Polars together
  domain/
    model/           # RiskRecord, ColumnMapping, MappingResult, ProcessingResult, errors
    service/         # MappingService — orchestrates mapping and row validation
  ports/
    input/           # IngestorPort (how data enters the domain)
    output/          # MapperPort (SLM calls), CachePort (Redis)
  adapters/
    http/            # FastAPI routes
    slm/             # Groq API implementation
    storage/         # Redis caching implementation
    parsers/         # Polars-based Excel/CSV readers
tests/
  unit/              # Domain and service tests — no I/O
  integration/       # E2E pipeline tests
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
- Load environment variables only in `src/entrypoint/main.py` using `os.environ` (fail fast, no defaults).

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
- Environment variables (`GROQ_API_KEY`) are loaded only in `src/entrypoint/main.py`.
