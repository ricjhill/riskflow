"""Tests for cache adapters: RedisCache and NullCache.

RedisCache tests use a mocked async Redis client — no real Redis needed.
NullCache is a trivial fallback for when Redis is unavailable.
"""

from unittest.mock import AsyncMock

import pytest
import structlog.testing

from src.adapters.storage.cache import NullCache, RedisCache
from src.domain.model.schema import ColumnMapping, MappingResult
from src.ports.output.repo import CachePort


def _make_mapping_result() -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(
                source_header="GWP",
                target_field="Gross_Premium",
                confidence=0.95,
            ),
        ],
        unmapped_headers=["Extra"],
    )


class TestRedisCacheProtocol:
    """RedisCache must satisfy CachePort at runtime."""

    def test_satisfies_cache_port(self) -> None:
        assert isinstance(RedisCache(client=AsyncMock()), CachePort)


class TestRedisCacheGetMapping:
    """get_mapping retrieves cached results or returns None on miss/error."""

    @pytest.mark.asyncio
    async def test_returns_none_on_cache_miss(self) -> None:
        client = AsyncMock()
        client.get.return_value = None
        cache = RedisCache(client=client)

        result = await cache.get_mapping("nonexistent-key")

        assert result is None
        client.get.assert_called_once_with("riskflow:mapping:nonexistent-key")

    @pytest.mark.asyncio
    async def test_deserializes_cached_json(self) -> None:
        expected = _make_mapping_result()
        client = AsyncMock()
        client.get.return_value = expected.model_dump_json().encode()
        cache = RedisCache(client=client)

        result = await cache.get_mapping("some-key")

        assert result is not None
        assert result == expected

    @pytest.mark.asyncio
    async def test_returns_none_on_invalid_json(self) -> None:
        client = AsyncMock()
        client.get.return_value = b"not valid json"
        cache = RedisCache(client=client)

        result = await cache.get_mapping("bad-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_connection_error(self) -> None:
        client = AsyncMock()
        client.get.side_effect = ConnectionError("Redis down")
        cache = RedisCache(client=client)

        result = await cache.get_mapping("any-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_error(self) -> None:
        """RedisError (not just ConnectionError) is also caught."""
        import redis as redis_lib

        client = AsyncMock()
        client.get.side_effect = redis_lib.RedisError("unexpected")
        cache = RedisCache(client=client)

        result = await cache.get_mapping("any-key")

        assert result is None

    @pytest.mark.asyncio
    async def test_logs_error_on_get_connection_failure(self) -> None:
        """Redis get failure emits an error log with cache_key and error message."""
        client = AsyncMock()
        client.get.side_effect = ConnectionError("Redis down")
        cache = RedisCache(client=client)

        with structlog.testing.capture_logs() as logs:
            await cache.get_mapping("any-key")

        error_logs = [e for e in logs if e.get("event") == "cache_get_failed"]
        assert len(error_logs) == 1
        assert error_logs[0]["cache_key"] == "any-key"
        assert "Redis down" in error_logs[0]["error"]

    @pytest.mark.asyncio
    async def test_empty_cache_key(self) -> None:
        """Empty string is a valid cache key — returns None on miss."""
        client = AsyncMock()
        client.get.return_value = None
        cache = RedisCache(client=client)

        result = await cache.get_mapping("")

        assert result is None
        client.get.assert_called_once_with("riskflow:mapping:")


class TestRedisCacheSetMapping:
    """set_mapping stores results with TTL, silently fails on error."""

    @pytest.mark.asyncio
    async def test_stores_json_with_ttl(self) -> None:
        client = AsyncMock()
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        await cache.set_mapping("some-key", mapping, ttl=7200)

        client.setex.assert_called_once()
        args = client.setex.call_args[0]
        assert args[0] == "riskflow:mapping:some-key"
        assert args[1] == 7200
        assert isinstance(args[2], (str, bytes))

    @pytest.mark.asyncio
    async def test_default_ttl_is_3600(self) -> None:
        client = AsyncMock()
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        await cache.set_mapping("some-key", mapping)

        args = client.setex.call_args[0]
        assert args[1] == 3600

    @pytest.mark.asyncio
    async def test_swallows_connection_error(self) -> None:
        client = AsyncMock()
        client.setex.side_effect = ConnectionError("Redis down")
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        await cache.set_mapping("some-key", mapping)  # should not raise

    @pytest.mark.asyncio
    async def test_logs_error_on_set_connection_failure(self) -> None:
        """Redis set failure emits an error log with cache_key and error message."""
        client = AsyncMock()
        client.setex.side_effect = ConnectionError("Redis down")
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        with structlog.testing.capture_logs() as logs:
            await cache.set_mapping("some-key", mapping)

        error_logs = [e for e in logs if e.get("event") == "cache_set_failed"]
        assert len(error_logs) == 1
        assert error_logs[0]["cache_key"] == "some-key"
        assert "Redis down" in error_logs[0]["error"]


class TestNullCacheProtocol:
    """NullCache must satisfy CachePort at runtime."""

    def test_satisfies_cache_port(self) -> None:
        assert isinstance(NullCache(), CachePort)


class TestNullCache:
    """NullCache always returns None and silently discards writes."""

    @pytest.mark.asyncio
    async def test_get_always_returns_none(self) -> None:
        assert await NullCache().get_mapping("any-key") is None

    @pytest.mark.asyncio
    async def test_set_is_a_noop(self) -> None:
        mapping = _make_mapping_result()
        await NullCache().set_mapping("any-key", mapping)  # should not raise

    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["", "abc", "x" * 1000])
    async def test_get_returns_none_for_any_key(self, key: str) -> None:
        assert await NullCache().get_mapping(key) is None
