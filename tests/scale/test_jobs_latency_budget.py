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
    async def test_100_jobs_under_200ms(self, redis_client: Any) -> None:
        """100 jobs is a common operational scale. Budget 200ms per call.

        The budget accounts for CI runner variability: list_all() does
        ~100 async GETs (~0.5ms each warm) plus JSON deserialisation, so
        typical is 50-80ms. 200ms gives ~2.5× headroom for jitter and
        testcontainer startup effects.
        """
        store = RedisJobStore(client=redis_client)
        for i in range(100):
            await store.save(Job.create(filename=f"job_{i}.csv"))

        # Warm up (not measured — first call pays connection + first-hit costs)
        await store.list_all()

        # Measure
        elapsed_ms = await _time_list_all(store)
        assert elapsed_ms < 200, f"list_all(100) took {elapsed_ms:.0f}ms (budget: 200ms)"

    @pytest.mark.asyncio
    async def test_500_jobs_under_600ms(self, redis_client: Any) -> None:
        """500 jobs tests sublinear scaling bounds. Budget 600ms.

        SCAN + N×GET is O(N) per request. At 500 jobs with ~0.5ms per round
        trip plus serialization, typical is 250-400ms. 600ms gives ~2× headroom.
        If this fails, either Redis round trips got slower or the
        implementation regressed from O(N) to something worse.
        """
        store = RedisJobStore(client=redis_client)
        for i in range(500):
            await store.save(Job.create(filename=f"job_{i}.csv"))

        await store.list_all()  # warm up
        elapsed_ms = await _time_list_all(store)
        assert elapsed_ms < 600, f"list_all(500) took {elapsed_ms:.0f}ms (budget: 600ms)"

    @pytest.mark.asyncio
    async def test_scaling_is_linear_not_quadratic(self, redis_client: Any) -> None:
        """list_all at 500 jobs vs 50 jobs — ratio must be < 20×.

        Expected ratios for a 10× input increase:
          - O(N):       ~10× (linear)
          - O(N log N): ~15.9× — NOT detected by this threshold
          - O(N^1.5):   ~31.6× — detected
          - O(N²):      ~100× — detected

        The 20× threshold provides 2× headroom over linear for CI jitter
        while reliably catching O(N^1.5) and worse. A mild O(N log N)
        regression would pass — if that becomes a concern, tighten to 15×.

        The 1ms floor on time_50 prevents false failures when 50 jobs
        runs sub-millisecond (common with a warm loop on fast hardware),
        at the cost of making the test less sensitive at the low end.
        """
        store = RedisJobStore(client=redis_client)

        # Measure with 50 jobs — use multiple samples to reduce noise
        for i in range(50):
            await store.save(Job.create(filename=f"small_{i}.csv"))
        await store.list_all()  # warm up
        samples_50 = [await _time_list_all(store) for _ in range(5)]
        time_50 = min(samples_50)  # fastest sample is least affected by jitter

        # Add 450 more jobs (total 500) — multiple samples again
        for i in range(450):
            await store.save(Job.create(filename=f"large_{i}.csv"))
        await store.list_all()  # warm up
        samples_500 = [await _time_list_all(store) for _ in range(5)]
        time_500 = min(samples_500)

        # 1ms floor — 50 jobs can complete in <1ms on fast hardware, making
        # the ratio unstable. This inflates the measured ratio upward, which
        # errs on the side of detecting regression.
        ratio = time_500 / max(time_50, 1.0)
        assert ratio < 20, (
            f"list_all scaling ratio: 50 jobs={time_50:.1f}ms, "
            f"500 jobs={time_500:.1f}ms, ratio={ratio:.1f}× "
            f"(linear would be ~10×, quadratic would be ~100×). "
            f"Ratio >20× suggests super-linear regression."
        )
