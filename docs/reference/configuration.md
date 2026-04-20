# Configuration Reference

All environment variables are read in `src/entrypoint/main.py` — the only place where configuration happens.

## Required

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Groq API key for SLM header mapping. Get one at [console.groq.com](https://console.groq.com). Fails on first upload if missing (not at startup). |

## Optional — Infrastructure

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | None | Redis connection URL (e.g. `redis://localhost:6379`). When missing, NullCache is used (SLM called on every request, no job persistence). |
| `SCHEMA_PATH` | None | Path to a single YAML schema file. If set, only this schema is loaded (ignoring `schemas/` directory). |
| `DEFAULT_SCHEMA` | `standard_reinsurance` | Name of the default schema when multiple are loaded. Must match the `name` field in one of the YAML files. Falls back to the first loaded schema if the named one doesn't exist. |

## Optional — Scaling

These control the scaling features added in v0.3.0 (5-user baseline) and extended in v0.4.0 (Phase 4 — async Redis migration, 4 workers, tenacity retry on Groq 429). All have production-ready defaults — only change them for rollback or debugging.

| Variable | Default | Rollback | Description |
|----------|---------|----------|-------------|
| `JOB_STORE` | `redis` | `memory` | Which job store to use. `redis`: persistent across restarts, shared across workers. `memory`: in-process dict, lost on restart, per-worker. |
| `JOB_TTL` | `86400` | `3600` | Redis job expiry in seconds. Each save() resets the TTL. Default 24 hours. |
| `ASYNC_BACKEND` | `tasks` | `background` | How async uploads are processed. `tasks`: `asyncio.create_task()` for concurrent execution. `background`: FastAPI `BackgroundTasks` for sequential execution. |
| `SLM_CONCURRENCY` | `3` | `0` | Maximum concurrent Groq API calls via `asyncio.Semaphore`. `0` disables the limit. Per-process — with `--workers 4`, the effective limit is 4x this value (12 concurrent calls). |
| `LOG_LEVEL` | `INFO` | `DEBUG` | Root logger level. `DEBUG` surfaces infrastructure timing events (semaphore waits, Redis I/O). Invalid values fall back to `INFO`. `NOTSET` is treated as invalid. |

## Rollback

Every scaling variable can be changed without code changes or rebuilds:

```bash
# Local dev
JOB_STORE=memory uv run uvicorn src.entrypoint.main:app

# Docker Compose — add to .env or docker-compose.override.yml
JOB_STORE=memory
ASYNC_BACKEND=background
SLM_CONCURRENCY=0
LOG_LEVEL=DEBUG
```

Then restart (`docker compose up -d`).

## Docker Compose

Docker Compose overrides `REDIS_URL` to point to the Redis service:

```yaml
environment:
  - REDIS_URL=redis://redis:6379
```

All other variables come from `.env` (via `env_file: .env`).
