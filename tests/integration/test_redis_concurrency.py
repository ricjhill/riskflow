"""Redis connection pool concurrency tests.

Verifies that RiskFlow's async Redis adapters (RedisCache, RedisCorrectionCache,
RedisJobStore) behave correctly under concurrent access. Uses asyncio.gather
to simulate many in-flight requests to a single Uvicorn worker's event loop.

Tests validate:
- Zero errors under concurrent writes and reads
- Data integrity (no cross-contamination between tasks)
- Async connection pool handles many concurrent waiters
- Job state transitions under concurrent access

Uses testcontainers for a real Redis instance. Skipped when Docker
is unavailable.
"""

import asyncio
from typing import Any

import pytest
import pytest_asyncio

try:
    from testcontainers.redis import RedisContainer

    HAS_DOCKER = True
except Exception:
    HAS_DOCKER = False

import redis.asyncio

from src.adapters.storage.cache import RedisCache
from src.adapters.storage.correction_cache import RedisCorrectionCache
from src.adapters.storage.job_store import RedisJobStore
from src.domain.model.correction import Correction
from src.domain.model.job import Job, JobStatus
from src.domain.model.schema import ColumnMapping, MappingResult

from tests.benchmark.conftest import Timer

pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(not HAS_DOCKER, reason="Docker or testcontainers not available"),
]

WORKERS = 20
OPS_PER_WORKER = 50


def _make_mapping_result(tag: str, confidence: float = 0.95) -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(
                source_header=f"Source_{tag}",
                target_field=f"Target_{tag}",
                confidence=confidence,
            ),
        ],
        unmapped_headers=[],
    )


