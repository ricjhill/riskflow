"""Correction cache adapters for human-verified mapping corrections.

NullCorrectionCache: no-op fallback when Redis is unavailable.
RedisCorrectionCache: Redis hash per cedent — corrections:{cedent_id}
  with fields {source_header} and values {target_field}.
"""

from typing import Any

import redis as redis_lib
import structlog

from src.domain.model.correction import Correction

CORRECTION_KEY_PREFIX = "corrections:"


class NullCorrectionCache:
    """No-op correction cache — returns no corrections, discards writes.

    Used when Redis is unavailable or no cedent_id is provided.
    """

    async def get_corrections(self, cedent_id: str, headers: list[str]) -> dict[str, str]:
        return {}

    async def set_correction(self, correction: Correction) -> None:
        pass


class RedisCorrectionCache:
    """Redis-backed correction cache using one hash per cedent.

    Key: corrections:{cedent_id}
    Fields: source_header → target_field

    Uses HMGET for batch lookup (one round-trip for all headers)
    and HSET for single writes. Gracefully degrades on connection
    errors — returns empty dict / logs errors.
    """

    def __init__(self, client: Any) -> None:
        self._client = client
        self._logger = structlog.get_logger()

    async def get_corrections(self, cedent_id: str, headers: list[str]) -> dict[str, str]:
        if not headers:
            return {}
        try:
            key = f"{CORRECTION_KEY_PREFIX}{cedent_id}"
            values: list[bytes | None] = await self._client.hmget(key, headers)
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("correction_cache_get_failed", cedent_id=cedent_id, error=str(exc))
            return {}
        return {
            header: value.decode()
            for header, value in zip(headers, values, strict=True)
            if value is not None
        }

    async def set_correction(self, correction: Correction) -> None:
        try:
            key = f"{CORRECTION_KEY_PREFIX}{correction.cedent_id}"
            await self._client.hset(key, correction.source_header, correction.target_field)
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error(
                "correction_cache_set_failed", cedent_id=correction.cedent_id, error=str(exc)
            )
