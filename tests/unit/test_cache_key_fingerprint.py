"""Tests for schema-aware cache key generation.

Loop 16: Cache key includes the schema fingerprint so that changing
the target schema invalidates cached mappings. Without this, switching
from schema A to schema B with the same source headers would return
stale mappings from schema A.
"""

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.model.target_schema import (
    FieldDefinition,
    FieldType,
    TargetSchema,
)
from src.domain.service.mapping_service import MappingService


def _make_service(schema: TargetSchema | None = None) -> MappingService:
    """Create a MappingService with mocked ports and optional schema."""
    ingestor = MagicMock()
    mapper = MagicMock()
    cache = MagicMock()
    return MappingService(
        ingestor=ingestor,
        mapper=mapper,
        cache=cache,
        schema=schema,
    )


SCHEMA_A = TargetSchema(
    name="schema_a",
    fields={
        "Policy_ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
        "Premium": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
    },
)

SCHEMA_B = TargetSchema(
    name="schema_b",
    fields={
        "Policy_ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
        "Amount": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
    },
)


class TestCacheKeyIncludesFingerprint:
    """Cache key must incorporate the schema fingerprint."""

    def test_same_headers_same_schema_same_key(self) -> None:
        """Identical headers and schema produce the same cache key."""
        service = _make_service(SCHEMA_A)
        key1 = service._build_cache_key(["Col1", "Col2"])
        key2 = service._build_cache_key(["Col1", "Col2"])
        assert key1 == key2

    def test_same_headers_different_schema_different_key(self) -> None:
        """Same headers but different schemas must produce different keys."""
        service_a = _make_service(SCHEMA_A)
        service_b = _make_service(SCHEMA_B)
        key_a = service_a._build_cache_key(["Col1", "Col2"])
        key_b = service_b._build_cache_key(["Col1", "Col2"])
        assert key_a != key_b

    def test_cache_key_is_deterministic(self) -> None:
        """Same inputs always produce the same key."""
        service = _make_service(SCHEMA_A)
        keys = [service._build_cache_key(["X", "Y"]) for _ in range(10)]
        assert len(set(keys)) == 1

    def test_cache_key_ignores_header_order(self) -> None:
        """Headers in different orders produce the same key."""
        service = _make_service(SCHEMA_A)
        key1 = service._build_cache_key(["Col1", "Col2", "Col3"])
        key2 = service._build_cache_key(["Col3", "Col1", "Col2"])
        assert key1 == key2

    def test_cache_key_contains_fingerprint(self) -> None:
        """The schema fingerprint is part of the cache key derivation."""
        service = _make_service(SCHEMA_A)
        key = service._build_cache_key(["Col1"])
        # Key should be different from a pure header-only hash
        header_only = hashlib.sha256("col1".encode()).hexdigest()
        assert key != header_only


class TestCacheKeyInService:
    """MappingService uses schema-aware key for cache lookups."""

    @pytest.mark.asyncio
    async def test_cache_hit_uses_schema_aware_key(self) -> None:
        """Cache.get_mapping is called with a key that includes the fingerprint."""
        service = _make_service(SCHEMA_A)
        service._ingestor.get_headers.return_value = ["Col1"]
        service._ingestor.get_preview.return_value = [{"Col1": "val"}]

        expected_key = service._build_cache_key(["Col1"])
        mapping = MappingResult(
            mappings=[
                ColumnMapping(
                    source_header="Col1", target_field="Policy_ID", confidence=0.9
                )
            ],
            unmapped_headers=[],
        )
        service._cache.get_mapping.return_value = mapping

        with patch.object(service, "_validate_rows") as mock_validate:
            mock_validate.return_value = MagicMock()
            await service.process_file("test.csv")

        service._cache.get_mapping.assert_called_once_with(expected_key)
