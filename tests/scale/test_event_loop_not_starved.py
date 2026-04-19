"""Scaling regression test: event loop stays responsive under /jobs load.

This test protects the fix for issue #198 (sync Redis blocking the event loop).
Before the async Redis migration, 1000 concurrent Redis GETs during list_all()
blocked the event loop for 2.9 seconds at P95, making /health unresponsive.

The test seeds Redis with N jobs, then while calling list_all() in a loop it
also measures /health latency. The two endpoints share a single FastAPI
worker's event loop — if Redis calls block, /health degrades.

Pass criteria: /health P95 < 100ms while /jobs is under concurrent load.

Requires Docker (uses testcontainers for real Redis).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest
import pytest_asyncio

try:
    from testcontainers.redis import RedisContainer

    HAS_DOCKER = True
except Exception:
    HAS_DOCKER = False

import redis.asyncio

from src.adapters.storage.job_store import RedisJobStore
from src.domain.model.job import Job

pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(not HAS_DOCKER, reason="Docker or testcontainers not available"),
]


@pytest.fixture(scope="module")
def redis_container():  # type: ignore[no-untyped-def]
    """Start a real Redis container for the scaling tests."""
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest_asyncio.fixture
async def redis_client(redis_container) -> Any:  # type: ignore[no-untyped-def]
    """Async Redis client connected to the testcontainer."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client = redis.asyncio.Redis(host=host, port=int(port), db=0)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.aclose()


async def _seed_jobs(store: RedisJobStore, count: int) -> None:
    """Seed the store with N jobs."""
    for i in range(count):
        job = Job.create(filename=f"seed_{i:04d}.csv")
        await store.save(job)


class TestEventLoopNotStarved:
    """Protects the fix for #198 — async Redis must not block the event loop."""

    @pytest.mark.asyncio
    async def test_fast_probe_stays_fast_during_list_all_load(self, redis_client: Any) -> None:
        """While list_all() runs against 500 jobs concurrently, a simple Redis
        PING (simulating /health's Redis probe) must still complete in <100ms P95.

        Before PR #203 (async Redis migration), sync redis.Redis.scan() + GET
        calls blocked the event loop during list_all(), causing /health to spike
        to 2.9s. After the migration, Redis I/O yields the event loop and /health
        stays fast.
        """
        store = RedisJobStore(client=redis_client)
        await _seed_jobs(store, 500)

        probe_latencies_ms: list[float] = []
        stop = asyncio.Event()

        async def fast_probe() -> None:
            """Simulates /health probing Redis while list_all runs."""
            while not stop.is_set():
                t0 = time.monotonic()
                await redis_client.ping()
                probe_latencies_ms.append((time.monotonic() - t0) * 1000)
                await asyncio.sleep(0.01)

        async def list_all_load() -> None:
            """Simulates 10 concurrent /jobs callers."""
            for _ in range(10):
                await store.list_all()

        probe_task = asyncio.create_task(fast_probe())
        try:
            # Run 3 rounds of concurrent list_all() so probes overlap with load
            for _ in range(3):
                await asyncio.gather(*[list_all_load() for _ in range(5)])
        finally:
            stop.set()
            await probe_task

        probe_latencies_ms.sort()
        assert len(probe_latencies_ms) > 10, "probe didn't run enough times"
        p95 = probe_latencies_ms[int(len(probe_latencies_ms) * 0.95)]

        # Before async migration this was ~2900ms at 1000 jobs.
        # After migration the probe is effectively unaffected by list_all load.
        assert p95 < 100, (
            f"Fast Redis probe P95={p95:.0f}ms under list_all load. "
            f"This means list_all is blocking the event loop — a regression "
            f"of PR #203 (async Redis migration)."
        )

    @pytest.mark.asyncio
    async def test_concurrent_list_all_calls_complete(self, redis_client: Any) -> None:
        """20 concurrent list_all() coroutines against 200 jobs all complete
        without errors. Proves async Redis connection pool handles concurrent
        in-flight requests gracefully (no connection exhaustion).
        """
        store = RedisJobStore(client=redis_client)
        await _seed_jobs(store, 200)

        results = await asyncio.gather(
            *[store.list_all() for _ in range(20)],
            return_exceptions=True,
        )

        failures = [r for r in results if isinstance(r, Exception)]
        assert len(failures) == 0, f"{len(failures)} failed: {failures[:3]}"

        # Each result should have all 200 jobs
        for result in results:
            assert isinstance(result, list)
            assert len(result) == 200
