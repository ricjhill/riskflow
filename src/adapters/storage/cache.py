"""Cache adapters implementing CachePort.

RedisCache: production adapter backed by Redis. Gracefully degrades on
connection failures — cache is an optimization, not a requirement.

NullCache: no-op fallback used when Redis is unavailable or in tests.
"""

import contextlib
from typing import cast

import redis

from src.domain.model.schema import MappingResult

KEY_PREFIX = "riskflow:mapping:"


class RedisCache:
    """CachePort implementation backed by Redis."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def get_mapping(self, cache_key: str) -> MappingResult | None:
        """Retrieve a cached mapping result, or None on miss/error."""
        try:
            data = cast(bytes | None, self._client.get(f"{KEY_PREFIX}{cache_key}"))
        except (ConnectionError, redis.RedisError):
            return None

        if data is None:
            return None

        try:
            return MappingResult.model_validate_json(data)
        except (ValueError, TypeError):
            return None

    def set_mapping(self, cache_key: str, result: MappingResult, ttl: int = 3600) -> None:
        """Store a mapping result with TTL. Silently fails on error."""
        with contextlib.suppress(ConnectionError, redis.RedisError):
            self._client.setex(
                f"{KEY_PREFIX}{cache_key}",
                ttl,
                result.model_dump_json(),
            )


class NullCache:
    """No-op CachePort for when Redis is unavailable."""

    def get_mapping(self, cache_key: str) -> MappingResult | None:
        return None

    def set_mapping(self, cache_key: str, result: MappingResult, ttl: int = 3600) -> None:
        pass
