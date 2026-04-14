# Scaling & Performance Testing Infrastructure

**RiskFlow Engineering Session — 30 March 2026**
**Duration: 45 minutes**

---

## Agenda

| # | Section | Time |
|---|---------|------|
| 1 | Why Performance Testing Now? | 3 min |
| 2 | The Testing Pyramid for Performance | 3 min |
| 3 | Microbenchmarks: pytest-benchmark Suite | 4 min |
| 4 | Performance Guardrails: TDD-Friendly Regression Detection | 5 min |
| 5 | Endpoint TTFB Guardrails | 4 min |
| 6 | Memory Endurance Tests | 4 min |
| 7 | Contract Tests: Poor Man's Pact | 3 min |
| 8 | Redis Concurrency: Real Connection Pool Under Load | 3 min |
| 9 | Load Testing: Locust in CI | 4 min |
| 10 | CI Integration & Results | 2 min |
| 11 | Architecture for Scaling | 10 min |

---

## 1. Why Performance Testing Now?

### The Gemini Review

An external review (Gemini) scored RiskFlow's test infrastructure:

| Dimension | Score | Verdict |
|-----------|-------|---------|
| TDD quality | 8/10 | Strong |
| Correctness | 8/10 | Strong |
| **Throughput** | **2/10** | No measurement |
| **Latency** | **3/10** | No TTFB tests |
| **Resources** | **2/10** | No memory checks |

**The diagnosis:** RiskFlow had excellent correctness tests but zero production-like performance measurement. Fast enough on a developer laptop is not fast enough under concurrent load.

### What We Built

In one session, we shipped **7 new test files** covering:

- 9 microbenchmarks with statistical precision
- 9 time-budget guardrails for hot-path functions
- 5 endpoint TTFB (Time To First Byte) tests
- 5 memory endurance tests with tracemalloc + RSS tracking
- 11 consumer-driven contract tests
- 4 Redis connection pool concurrency tests
- 1 Locust-based load test running in CI

**Total: 44 new tests, ~1700 lines of test code.**

---

## 2. The Testing Pyramid for Performance

### Traditional Testing Pyramid

```
        /\
       /  \       E2E (Groq API, real Redis)
      /    \
     /------\     Integration (mocked SLM, real Redis)
    /        \
   /----------\   Unit (everything mocked)
  /            \
 /--------------\ Benchmarks & Guardrails (new!)
```

### The Performance Layer

We added a new layer at the base — performance tests that run on every PR:

```
┌─────────────────────────────────────────────────┐
│  Microbenchmarks    — precise measurement        │
│  Guardrails         — time budget assertions     │
│  TTFB tests         — full HTTP lifecycle        │
│  Memory endurance   — heap growth detection      │
│  Contract tests     — API shape stability        │
│  Concurrency tests  — thread-safe Redis ops      │
│  Load tests         — Locust in CI               │
└─────────────────────────────────────────────────┘
```

### Key Principle: Guardrails, Not Goals

Budgets are intentionally **10-50x typical** to avoid CI flakiness:

| Function | Typical | Budget | Catches |
|----------|---------|--------|---------|
| Cache key (500 headers) | <1ms | 50ms | O(n^2) string building |
| Model build (cold) | ~5ms | 100ms | Excessive reflection |
| 1000 row validations | ~80ms | 500ms | Per-row I/O leaks |
| /health TTFB | ~2ms | 50ms | Blocking middleware |
| /upload TTFB | ~30ms | 500ms | Full-file re-read |

The goal is not to optimize — it's to **prevent regressions**.

---

## 3. Microbenchmarks: pytest-benchmark Suite

### File: `tests/benchmark/test_benchmarks.py`

9 precise measurements using pytest-benchmark, grouped by function:

```
$ uv run pytest tests/benchmark/test_benchmarks.py --benchmark-only

----- benchmark 'cache-key': 2 tests -----
Name                        Mean        StdDev      Rounds
test_cache_key_50_headers   0.0234ms    0.0012ms    1000
test_cache_key_200_headers  0.0891ms    0.0034ms    1000

----- benchmark 'model-build': 2 tests -----
test_model_build_cold       4.1230ms    0.2100ms    100
test_model_build_warm       0.0003ms    0.0001ms    10000

----- benchmark 'row-validation': 2 tests -----
test_validate_single_row    0.0312ms    0.0018ms    1000
test_validate_100_rows      3.2100ms    0.1500ms    100
```

