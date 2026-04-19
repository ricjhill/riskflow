"""Output port for mapping cache."""

from typing import Protocol, runtime_checkable

from src.domain.model.schema import MappingResult


@runtime_checkable
class CachePort(Protocol):
    """How the domain caches mapping results."""

    async def get_mapping(self, cache_key: str) -> MappingResult | None: ...

    async def set_mapping(self, cache_key: str, result: MappingResult, ttl: int = 3600) -> None: ...
