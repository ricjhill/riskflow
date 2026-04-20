# How to: Configure Scaling for Multiple Users

## Goal

Configure RiskFlow to handle 5 concurrent users with persistent job tracking, concurrent processing, and rate-limited SLM calls.

## Default setup (no changes needed)

If Redis is running (via Docker Compose), the scaling features activate automatically:

```bash
cp .env.example .env
# Edit GROQ_API_KEY
docker compose up -d
```

This gives you:
- RedisJobStore (persistent, cross-worker)
- Concurrent background processing via `asyncio.create_task`
- Groq API limited to 3 concurrent calls
- Multi-worker Uvicorn (4 workers)

## Customise concurrency limits

```bash
# Allow more concurrent Groq calls (default: 3)
SLM_CONCURRENCY=5

# Or disable the limit entirely
SLM_CONCURRENCY=0
```

With `--workers 4`, the effective limit is `SLM_CONCURRENCY × 4` (each worker has its own semaphore — default 12 concurrent Groq calls).

## Change the job store

```bash
# Use Redis (default when REDIS_URL is set)
JOB_STORE=redis

# Fall back to in-memory (no persistence, per-worker)
JOB_STORE=memory
```

`memory` is useful for development without Redis, or as a rollback if Redis causes issues.

## Change the async backend

```bash
# Concurrent processing (default)
ASYNC_BACKEND=tasks

# Sequential processing (rollback)
ASYNC_BACKEND=background
```

`background` uses FastAPI's `BackgroundTasks` — tasks run one at a time. Use this if concurrent processing causes issues.

## Adjust job TTL

```bash
# Jobs expire 24 hours after last status change (default)
JOB_TTL=86400

# Shorter TTL for development
JOB_TTL=3600
```

Each `save()` resets the TTL, so jobs that progress through PENDING → PROCESSING → COMPLETE stay alive.

## Rollback everything

To revert to pre-scaling behaviour:

```bash
JOB_STORE=memory
ASYNC_BACKEND=background
SLM_CONCURRENCY=0
```

No code changes, no rebuild — just restart.

## Known limitations

- `asyncio.Semaphore` and `asyncio.Lock` are per-process. With `--workers 4`, each worker has its own limits.
- `JOB_STORE=memory` with `--workers 4` means each worker has its own job dict — jobs created in one worker are invisible to the others.
- Redis connection pool is 10 per worker (default). With 4 workers, that's 40 connections to Redis.
