"""Port for interactive mapping session persistence."""

from typing import Protocol, runtime_checkable

from src.domain.model.session import MappingSession


@runtime_checkable
class MappingSessionStorePort(Protocol):
    """Stores and retrieves interactive mapping sessions."""

    async def save(self, session: MappingSession) -> None: ...
    async def get(self, session_id: str) -> MappingSession | None: ...
    async def delete(self, session_id: str) -> None: ...
