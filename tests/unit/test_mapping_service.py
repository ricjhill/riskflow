"""Tests for MappingService orchestrator.

The service coordinates ingestor, mapper, cache, and row validation.
Tests use real CSV files (via tmp_path) and mocked mapper/cache to
test orchestration logic — call ordering, cache behavior, and confidence.
"""

import csv
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.adapters.parsers.ingestor import PolarsIngestor
from src.domain.model.errors import InvalidCorrectionError, MappingConfidenceLowError
from src.domain.model.schema import ColumnMapping, MappingResult, ProcessingResult
from src.domain.model.target_schema import (
    DEFAULT_TARGET_SCHEMA,
    FieldDefinition,
    FieldType,
    TargetSchema,
)
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


def _cache_key_for(headers: list[str], schema: TargetSchema = DEFAULT_TARGET_SCHEMA) -> str:
    normalized = "|".join(sorted(h.lower().strip() for h in headers))
    key_input = f"{schema.fingerprint}:{normalized}"
    return hashlib.sha256(key_input.encode()).hexdigest()


@pytest.fixture
def mapper() -> AsyncMock:
    mock = AsyncMock()
    mock.map_headers.return_value = _make_mapping_result()
    return mock


@pytest.fixture
def cache() -> AsyncMock:
    mock = AsyncMock()
    mock.get_mapping.return_value = None
    return mock


@pytest.fixture
def service(mapper: AsyncMock, cache: AsyncMock) -> MappingService:
    return MappingService(
        ingestor=PolarsIngestor(),
        mapper=mapper,
        cache=cache,
    )


