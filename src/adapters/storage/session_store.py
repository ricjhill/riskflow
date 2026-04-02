"""Session store adapters for interactive mapping session persistence."""

from typing import Any, cast

import redis as redis_lib

from src.domain.model.session import MappingSession

KEY_PREFIX = "riskflow:session:"
DEFAULT_TTL = 3600  # 1 hour


class NullMappingSessionStore:
    """No-op fallback when Redis is unavailable."""

    def save(self, session: MappingSession) -> None:
        pass

    def get(self, session_id: str) -> MappingSession | None:
        return None

    def delete(self, session_id: str) -> None:
        pass


class RedisMappingSessionStore:
    """Redis-backed session store. Sessions expire after TTL."""

    def __init__(self, client: Any, ttl: int = DEFAULT_TTL) -> None:
        self._client = client
        self._ttl = ttl

    def save(self, session: MappingSession) -> None:
        try:
            self._client.setex(
                f"{KEY_PREFIX}{session.id}",
                self._ttl,
                session.model_dump_json(),
            )
        except (ConnectionError, redis_lib.RedisError):
            pass

    def get(self, session_id: str) -> MappingSession | None:
        try:
            data = cast(bytes | None, self._client.get(f"{KEY_PREFIX}{session_id}"))
        except (ConnectionError, redis_lib.RedisError):
            return None
        if data is None:
            return None
        try:
            return MappingSession.model_validate_json(data)
        except (ValueError, TypeError):
            return None

    def delete(self, session_id: str) -> None:
        try:
            self._client.delete(f"{KEY_PREFIX}{session_id}")
        except (ConnectionError, redis_lib.RedisError):
            pass
