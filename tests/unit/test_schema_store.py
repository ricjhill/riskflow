"""Tests for SchemaStorePort and its implementations.

The SchemaStorePort persists runtime schemas to Redis. Bootstrap schemas
from YAML files are loaded separately at startup and are not stored here.
"""

import structlog.testing

from src.adapters.storage.schema_store import NullSchemaStore
from src.domain.model.target_schema import FieldDefinition, FieldType, TargetSchema
from src.ports.output.schema_store import SchemaStorePort


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


class TestRedisSchemaStoreProtocol:
    def test_satisfies_schema_store_port(self) -> None:
        from unittest.mock import MagicMock

        client = MagicMock()
        from src.adapters.storage.schema_store import RedisSchemaStore

        assert isinstance(RedisSchemaStore(client=client), SchemaStorePort)


class TestRedisSchemaStoreGetSave:
    def test_save_then_get_roundtrip(self) -> None:
        from unittest.mock import MagicMock

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        store = RedisSchemaStore(client=client)
        schema = _make_schema("my_schema")

        store.save(schema)
        client.set.assert_called_once()
        call_args = client.set.call_args
        assert "riskflow:schema:my_schema" in str(call_args)

    def test_get_returns_schema(self) -> None:
        from unittest.mock import MagicMock

        from src.adapters.storage.schema_store import RedisSchemaStore

        schema = _make_schema("my_schema")
        client = MagicMock()
        client.get.return_value = schema.model_dump_json().encode()
        store = RedisSchemaStore(client=client)

        result = store.get("my_schema")
        assert result is not None
        assert result.name == "my_schema"
        assert result.field_names == schema.field_names

    def test_get_unknown_returns_none(self) -> None:
        from unittest.mock import MagicMock

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.get.return_value = None
        store = RedisSchemaStore(client=client)

        assert store.get("nonexistent") is None

    def test_get_graceful_on_connection_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.get.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        assert store.get("any") is None

    def test_save_graceful_on_connection_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.set.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        store.save(_make_schema())  # Should not raise


class TestRedisSchemaStoreDeleteListAll:
    def test_delete_calls_redis_delete(self) -> None:
        from unittest.mock import MagicMock

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        store = RedisSchemaStore(client=client)
        store.delete("my_schema")
        client.delete.assert_called_once_with("riskflow:schema:my_schema")

    def test_delete_graceful_on_connection_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.delete.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)
        store.delete("any")  # Should not raise

    def test_list_all_returns_names(self) -> None:
        from unittest.mock import MagicMock

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.scan.return_value = (0, [b"riskflow:schema:alpha", b"riskflow:schema:beta"])
        store = RedisSchemaStore(client=client)

        result = store.list_all()
        assert result == ["alpha", "beta"]

    def test_list_all_returns_empty_on_no_schemas(self) -> None:
        from unittest.mock import MagicMock

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.scan.return_value = (0, [])
        store = RedisSchemaStore(client=client)

        assert store.list_all() == []

    def test_list_all_graceful_on_connection_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.scan.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        assert store.list_all() == []


class TestRedisSchemaStoreErrorLogging:
    """Redis failures emit error-level structlog events."""

    def test_get_logs_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.get.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        with structlog.testing.capture_logs() as logs:
            store.get("test")

        error_logs = [l for l in logs if l.get("event") == "schema_store_get_failed"]
        assert len(error_logs) == 1
        assert error_logs[0]["schema_name"] == "test"

    def test_save_logs_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.set.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        with structlog.testing.capture_logs() as logs:
            store.save(_make_schema())

        error_logs = [l for l in logs if l.get("event") == "schema_store_save_failed"]
        assert len(error_logs) == 1

    def test_delete_logs_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.delete.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        with structlog.testing.capture_logs() as logs:
            store.delete("test")

        error_logs = [l for l in logs if l.get("event") == "schema_store_delete_failed"]
        assert len(error_logs) == 1

    def test_list_all_logs_error(self) -> None:
        from unittest.mock import MagicMock

        import redis as redis_lib

        from src.adapters.storage.schema_store import RedisSchemaStore

        client = MagicMock()
        client.scan.side_effect = redis_lib.ConnectionError("down")
        store = RedisSchemaStore(client=client)

        with structlog.testing.capture_logs() as logs:
            store.list_all()

        error_logs = [l for l in logs if l.get("event") == "schema_store_list_failed"]
        assert len(error_logs) == 1
