"""Tests for MappingService orchestrator.

The service coordinates ingestor, mapper, cache, and validation.
All ports are mocked — this tests orchestration logic only.
"""

import hashlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.errors import MappingConfidenceLowError
from src.domain.model.schema import ColumnMapping, MappingResult
from src.domain.service.mapping_service import MappingService


def _make_mapping_result(confidence: float = 0.95) -> MappingResult:
    return MappingResult(
        mappings=[
            ColumnMapping(
                source_header="Policy No.",
                target_field="Policy_ID",
                confidence=confidence,
            ),
            ColumnMapping(
                source_header="GWP",
                target_field="Gross_Premium",
                confidence=confidence,
            ),
        ],
        unmapped_headers=["Extra"],
    )


def _cache_key_for(headers: list[str]) -> str:
    """Reproduce the expected cache key algorithm."""
    normalized = "|".join(sorted(h.lower().strip() for h in headers))
    return hashlib.sha256(normalized.encode()).hexdigest()


@pytest.fixture
def ingestor() -> MagicMock:
    mock = MagicMock()
    mock.get_headers.return_value = ["Policy No.", "GWP", "Extra"]
    mock.get_preview.return_value = [
        {"Policy No.": "P001", "GWP": 50000, "Extra": "x"},
    ]
    return mock


@pytest.fixture
def mapper() -> AsyncMock:
    mock = AsyncMock()
    mock.map_headers.return_value = _make_mapping_result()
    return mock


@pytest.fixture
def cache() -> MagicMock:
    mock = MagicMock()
    mock.get_mapping.return_value = None
    return mock


@pytest.fixture
def service(
    ingestor: MagicMock, mapper: AsyncMock, cache: MagicMock
) -> MappingService:
    return MappingService(
        ingestor=ingestor,
        mapper=mapper,
        cache=cache,
    )


class TestMappingServiceOrchestration:
    """Test the coordination between ingestor, mapper, and cache."""

    @pytest.mark.asyncio
    async def test_calls_ingestor_with_file_path(
        self, service: MappingService, ingestor: MagicMock
    ) -> None:
        await service.process_file("/data/test.csv")
        ingestor.get_headers.assert_called_once_with("/data/test.csv")
        ingestor.get_preview.assert_called_once_with("/data/test.csv")

    @pytest.mark.asyncio
    async def test_returns_mapping_result(
        self, service: MappingService
    ) -> None:
        result = await service.process_file("/data/test.csv")
        assert isinstance(result, MappingResult)
        assert len(result.mappings) == 2

    @pytest.mark.asyncio
    async def test_passes_headers_and_preview_to_mapper(
        self, service: MappingService, mapper: AsyncMock
    ) -> None:
        await service.process_file("/data/test.csv")
        mapper.map_headers.assert_called_once_with(
            ["Policy No.", "GWP", "Extra"],
            [{"Policy No.": "P001", "GWP": 50000, "Extra": "x"}],
        )


class TestCacheInteraction:
    """Test cache hit/miss behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_mapper_and_stores(
        self,
        service: MappingService,
        cache: MagicMock,
        mapper: AsyncMock,
    ) -> None:
        cache.get_mapping.return_value = None
        await service.process_file("/data/test.csv")

        # Mapper should be called on cache miss
        mapper.map_headers.assert_called_once()

        # Result should be stored in cache
        expected_key = _cache_key_for(["Policy No.", "GWP", "Extra"])
        cache.set_mapping.assert_called_once()
        actual_key = cache.set_mapping.call_args[0][0]
        assert actual_key == expected_key

    @pytest.mark.asyncio
    async def test_cache_hit_skips_mapper(
        self,
        service: MappingService,
        cache: MagicMock,
        mapper: AsyncMock,
    ) -> None:
        cached_result = _make_mapping_result()
        cache.get_mapping.return_value = cached_result

        result = await service.process_file("/data/test.csv")

        # Mapper should NOT be called on cache hit
        mapper.map_headers.assert_not_called()
        # Cache should NOT be written again
        cache.set_mapping.assert_not_called()
        # Should return the cached result
        assert result == cached_result

    @pytest.mark.asyncio
    async def test_cache_key_is_deterministic(
        self,
        service: MappingService,
        cache: MagicMock,
    ) -> None:
        """Same headers in different order should produce the same cache key."""
        await service.process_file("/data/test.csv")
        key1 = cache.get_mapping.call_args[0][0]

        # Reset and change header order
        cache.reset_mock()
        service._ingestor.get_headers.return_value = ["GWP", "Extra", "Policy No."]
        await service.process_file("/data/test.csv")
        key2 = cache.get_mapping.call_args[0][0]

        assert key1 == key2


class TestConfidenceThreshold:
    """Test that low-confidence mappings are rejected."""

    @pytest.mark.asyncio
    async def test_raises_on_low_confidence(
        self,
        service: MappingService,
        mapper: AsyncMock,
    ) -> None:
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.3)
        with pytest.raises(
            MappingConfidenceLowError, match="below threshold"
        ):
            await service.process_file("/data/test.csv")

    @pytest.mark.asyncio
    async def test_accepts_confidence_at_threshold(
        self,
        service: MappingService,
        mapper: AsyncMock,
    ) -> None:
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.6)
        result = await service.process_file("/data/test.csv")
        assert len(result.mappings) == 2

    @pytest.mark.asyncio
    async def test_custom_threshold(
        self,
        ingestor: MagicMock,
        mapper: AsyncMock,
        cache: MagicMock,
    ) -> None:
        service = MappingService(
            ingestor=ingestor,
            mapper=mapper,
            cache=cache,
            confidence_threshold=0.8,
        )
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.7)
        with pytest.raises(MappingConfidenceLowError):
            await service.process_file("/data/test.csv")
