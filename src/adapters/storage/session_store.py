"""Session store adapters for interactive mapping session persistence."""

from src.domain.model.session import MappingSession


class NullMappingSessionStore:
    """No-op fallback when Redis is unavailable."""

    def save(self, session: MappingSession) -> None:
        pass

    def get(self, session_id: str) -> MappingSession | None:
        return None

    def delete(self, session_id: str) -> None:
        pass
