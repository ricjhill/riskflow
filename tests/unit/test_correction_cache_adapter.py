"""Tests for NullCorrectionCache and RedisCorrectionCache adapters.

NullCorrectionCache returns empty results and discards writes.
RedisCorrectionCache uses Redis hashes per cedent with graceful degradation.
"""

from unittest.mock import AsyncMock

import pytest
import redis
import structlog.testing

from src.adapters.storage.correction_cache import (
    NullCorrectionCache,
    RedisCorrectionCache,
)
from src.domain.model.correction import Correction
from src.ports.output.correction_cache import CorrectionCachePort


class TestNullCorrectionCacheProtocol:
    """NullCorrectionCache must satisfy CorrectionCachePort at runtime."""

    def test_satisfies_correction_cache_port(self) -> None:
        assert isinstance(NullCorrectionCache(), CorrectionCachePort)


class TestNullCorrectionCache:
    """No-op fallback — returns empty, discards writes."""

    @pytest.mark.asyncio
    async def test_get_corrections_returns_empty_dict(self) -> None:
        cache = NullCorrectionCache()
        result = await cache.get_corrections("ABC", ["GWP", "Policy No."])
        assert result == {}

    @pytest.mark.asyncio
    async def test_set_correction_is_noop(self) -> None:
        cache = NullCorrectionCache()
        correction = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")
        await cache.set_correction(correction)  # should not raise

    @pytest.mark.asyncio
    async def test_get_corrections_with_empty_headers(self) -> None:
        cache = NullCorrectionCache()
        result = await cache.get_corrections("ABC", [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_corrections_returns_empty_for_any_cedent(self) -> None:
        cache = NullCorrectionCache()
        assert await cache.get_corrections("any_cedent", ["h1"]) == {}
        assert await cache.get_corrections("", ["h1"]) == {}
        assert await cache.get_corrections("x" * 1000, ["h1"]) == {}


class TestRedisCorrectionCacheProtocol:
    """RedisCorrectionCache must satisfy CorrectionCachePort at runtime."""

    def test_satisfies_correction_cache_port(self) -> None:
        assert isinstance(RedisCorrectionCache(client=AsyncMock()), CorrectionCachePort)


class TestRedisCorrectionCacheGet:
    """get_corrections retrieves matching headers from Redis hash."""

    @pytest.mark.asyncio
    async def test_returns_matching_headers(self) -> None:
        client = AsyncMock()
        client.hmget.return_value = [b"Policy_ID", None]
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", ["Policy No.", "Extra"])

        assert result == {"Policy No.": "Policy_ID"}
        client.hmget.assert_called_once_with("corrections:ABC", ["Policy No.", "Extra"])

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_matches(self) -> None:
        client = AsyncMock()
        client.hmget.return_value = [None, None, None]
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", ["A", "B", "C"])

        assert result == {}

    @pytest.mark.asyncio
    async def test_returns_empty_on_connection_error(self) -> None:
        client = AsyncMock()
        client.hmget.side_effect = redis.ConnectionError("down")
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", ["GWP"])

        assert result == {}

    @pytest.mark.asyncio
    async def test_logs_error_on_get_connection_failure(self) -> None:
        """Redis get failure emits an error log with cedent_id."""
        client = AsyncMock()
        client.hmget.side_effect = redis.ConnectionError("down")
        cache = RedisCorrectionCache(client=client)

        with structlog.testing.capture_logs() as logs:
            await cache.get_corrections("ABC", ["GWP"])

        error_logs = [e for e in logs if e.get("event") == "correction_cache_get_failed"]
        assert len(error_logs) == 1
        assert error_logs[0]["cedent_id"] == "ABC"
        assert "down" in error_logs[0]["error"]

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_headers(self) -> None:
        """Empty headers list short-circuits without calling Redis."""
        client = AsyncMock()
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", [])

        assert result == {}
        client.hmget.assert_not_called()

    @pytest.mark.asyncio
    async def test_single_header_match(self) -> None:
        client = AsyncMock()
        client.hmget.return_value = [b"Gross_Premium"]
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", ["GWP"])

        assert result == {"GWP": "Gross_Premium"}

    @pytest.mark.asyncio
    async def test_many_headers(self) -> None:
        """20+ headers in one call — realistic for a wide bordereaux."""
        headers = [f"Col_{i}" for i in range(25)]
        values: list[bytes | None] = [None] * 25
        values[5] = b"Policy_ID"
        values[20] = b"Currency"

        client = AsyncMock()
        client.hmget.return_value = values
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", headers)

        assert result == {"Col_5": "Policy_ID", "Col_20": "Currency"}

    @pytest.mark.asyncio
    async def test_redis_key_format(self) -> None:
        """Key must be corrections:{cedent_id}."""
        client = AsyncMock()
        client.hmget.return_value = [None]
        cache = RedisCorrectionCache(client=client)

        await cache.get_corrections("ACME_RE", ["GWP"])

        client.hmget.assert_called_once_with("corrections:ACME_RE", ["GWP"])

    @pytest.mark.asyncio
    async def test_handles_redis_error(self) -> None:
        client = AsyncMock()
        client.hmget.side_effect = redis.RedisError("unexpected")
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", ["GWP"])

        assert result == {}

    @pytest.mark.asyncio
    async def test_partial_match_returns_only_matched(self) -> None:
        """3 headers provided, only 1 has a correction — return just that one."""
        client = AsyncMock()
        client.hmget.return_value = [b"Policy_ID", None, None]
        cache = RedisCorrectionCache(client=client)

        result = await cache.get_corrections("ABC", ["Policy No.", "Notes", "Extra"])

        assert result == {"Policy No.": "Policy_ID"}
        assert "Notes" not in result
        assert "Extra" not in result


class TestRedisCorrectionCacheSet:
    """set_correction writes to Redis hash, gracefully degrades on error."""

    @pytest.mark.asyncio
    async def test_writes_to_hash(self) -> None:
        client = AsyncMock()
        cache = RedisCorrectionCache(client=client)
        correction = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")

        await cache.set_correction(correction)

        client.hset.assert_called_once_with("corrections:ABC", "GWP", "Gross_Premium")

    @pytest.mark.asyncio
    async def test_swallows_connection_error(self) -> None:
        client = AsyncMock()
        client.hset.side_effect = redis.ConnectionError("down")
        cache = RedisCorrectionCache(client=client)
        correction = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")

        await cache.set_correction(correction)  # should not raise

    @pytest.mark.asyncio
    async def test_swallows_redis_error(self) -> None:
        client = AsyncMock()
        client.hset.side_effect = redis.RedisError("unexpected")
        cache = RedisCorrectionCache(client=client)
        correction = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")

        await cache.set_correction(correction)  # should not raise

    @pytest.mark.asyncio
    async def test_logs_error_on_set_connection_failure(self) -> None:
        """Redis set failure emits an error log with cedent_id."""
        client = AsyncMock()
        client.hset.side_effect = redis.ConnectionError("down")
        cache = RedisCorrectionCache(client=client)
        correction = Correction(cedent_id="ABC", source_header="GWP", target_field="Gross_Premium")

        with structlog.testing.capture_logs() as logs:
            await cache.set_correction(correction)

        error_logs = [e for e in logs if e.get("event") == "correction_cache_set_failed"]
        assert len(error_logs) == 1
        assert error_logs[0]["cedent_id"] == "ABC"
        assert "down" in error_logs[0]["error"]
