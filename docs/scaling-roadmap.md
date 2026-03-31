# RiskFlow: Architectural Scaling & TDD Roadmap

## Current State

RiskFlow is a well-structured hexagonal architecture monolith with:
- **456 unit tests** (all passing, ~7.5s single-threaded, ~6.5s with xdist)
- **Clean dependency direction**: domain → ports → adapters → entrypoint
- **Full async pipeline**: FastAPI → MappingService → Groq SLM
- **Graceful degradation**: Redis failures don't crash the system

This roadmap scales it to handle increased load while maintaining strict TDD.

---

## 1. Isolation Strategy: DI + Clean Architecture

### What We Already Have (Preserve This)

RiskFlow's hexagonal architecture is production-grade:

```
domain/model/     ← domain/service/     ← ports/      ← adapters/      ← entrypoint/
(pure types)        (business logic)      (protocols)    (implementations)  (wiring)
```

**Constructor injection** — no service locators, no globals:
```python
# entrypoint/main.py — the ONLY place adapters are constructed
service = MappingService(
    ingestor=ingestor,       # IngestorPort
    mapper=mapper,           # MapperPort
    cache=cache,             # CachePort
    correction_cache=corr,   # CorrectionCachePort
)
```

### Scaling: New Infrastructure Without Domain Changes

When adding Redis Streams, RabbitMQ, or a distributed database:

1. **Define a new port** in `src/ports/output/`:
   ```python
   # src/ports/output/queue.py
   class QueuePort(Protocol):
       async def enqueue(self, task: dict[str, Any]) -> str: ...
       async def dequeue(self) -> dict[str, Any] | None: ...
   ```

2. **Implement the adapter** in `src/adapters/`:
   ```python
   # src/adapters/messaging/rabbitmq.py
   class RabbitMQQueue:
       def __init__(self, connection: aio_pika.Connection) -> None: ...
       async def enqueue(self, task: dict[str, Any]) -> str: ...
   ```

3. **Wire in entrypoint** — domain service never knows:
   ```python
   # src/entrypoint/main.py
   queue = RabbitMQQueue(connection=amqp_conn)
   service = MappingService(..., queue=queue)
   ```

4. **Test with mocks** in unit tests, **real containers** in integration:
   ```python
   # Unit: fast, no Docker
   queue = AsyncMock(spec=QueuePort)

   # Integration: real RabbitMQ via testcontainers
   with RabbitMqContainer() as rabbit:
       queue = RabbitMQQueue(connection=rabbit.get_connection())
   ```

### Key Principle: The Domain Never Imports Infrastructure

The hexagonal linter (`tools/hexagonal_linter.py`) enforces this:
- `domain/` cannot import from `adapters/` or `entrypoint/`
- `ports/` cannot import from `adapters/`
- Violations fail CI

---

## 2. Handling Asynchronicity: TDD for Async Code

### Three Patterns (Implemented in `tests/unit/test_async_background_tasks.py`)

#### Pattern 1: Pure State Machine Testing
Test state transitions without async at all:
```python
def test_cannot_complete_pending_job() -> None:
    job = Job.create()   # PENDING
    with pytest.raises(ValueError):
        job.complete(result={})  # Can't skip PROCESSING
```

#### Pattern 2: Deterministic Async Mocks
`AsyncMock` makes coroutines complete immediately:
```python
@pytest.mark.asyncio
async def test_mapper_called(service, mapper):
    await service.process_file("test.csv")
    mapper.map_headers.assert_awaited_once()
    # No sleep(), no polling, no flakiness
```

#### Pattern 3: FastAPI TestClient Runs Background Tasks Synchronously
```python
def test_async_upload(client):
    resp = client.post("/upload/async", files={"file": csv_file})
    job_id = resp.json()["job_id"]

    # Background task ALREADY completed — TestClient is synchronous
    status = client.get(f"/jobs/{job_id}").json()
    assert status["status"] == "complete"
```

### Scaling to Celery/Task Queues

When moving from FastAPI `BackgroundTasks` to Celery:

1. **Define a `TaskRunnerPort`**:
   ```python
   class TaskRunnerPort(Protocol):
       def submit(self, task_fn: Callable, *args: Any) -> str: ...
       def get_result(self, task_id: str) -> Any | None: ...
   ```

2. **In tests**: `InMemoryTaskRunner` that executes synchronously
3. **In production**: `CeleryTaskRunner` that dispatches to workers
4. **Domain service unchanged** — it calls `task_runner.submit()`, doesn't know about Celery

---

## 3. Consumer-Driven Contract Testing

### Implemented in `tests/contract/test_api_contracts.py`

Contracts are defined as Python dataclasses — zero infrastructure:

```python
@dataclass(frozen=True)
class ResponseContract:
    status_code: int
    required_fields: frozenset[str]

UPLOAD_SUCCESS_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset({
        "mapping", "confidence_report", "valid_records",
        "invalid_records", "errors",
    }),
)
```