### How It Integrates with TDD

```
1. Before refactoring:
   $ uv run pytest tests/benchmark/ --benchmark-json=benchmarks/baseline.json

2. After refactoring:
   $ uv run pytest tests/benchmark/ --benchmark-json=benchmarks/results.json

3. Compare:
   $ uv run pytest-benchmark compare benchmarks/baseline.json benchmarks/results.json
```

If any function regressed >10%, investigate before merging.

### Benchmark Groups

| Group | Tests | What It Measures |
|-------|-------|-----------------|
| cache-key | 2 | SHA-256 of sorted headers + schema fingerprint |
| model-build | 2 | Cold (cache cleared) vs warm (LRU hit) Pydantic model generation |
| row-validation | 2 | Single row and batch of 100 rows through `model_validate` |
| mapping-result | 1 | MappingResult construction with 20 fields + duplicate check |
| confidence-report | 1 | ConfidenceReport aggregation over 50 mappings |
| fingerprint | 1 | Schema fingerprint computation (blake2b) |

---

## 4. Performance Guardrails: TDD-Friendly Regression Detection

### File: `tests/benchmark/test_perf_guardrails.py`

Unlike microbenchmarks (which measure), guardrails **assert**:

```python
@pytest.mark.perf_guardrail
class TestCacheKeyPerformance:

    def test_500_headers_under_50ms(self):
        headers = [f"Column_{i}" for i in range(500)]
        with Timer() as t:
            self._build_cache_key(headers, DEFAULT_TARGET_SCHEMA)
        assert t.elapsed_ms < 50, f"Cache key took {t.elapsed_ms:.1f}ms (budget: 50ms)"
```

### The Timer Utility

Shared across all guardrail files via `tests/benchmark/conftest.py`:

```python
class Timer:
    """Context manager that measures wall-clock time in milliseconds."""
    def __enter__(self):
        self._start = time.perf_counter()
        return self
    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
```

### Linear Scaling Detection

The most valuable guardrail pattern — catches O(n^2) regressions:

```python
def test_1000_headers_scales_linearly(self):
    """1000 headers should not take more than ~3x the time of 500."""
    t500 = time(build_cache_key, 500_headers)
    t1000 = time(build_cache_key, 1000_headers)

    ratio = t1000 / t500
    assert ratio < 4  # O(n^2) would show >10x
```

### 9 Guardrail Tests

| Class | Tests | Budget |
|-------|-------|--------|
| TestCacheKeyPerformance | 2 | 50ms for 500 headers, linear scaling |
| TestRecordModelBuildPerformance | 2 | 100ms cold, 1ms cached |
| TestRowValidationThroughput | 2 | 500ms for 1000 rows, linear scaling |
| TestMappingResultPerformance | 1 | 50ms for 100 mappings |
| TestIngestorPerformance | 1 | 500ms for 10k-row CSV headers |
| TestSchemaFingerprintPerformance | 1 | 10ms per call |

---

## 5. Endpoint TTFB Guardrails

### File: `tests/benchmark/test_endpoint_guardrails.py`

Measures the full HTTP request lifecycle through FastAPI's TestClient:

```
Client → ASGI routing → middleware → file parsing →
  Pydantic validation → response serialization → Client
```

SLM mapper is mocked — we measure everything EXCEPT the external API call.

### 5 Endpoint Tests

| Endpoint | Budget | What It Covers |
|----------|--------|----------------|
| GET /health | 50ms | Pure ASGI baseline — zero business logic |
| GET /schemas | 50ms | In-memory dict lookup |
| POST /upload | 500ms | Real CSV parsing + mocked SLM + 50-row validation |
| POST /upload/async | 200ms | Enqueue only — BackgroundTasks.add_task patched to no-op |
| GET /jobs/{id} | 50ms | In-memory job store lookup |

