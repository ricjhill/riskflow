"""Port for runtime schema persistence."""

from typing import Protocol, runtime_checkable

from src.domain.model.target_schema import TargetSchema


@runtime_checkable
class SchemaStorePort(Protocol):
    """Stores and retrieves runtime schemas (not bootstrap YAML schemas)."""

    async def get(self, name: str) -> TargetSchema | None: ...
    async def save(self, schema: TargetSchema) -> None: ...
    async def delete(self, name: str) -> None: ...
    async def list_all(self) -> list[str]: ...
