"""Correction cache adapters for human-verified mapping corrections.

NullCorrectionCache: no-op fallback when Redis is unavailable.
RedisCorrectionCache: Redis hash per cedent — corrections:{cedent_id}
  with fields {source_header} and values {target_field}.
"""

import contextlib

import redis as redis_lib

from src.domain.model.correction import Correction

CORRECTION_KEY_PREFIX = "corrections:"


class NullCorrectionCache:
    """No-op correction cache — returns no corrections, discards writes.

    Used when Redis is unavailable or no cedent_id is provided.
    """

    def get_corrections(self, cedent_id: str, headers: list[str]) -> dict[str, str]:
        return {}

    def set_correction(self, correction: Correction) -> None:
        pass


class RedisCorrectionCache:
    """Redis-backed correction cache using one hash per cedent.

    Key: corrections:{cedent_id}
    Fields: source_header → target_field

    Uses HMGET for batch lookup (one round-trip for all headers)
    and HSET for single writes. Gracefully degrades on connection
    errors — returns empty dict / silently drops writes.
    """

    def __init__(self, client: redis_lib.Redis) -> None:
        self._client = client

    def get_corrections(self, cedent_id: str, headers: list[str]) -> dict[str, str]:
        if not headers:
            return {}
        try:
            key = f"{CORRECTION_KEY_PREFIX}{cedent_id}"
            values: list[bytes | None] = self._client.hmget(key, headers)  # type: ignore[assignment]
        except (ConnectionError, redis_lib.RedisError):
            return {}
        return {
            header: value.decode()
            for header, value in zip(headers, values, strict=True)
            if value is not None
        }

    def set_correction(self, correction: Correction) -> None:
        with contextlib.suppress(ConnectionError, redis_lib.RedisError):
            key = f"{CORRECTION_KEY_PREFIX}{correction.cedent_id}"
            self._client.hset(key, correction.source_header, correction.target_field)
