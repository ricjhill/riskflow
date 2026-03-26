"""Tests for cache adapters: RedisCache and NullCache.

RedisCache tests use a mocked redis.Redis client — no real Redis needed.
NullCache is a trivial fallback for when Redis is unavailable.
"""

from unittest.mock import MagicMock

import pytest

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
    def test_satisfies_cache_port(self) -> None:
        assert isinstance(RedisCache(client=MagicMock()), CachePort)


class TestRedisCacheGetMapping:
    def test_returns_none_on_cache_miss(self) -> None:
        client = MagicMock()
        client.get.return_value = None
        cache = RedisCache(client=client)

        result = cache.get_mapping("nonexistent-key")

        assert result is None
        client.get.assert_called_once_with("riskflow:mapping:nonexistent-key")

    def test_deserializes_cached_json(self) -> None:
        expected = _make_mapping_result()
        client = MagicMock()
        client.get.return_value = expected.model_dump_json().encode()
        cache = RedisCache(client=client)

        result = cache.get_mapping("some-key")

        assert result is not None
        assert result == expected

    def test_returns_none_on_invalid_json(self) -> None:
        client = MagicMock()
        client.get.return_value = b"not valid json"
        cache = RedisCache(client=client)

        result = cache.get_mapping("bad-key")

        assert result is None

    def test_returns_none_on_connection_error(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConnectionError("Redis down")
        cache = RedisCache(client=client)

        result = cache.get_mapping("any-key")

        assert result is None


class TestRedisCacheSetMapping:
    def test_stores_json_with_ttl(self) -> None:
        client = MagicMock()
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        cache.set_mapping("some-key", mapping, ttl=7200)

        client.setex.assert_called_once()
        args = client.setex.call_args[0]
        assert args[0] == "riskflow:mapping:some-key"
        assert args[1] == 7200
        assert isinstance(args[2], (str, bytes))

    def test_default_ttl_is_3600(self) -> None:
        client = MagicMock()
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        cache.set_mapping("some-key", mapping)

        args = client.setex.call_args[0]
        assert args[1] == 3600

    def test_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.setex.side_effect = ConnectionError("Redis down")
        cache = RedisCache(client=client)
        mapping = _make_mapping_result()

        # Should not raise — cache failures are non-fatal
        cache.set_mapping("some-key", mapping)


class TestNullCacheProtocol:
    def test_satisfies_cache_port(self) -> None:
        assert isinstance(NullCache(), CachePort)


class TestNullCache:
    def test_get_always_returns_none(self) -> None:
        assert NullCache().get_mapping("any-key") is None

    def test_set_is_a_noop(self) -> None:
        mapping = _make_mapping_result()
        # Should not raise
        NullCache().set_mapping("any-key", mapping)

    @pytest.mark.parametrize("key", ["", "abc", "x" * 1000])
    def test_get_returns_none_for_any_key(self, key: str) -> None:
        assert NullCache().get_mapping(key) is None
