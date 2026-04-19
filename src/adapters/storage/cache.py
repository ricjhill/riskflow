"""Cache adapters implementing CachePort.

RedisCache: production adapter backed by async Redis. Gracefully degrades on
connection failures — cache is an optimization, not a requirement.

NullCache: no-op fallback used when Redis is unavailable or in tests.
"""

from typing import Any

import redis
import structlog

from src.domain.model.schema import MappingResult

KEY_PREFIX = "riskflow:mapping:"


class RedisCache:
    """CachePort implementation backed by async Redis."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._logger = structlog.get_logger()

    async def get_mapping(self, cache_key: str) -> MappingResult | None:
        """Retrieve a cached mapping result, or None on miss/error."""
        try:
            data = await self._client.get(f"{KEY_PREFIX}{cache_key}")
        except (ConnectionError, redis.RedisError) as exc:
            self._logger.error("cache_get_failed", cache_key=cache_key, error=str(exc))
            return None

        if data is None:
            return None

        try:
            return MappingResult.model_validate_json(data)
        except (ValueError, TypeError):
            return None

    async def set_mapping(self, cache_key: str, result: MappingResult, ttl: int = 3600) -> None:
        """Store a mapping result with TTL. Silently fails on error."""
        try:
            await self._client.setex(
                f"{KEY_PREFIX}{cache_key}",
                ttl,
                result.model_dump_json(),
            )
        except (ConnectionError, redis.RedisError) as exc:
            self._logger.error("cache_set_failed", cache_key=cache_key, error=str(exc))


class NullCache:
    """No-op CachePort for when Redis is unavailable."""

    async def get_mapping(self, cache_key: str) -> MappingResult | None:
        return None

    async def set_mapping(self, cache_key: str, result: MappingResult, ttl: int = 3600) -> None:
        pass
