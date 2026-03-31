"""Redis connection pool concurrency tests.

Verifies that RiskFlow's Redis adapters (RedisCache, RedisCorrectionCache)
behave correctly under concurrent access from multiple threads. This
simulates a Uvicorn worker handling multiple requests simultaneously,
each reading/writing to Redis.

Tests validate:
- Zero errors under concurrent writes and reads
- Data integrity (no cross-contamination between threads)
- Connection pool queuing (more threads than connections)

Uses testcontainers for a real Redis instance. Skipped when Docker
is unavailable.
"""

import concurrent.futures

import pytest

try:
    from testcontainers.redis import RedisContainer

    HAS_DOCKER = True
except Exception:
    HAS_DOCKER = False

import redis as redis_lib

from src.adapters.storage.cache import RedisCache
from src.adapters.storage.correction_cache import RedisCorrectionCache
from src.domain.model.correction import Correction
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


@pytest.fixture
def pooled_redis(redis_container) -> redis_lib.Redis:  # type: ignore[type-arg,no-untyped-def]
    """Redis client with explicit connection pool (max 20 connections)."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    pool = redis_lib.ConnectionPool(host=host, port=int(port), db=0, max_connections=20)
    client: redis_lib.Redis = redis_lib.Redis(connection_pool=pool)  # type: ignore[type-arg]
    client.flushdb()
    yield client  # type: ignore[misc]
    pool.disconnect()


@pytest.fixture
def small_pool_redis(redis_container) -> redis_lib.Redis:  # type: ignore[type-arg,no-untyped-def]
    """Redis client with deliberately small pool (10 connections) for exhaustion test."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    pool = redis_lib.ConnectionPool(host=host, port=int(port), db=0, max_connections=10)
    client: redis_lib.Redis = redis_lib.Redis(connection_pool=pool)  # type: ignore[type-arg]
    client.flushdb()
    yield client  # type: ignore[misc]
    pool.disconnect()


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------
class TestRedisConcurrency:
    """Concurrent access to Redis via RiskFlow adapters."""

    def test_concurrent_cache_writes_no_errors(
        self,
        pooled_redis: redis_lib.Redis,  # type: ignore[type-arg]
    ) -> None:
        """20 threads × 50 writes = 1000 cache entries, zero errors."""
        cache = RedisCache(client=pooled_redis)
        errors: list[Exception] = []

        def write_batch(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                try:
                    key = f"w{worker_id}_k{i}"
                    cache.set_mapping(key, _make_mapping_result(key), ttl=60)
                except Exception as e:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(write_batch, w) for w in range(WORKERS)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, (
            f"{len(errors)} errors during concurrent writes: {errors[:3]}"
        )

        # Verify all keys exist
        for w in range(WORKERS):
            for i in range(OPS_PER_WORKER):
                key = f"w{w}_k{i}"
                result = cache.get_mapping(key)
                assert result is not None, f"Missing key: {key}"

    def test_concurrent_cache_reads_after_writes(
        self,
        pooled_redis: redis_lib.Redis,  # type: ignore[type-arg]
    ) -> None:
        """Pre-populate 100 keys, then 20 threads read concurrently."""
        cache = RedisCache(client=pooled_redis)

        # Pre-populate
        for i in range(100):
            cache.set_mapping(f"read_k{i}", _make_mapping_result(f"read_{i}"), ttl=60)

        errors: list[Exception] = []
        none_results: list[str] = []

        def read_batch(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                key_idx = (worker_id * OPS_PER_WORKER + i) % 100
                key = f"read_k{key_idx}"
                try:
                    result = cache.get_mapping(key)
                    if result is None:
                        none_results.append(key)
                except Exception as e:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(read_batch, w) for w in range(WORKERS)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"{len(errors)} errors during concurrent reads"
        assert len(none_results) == 0, f"Got None for keys: {none_results[:5]}"

    def test_concurrent_mixed_operations(
        self,
        pooled_redis: redis_lib.Redis,  # type: ignore[type-arg]
    ) -> None:
        """20 threads doing mixed cache + correction ops simultaneously."""
        cache = RedisCache(client=pooled_redis)
        correction_cache = RedisCorrectionCache(client=pooled_redis)
        errors: list[Exception] = []

        def mixed_ops(worker_id: int) -> None:
            for i in range(10):
                try:
                    # Write a mapping
                    mk = f"mix_m_{worker_id}_{i}"
                    cache.set_mapping(mk, _make_mapping_result(mk), ttl=60)

                    # Read it back
                    cache.get_mapping(mk)

                    # Write a correction
                    correction_cache.set_correction(
                        Correction(
                            cedent_id=f"cedent_{worker_id}",
                            source_header=f"hdr_{i}",
                            target_field=f"tgt_{i}",
                        )
                    )

                    # Read corrections
                    correction_cache.get_corrections(
                        f"cedent_{worker_id}", [f"hdr_{i}"]
                    )
                except Exception as e:
                    errors.append(e)

        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(mixed_ops, w) for w in range(WORKERS)]
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"{len(errors)} errors during mixed ops: {errors[:3]}"

        # Verify data integrity for a sample
        for w in range(WORKERS):
            result = correction_cache.get_corrections(f"cedent_{w}", ["hdr_0"])
            assert result == {"hdr_0": "tgt_0"}, (
                f"Integrity check failed for cedent_{w}"
            )

    def test_pool_exhaustion_handled(
        self,
        small_pool_redis: redis_lib.Redis,  # type: ignore[type-arg]
    ) -> None:
        """10-connection pool with 20 concurrent threads.

        redis-py queues waiters when all connections are in use.
        All operations must complete (no ConnectionError), proving
        the pool correctly serializes excess demand.
        """
        cache = RedisCache(client=small_pool_redis)
        errors: list[Exception] = []

        def write_burst(worker_id: int) -> None:
            for i in range(OPS_PER_WORKER):
                try:
                    key = f"pool_w{worker_id}_k{i}"
                    cache.set_mapping(key, _make_mapping_result(key), ttl=60)
                    cache.get_mapping(key)
                except Exception as e:
                    errors.append(e)

        with Timer() as t:
            with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = [pool.submit(write_burst, w) for w in range(WORKERS)]
                concurrent.futures.wait(futures)

        assert len(errors) == 0, (
            f"{len(errors)} errors with pool exhaustion: {errors[:3]}"
        )
        assert t.elapsed_ms < 30_000, (
            f"Pool exhaustion took {t.elapsed_ms:.0f}ms (budget: 30s)"
        )