class TestMappingServiceOrchestration:
    """Test the coordination between ingestor, mapper, and cache."""

    @pytest.mark.asyncio
    async def test_returns_processing_result(self, service: MappingService, tmp_path: Path) -> None:
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
        cache: AsyncMock,
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
        cache: AsyncMock,
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
        cache: AsyncMock,
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

        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)

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

    @pytest.fixture
    def service(self, mapper: AsyncMock, cache: AsyncMock) -> MappingService:
        """Override module-level fixture to inject structlog logger."""
        import structlog

        return MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            logger=structlog.get_logger(),
        )

    @pytest.mark.asyncio
    async def test_logs_cache_miss(
        self,
        service: MappingService,
        cache: AsyncMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import json

        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = None
        with caplog.at_level("INFO"):
            await service.process_file(path)
        log_events = [json.loads(r.message) for r in caplog.records if "cache_lookup" in r.message]
        assert len(log_events) == 1
        assert log_events[0]["result"] == "miss"

    @pytest.mark.asyncio
    async def test_logs_cache_hit(
        self,
        service: MappingService,
        cache: AsyncMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import json

        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = _make_mapping_result()
        with caplog.at_level("INFO"):
            await service.process_file(path)
        log_events = [json.loads(r.message) for r in caplog.records if "cache_lookup" in r.message]
        assert len(log_events) == 1
        assert log_events[0]["result"] == "hit"

    @pytest.mark.asyncio
    async def test_cache_miss_includes_duration_ms(
        self,
        service: MappingService,
        cache: AsyncMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Issue #117: cache_lookup events must include duration_ms."""
        import json

        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = None
        with caplog.at_level("INFO"):
            await service.process_file(path)
        log_events = [json.loads(r.message) for r in caplog.records if "cache_lookup" in r.message]
        assert len(log_events) == 1
        assert "duration_ms" in log_events[0]
        assert isinstance(log_events[0]["duration_ms"], int)
        assert log_events[0]["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_cache_hit_includes_duration_ms(
        self,
        service: MappingService,
        cache: AsyncMock,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Issue #117: cache_lookup events must include duration_ms."""
        import json

        path = _write_csv(tmp_path)
        cache.get_mapping.return_value = _make_mapping_result()
        with caplog.at_level("INFO"):
            await service.process_file(path)
        log_events = [json.loads(r.message) for r in caplog.records if "cache_lookup" in r.message]
        assert len(log_events) == 1
        assert "duration_ms" in log_events[0]
        assert isinstance(log_events[0]["duration_ms"], int)
        assert log_events[0]["duration_ms"] >= 0


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
        with pytest.raises(MappingConfidenceLowError, match="below threshold"):
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
        cache: AsyncMock,
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
    async def test_partial_mapping_returns_result(self, cache: AsyncMock, tmp_path: Path) -> None:
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
                ColumnMapping(
                    source_header="Policy No.", target_field="Policy_ID", confidence=0.95
                ),
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=["Notes"],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = partial_mapping
        cache.get_mapping.return_value = None

        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)

        result = await service.process_file(file_path)
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_partial_mapping_reports_missing_fields(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        file_path = str(tmp_path / "partial.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP"])
            writer.writerow(["P001", "50000"])

        partial_mapping = MappingResult(
            mappings=[
                ColumnMapping(
                    source_header="Policy No.", target_field="Policy_ID", confidence=0.95
                ),
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = partial_mapping
        cache.get_mapping.return_value = None

        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)

        result = await service.process_file(file_path)
        assert "Inception_Date" in result.confidence_report.missing_fields
        assert "Currency" in result.confidence_report.missing_fields
        assert len(result.confidence_report.missing_fields) == 4

    @pytest.mark.asyncio
    async def test_partial_mapping_rows_are_invalid(self, cache: AsyncMock, tmp_path: Path) -> None:
        """Rows with missing required fields go to invalid_records."""
        file_path = str(tmp_path / "partial.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP"])
            writer.writerow(["P001", "50000"])

        partial_mapping = MappingResult(
            mappings=[
                ColumnMapping(
                    source_header="Policy No.", target_field="Policy_ID", confidence=0.95
                ),
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = partial_mapping
        cache.get_mapping.return_value = None

        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)

        result = await service.process_file(file_path)
        # Row has Policy_ID and Gross_Premium but missing 4 other fields
        # → should be invalid because the schema requires all 6
        assert len(result.valid_records) == 0
        assert len(result.invalid_records) == 1
        assert len(result.errors) == 1


class TestCustomSchema:
    """MappingService accepts an optional TargetSchema. When provided,
    row validation uses a dynamic model built from that schema instead
    of the default schema's record model."""

    @pytest.mark.asyncio
    async def test_validates_rows_against_custom_schema(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """A 2-field schema should validate rows with just those 2 fields."""
        file_path = str(tmp_path / "simple.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Amount"])
            writer.writerow(["P001", "50000"])

        custom_schema = TargetSchema(
            name="simple",
            fields={
                "ID": FieldDefinition(type=FieldType.STRING, not_empty=True),
                "Amount": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
            },
        )

        mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="ID", target_field="ID", confidence=0.95),
                ColumnMapping(source_header="Amount", target_field="Amount", confidence=0.90),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            schema=custom_schema,
        )

        result = await service.process_file(file_path)
        assert len(result.valid_records) == 1
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_custom_schema_rejects_invalid_rows(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """Custom schema with non_negative should reject negative amounts."""
        file_path = str(tmp_path / "bad.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Amount"])
            writer.writerow(["P001", "-100"])

        custom_schema = TargetSchema(
            name="simple",
            fields={
                "ID": FieldDefinition(type=FieldType.STRING),
                "Amount": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
            },
        )

        mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="ID", target_field="ID", confidence=0.95),
                ColumnMapping(source_header="Amount", target_field="Amount", confidence=0.90),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            schema=custom_schema,
        )

        result = await service.process_file(file_path)
        assert len(result.valid_records) == 0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_default_schema_when_none_provided(
        self, service: MappingService, mapper: AsyncMock, tmp_path: Path
    ) -> None:
        """When no schema is provided, existing behavior is preserved."""
        path = _write_csv(tmp_path)
        result = await service.process_file(path)
        assert isinstance(result, ProcessingResult)

    @pytest.mark.asyncio
    async def test_confidence_report_uses_custom_schema_fields(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """missing_fields should reference the custom schema's fields,
        not the hardcoded 6-field set."""
        file_path = str(tmp_path / "partial.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["ID"])
            writer.writerow(["P001"])

        custom_schema = TargetSchema(
            name="three_field",
            fields={
                "ID": FieldDefinition(type=FieldType.STRING),
                "Amount": FieldDefinition(type=FieldType.FLOAT),
                "Notes": FieldDefinition(type=FieldType.STRING),
            },
        )

        mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="ID", target_field="ID", confidence=0.95),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            schema=custom_schema,
        )

        result = await service.process_file(file_path)
        # Custom schema has 3 fields, only 1 mapped → 2 missing
        assert len(result.confidence_report.missing_fields) == 2
        assert "Amount" in result.confidence_report.missing_fields
        assert "Notes" in result.confidence_report.missing_fields