### The Warm-Up Pattern

```python
def test_health_under_50ms(self, client):
    # First request initializes ASGI middleware
    client.get("/health")

    # Second request is the timed measurement
    with Timer() as t:
        resp = client.get("/health")
    assert t.elapsed_ms < 50
```

The warm-up request prevents misleading results from one-time ASGI initialization.

### Async Enqueue Isolation

```python
def test_upload_async_enqueue_under_200ms(self, client, tmp_path):
    """Measures enqueue time only — not background task execution."""
    with patch("src.adapters.http.routes.BackgroundTasks.add_task"):
        with Timer() as t:
            resp = client.post("/upload/async", files={...})

    assert resp.status_code == 202
    assert t.elapsed_ms < 200
```

TestClient normally runs BackgroundTasks synchronously, which would inflate the measurement. Patching `add_task` to a no-op isolates the enqueue path.

---

## 6. Memory Endurance Tests

### File: `tests/benchmark/test_memory_endurance.py`

Detects heap growth under sustained load using two measurement strategies:

### Strategy 1: tracemalloc (Python Allocations)

```python
def _tracemalloc_delta(func):
    gc.collect()
    tracemalloc.start()
    before = tracemalloc.take_snapshot()

    func()

    gc.collect()
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    stats = after.compare_to(before, "lineno")
    growth = sum(s.size_diff for s in stats if s.size_diff > 0)
    return growth
```

### Strategy 2: VmRSS (Native/Rust Allocations)

tracemalloc cannot see allocations from Pydantic-core (Rust) or Polars (Rust). For those, we read `/proc/self/status`:

```python
def _read_vmrss_kib():
    """Read current VmRSS from /proc/self/status in KiB.

    Unlike resource.getrusage().ru_maxrss which reports peak RSS
    (monotonically increasing), VmRSS reports current RSS and
    can decrease after GC.
    """
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0
```

### 5 Memory Tests

| Test | Operations | Budget | Catches |
|------|-----------|--------|---------|
| Row validation | 1000 rows | 10 MiB | Accumulating ValidationError objects |
| Cache key | 1000 computations | 5 MiB | String accumulation in sort/join |
| Dynamic model build | 100 cold builds | 50 MiB | LRU cache growing beyond maxsize |
| MappingResult | 1000 constructions | 10 MiB | Reference retention in global lists |
| RSS stability | 5000 validations | 50 MiB | Native memory leaks (Pydantic-core Rust, Polars) |

---

## 7. Contract Tests: Poor Man's Pact

### File: `tests/contract/test_api_contracts.py`

Consumer-driven contract tests catch API shape breakage before deployment.

### The Problem They Solve

```
GUI (consumer) → HTTP → FastAPI API (provider)

If someone changes the /upload response shape, the GUI breaks.
Contract tests catch this BEFORE deployment.
```

### Contract Definition

```python
@dataclass(frozen=True)
class ResponseContract:
    status_code: int
    required_fields: frozenset[str]
    optional_fields: frozenset[str] = frozenset()

UPLOAD_SUCCESS_CONTRACT = ResponseContract(
    status_code=200,
    required_fields=frozenset({
        "mapping", "confidence_report",
        "valid_records", "invalid_records", "errors",
    }),
)
```

### Provider Tests (8 tests)

Verify the actual API matches the contract:

```python
def test_upload_success_matches_contract(self, client, csv_path):
    resp = client.post("/upload", files={...})
    assert resp.status_code == UPLOAD_SUCCESS_CONTRACT.status_code
    body = resp.json()
    for field in UPLOAD_SUCCESS_CONTRACT.required_fields:
        assert field in body, f"Missing required field: {field}"
```

### Consumer Tests (3 tests)

Verify the consumer code can parse the contracted shapes:

```python
def test_consumer_parses_upload_response(self):
    """Simulate GUI parsing the upload response shape."""
    fake_response = {
        "mapping": {"mappings": [...], "unmapped_headers": []},
        "confidence_report": {"min_confidence": 0.9, ...},
        "valid_records": [...],
        "invalid_records": [],
        "errors": [],
    }
    # Consumer code should not crash on this shape
    mappings = fake_response["mapping"]["mappings"]
    assert isinstance(mappings, list)
```

