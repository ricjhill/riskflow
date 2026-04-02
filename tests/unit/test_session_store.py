"""Tests for MappingSessionStorePort implementations.

Covers: protocol conformance, NullMappingSessionStore behavior,
and RedisMappingSessionStore (save/get roundtrip, TTL, delete, graceful degradation).
"""

from unittest.mock import MagicMock

import redis as redis_lib

from src.adapters.storage.session_store import (
    NullMappingSessionStore,
    RedisMappingSessionStore,
)
from src.domain.model.schema import ColumnMapping
from src.domain.model.session import MappingSession, SessionStatus
from src.ports.output.session_store import MappingSessionStorePort


def _make_session(session_id: str = "test-id-123") -> MappingSession:
    """Create a minimal session for testing."""
    return MappingSession(
        id=session_id,
        status=SessionStatus.CREATED,
        schema_name="standard_reinsurance",
        file_path="/tmp/test.csv",
        sheet_name=None,
        source_headers=["Premium"],
        target_fields=["Gross_Premium"],
        mappings=[
            ColumnMapping(
                source_header="Premium",
                target_field="Gross_Premium",
                confidence=0.95,
            ),
        ],
        unmapped_headers=[],
        preview_rows=[{"Premium": 1000}],
    )


class TestMappingSessionStoreProtocol:
    """Port is a runtime-checkable Protocol."""

    def test_null_store_satisfies_protocol(self) -> None:
        store = NullMappingSessionStore()
        assert isinstance(store, MappingSessionStorePort)


class TestNullMappingSessionStore:
    """No-op fallback — save is silent, get returns None, delete is silent."""

    def test_get_returns_none(self) -> None:
        store = NullMappingSessionStore()
        assert store.get("any-id") is None

    def test_save_does_not_raise(self) -> None:
        store = NullMappingSessionStore()
        session = _make_session()
        store.save(session)  # Should not raise

    def test_delete_does_not_raise(self) -> None:
        store = NullMappingSessionStore()
        store.delete("any-id")  # Should not raise


class TestRedisMappingSessionStoreProtocol:
    """Redis adapter satisfies the port protocol."""

    def test_satisfies_protocol(self) -> None:
        store = RedisMappingSessionStore(client=MagicMock())
        assert isinstance(store, MappingSessionStorePort)


class TestRedisMappingSessionStoreSaveGet:
    """Save/get roundtrip with mocked Redis client."""

    def test_save_and_get_roundtrip(self) -> None:
        client = MagicMock()
        store = RedisMappingSessionStore(client=client)
        session = _make_session("roundtrip-id")

        store.save(session)

        # Verify setex was called with correct key and TTL
        call_args = client.setex.call_args
        assert call_args[0][0] == "riskflow:session:roundtrip-id"
        assert call_args[0][1] == 3600  # Default TTL
        stored_json = call_args[0][2]

        # Simulate Redis returning the stored JSON
        client.get.return_value = (
            stored_json.encode() if isinstance(stored_json, str) else stored_json
        )
        retrieved = store.get("roundtrip-id")

        assert retrieved is not None
        assert retrieved.id == "roundtrip-id"
        assert retrieved.status == SessionStatus.CREATED
        assert retrieved.schema_name == "standard_reinsurance"
        assert len(retrieved.mappings) == 1
        assert retrieved.mappings[0].source_header == "Premium"

    def test_get_returns_none_on_miss(self) -> None:
        client = MagicMock()
        client.get.return_value = None
        store = RedisMappingSessionStore(client=client)
        assert store.get("nonexistent") is None

    def test_get_returns_none_on_corrupt_data(self) -> None:
        client = MagicMock()
        client.get.return_value = b"not-valid-json"
        store = RedisMappingSessionStore(client=client)
        assert store.get("corrupt") is None


class TestRedisMappingSessionStoreDelete:
    """Delete removes the key from Redis."""

    def test_delete_calls_redis_delete(self) -> None:
        client = MagicMock()
        store = RedisMappingSessionStore(client=client)
        store.delete("del-id")
        client.delete.assert_called_once_with("riskflow:session:del-id")


class TestRedisMappingSessionStoreGracefulDegradation:
    """Redis errors are swallowed — session store is best-effort."""

    def test_save_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.setex.side_effect = ConnectionError("gone")
        store = RedisMappingSessionStore(client=client)
        store.save(_make_session())  # Should not raise

    def test_save_swallows_redis_error(self) -> None:
        client = MagicMock()
        client.setex.side_effect = redis_lib.RedisError("oops")
        store = RedisMappingSessionStore(client=client)
        store.save(_make_session())  # Should not raise

    def test_get_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.get.side_effect = ConnectionError("gone")
        store = RedisMappingSessionStore(client=client)
        assert store.get("any") is None

    def test_get_swallows_redis_error(self) -> None:
        client = MagicMock()
        client.get.side_effect = redis_lib.RedisError("oops")
        store = RedisMappingSessionStore(client=client)
        assert store.get("any") is None

    def test_delete_swallows_connection_error(self) -> None:
        client = MagicMock()
        client.delete.side_effect = ConnectionError("gone")
        store = RedisMappingSessionStore(client=client)
        store.delete("any")  # Should not raise

    def test_delete_swallows_redis_error(self) -> None:
        client = MagicMock()
        client.delete.side_effect = redis_lib.RedisError("oops")
        store = RedisMappingSessionStore(client=client)
        store.delete("any")  # Should not raise
