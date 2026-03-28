# RiskFlow

Automates the mapping of messy reinsurance spreadsheets (Bordereaux) to a standardized schema using Small Language Models (Groq/Llama 3.1).

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker & Docker Compose (for Redis)

## Getting Started

```bash
# Install dependencies
uv sync

# Copy environment template and add your Groq API key
cp .env.example .env

# Start Redis
docker compose up -d redis

# Run the API
uv run uvicorn src.entrypoint.main:app --reload --port 8000
```

## Development

```bash
# Run tests
uv run pytest -x -v tests/unit/

# Type checking
uv run mypy src/

# Lint and format
uv run ruff check src/
uv run ruff format src/
```

## TDD Cycle

1. **Red** — Write a failing test in `tests/unit/`
2. **Green** — Implement the minimum code in `src/domain/` or `src/adapters/` to make it pass
3. **Check** — Run `uv run mypy src/` and `uv run ruff check src/`
4. **Commit** — If all pass, commit with a descriptive message

Claude Code hooks enforce this — they block any commit where mypy, pytest, ruff check, or ruff format fail. GitHub Actions CI provides the same checks on PRs and pushes to main.

## Architecture

Hexagonal (Ports & Adapters). Dependencies only point inward.

```mermaid
graph LR
    subgraph External
        Client([Client])
        Excel[(Excel/CSV)]
        Groq([Groq API])
        Redis[(Redis)]
    end

    subgraph Adapters
        HTTP[HTTP Adapter<br>FastAPI Routes]
        Parser[Parser Adapter<br>Polars Ingestor]
        SchemaLoader[Schema Loader<br>YAML Parser]
        SLM[SLM Adapter<br>Groq Mapper]
        Cache[Cache Adapter<br>Redis Client]
        CorrCache[Correction Cache<br>Redis Hash]
        JobStore[Job Store<br>In-Memory]
    end

    subgraph Ports
        IngestorPort{{IngestorPort}}
        MapperPort{{MapperPort}}
        CachePort{{CachePort}}
        CorrectionCachePort{{CorrectionCachePort}}
        JobStorePort{{JobStorePort}}
        SchemaLoaderPort{{SchemaLoaderPort}}
    end

    subgraph Domain
        Service[MappingService]
        Models[TargetSchema<br>ColumnMapping<br>MappingResult<br>ConfidenceReport<br>Correction]
        RecordFactory[record_factory<br>Dynamic pydantic models]
        Errors[Domain Errors]
    end

    Client -->|POST /upload| HTTP
    Client -->|POST /corrections| HTTP
    Client -->|POST /upload/async| HTTP
    Client -->|GET /jobs/id| HTTP
    Client -->|POST /sheets| HTTP
    HTTP --> Service
    Service --> IngestorPort
    Service --> MapperPort
    Service --> CachePort
    Service --> CorrectionCachePort
    Service --> RecordFactory
    Service --> Models
    IngestorPort -.-> Parser
    MapperPort -.-> SLM
    CachePort -.-> Cache
    CorrectionCachePort -.-> CorrCache
    JobStorePort -.-> JobStore
    SchemaLoaderPort -.-> SchemaLoader
    Parser --> Excel
    SLM --> Groq
    Cache --> Redis
    CorrCache --> Redis
```

**Data flow:** Upload → Parse headers → Check cache → (miss?) Check corrections → SLM maps uncorrected headers → Merge → Validate rows → Return results with confidence report

**Endpoints:**
- `POST /upload` — synchronous upload with optional `?sheet_name` and `?cedent_id`
- `POST /upload/async` — async upload, returns job ID for polling
- `GET /jobs/{id}` — poll async job status and result
- `POST /sheets` — list sheet names in an Excel file
- `POST /corrections` — submit human-verified mapping corrections
- `GET /health` — health check

```
src/
  entrypoint/        # FastAPI wiring (composition root)
  domain/            # Business logic, models, validation
  ports/             # Interfaces (Protocol-based)
  adapters/          # Implementations (HTTP, Groq, Redis, Polars)
```

## Target Schema

The default target schema (`schemas/default.yaml`) maps Bordereaux data to:

| Field | Type | Constraints |
|-------|------|------------|
| `Policy_ID` | String | Not empty |
| `Inception_Date` | Date | Required |
| `Expiry_Date` | Date | Must not precede Inception_Date |
| `Sum_Insured` | Float | Non-negative |
| `Gross_Premium` | Float | Non-negative |
| `Currency` | Currency | USD, GBP, EUR, JPY |

The schema is configurable via YAML. Custom schemas can define different fields, types, constraints, cross-field rules, and SLM hints. See `src/domain/model/target_schema.py` for the `TargetSchema` model.