**Provider test** (does the API match?):
```python
def test_upload_matches_contract(client, tmp_path):
    resp = upload_csv(client, tmp_path)
    assert resp.status_code == UPLOAD_SUCCESS_CONTRACT.status_code
    for field in UPLOAD_SUCCESS_CONTRACT.required_fields:
        assert field in resp.json()
```

**Consumer test** (can the GUI parse it?):
```python
def test_consumer_parses_upload():
    response_body = { ... }  # Contracted shape
    mappings = response_body["mapping"]["mappings"]
    assert isinstance(mappings[0]["confidence"], float)
```

### Scaling to Pact

When splitting into microservices:

1. Export contracts to Pact JSON format
2. Run Pact broker (pactflow.io or self-hosted)
3. Provider verification runs in CI — breaks build if contract violated
4. Consumer tests generate Pact files checked into the broker

The Python dataclass contracts migrate to Pact with minimal changes.

---

## 4. The Test Pyramid at Scale

### Current Structure

```
                    ╱╲
                   ╱E2E╲          1 test   — real Groq API
                  ╱──────╲
                 ╱Integr. ╲       1 file   — full pipeline, mocked SLM
                ╱──────────╲
               ╱  Contract  ╲     11 tests — API shape verification
              ╱──────────────╲
             ╱   Guardrails   ╲   9 tests  — performance regression
            ╱──────────────────╲
           ╱      456 Unit      ╲ 456 tests — all dependencies mocked
          ╱──────────────────────╲
```

### Keeping CI Fast with pytest-xdist

**Parallel execution** splits tests across CPU cores:
```bash
# Auto-detect cores (4 workers on 4-core machine)
uv run pytest tests/unit/ -n auto --benchmark-disable

# Result: 456 tests in 6.5s (vs 7.5s single-threaded)
```

**Benchmark isolation** (pytest-benchmark conflicts with xdist):
```bash
# Benchmarks run single-process
uv run pytest tests/benchmark/ -p no:xdist --benchmark-only
```

### CI Pipeline Organization

```yaml
# Fast feedback (< 30s)
quality:
  - uv run pytest tests/unit/ -n auto --benchmark-disable
  - uv run pytest tests/contract/ -n auto
  - uv run mypy src/
  - uv run ruff check src/

# Medium feedback (1-2 min)
performance:
  - uv run pytest tests/benchmark/test_perf_guardrails.py
  - uv run pytest tests/benchmark/test_benchmarks.py --benchmark-json=results.json
  # Compare against baseline (fail if >20% regression)

# Slow feedback (requires Docker)
integration:
  - uv run pytest tests/integration/ -m "not container"
  - uv run pytest tests/integration/ -m container  # testcontainers

# On merge to main only
e2e:
  - uv run pytest tests/e2e/  # real Groq API

# Manual/scheduled
load:
  - uv run locust -f tests/load/locustfile.py --headless ...
```

### Tools Summary

| Tool | Purpose | When |
|------|---------|------|
| **pytest-xdist** | Parallel test execution | Every CI run |
| **pytest-benchmark** | Precise perf measurements | Every CI run (JSON output) |
| **testcontainers** | Real Docker services in tests | Integration stage |
| **Locust** | HTTP load testing | Pre-release / scheduled |

---

## 5. Performance Benchmarking as Part of TDD

### Baseline Measurements (2026-03-31)

| Operation | Mean | Min | Rounds | Budget |
|-----------|------|-----|--------|--------|
| Cache key (50 headers) | 70.3 μs | 60.9 μs | 4,366 | 50 ms |
| Cache key (200 headers) | 107.2 μs | 92.0 μs | 5,536 | — |
| Model build (cold) | 2,113.4 μs | 1,541.6 μs | 284 | 100 ms |
| Model build (cached) | 54.3 μs | 46.4 μs | 9,783 | 1 ms |
| Row validation (1 row) | 3.8 μs | 3.2 μs | 36,809 | — |
| Row validation (100 rows) | 347.8 μs | 298.2 μs | 2,508 | 500 ms |
| MappingResult (20 fields) | 14.6 μs | 11.6 μs | 32,708 | 50 ms |
| ConfidenceReport (50 maps) | 17.5 μs | 15.3 μs | 22,440 | — |
| Schema fingerprint | 46.5 μs | 42.5 μs | 9,222 | 10 ms |

**Key insight**: Row validation at 3.8 μs/row means 10,000 rows process in ~38ms.
The bottleneck is the SLM call (100-2000ms), not local computation.

### Tracking Regressions

```bash
# Save baseline
uv run pytest tests/benchmark/test_benchmarks.py \
    --benchmark-only --benchmark-json=benchmarks/baseline.json

# After changes, compare
uv run pytest tests/benchmark/test_benchmarks.py \
    --benchmark-only --benchmark-json=benchmarks/results.json

uv run pytest-benchmark compare benchmarks/baseline.json benchmarks/results.json
```

