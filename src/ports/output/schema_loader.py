"""Output port for loading target schema configuration."""

from typing import Protocol, runtime_checkable

from src.domain.model.target_schema import TargetSchema


@runtime_checkable
class SchemaLoaderPort(Protocol):
    """How the domain loads target schema definitions."""

    def load(self, path: str) -> TargetSchema: ...
