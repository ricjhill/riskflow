"""Session store adapters for interactive mapping session persistence."""

from typing import Any

import redis as redis_lib
import structlog

from src.domain.model.session import MappingSession

KEY_PREFIX = "riskflow:session:"
DEFAULT_TTL = 3600  # 1 hour


class NullMappingSessionStore:
    """No-op fallback when Redis is unavailable."""

    async def save(self, session: MappingSession) -> None:
        pass

    async def get(self, session_id: str) -> MappingSession | None:
        return None

    async def delete(self, session_id: str) -> None:
        pass


class RedisMappingSessionStore:
    """Redis-backed session store. Sessions expire after TTL."""

    def __init__(self, client: Any, ttl: int = DEFAULT_TTL) -> None:
        self._client = client
        self._ttl = ttl
        self._logger = structlog.get_logger()

    async def save(self, session: MappingSession) -> None:
        try:
            await self._client.setex(
                f"{KEY_PREFIX}{session.id}",
                self._ttl,
                session.model_dump_json(),
            )
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("session_store_save_failed", session_id=session.id, error=str(exc))

    async def get(self, session_id: str) -> MappingSession | None:
        try:
            data = await self._client.get(f"{KEY_PREFIX}{session_id}")
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("session_store_get_failed", session_id=session_id, error=str(exc))
            return None
        if data is None:
            return None
        try:
            return MappingSession.model_validate_json(data)
        except (ValueError, TypeError):
            return None

    async def delete(self, session_id: str) -> None:
        try:
            await self._client.delete(f"{KEY_PREFIX}{session_id}")
        except (ConnectionError, redis_lib.RedisError) as exc:
            self._logger.error("session_store_delete_failed", session_id=session_id, error=str(exc))