### Migration Path

This is "poor man's Pact" — zero infrastructure. When splitting into microservices, generate Pact JSON from these dataclasses.

---

## 8. Redis Concurrency: Real Connection Pool Under Load

### File: `tests/integration/test_redis_concurrency.py`

Uses testcontainers for a real Redis 7 instance with 20 concurrent threads.

### Why Not Just Mock Redis?

The mock tests pass, but they can't catch:
- Connection pool exhaustion
- Thread-safety issues in redis-py
- TTL behavior under concurrent writes
- Data integrity across threads

### 4 Concurrency Tests

```python
WORKERS = 20
OPS_PER_WORKER = 50
```

| Test | Workers | Asserts |
|------|---------|---------|
| Concurrent writes | 20 threads x 50 writes | Zero errors, all 1000 keys present |
| Concurrent reads after writes | 20 threads x 50 reads | Every read returns correct value |
| Mixed operations | 20 threads (cache + corrections) | Data integrity, no cross-contamination |
| Pool exhaustion | 20 threads, 10-connection pool | No ConnectionError — redis-py queues waiters |

### Pool Exhaustion Test

The most interesting test — more threads than connections:

```python
def test_pool_exhaustion_handled(self, redis_container):
    """20 threads, 10-connection pool — verifies redis-py queues
    waiters correctly without ConnectionError."""
    pool = redis_lib.ConnectionPool(
        host=host, port=port, max_connections=10
    )
    client = redis_lib.Redis(connection_pool=pool)
    cache = RedisCache(client=client)

    # 20 threads all trying to write simultaneously
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(write_50_keys, cache) for _ in range(20)]
    errors = [f for f in futures if f.exception()]
    assert len(errors) == 0  # redis-py queues, doesn't crash
```

---

## 9. Load Testing: Locust in CI

### File: `tests/load/test_locust_ci.py`

A real HTTP load test that runs in CI on every PR.

### Architecture

```
pytest test function
    │
    ├── 1. Build FastAPI app (real Polars, mocked SLM)
    ├── 2. Start uvicorn on random port (daemon thread)
    ├── 3. Write a minimal Locust user class to temp file
    ├── 4. Run Locust via subprocess (avoids gevent conflicts)
    │       └── 5 users, 15 seconds, mixed workload
    ├── 5. Parse Locust CSV stats output
    └── 6. Assert thresholds
```

### The Locust User

```python
class CIUser(HttpUser):
    wait_time = between(0.1, 0.3)

    @task(5)    # 5x weight — most requests
    def health(self):
        self.client.get("/health")

    @task(2)    # 2x weight
    def schemas(self):
        self.client.get("/schemas")

    @task(1)    # 1x weight — least frequent
    def upload(self):
        self.client.post("/upload",
            files={"file": ("test.csv", self._csv, "text/csv")})
```

### Thresholds

| Metric | Threshold | What It Catches |
|--------|-----------|-----------------|
| Error rate | < 1% | Crashes under concurrent load |
| Avg response time | < 5000ms | Catastrophic regressions |
| P95 response time | < 5000ms | Tail latency explosions |
| /health P95 | < 100ms | Middleware blocking |
| /schemas P95 | < 100ms | In-memory lookup degradation |

### Why Subprocess?

Locust uses gevent internally. Running it in-process would require `monkey.patch_all()`, which conflicts with pytest-asyncio. Subprocess isolates the gevent event loop entirely.

---

## 10. CI Integration & Results

### CI Workflow Changes

```yaml
# .github/workflows/ci.yml — quality job
- name: Run unit, contract, and guardrail tests
  run: |
    uv run pytest tests/unit/ tests/contract/ tests/benchmark/ \
      -p no:xdist --benchmark-disable -x -v

- name: Load test
  run: |
    uv run pytest tests/load/test_locust_ci.py -v --timeout=120
```

### What Runs on Every PR

