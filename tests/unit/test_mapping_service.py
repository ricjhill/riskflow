"""Tests for MappingService orchestrator.

The service coordinates ingestor, mapper, cache, and row validation.
Tests use real CSV files (via tmp_path) and mocked mapper/cache to
test orchestration logic — call ordering, cache behavior, and confidence.
"""

import csv
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.parsers.ingestor import PolarsIngestor
from src.domain.model.errors import MappingConfidenceLowError
from src.domain.model.schema import ColumnMapping, MappingResult, ProcessingResult
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


def _write_csv(path: Path) -> str:
    """Write a minimal CSV that matches the mapping fixture."""
    file_path = str(path / "test.csv")
    with open(file_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Policy No.", "GWP", "Extra"])
        writer.writerow(["P001", "50000", "x"])
    return file_path


def _cache_key_for(headers: list[str]) -> str:
    normalized = "|".join(sorted(h.lower().strip() for h in headers))
    return hashlib.sha256(normalized.encode()).hexdigest()


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
def service(mapper: AsyncMock, cache: MagicMock) -> MappingService:
    return MappingService(
        ingestor=PolarsIngestor(),
        mapper=mapper,
        cache=cache,
    )


class TestMappingServiceOrchestration:
    """Test the coordination between ingestor, mapper, and cache."""

    @pytest.mark.asyncio
    async def test_returns_processing_result(
        self, service: MappingService, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        result = await service.process_file(path)
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_passes_headers_to_mapper(
        self, service: MappingService, mapper: AsyncMock, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        await service.process_file(path)
        call_args = mapper.map_headers.call_args
        assert call_args[0][0] == ["Policy No.", "GWP", "Extra"]


class TestCacheInteraction:
    """Test cache hit/miss behavior."""

    @pytest.mark.asyncio
    async def test_cache_miss_calls_mapper_and_stores(
        self,
        service: MappingService,
        cache: MagicMock,
        mapper: AsyncMock,
        tmp_path: Path,
    ) -> None:
        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = None
        await service.process_file(path)

        mapper.map_headers.assert_called_once()

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
        tmp_path: Path,
    ) -> None:
        path = _write_csv(tmp_path)
        cached_result = _make_mapping_result()
        cache.get_mapping.return_value = cached_result

        result = await service.process_file(path)

        mapper.map_headers.assert_not_called()
        cache.set_mapping.assert_not_called()
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_cache_key_is_deterministic(
        self,
        mapper: AsyncMock,
        cache: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Same headers in different order produce the same cache key."""
        # File 1: headers in one order
        f1 = str(tmp_path / "test1.csv")
        with open(f1, "w", newline="") as f:
            csv.writer(f).writerow(["Policy No.", "GWP", "Extra"])
            csv.writer(f).writerow(["P001", "50000", "x"])

        # File 2: headers in different order
        f2 = str(tmp_path / "test2.csv")
        with open(f2, "w", newline="") as f:
            csv.writer(f).writerow(["GWP", "Extra", "Policy No."])
            csv.writer(f).writerow(["50000", "x", "P001"])

        service = MappingService(
            ingestor=PolarsIngestor(), mapper=mapper, cache=cache
        )

        await service.process_file(f1)
        key1 = cache.get_mapping.call_args[0][0]

        cache.reset_mock()
        await service.process_file(f2)
        key2 = cache.get_mapping.call_args[0][0]

        assert key1 == key2


class TestCacheLogging:
    """Test that cache hit/miss events are logged via structlog."""

    @pytest.fixture(autouse=True)
    def _configure_structlog(self) -> None:
        from src.entrypoint.main import configure_logging

        configure_logging()

    @pytest.mark.asyncio
    async def test_logs_cache_miss(
        self,
        service: MappingService,
        cache: MagicMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import json

        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = None
        with caplog.at_level("INFO"):
            await service.process_file(path)
        log_events = [
            json.loads(r.message)
            for r in caplog.records
            if "cache_lookup" in r.message
        ]
        assert len(log_events) == 1
        assert log_events[0]["result"] == "miss"

    @pytest.mark.asyncio
    async def test_logs_cache_hit(
        self,
        service: MappingService,
        cache: MagicMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import json

        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = _make_mapping_result()
        with caplog.at_level("INFO"):
            await service.process_file(path)
        log_events = [
            json.loads(r.message)
            for r in caplog.records
            if "cache_lookup" in r.message
        ]
        assert len(log_events) == 1
        assert log_events[0]["result"] == "hit"


class TestConfidenceThreshold:
    """Test that low-confidence mappings are rejected."""

    @pytest.mark.asyncio
    async def test_raises_on_low_confidence(
        self,
        service: MappingService,
        mapper: AsyncMock,
        tmp_path: Path,
    ) -> None:
        path = _write_csv(tmp_path)
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.3)
        with pytest.raises(
            MappingConfidenceLowError, match="below threshold"
        ):
            await service.process_file(path)

    @pytest.mark.asyncio
    async def test_accepts_confidence_at_threshold(
        self,
        service: MappingService,
        mapper: AsyncMock,
        tmp_path: Path,
    ) -> None:
        path = _write_csv(tmp_path)
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.6)
        result = await service.process_file(path)
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_custom_threshold(
        self,
        mapper: AsyncMock,
        cache: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_csv(tmp_path)
        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            confidence_threshold=0.8,
        )
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.7)
        with pytest.raises(MappingConfidenceLowError):
            await service.process_file(path)


class TestPartialMapping:
    """When the SLM maps fewer than 6 target fields, the service should
    still return a result with the confidence report showing missing fields,
    rather than failing entirely."""

    @pytest.mark.asyncio
    async def test_partial_mapping_returns_result(
        self, cache: MagicMock, tmp_path: Path
    ) -> None:
        """A file with only 2 of 6 target fields should still process."""
        # CSV has Policy No. and GWP but not the other 4 target fields
        file_path = str(tmp_path / "partial.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Notes"])
            writer.writerow(["P001", "50000", "test"])

        # SLM maps only 2 fields
        partial_mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="Policy No.", target_field="Policy_ID", confidence=0.95),
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=["Notes"],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = partial_mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(), mapper=mapper, cache=cache
        )

        result = await service.process_file(file_path)
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_partial_mapping_reports_missing_fields(
        self, cache: MagicMock, tmp_path: Path
    ) -> None:
        file_path = str(tmp_path / "partial.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP"])
            writer.writerow(["P001", "50000"])

        partial_mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="Policy No.", target_field="Policy_ID", confidence=0.95),
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = partial_mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(), mapper=mapper, cache=cache
        )

        result = await service.process_file(file_path)
        assert "Inception_Date" in result.confidence_report.missing_fields
        assert "Currency" in result.confidence_report.missing_fields
        assert len(result.confidence_report.missing_fields) == 4

    @pytest.mark.asyncio
    async def test_partial_mapping_rows_are_invalid(
        self, cache: MagicMock, tmp_path: Path
    ) -> None:
        """Rows with missing required fields go to invalid_records."""
        file_path = str(tmp_path / "partial.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP"])
            writer.writerow(["P001", "50000"])

        partial_mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="Policy No.", target_field="Policy_ID", confidence=0.95),
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = partial_mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(), mapper=mapper, cache=cache
        )

        result = await service.process_file(file_path)
        # Row has Policy_ID and Gross_Premium but missing 4 other fields
        # → should be invalid because RiskRecord requires all 6
        assert len(result.valid_records) == 0
        assert len(result.invalid_records) == 1
        assert len(result.errors) == 1
