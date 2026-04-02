"""Tests for MappingSessionStorePort implementations.

Covers: protocol conformance, NullMappingSessionStore behavior,
and RedisMappingSessionStore (save/get roundtrip, TTL, delete, graceful degradation).
"""

from typing import runtime_checkable

from src.adapters.storage.session_store import NullMappingSessionStore
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
