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

## Architecture

Hexagonal (Ports & Adapters). Dependencies only point inward.

```
src/
  entrypoint/        # FastAPI wiring
  domain/            # Business logic, models, validation
  ports/             # Interfaces (Protocol-based)
  adapters/          # Implementations (HTTP, Groq, Redis, Polars)
```

## Target Schema

All Bordereaux data is mapped to:

| Field | Format |
|-------|--------|
| `Policy_ID` | String |
| `Inception_Date` | ISO 8601 (YYYY-MM-DD) |
| `Expiry_Date` | ISO 8601 (YYYY-MM-DD) |
| `Sum_Insured` | Non-negative float |
| `Gross_Premium` | Non-negative float |
| `Currency` | ISO 4217 (USD, GBP, EUR, JPY) |