| Suite | Tests | Time | Runner |
|-------|-------|------|--------|
| Unit | 483 | ~4s | ubuntu-latest |
| Contract | 11 | ~1s | ubuntu-latest |
| Guardrails | 9 | ~2s | ubuntu-latest |
| TTFB | 5 | ~3s | ubuntu-latest |
| Memory | 5 | ~5s | ubuntu-latest |
| Load (Locust) | 1 | ~17s | ubuntu-latest |
| **Total** | **514** | **~32s** | |

### What Requires Docker (Optional)

| Suite | Tests | Requires |
|-------|-------|----------|
| Redis real | 6 | testcontainers |
| Redis concurrency | 4 | testcontainers |
| **Total** | **10** | Docker daemon |

### Final Test Count After This Session

```
Before:  456 tests (unit + integration)
After:   500 tests (unit + contract + guardrails + TTFB + memory + load)
Added:   44 new tests across 7 files
```

---

## Summary: The Performance Testing Stack

```
┌────────────────────────────────────────────────────────────────┐
│                      Load Tests (Locust)                       │
│  5 users, 15s, mixed workload, error rate + P95 assertions     │
├────────────────────────────────────────────────────────────────┤
│                  Concurrency Tests (Redis)                     │
│  20 threads, real Redis, pool exhaustion, data integrity       │
├────────────────────────────────────────────────────────────────┤
│                  Contract Tests (API shapes)                   │
│  Provider + consumer verification, frozen dataclass contracts  │
├────────────────────────────────────────────────────────────────┤
│                Memory Endurance (tracemalloc + RSS)             │
│  1000-5000 ops, heap growth budgets, native leak detection     │
├────────────────────────────────────────────────────────────────┤
│              Endpoint TTFB Guardrails (TestClient)              │
│  Full HTTP lifecycle, warm-up pattern, async isolation          │
├────────────────────────────────────────────────────────────────┤
│              Performance Guardrails (Timer + assert)            │
│  Time budgets, linear scaling checks, 10-50x headroom          │
├────────────────────────────────────────────────────────────────┤
│              Microbenchmarks (pytest-benchmark)                 │
│  Statistical precision, baseline comparison, trend tracking    │
└────────────────────────────────────────────────────────────────┘
```

Every layer runs in CI. No production infrastructure required. No flakiness. Catches regressions before they ship.

---

## 11. Architecture for Scaling

Performance tests are only useful if the architecture can actually scale. This section covers how RiskFlow is designed to go from a single laptop to multiple containers behind a load balancer — without changing a single line of domain code.

### Hexagonal Architecture: The Foundation

Dependencies point **inward only**. No layer may import from a layer above it.

```
┌─────────────────────────────────────────────────────────────┐
│  entrypoint/main.py                                         │
│  Reads env vars, wires adapters, creates FastAPI app        │
├─────────────────────────────────────────────────────────────┤
│  adapters/                                                  │
│  http/routes.py  slm/mapper.py  storage/cache.py            │
│  parsers/ingestor.py  parsers/schema_loader.py              │
├─────────────────────────────────────────────────────────────┤
│  ports/                                                     │
│  CachePort  MapperPort  IngestorPort  JobStorePort          │
│  CorrectionCachePort  SchemaLoaderPort                      │
├─────────────────────────────────────────────────────────────┤
│  domain/                                                    │
│  model/ (TargetSchema, RiskRecord, Job, ColumnMapping...)   │
│  service/ (MappingService — orchestrates everything)        │
└─────────────────────────────────────────────────────────────┘
```

**Why this matters for scaling:** You can swap any adapter (Redis for Memcached, Groq for local Ollama, in-memory job store for Celery) without touching domain logic. The domain never knows — or cares — what infrastructure it runs on.

### Ports: The Scaling Contracts

Every external dependency is accessed through a `typing.Protocol`:

```python
# src/ports/output/repo.py
class CachePort(Protocol):
    def get_mapping(self, cache_key: str) -> MappingResult | None: ...
    def set_mapping(self, cache_key: str, result: MappingResult) -> None: ...
```

Two implementations exist today:

