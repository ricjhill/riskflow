# How RiskFlow Scales to Multiple Users

## The problem

RiskFlow v0.2.0 ran as a single Uvicorn process with in-memory storage. Under concurrent users:
- Jobs were stored in a Python dict — lost on restart, invisible across workers
- Background tasks ran sequentially — 5 uploads took 25 seconds, not 5
- Groq API calls had no concurrency limit — risk of rate limiting
- Schema mutations could race on concurrent POST /schemas

## The solution (v0.3.0)

Five changes, each controlled by an environment variable for instant rollback:

### 1. RedisJobStore (`JOB_STORE=redis`)

Jobs are persisted in Redis with a configurable TTL. Each status transition (PENDING → PROCESSING → COMPLETE) saves to Redis and resets the TTL. Both Uvicorn workers share the same Redis, so jobs created in one worker are visible to the other.

Fallback: `JOB_STORE=memory` reverts to the in-process dict.

### 2. Concurrent background processing (`ASYNC_BACKEND=tasks`)

`asyncio.create_task()` fires background tasks concurrently within the event loop. Five uploads each taking 5 seconds complete in ~5 seconds total, not 25.

Fallback: `ASYNC_BACKEND=background` reverts to sequential `BackgroundTasks`.

### 3. Groq API semaphore (`SLM_CONCURRENCY=3`)

An `asyncio.Semaphore` limits concurrent Groq API calls. With 5 users uploading simultaneously, at most 3 calls hit Groq at once — the rest queue.

Fallback: `SLM_CONCURRENCY=0` removes the limit.

### 4. Schema registry lock

`asyncio.Lock` serialises schema create and delete operations. Prevents two concurrent `POST /schemas` with the same name from both succeeding.

### 5. Multi-worker Uvicorn (`--workers 2`)

Two Uvicorn workers handle concurrent HTTP requests. Each worker runs its own event loop, semaphore, and lock. Redis is the shared state layer.

## Per-process scope

`asyncio.Semaphore` and `asyncio.Lock` are per-process. With `--workers 2`:
- `SLM_CONCURRENCY=3` means 3 concurrent Groq calls per worker = 6 total
- The schema lock prevents races within a worker, not across workers (Redis is the authoritative source)

This is acceptable for 5 users. For larger scale, the roadmap's Phase 4 describes Redis-backed distributed rate limiting and locking.

## What we chose NOT to build

| Alternative | Why we didn't use it |
|-------------|---------------------|
| Celery task queue | Overkill for 5 users — adds broker, workers, monitoring infrastructure |
| Redis Streams | Event sourcing not needed at this scale |
| Distributed semaphore | Per-process semaphore is sufficient for 5 users with 2 workers |
| Kubernetes | Single Docker Compose stack is appropriate for a small team tool |

## How it's tested

| Layer | What's tested | How |
|-------|--------------|-----|
| Unit | Each component in isolation (mocked Redis) | ~844 pytest tests |
| Integration | RedisJobStore under 20-thread concurrency (real Redis) | testcontainers |
| Load | 5 Locust users against in-process server | Locust CI assertions |
| CI concurrency | 5 Locust users against Docker stack (multi-worker + Redis) | GitHub Actions job |

## Observability

Every scaling component emits structured log events. Set `LOG_LEVEL=DEBUG` to see infrastructure timing. See [Debug with Logging](../how-to/debug-with-logging.md) for details.
