"""Port for runtime schema persistence."""

from typing import Protocol, runtime_checkable

from src.domain.model.target_schema import TargetSchema


@runtime_checkable
class SchemaStorePort(Protocol):
    """Stores and retrieves runtime schemas (not bootstrap YAML schemas)."""

    def get(self, name: str) -> TargetSchema | None: ...
    def save(self, schema: TargetSchema) -> None: ...
    def delete(self, name: str) -> None: ...
    def list_all(self) -> list[str]: ...