---

## 6. Refactoring for Performance: TDD Workflow

### Step-by-Step: Optimizing a Slow Function

**Example**: Suppose `_build_cache_key` becomes slow with 500+ headers.

#### Step 1: Write the guardrail test FIRST (Red if current code is slow)

```python
@pytest.mark.perf_guardrail
def test_500_headers_under_50ms():
    headers = [f"Column_{i}" for i in range(500)]
    with Timer() as t:
        service._build_cache_key(headers)
    assert t.elapsed_ms < 50
```

#### Step 2: Run it — GREEN means the budget is met

```
PASSED — 0.8ms (budget: 50ms)
```

#### Step 3: Write a scaling test to catch O(n²)

```python
def test_linear_scaling():
    t500 = measure(500)
    t1000 = measure(1000)
    assert t1000 / t500 < 4  # Allow noise, catch quadratic
```

#### Step 4: Refactor with confidence

Now you can refactor freely. If either guardrail goes red:
- The time budget test catches absolute regressions
- The scaling test catches algorithmic regressions

#### Step 5: Run benchmarks to measure the improvement

```bash
uv run pytest tests/benchmark/test_benchmarks.py \
    --benchmark-only --benchmark-compare=benchmarks/baseline.json
```

---

## 7. Mock vs. Reality: Test Case Example

### The Problem Mocks Hide

```python
# Unit test (mocked Redis) — PASSES
def test_cache_roundtrip_mock():
    client = MagicMock()
    client.get.return_value = mapping.model_dump_json().encode()
    cache = RedisCache(client=client)
    assert cache.get_mapping("key") == mapping
```

What if the real Redis returns `str` instead of `bytes`? The mock happily returns whatever you configure. The test passes, production breaks.

### The Solution: testcontainers

```python
# Integration test (real Redis) — catches real behavior
# See: tests/integration/test_redis_real.py

@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        yield container

def test_roundtrip_real(real_redis):
    cache = RedisCache(client=real_redis)
    cache.set_mapping("key", mapping, ttl=60)
    assert cache.get_mapping("key") == mapping

def test_ttl_actually_applied(real_redis):
    cache = RedisCache(client=real_redis)
    cache.set_mapping("key", mapping, ttl=300)
    ttl = real_redis.ttl("riskflow:mapping:key")
    assert 0 < ttl <= 300  # Mocks can't verify this
```

### When to Use Each

| Scenario | Mock | Real Container |
|----------|------|----------------|
| TDD red-green cycle | Yes | No |
| Pre-commit CI | Yes | No |
| Integration CI stage | No | Yes |
| Validating serialization | No | Yes |
| Testing TTL/expiry | No | Yes |
| Testing connection pooling | No | Yes |

---

## 8. Implementation Phases

### Phase 1: Observability (Now — implemented)
- [x] pytest-benchmark suite with JSON output
- [x] Performance guardrail tests (time budgets)
- [x] Baseline measurements recorded
- [x] pytest-xdist for parallel CI

### Phase 2: Contract Confidence (Now — implemented)
- [x] Consumer-driven contract tests
- [x] Mock vs. Reality tests with testcontainers
- [x] Locust load test skeleton

### Phase 3: Background Processing (Next)
- [ ] Replace `BackgroundTasks` with a `TaskRunnerPort`
- [ ] Implement `CeleryTaskRunner` adapter
- [ ] Add Redis Streams adapter for event sourcing
- [ ] Job persistence: replace `InMemoryJobStore` with Redis/Postgres

### Phase 4: Horizontal Scaling
- [ ] Stateless API (move all state to Redis/DB)
- [ ] Kubernetes-ready health checks (/health, /ready, /live)
- [ ] Rate limiting port + Redis adapter
- [ ] Circuit breaker for SLM calls (resilience4j pattern)

### Phase 5: Multi-Service Split (If/When Needed)
- [ ] Extract SLM mapping to a separate service
- [ ] Pact broker for inter-service contracts
- [ ] Distributed tracing (OpenTelemetry)
- [ ] API gateway for routing

---

## Running Everything

```bash
# Fast TDD cycle (< 10s)
uv run pytest tests/unit/ -x -v --benchmark-disable

# Full quality gate (< 30s)
uv run pytest tests/unit/ -n auto --benchmark-disable && \
uv run pytest tests/contract/ && \
uv run mypy src/ && \
uv run ruff check src/

# Performance check
uv run pytest tests/benchmark/test_perf_guardrails.py -v
uv run pytest tests/benchmark/test_benchmarks.py --benchmark-only --benchmark-json=benchmarks/results.json

# Integration (requires Docker)
uv run pytest tests/integration/ -v

# Load test (requires running server)
uv run locust -f tests/load/locustfile.py --host http://localhost:8000 --headless --users 10 --spawn-rate 2 --run-time 30s
```