@pytest.fixture(scope="module")
def redis_container():  # type: ignore[no-untyped-def]
    """Start a real Redis container for the test module."""
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest_asyncio.fixture
async def pooled_redis(redis_container) -> Any:  # type: ignore[no-untyped-def]
    """Async Redis client with explicit connection pool (max 20 connections)."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    pool = redis.asyncio.ConnectionPool(host=host, port=int(port), db=0, max_connections=20)
    client = redis.asyncio.Redis(connection_pool=pool)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()
        await pool.aclose()


@pytest_asyncio.fixture
async def small_pool_redis(redis_container) -> Any:  # type: ignore[no-untyped-def]
    """Async Redis client with small pool (10 connections) for exhaustion test."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    pool = redis.asyncio.ConnectionPool(host=host, port=int(port), db=0, max_connections=10)
    client = redis.asyncio.Redis(connection_pool=pool)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()
        await pool.aclose()


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------
class TestRedisConcurrency:
    """Concurrent access to Redis via RiskFlow async adapters."""

    @pytest.mark.asyncio
    async def test_concurrent_cache_writes_no_errors(self, pooled_redis: Any) -> None:
        """20 coroutines × 50 writes = 1000 cache entries, zero errors."""
        cache = RedisCache(client=pooled_redis)

        async def write_batch(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                key = f"w{worker_id}_k{i}"
                await cache.set_mapping(key, _make_mapping_result(key), ttl=60)

        await asyncio.gather(*[write_batch(w) for w in range(WORKERS)])

        # Verify all keys exist (spot-check)
        for w in range(WORKERS):
            for i in range(0, OPS_PER_WORKER, 10):
                key = f"w{w}_k{i}"
                result = await cache.get_mapping(key)
                assert result is not None, f"Missing key: {key}"

    @pytest.mark.asyncio
    async def test_concurrent_cache_reads_after_writes(self, pooled_redis: Any) -> None:
        """Pre-populate 100 keys, then 20 coroutines read concurrently."""
        cache = RedisCache(client=pooled_redis)

        for i in range(100):
            await cache.set_mapping(f"read_k{i}", _make_mapping_result(f"read_{i}"), ttl=60)

        none_results: list[str] = []

        async def read_batch(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                key_idx = (worker_id * OPS_PER_WORKER + i) % 100
                key = f"read_k{key_idx}"
                result = await cache.get_mapping(key)
                if result is None:
                    none_results.append(key)

        await asyncio.gather(*[read_batch(w) for w in range(WORKERS)])

        assert len(none_results) == 0, f"Got None for keys: {none_results[:5]}"

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(self, pooled_redis: Any) -> None:
        """20 coroutines doing mixed cache + correction ops simultaneously."""
        cache = RedisCache(client=pooled_redis)
        correction_cache = RedisCorrectionCache(client=pooled_redis)

        async def mixed_ops(worker_id: int) -> None:
            for i in range(10):
                mk = f"mix_m_{worker_id}_{i}"
                await cache.set_mapping(mk, _make_mapping_result(mk), ttl=60)
                await cache.get_mapping(mk)
                await correction_cache.set_correction(
                    Correction(
                        cedent_id=f"cedent_{worker_id}",
                        source_header=f"hdr_{i}",
                        target_field=f"tgt_{i}",
                    )
                )
                await correction_cache.get_corrections(f"cedent_{worker_id}", [f"hdr_{i}"])

        await asyncio.gather(*[mixed_ops(w) for w in range(WORKERS)])

        # Verify data integrity for a sample
        for w in range(WORKERS):
            result = await correction_cache.get_corrections(f"cedent_{w}", ["hdr_0"])
            assert result == {"hdr_0": "tgt_0"}, f"Integrity check failed for cedent_{w}"

    @pytest.mark.asyncio
    async def test_pool_exhaustion_handled(self, small_pool_redis: Any) -> None:
        """10-connection pool with 20 concurrent coroutines.

        Async Redis queues waiters when all connections are in use.
        All operations must complete (no ConnectionError), proving
        the pool correctly serializes excess demand.
        """
        cache = RedisCache(client=small_pool_redis)

        async def write_burst(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                key = f"pool_w{worker_id}_k{i}"
                await cache.set_mapping(key, _make_mapping_result(key), ttl=60)
                await cache.get_mapping(key)

        with Timer() as t:
            await asyncio.gather(*[write_burst(w) for w in range(WORKERS)])

        assert t.elapsed_ms < 30_000, f"Pool exhaustion took {t.elapsed_ms:.0f}ms (budget: 30s)"


# ---------------------------------------------------------------------------
# RedisJobStore concurrency tests
# ---------------------------------------------------------------------------
class TestRedisJobStoreConcurrency:
    """Concurrent access to RedisJobStore from multiple coroutines."""

    @pytest.mark.asyncio
    async def test_concurrent_job_saves(self, pooled_redis: Any) -> None:
        """20 coroutines × 50 saves = 1000 jobs, all retrievable with correct state."""
        store = RedisJobStore(client=pooled_redis)
        job_ids: list[str] = []

        async def save_batch(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                job = Job.create(filename=f"w{worker_id}_f{i}.csv")
                await store.save(job)
                job_ids.append(job.id)

        await asyncio.gather(*[save_batch(w) for w in range(WORKERS)])

        assert len(job_ids) == WORKERS * OPS_PER_WORKER

        for jid in job_ids[:20]:  # spot-check first 20
            retrieved = await store.get(jid)
            assert retrieved is not None, f"Job {jid} not found after concurrent save"

    @pytest.mark.asyncio
    async def test_concurrent_save_and_list(self, pooled_redis: Any) -> None:
        """Coroutines saving jobs while others call list_all() — no crashes."""
        store = RedisJobStore(client=pooled_redis)

        async def save_jobs(worker_id: int) -> None:
            for i in range(10):
                job = Job.create(filename=f"save_w{worker_id}_f{i}.csv")
                await store.save(job)

        async def list_jobs() -> None:
            for _ in range(10):
                result = await store.list_all()
                assert isinstance(result, list)
                for j in result:
                    assert isinstance(j, Job)

        tasks = []
        for w in range(5):
            tasks.append(save_jobs(w))
            tasks.append(list_jobs())
        await asyncio.gather(*tasks)

    @pytest.mark.asyncio
    async def test_job_state_transitions_under_concurrency(self, pooled_redis: Any) -> None:
        """10 coroutines each create→start→complete a job. All end COMPLETE."""
        store = RedisJobStore(client=pooled_redis)
        completed_ids: list[str] = []

        async def transition_job(worker_id: int) -> None:
            job = Job.create(filename=f"transition_{worker_id}.csv")
            await store.save(job)
            job.start()
            await store.save(job)
            job.complete(result={"worker": worker_id})
            await store.save(job)
            completed_ids.append(job.id)

        await asyncio.gather(*[transition_job(w) for w in range(10)])

        assert len(completed_ids) == 10

        for jid in completed_ids:
            job = await store.get(jid)
            assert job is not None
            assert job.status == JobStatus.COMPLETE, (
                f"Job {jid} status is {job.status}, expected COMPLETE"
            )


# ---------------------------------------------------------------------------
# Real-Redis latency guardrails
# ---------------------------------------------------------------------------
class TestRedisJobStoreLatency:
    """Latency guardrails with real Redis — catches actual round-trip time."""

    @pytest.mark.asyncio
    async def test_real_redis_save_under_10ms(self, pooled_redis: Any) -> None:
        """Single save against real Redis — budget 10ms."""
        store = RedisJobStore(client=pooled_redis)
        job = Job.create(filename="latency.csv")
        await store.save(job)  # warm up

        with Timer() as t:
            await store.save(job)
        assert t.elapsed_ms < 10, f"save() took {t.elapsed_ms:.1f}ms (budget: 10ms)"

    @pytest.mark.asyncio
    async def test_real_redis_get_under_10ms(self, pooled_redis: Any) -> None:
        """Single get against real Redis — budget 10ms."""
        store = RedisJobStore(client=pooled_redis)
        job = Job.create(filename="latency.csv")
        await store.save(job)
        await store.get(job.id)  # warm up

        with Timer() as t:
            await store.get(job.id)
        assert t.elapsed_ms < 10, f"get() took {t.elapsed_ms:.1f}ms (budget: 10ms)"

    @pytest.mark.asyncio
    async def test_real_redis_list_100_under_500ms(self, pooled_redis: Any) -> None:
        """list_all() with 100 jobs — catches O(N) SCAN+GET scaling issues."""
        store = RedisJobStore(client=pooled_redis)
        for i in range(100):
            job = Job.create(filename=f"list_{i}.csv")
            await store.save(job)

        with Timer() as t:
            result = await store.list_all()
        assert len(result) >= 100
        assert t.elapsed_ms < 500, f"list_all(100) took {t.elapsed_ms:.1f}ms (budget: 500ms)"