class TestCorrectionCache:
    """MappingService checks human-verified corrections before calling
    the SLM. Corrected headers get confidence 1.0 and skip the SLM."""

    @pytest.fixture
    def correction_cache(self) -> AsyncMock:
        mock = AsyncMock()
        mock.get_corrections.return_value = {}
        return mock

    def _make_service(
        self,
        mapper: AsyncMock,
        cache: AsyncMock,
        correction_cache: AsyncMock,
        logger: object | None = None,
    ) -> MappingService:
        return MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            correction_cache=correction_cache,
            logger=logger,
        )

    @pytest.mark.asyncio
    async def test_without_cedent_id_skips_corrections(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path)

        correction_cache.get_corrections.assert_not_called()
        mapper.map_headers.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_cedent_id_checks_corrections(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path, cedent_id="ABC")

        correction_cache.get_corrections.assert_called_once()
        call_args = correction_cache.get_corrections.call_args
        assert call_args[0][0] == "ABC"

    @pytest.mark.asyncio
    async def test_corrections_used_with_confidence_1(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        correction_cache.get_corrections.return_value = {"Policy No.": "Policy_ID"}
        # SLM maps the remaining header
        mapper.map_headers.return_value = MappingResult(
            mappings=[
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=["Extra"],
        )
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        result = await service.process_file(path, cedent_id="ABC")

        corrected = [m for m in result.mapping.mappings if m.source_header == "Policy No."]
        assert len(corrected) == 1
        assert corrected[0].confidence == 1.0
        assert corrected[0].target_field == "Policy_ID"

    @pytest.mark.asyncio
    async def test_corrected_headers_not_sent_to_slm(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        correction_cache.get_corrections.return_value = {"Policy No.": "Policy_ID"}
        mapper.map_headers.return_value = MappingResult(
            mappings=[
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=["Extra"],
        )
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path, cedent_id="ABC")

        slm_headers = mapper.map_headers.call_args[0][0]
        assert "Policy No." not in slm_headers
        assert "GWP" in slm_headers

    @pytest.mark.asyncio
    async def test_all_headers_corrected_skips_slm(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        correction_cache.get_corrections.return_value = {
            "Policy No.": "Policy_ID",
            "GWP": "Gross_Premium",
            "Extra": "Currency",
        }
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        result = await service.process_file(path, cedent_id="ABC")

        mapper.map_headers.assert_not_called()
        assert len(result.mapping.mappings) == 3

    @pytest.mark.asyncio
    async def test_no_corrections_falls_through_to_slm(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        correction_cache.get_corrections.return_value = {}
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path, cedent_id="ABC")

        mapper.map_headers.assert_called_once()

    @pytest.mark.asyncio
    async def test_correction_with_invalid_target_raises(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        """Correction referencing a field not in the schema should raise."""
        correction_cache.get_corrections.return_value = {
            "Policy No.": "Nonexistent_Field",
        }
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        with pytest.raises(InvalidCorrectionError, match="Nonexistent_Field"):
            await service.process_file(path, cedent_id="ABC")

    @pytest.mark.asyncio
    async def test_cedent_id_with_no_correction_cache_injected(
        self, mapper: AsyncMock, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """When correction_cache is None, cedent_id is ignored gracefully."""
        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )
        path = _write_csv(tmp_path)

        result = await service.process_file(path, cedent_id="ABC")

        assert isinstance(result, ProcessingResult)
        mapper.map_headers.assert_called_once()

    @pytest.mark.asyncio
    async def test_merged_result_has_no_duplicate_targets(
        self, mapper: AsyncMock, cache: AsyncMock, correction_cache: AsyncMock, tmp_path: Path
    ) -> None:
        """If SLM maps a target already covered by a correction,
        the SLM mapping is filtered out to prevent duplicate target error."""
        correction_cache.get_corrections.return_value = {"Policy No.": "Policy_ID"}
        # SLM also tries to map something to Policy_ID — this should be filtered
        mapper.map_headers.return_value = MappingResult(
            mappings=[
                ColumnMapping(source_header="GWP", target_field="Policy_ID", confidence=0.80),
            ],
            unmapped_headers=["Extra"],
        )
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        result = await service.process_file(path, cedent_id="ABC")

        # Correction wins — only one Policy_ID mapping with confidence 1.0
        policy_mappings = [m for m in result.mapping.mappings if m.target_field == "Policy_ID"]
        assert len(policy_mappings) == 1
        assert policy_mappings[0].confidence == 1.0

    @pytest.mark.asyncio
    async def test_corrections_logged(
        self,
        mapper: AsyncMock,
        cache: AsyncMock,
        correction_cache: AsyncMock,
        tmp_path: Path,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        import json

        import structlog

        from src.entrypoint.main import configure_logging

        configure_logging()
        capfd.readouterr()  # clear setup output

        correction_cache.get_corrections.return_value = {"Policy No.": "Policy_ID"}
        mapper.map_headers.return_value = MappingResult(
            mappings=[
                ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.90),
            ],
            unmapped_headers=["Extra"],
        )
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache, logger=structlog.get_logger())

        await service.process_file(path, cedent_id="ABC")

        captured = capfd.readouterr().out
        lines = [l for l in captured.strip().splitlines() if l.strip()]
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        correction_events = [e for e in events if e.get("event") == "corrections_applied"]
        assert len(correction_events) == 1
        assert correction_events[0]["corrected_count"] == 1
        assert correction_events[0]["cedent_id"] == "ABC"


class TestDateFormatDetection:
    """MappingService detects date column formats from preview and
    pre-converts values before row validation. Fixes YYYY/MM/DD
    misparsing where dateutil with dayfirst=True turns '2025/07/01'
    into January 7 instead of July 1."""

    @pytest.mark.asyncio
    async def test_yyyy_slash_dates_parsed_correctly(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """CSV with YYYY/MM/DD dates should validate with correct months."""
        file_path = str(tmp_path / "yyyy_slash.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Voyage", "Arrival", "Ship", "Value", "Premium", "Ccy", "Port"])
            writer.writerow(
                ["2024/03/15", "2024/04/02", "MV Star", "8500000", "212500", "USD", "Singapore"]
            )
            writer.writerow(
                ["2024/05/01", "2024/05/20", "MV Dawn", "3200000", "96000", "USD", "Shanghai"]
            )

        marine_schema = TargetSchema(
            name="test_marine",
            fields={
                "Voyage_Date": FieldDefinition(type=FieldType.DATE),
                "Arrival_Date": FieldDefinition(type=FieldType.DATE),
                "Vessel_Name": FieldDefinition(type=FieldType.STRING, not_empty=True),
                "Cargo_Value": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
                "Premium": FieldDefinition(type=FieldType.FLOAT, non_negative=True),
                "Currency": FieldDefinition(type=FieldType.CURRENCY, allowed_values=["USD", "GBP"]),
                "Port_Of_Loading": FieldDefinition(type=FieldType.STRING, not_empty=True),
            },
        )

        mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="Voyage", target_field="Voyage_Date", confidence=0.95),
                ColumnMapping(
                    source_header="Arrival", target_field="Arrival_Date", confidence=0.95
                ),
                ColumnMapping(source_header="Ship", target_field="Vessel_Name", confidence=0.95),
                ColumnMapping(source_header="Value", target_field="Cargo_Value", confidence=0.95),
                ColumnMapping(source_header="Premium", target_field="Premium", confidence=0.95),
                ColumnMapping(source_header="Ccy", target_field="Currency", confidence=0.95),
                ColumnMapping(
                    source_header="Port", target_field="Port_Of_Loading", confidence=0.95
                ),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            schema=marine_schema,
        )

        result = await service.process_file(file_path)

        assert len(result.errors) == 0, (
            f"Expected 0 errors but got {len(result.errors)}:\n"
            + "\n".join(f"  Row {e.row}: {e.error}" for e in result.errors)
        )
        assert len(result.valid_records) == 2

        # Verify dates are correct (not misparsed by dayfirst)
        import datetime

        row1 = result.valid_records[0]
        assert row1["Voyage_Date"] == datetime.date(2024, 3, 15)
        assert row1["Arrival_Date"] == datetime.date(2024, 4, 2)  # NOT Feb 4


class TestStoreCorrection:
    """store_correction validates target field against the active schema."""

    @pytest.mark.asyncio
    async def test_valid_correction_stored(self, mapper: AsyncMock, cache: AsyncMock) -> None:
        from src.domain.model.correction import Correction

        correction_cache = AsyncMock()
        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            correction_cache=correction_cache,
        )
        correction = Correction(
            cedent_id="ABC",
            source_header="GWP",
            target_field="Gross_Premium",
        )
        await service.store_correction(correction)
        correction_cache.set_correction.assert_called_once_with(correction)

    @pytest.mark.asyncio
    async def test_invalid_target_raises_invalid_correction_error(
        self, mapper: AsyncMock, cache: AsyncMock
    ) -> None:
        from src.domain.model.correction import Correction

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )
        correction = Correction(
            cedent_id="ABC",
            source_header="GWP",
            target_field="Nonexistent_Field",
        )
        with pytest.raises(InvalidCorrectionError, match="Nonexistent_Field"):
            await service.store_correction(correction)

    @pytest.mark.asyncio
    async def test_valid_correction_without_cache_is_noop(
        self, mapper: AsyncMock, cache: AsyncMock
    ) -> None:
        """When no correction_cache is configured, store_correction validates
        but doesn't persist (no error raised)."""
        from src.domain.model.correction import Correction

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )
        correction = Correction(
            cedent_id="ABC",
            source_header="GWP",
            target_field="Gross_Premium",
        )
        await service.store_correction(correction)  # should not raise


