"""Output port for human-verified mapping corrections."""

from typing import Protocol, runtime_checkable

from src.domain.model.correction import Correction


@runtime_checkable
class CorrectionCachePort(Protocol):
    """How the domain reads and writes correction mappings.

    get_corrections returns only the subset of headers that have
    corrections for the given cedent, as a {source_header: target_field}
    dict. This pre-filters to what is relevant for the current file.
    """

    async def get_corrections(self, cedent_id: str, headers: list[str]) -> dict[str, str]: ...

    async def set_correction(self, correction: Correction) -> None: ...
