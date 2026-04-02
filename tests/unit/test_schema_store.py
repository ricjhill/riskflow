"""Tests for SchemaStorePort and its implementations.

The SchemaStorePort persists runtime schemas to Redis. Bootstrap schemas
from YAML files are loaded separately at startup and are not stored here.
"""

from src.adapters.storage.schema_store import NullSchemaStore
from src.ports.output.schema_store import SchemaStorePort

from src.domain.model.target_schema import FieldDefinition, FieldType, TargetSchema


def _make_schema(name: str = "test_schema") -> TargetSchema:
    return TargetSchema(
        name=name,
        fields={
            "ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
            "Amount": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
        },
    )


class TestNullSchemaStoreProtocol:
    def test_satisfies_schema_store_port(self) -> None:
        assert isinstance(NullSchemaStore(), SchemaStorePort)


class TestNullSchemaStore:
    def test_get_returns_none(self) -> None:
        store = NullSchemaStore()
        assert store.get("anything") is None

    def test_list_all_returns_empty(self) -> None:
        store = NullSchemaStore()
        assert store.list_all() == []

    def test_save_is_noop(self) -> None:
        store = NullSchemaStore()
        store.save(_make_schema())  # Should not raise

    def test_delete_is_noop(self) -> None:
        store = NullSchemaStore()
        store.delete("anything")  # Should not raise