| Port | Production Adapter | Fallback Adapter |
|------|-------------------|-----------------|
| CachePort | RedisCache | NullCache |
| CorrectionCachePort | RedisCorrectionCache | NullCorrectionCache |
| JobStorePort | InMemoryJobStore | (future: RedisJobStore) |
| MapperPort | GroqMapper | (mock in tests) |
| SchemaLoaderPort | YamlSchemaLoader | — |
| IngestorPort | PolarsIngestor | — |

The NullCache/NullCorrectionCache pattern means the API works **without Redis** — it just re-calls the SLM on every request. Useful for local dev and single-instance deployments.

### Dependency Injection: One Wiring Point

All adapter instantiation happens in **one file** — `src/entrypoint/main.py`:

```python
# Environment selects adapters at startup
redis_client = _create_redis_client()      # REDIS_URL set? → Redis. Otherwise → None
cache = _create_cache(redis_client)        # Redis client? → RedisCache. Otherwise → NullCache
correction_cache = _create_correction_cache(redis_client)

# Each schema gets its own MappingService with a dedicated SLM prompt
for name, schema in schemas.items():
    mapper = GroqMapper(client=groq_client, schema=schema)
    schema_registry[name] = MappingService(
        ingestor=ingestor,
        mapper=mapper,
        cache=cache,
        schema=schema,
        correction_cache=correction_cache,
    )
```

**Scaling implication:** To add a Celery task runner, you write a `CeleryTaskRunner` adapter, wire it in `main.py`, and nothing else changes.

### Stateless API Design

The API container holds **zero state that prevents horizontal scaling**:

| Aspect | Current Design | Scaling Implication |
|--------|---------------|-------------------|
| Mapping cache | Redis (shared) | All instances share cache hits |
| Correction cache | Redis (shared) | Corrections visible to all instances |
| Schema registry | Loaded from YAML at startup | Identical across instances |
| Temp files | Created per-request, deleted after | No cross-request state |
| Job store | In-memory (single instance) | **Bottleneck** — replace with Redis |

Everything except the job store is already multi-instance safe. The job store is the documented next step.

### Schema-Aware Cache Keys

Cache keys include the **schema fingerprint** so different schemas never collide:

```python
def _build_cache_key(self, headers: list[str]) -> str:
    normalized = "|".join(sorted(h.lower().strip() for h in headers))
    key_input = f"{self._schema.fingerprint}:{normalized}"
    return hashlib.sha256(key_input.encode()).hexdigest()
```

The fingerprint is a blake2b hash of schema fields, constraints, and rules — **excluding the schema name**. Two schemas with identical fields but different names share a cache entry. Change a field's type or add a constraint, and the fingerprint changes, invalidating stale entries automatically.

### Schema Registry: Multi-Schema Routing

The API loads all YAML files from `schemas/` at startup and builds a per-schema service registry:

```
GET /schemas → {"schemas": ["marine_cargo", "standard_reinsurance"]}

POST /upload?schema=marine_cargo    → marine_cargo MappingService
POST /upload?schema=standard_reinsurance → standard_reinsurance MappingService
POST /upload                        → default schema
```

Each MappingService has its own GroqMapper with a **schema-specific SLM prompt** — the AI receives different field names, hints, and constraints per schema.

### Async Upload: Non-Blocking File Processing

```
Client                     API                      Background
  │                         │                          │
  ├── POST /upload/async ──>│                          │
  │                         ├── Create Job (PENDING)   │
  │                         ├── Save temp file         │
  │<── 202 {job_id} ───────┤                          │
  │                         ├── add_task ─────────────>│
  │                         │                          ├── Job → PROCESSING
  │                         │                          ├── SLM call
  │                         │                          ├── Row validation
  │                         │                          ├── Job → COMPLETE
  ├── GET /jobs/{id} ──────>│                          │
  │<── {status: complete} ──┤                          │
```

The Job model is a **pure state machine** in the domain layer — no I/O, fully testable:

