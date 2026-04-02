"""Schema store adapters for runtime schema persistence."""

from typing import Any, cast

import redis as redis_lib

from src.domain.model.target_schema import TargetSchema

KEY_PREFIX = "riskflow:schema:"


class NullSchemaStore:
    """No-op fallback when Redis is unavailable."""

    def get(self, name: str) -> TargetSchema | None:
        return None

    def save(self, schema: TargetSchema) -> None:
        pass

    def delete(self, name: str) -> None:
        pass

    def list_all(self) -> list[str]:
        return []


class RedisSchemaStore:
    """Redis-backed schema store. Persists schemas as JSON strings."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def get(self, name: str) -> TargetSchema | None:
        try:
            data = cast(bytes | None, self._client.get(f"{KEY_PREFIX}{name}"))
        except (ConnectionError, redis_lib.RedisError):
            return None
        if data is None:
            return None
        try:
            return TargetSchema.model_validate_json(data)
        except (ValueError, TypeError):
            return None

    def save(self, schema: TargetSchema) -> None:
        try:
            self._client.set(f"{KEY_PREFIX}{schema.name}", schema.model_dump_json())
        except (ConnectionError, redis_lib.RedisError):
            pass

    def delete(self, name: str) -> None:
        try:
            self._client.delete(f"{KEY_PREFIX}{name}")
        except (ConnectionError, redis_lib.RedisError):
            pass

    def list_all(self) -> list[str]:
        try:
            names: list[str] = []
            cursor: int = 0
            while True:
                cursor, keys = self._client.scan(cursor=cursor, match=f"{KEY_PREFIX}*", count=100)
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    names.append(key_str.removeprefix(KEY_PREFIX))
                if cursor == 0:
                    break
            return sorted(names)
        except (ConnectionError, redis_lib.RedisError, ValueError, TypeError):
            return []
