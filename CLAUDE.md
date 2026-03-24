# RiskFlow: Reinsurance Data Mapper — Agent Instructions

## Project Context
A DevOps-oriented tool to automate the mapping of messy reinsurance spreadsheets (Bordereaux) to a standardized schema using SLMs (Groq/Llama 3.1).

## Language-Specific Instructions
This project follows the **Python** conventions.
- **Language File:** `agent.py.md` (Refer to this for TDD workflow, checkpointing, error handling, and `uv`/`pip` specifics)
- **Primary Stack:** Python 3.12, FastAPI, Polars, Redis, Groq API

---

## Architecture: Hexagonal (Ports & Adapters)
The codebase is strictly organized into three zones. Dependencies only point inward.

```
entrypoint/          # main.py — wires FastAPI, Groq, and Polars together
domain/
  model/             # Reinsurance entities (Risk, Premium, Treaty)
  service/           # Mapping logic, SLM prompt construction
ports/               # Interfaces
  input/             # IngestorInterface (how data enters the domain)
  output/            # MapperInterface (SLM calls), RepoInterface (Redis)
adapters/            # Implementations
  http/              # FastAPI routes
  slm/               # Groq API implementation
  storage/           # Redis caching implementation
  parsers/           # Polars-based Excel/CSV readers
mocks/               # Generated mocks for ports
```

---

## Reinsurance Domain Rules
- **Target Schema:** All mapping must result in these fields: `Policy_ID`, `Inception_Date`, `Expiry_Date`, `Sum_Insured`, `Gross_Premium`, `Currency`.
- **Validation:**
  - Currencies must be ISO 4217 (USD, GBP, EUR, JPY).
  - Dates must be ISO 8601 (YYYY-MM-DD).
  - Financials (Sum_Insured, Gross_Premium) must be non-negative floats.
- **Context:** SLM prompts must emphasize that "GWP" usually means `Gross_Premium`.

---

## Permissions & Tools
- Use `polars` for all data manipulation (do not use `pandas`).
- Access Groq via the `openai` Python SDK (OpenAI-compatible).
- Use `pydantic` for data validation and schema enforcement.
- Do not modify `uv.lock` or `requirements.txt` manually.

---

## Git
- Default branch: `main`. Always use `main` when initializing repos or referencing the default branch.
- Create a feature branch before writing code. Use the format: `feature/<short-description>`.
- Do not commit directly to `main`.
---

## Infrastructure (Docker Compose)
- **API:** Runs on port `8000`.
- **Redis:** Runs on port `6379`.
- Environment variables (`GROQ_API_KEY`) are loaded only at `entrypoint/main.py`.
