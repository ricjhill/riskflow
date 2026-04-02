"""Port for interactive mapping session persistence."""

from typing import Protocol, runtime_checkable

from src.domain.model.session import MappingSession


@runtime_checkable
class MappingSessionStorePort(Protocol):
    """Stores and retrieves interactive mapping sessions."""

    def save(self, session: MappingSession) -> None: ...
    def get(self, session_id: str) -> MappingSession | None: ...
    def delete(self, session_id: str) -> None: ...