class TestConfidenceThresholdBoundary:
    """Test exact boundary values for confidence threshold."""

    @pytest.mark.asyncio
    async def test_confidence_just_below_threshold_raises(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """0.599999 is below 0.6 threshold — should raise."""
        path = _write_csv(tmp_path)
        mapper = AsyncMock()
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.599999)
        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)
        with pytest.raises(MappingConfidenceLowError):
            await service.process_file(path)


class TestHeaderOnlyFile:
    """CSV with headers but no data rows."""

    @pytest.mark.asyncio
    async def test_header_only_csv_produces_empty_result(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """A file with headers but no data rows should produce 0 valid/invalid records."""
        file_path = str(tmp_path / "empty.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Policy No.", "GWP", "Extra"])

        mapper = AsyncMock()
        mapper.map_headers.return_value = _make_mapping_result()
        cache.get_mapping.return_value = None

        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)
        result = await service.process_file(file_path)

        assert result.valid_records == []
        assert result.invalid_records == []
        assert result.errors == []


class TestOptionalFieldValidation:
    """Row validation with optional fields in a custom schema."""

    @pytest.mark.asyncio
    async def test_optional_date_none_passes_validation(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """A schema with an optional date field should accept rows missing that field."""
        file_path = str(tmp_path / "optional.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Name"])
            writer.writerow(["Alice"])

        schema = TargetSchema(
            name="with_optional",
            fields={
                "Name": FieldDefinition(type=FieldType.STRING, not_empty=True),
                "Birthday": FieldDefinition(type=FieldType.DATE, required=False),
            },
        )

        mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="Name", target_field="Name", confidence=0.95),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(), mapper=mapper, cache=cache, schema=schema
        )
        result = await service.process_file(file_path)

        assert len(result.valid_records) == 1
        assert result.valid_records[0]["Birthday"] is None

    @pytest.mark.asyncio
    async def test_optional_float_none_passes_validation(
        self, cache: AsyncMock, tmp_path: Path
    ) -> None:
        """Optional float field should accept rows missing that field."""
        file_path = str(tmp_path / "opt_float.csv")
        with open(file_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Name"])
            writer.writerow(["Bob"])

        schema = TargetSchema(
            name="with_optional_float",
            fields={
                "Name": FieldDefinition(type=FieldType.STRING, not_empty=True),
                "Amount": FieldDefinition(type=FieldType.FLOAT, required=False),
            },
        )

        mapping = MappingResult(
            mappings=[
                ColumnMapping(source_header="Name", target_field="Name", confidence=0.95),
            ],
            unmapped_headers=[],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = mapping
        cache.get_mapping.return_value = None

        service = MappingService(
            ingestor=PolarsIngestor(), mapper=mapper, cache=cache, schema=schema
        )
        result = await service.process_file(file_path)

        assert len(result.valid_records) == 1
        assert result.valid_records[0]["Amount"] is None


class TestGetHeaders:
    """get_headers delegates to the ingestor and returns a list of strings."""

    def test_returns_headers_from_csv(self, service: MappingService, tmp_path: Path) -> None:
        path = _write_csv(tmp_path)
        headers = service.get_headers(path)
        assert headers == ["Policy No.", "GWP", "Extra"]

    def test_returns_headers_with_sheet_name(self, service: MappingService, tmp_path: Path) -> None:
        path = _write_csv(tmp_path)
        # CSV ignores sheet_name, but the API should accept it
        headers = service.get_headers(path, sheet_name=None)
        assert headers == ["Policy No.", "GWP", "Extra"]


class TestGetPreview:
    """get_preview delegates to the ingestor and returns a list of row dicts."""

    def test_returns_preview_rows(self, service: MappingService, tmp_path: Path) -> None:
        path = _write_csv(tmp_path)
        preview = service.get_preview(path)
        assert len(preview) >= 1
        assert "Policy No." in preview[0]

    def test_returns_preview_with_sheet_name(self, service: MappingService, tmp_path: Path) -> None:
        path = _write_csv(tmp_path)
        preview = service.get_preview(path, sheet_name=None)
        assert isinstance(preview, list)


class TestSuggestMapping:
    """suggest_mapping calls the SLM without cache or confidence check."""

    @pytest.mark.asyncio
    async def test_returns_mapping_result(self, service: MappingService, mapper: AsyncMock) -> None:
        headers = ["Premium", "PolicyNum"]
        preview = [{"Premium": 1000, "PolicyNum": "P001"}]
        result = await service.suggest_mapping(headers, preview)
        assert isinstance(result, MappingResult)
        mapper.map_headers.assert_called_once_with(headers, preview)

    @pytest.mark.asyncio
    async def test_does_not_use_cache(
        self, service: MappingService, mapper: AsyncMock, cache: AsyncMock
    ) -> None:
        await service.suggest_mapping(["H"], [{"H": 1}])
        cache.get_mapping.assert_not_called()
        cache.set_mapping.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_check_confidence(self, mapper: AsyncMock, cache: AsyncMock) -> None:
        """Low confidence should NOT raise — suggest_mapping skips threshold."""
        mapper.map_headers.return_value = _make_mapping_result(confidence=0.1)
        service = MappingService(ingestor=PolarsIngestor(), mapper=mapper, cache=cache)
        result = await service.suggest_mapping(["H"], [{"H": 1}])
        assert result.mappings[0].confidence == 0.1


class TestValidateRowsWithMapping:
    """validate_rows_with_mapping validates a file using a supplied mapping."""

    def test_returns_processing_result(self, service: MappingService, tmp_path: Path) -> None:
        path = _write_csv(tmp_path)
        mapping = _make_mapping_result()
        result = service.validate_rows_with_mapping(path, mapping)
        assert isinstance(result, ProcessingResult)

    def test_uses_supplied_mapping_not_slm(
        self, service: MappingService, mapper: AsyncMock, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        mapping = _make_mapping_result()
        service.validate_rows_with_mapping(path, mapping)
        mapper.map_headers.assert_not_called()

    def test_with_sheet_name(self, service: MappingService, tmp_path: Path) -> None:
        path = _write_csv(tmp_path)
        mapping = _make_mapping_result()
        # CSV ignores sheet_name but API should accept it
        result = service.validate_rows_with_mapping(path, mapping, sheet_name=None)
        assert isinstance(result, ProcessingResult)
