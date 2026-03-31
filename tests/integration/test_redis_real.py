"""Mock vs. Reality: Redis cache adapter with a real Redis container.

This test demonstrates the testcontainers pattern for validating that
adapters work identically against real infrastructure, not just mocks.

Why this matters at scale:
    - Mocked Redis tests pass even if the serialization format changes.
    - Mocked Redis tests can't catch TTL behavior, key prefix collisions,
      or connection pool exhaustion.
    - testcontainers spins up a real Redis in Docker, runs the exact same
      assertions, then tears it down. No flaky external dependencies.

The pattern:
    1. Write the test against the port interface (CachePort).
    2. Run it with NullCache/MagicMock in unit tests (fast, no Docker).
    3. Run it with RedisCache + testcontainers in integration (slower, real).
    4. If mock passes but real fails → the mock was lying.

Requires Docker. Skipped automatically when Docker is unavailable.
"""

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
from src.ports.output.correction_cache import CorrectionCachePort
from src.ports.output.repo import CachePort

pytestmark = [
    pytest.mark.container,
    pytest.mark.skipif(not HAS_DOCKER, reason="Docker or testcontainers not available"),
]


def _make_mapping_result(confidence: float = 0.95) -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(
                source_header="GWP",
                target_field="Gross_Premium",
                confidence=confidence,
            ),
            ColumnMapping(
                source_header="Policy No.",
                target_field="Policy_ID",
                confidence=confidence,
            ),
        ],
        unmapped_headers=["Extra"],
    )


@pytest.fixture(scope="module")
def redis_container():  # type: ignore[no-untyped-def]
    """Start a real Redis container for the test module."""
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture
def real_redis(redis_container) -> redis_lib.Redis:  # type: ignore[type-arg,no-untyped-def]
    """Get a Redis client connected to the testcontainer."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    client: redis_lib.Redis = redis_lib.Redis(host=host, port=int(port), db=0)  # type: ignore[type-arg]
    client.flushdb()
    return client


# ---------------------------------------------------------------------------
# Mock vs. Reality: CachePort
# ---------------------------------------------------------------------------
class TestRedisCacheReal:
    """These tests mirror tests/unit/test_cache_adapter.py but hit real Redis.

    If any test here fails while the unit test passes, the mock was masking
    a real behavior difference.
    """

    def test_satisfies_cache_port(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCache(client=real_redis)
        assert isinstance(cache, CachePort)

    def test_roundtrip_set_then_get(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCache(client=real_redis)
        expected = _make_mapping_result()

        cache.set_mapping("test-key", expected, ttl=60)
        actual = cache.get_mapping("test-key")

        assert actual is not None
        assert actual == expected

    def test_get_returns_none_on_miss(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCache(client=real_redis)
        assert cache.get_mapping("nonexistent-key") is None

    def test_ttl_is_applied(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        """Verify the key actually has a TTL in Redis (not just mocked)."""
        cache = RedisCache(client=real_redis)
        cache.set_mapping("ttl-key", _make_mapping_result(), ttl=300)

        ttl = real_redis.ttl("riskflow:mapping:ttl-key")
        assert 0 < ttl <= 300

    def test_different_keys_are_independent(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCache(client=real_redis)
        result_a = _make_mapping_result(confidence=0.9)
        result_b = _make_mapping_result(confidence=0.7)

        cache.set_mapping("key-a", result_a)
        cache.set_mapping("key-b", result_b)

        assert cache.get_mapping("key-a") == result_a
        assert cache.get_mapping("key-b") == result_b

    def test_overwrite_replaces_value(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCache(client=real_redis)
        old = _make_mapping_result(confidence=0.5)
        new = _make_mapping_result(confidence=0.99)

        cache.set_mapping("replace-key", old)
        cache.set_mapping("replace-key", new)

        assert cache.get_mapping("replace-key") == new


# ---------------------------------------------------------------------------
# Mock vs. Reality: CorrectionCachePort
# ---------------------------------------------------------------------------
class TestRedisCorrectionCacheReal:
    """Same tests as unit/test_correction_cache_adapter.py, real Redis."""

    def test_satisfies_port(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCorrectionCache(client=real_redis)
        assert isinstance(cache, CorrectionCachePort)

    def test_set_then_get_correction(self, real_redis: redis_lib.Redis) -> None:  # type: ignore[type-arg]
        cache = RedisCorrectionCache(client=real_redis)
        correction = Correction(
            cedent_id="cedent-1",
            source_header="GWP",
            target_field="Gross_Premium",
        )
        cache.set_correction(correction)

        result = cache.get_corrections("cedent-1", ["GWP", "Other"])
        assert result == {"GWP": "Gross_Premium"}

    def test_returns_empty_for_unknown_cedent(
        self, real_redis: redis_lib.Redis
    ) -> None:  # type: ignore[type-arg]
        cache = RedisCorrectionCache(client=real_redis)
        result = cache.get_corrections("unknown", ["GWP"])
        assert result == {}

    def test_multiple_corrections_same_cedent(
        self, real_redis: redis_lib.Redis
    ) -> None:  # type: ignore[type-arg]
        cache = RedisCorrectionCache(client=real_redis)
        cache.set_correction(
            Correction(
                cedent_id="cedent-2",
                source_header="GWP",
                target_field="Gross_Premium",
            )
        )
        cache.set_correction(
            Correction(
                cedent_id="cedent-2",
                source_header="TSI",
                target_field="Sum_Insured",
            )
        )

        result = cache.get_corrections("cedent-2", ["GWP", "TSI", "Extra"])
        assert result == {"GWP": "Gross_Premium", "TSI": "Sum_Insured"}
