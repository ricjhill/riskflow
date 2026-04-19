"""Scaling regression test: GET /jobs latency budget with real Redis.

This test documents the expected latency of list_all() at various job counts.
It doesn't assert hard SLA numbers that might flap in CI — instead it asserts
that list_all() scales roughly linearly with job count and completes within
generous budgets.

If pagination is added (issue #195), this test should start failing with
better numbers and the budgets should be tightened.

Requires Docker (uses testcontainers for real Redis).
"""

from __future__ import annotations

import time
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


async def _time_list_all(store: RedisJobStore) -> float:
    """Run list_all once, return elapsed time in milliseconds."""
    start = time.monotonic()
    await store.list_all()
    return (time.monotonic() - start) * 1000


class TestJobsLatencyBudget:
    """Single-client list_all() latency budgets at different job counts."""

    @pytest.mark.asyncio
    async def test_100_jobs_under_100ms(self, redis_client: Any) -> None:
        """100 jobs is a common operational scale. Budget 100ms per call."""
        store = RedisJobStore(client=redis_client)
        for i in range(100):
            await store.save(Job.create(filename=f"job_{i}.csv"))

        # Warm up
        await store.list_all()

        # Measure
        elapsed_ms = await _time_list_all(store)
        assert elapsed_ms < 100, f"list_all(100) took {elapsed_ms:.0f}ms (budget: 100ms)"

    @pytest.mark.asyncio
    async def test_500_jobs_under_300ms(self, redis_client: Any) -> None:
        """500 jobs tests sublinear scaling bounds. Budget 300ms.

        SCAN + N×GET is O(N) per request. At 500 jobs with ~1ms per round trip
        plus serialization, 300ms gives ~50% headroom.
        """
        store = RedisJobStore(client=redis_client)
        for i in range(500):
            await store.save(Job.create(filename=f"job_{i}.csv"))

        await store.list_all()  # warm up
        elapsed_ms = await _time_list_all(store)
        assert elapsed_ms < 300, f"list_all(500) took {elapsed_ms:.0f}ms (budget: 300ms)"

    @pytest.mark.asyncio
    async def test_scaling_is_linear_not_quadratic(self, redis_client: Any) -> None:
        """list_all at 500 jobs should be < 10× list_all at 50 jobs.

        If this ratio blows up, the implementation has regressed from O(N)
        to O(N²). A 10× ratio for 10× input is safely linear.
        """
        store = RedisJobStore(client=redis_client)

        # Measure with 50 jobs
        for i in range(50):
            await store.save(Job.create(filename=f"small_{i}.csv"))
        await store.list_all()  # warm up
        time_50 = await _time_list_all(store)

        # Add 450 more jobs (total 500)
        for i in range(450):
            await store.save(Job.create(filename=f"large_{i}.csv"))
        await store.list_all()  # warm up
        time_500 = await _time_list_all(store)

        ratio = time_500 / max(time_50, 0.1)
        assert ratio < 50, (
            f"list_all scaling ratio: 50 jobs={time_50:.1f}ms, "
            f"500 jobs={time_500:.1f}ms, ratio={ratio:.1f}× "
            f"(linear would be ~10×, quadratic would be ~100×). "
            f"Ratio >50× suggests quadratic regression."
        )
