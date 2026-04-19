# How to: Debug with Structured Logging

## Goal

Use RiskFlow's structured JSON logs to diagnose performance issues, trace requests, and identify concurrency bottlenecks.

## Enable DEBUG logging

```bash
# Local dev
LOG_LEVEL=DEBUG uv run uvicorn src.entrypoint.main:app

# Docker Compose — add to .env
LOG_LEVEL=DEBUG
docker compose up -d
```

DEBUG surfaces infrastructure timing events that are hidden at INFO level.

## Log events

Every log line is JSON with `worker_pid`, `request_id` (when in a request), `level`, and `timestamp` automatically included.

### Always visible (INFO)

| Event | Fields | What it means |
|-------|--------|--------------|
| `file_received` | `filename`, `sheet_name`, `schema` | Upload accepted |
| `mapping_complete` | `filename`, `duration_ms`, `mapped_count` | SLM mapping finished |
| `cache_lookup` | `result` (hit/miss), `cache_key`, `duration_ms` | Cache checked |
| `slm_call` | `duration_ms`, `model`, `headers_count` | Groq API called |
| `task_started` | `job_id`, `filename` | Background task began |
| `task_completed` | `job_id`, `duration_ms`, `status` | Background task finished |
| `app_configured` | `cache_type`, `correction_cache_type`, `schema_count`, `job_store_type` | Startup config |
| `job_store_save_failed` | `job_id`, `error` | Redis save failed |
| `job_store_get_failed` | `job_id`, `error` | Redis get failed |
| `job_store_list_failed` | `error` | Redis list failed |

### DEBUG only (LOG_LEVEL=DEBUG)

| Event | Fields | What it means |
|-------|--------|--------------|
| `semaphore_wait` | `duration_ms`, `model` | Time waiting for Groq semaphore |
| `job_store_save` | `job_id`, `duration_ms` | Redis SETEX timing |
| `job_store_list` | `count`, `duration_ms` | Redis SCAN+GET timing |

## Query logs with jq

Install jq: `sudo apt install jq` (Ubuntu) or `brew install jq` (macOS).

```bash
# All errors
docker compose logs api --no-log-prefix | jq 'select(.level == "error")'

# Trace one request end-to-end
docker compose logs api --no-log-prefix | jq 'select(.request_id == "a1b2c3d4")'

# Filter to one worker
docker compose logs api --no-log-prefix | jq 'select(.worker_pid == 42)'

# Slow SLM calls (over 2 seconds)
docker compose logs api --no-log-prefix | jq 'select(.event == "slm_call" and .duration_ms > 2000)'

# Failed background tasks
docker compose logs api --no-log-prefix | jq 'select(.event == "task_completed" and .status == "failed")'

# Semaphore contention (DEBUG only)
docker compose logs api --no-log-prefix | jq 'select(.event == "semaphore_wait" and .duration_ms > 100)'
```

## Diagnosis playbook

| Symptom | What to check | Action |
|---------|--------------|--------|
| Requests slow | Filter `slm_call` by `duration_ms` | Groq latency. Reduce `SLM_CONCURRENCY` to lower contention. |
| Jobs stuck in pending | Filter `task_started` and `task_completed` | Are tasks starting? If not, rollback: `ASYNC_BACKEND=background` |
| Redis errors in logs | Filter `level == "error"` | Redis down. Rollback: `JOB_STORE=memory` |
| One worker overloaded | Group by `worker_pid` | Check load balancing. Uvicorn round-robins by default. |
| Semaphore bottleneck | Enable DEBUG, filter `semaphore_wait` | Increase `SLM_CONCURRENCY` or reduce concurrent users. |

## Log persistence

| Environment | How | Retention |
|-------------|-----|-----------|
| Docker Compose | `json-file` driver, 10MB rotation, 3 files | ~30MB per container |
| Local dev | `tee "logs/riskflow-$(date +%Y%m%d-%H%M%S).log"` | Manual cleanup |
| CI | GitHub Actions step logs + artifact upload | 30 days |
