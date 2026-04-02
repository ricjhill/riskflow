"""Schema store adapters for runtime schema persistence."""

from src.domain.model.target_schema import TargetSchema


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