```python
class JobStatus(StrEnum):
    PENDING = "pending"       # Created, not started
    PROCESSING = "processing" # SLM call in progress
    COMPLETE = "complete"     # Results available
    FAILED = "failed"         # Error captured

# Transitions enforced:
# PENDING → PROCESSING → COMPLETE
# PENDING → PROCESSING → FAILED
# All other transitions raise ValueError
```

### Graceful Degradation

Every Redis operation catches `ConnectionError` and `RedisError`:

```python
# Cache miss on error — app continues, just slower (re-calls SLM)
def get_mapping(self, cache_key: str) -> MappingResult | None:
    try:
        data = self._client.get(f"riskflow:mapping:{cache_key}")
    except (ConnectionError, redis.RedisError):
        return None  # Treat as cache miss

# Dropped write on error — app continues, just won't cache this result
def set_mapping(self, cache_key: str, result: MappingResult) -> None:
    try:
        self._client.setex(key, 3600, result.model_dump_json())
    except (ConnectionError, redis.RedisError):
        pass  # Silently drop
```

Redis goes down? The API keeps serving — every request hits the SLM, but no requests fail. When Redis recovers, caching resumes automatically.

### Docker Compose: Service Isolation

```yaml
services:
  api:       # Stateless, horizontally scalable
    build: .
    ports: ["8000:8000"]
    environment:
      - REDIS_URL=redis://redis:6379

  redis:     # Shared state (cache + corrections)
    image: redis:alpine
    ports: ["6379:6379"]

  gui:       # Independent Streamlit dashboard
    build: { dockerfile: gui/Dockerfile }
    ports: ["8501:8501"]
    environment:
      - RISKFLOW_API_URL=http://api:8000
```

**Scaling to 3 API instances:**

```yaml
  api:
    deploy:
      replicas: 3
    # All 3 instances connect to the same Redis
    # All 3 instances load the same schemas from YAML
    # No session affinity needed
```

### Architecture Linting: Enforced in CI

An AST-based linter (`tools/hexagonal_linter.py`) runs on every commit to catch boundary violations:

```python
# Catches: domain/ importing from adapters/
# Catches: ports/ importing from entrypoint/
# Catches: adapters/ importing from entrypoint/

# Example violation that would be caught:
# File: src/domain/service/mapping_service.py
# Import: from src.adapters.storage.cache import RedisCache  ← BLOCKED
```

This ensures the architecture stays clean as the team grows — no one accidentally couples domain logic to infrastructure.

### Scaling Roadmap

| Phase | What | Status |
|-------|------|--------|
| 1 | Observability: structlog JSON, schema fingerprint in logs | Done |
| 2 | Performance baselines: pytest-benchmark, guardrails | Done |
| 3 | Contract tests: API shape stability for GUI consumer | Done |
| 4 | Replace InMemoryJobStore with RedisJobStore | Next |
| 5 | Replace BackgroundTasks with TaskRunnerPort + Celery | Planned |
| 6 | Health probes: /health, /ready, /live for Kubernetes | Planned |
| 7 | Rate limiting, circuit breaker on SLM calls | Planned |
| 8 | Multi-service split, Pact broker, OpenTelemetry | Future |

### The Key Insight

The architecture is designed so that **scaling is an adapter change, not a domain change**:

- More throughput? → Add API replicas (stateless design)
- Distributed jobs? → Swap InMemoryJobStore for RedisJobStore (port stays the same)
- Task queues? → Swap BackgroundTasks for CeleryTaskRunner (new adapter, same port)
- Different SLM? → Swap GroqMapper for OllamaMapper (port stays the same)
- Kubernetes? → Add /ready and /live endpoints (health check pattern)

The domain service — `MappingService` — has never been modified for infrastructure reasons. It only changes when business rules change.

---

## Lessons Learned (retrospective)

| Problem | Impact | How it was caught |
|---------|--------|-------------------|
| No performance baselines before building features | Can't prove optimisations helped — no before/after comparison | Realised when writing the scaling plan (Session 8) |
| Benchmark JSON files initially committed to repo | Large binary files in git history | Cleanup scan — moved to .gitignore |

**Key insight:** Performance infrastructure should be built before the features that need it, not after. Baselines captured before scaling work would have made the improvement measurable.
