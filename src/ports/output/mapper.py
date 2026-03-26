"""Output port for SLM header mapping."""

from typing import Protocol, runtime_checkable

from src.domain.model.schema import MappingResult


@runtime_checkable
class MapperPort(Protocol):
    """How the domain calls the SLM to map headers."""

    async def map_headers(
        self,
        source_headers: list[str],
        preview_rows: list[dict[str, object]],
    ) -> MappingResult: ...
