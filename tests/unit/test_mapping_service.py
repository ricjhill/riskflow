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


def _cache_key_for(
    headers: list[str], schema: TargetSchema = DEFAULT_TARGET_SCHEMA
) -> str:
    normalized = "|".join(sorted(h.lower().strip() for h in headers))
    key_input = f"{schema.fingerprint}:{normalized}"
    return hashlib.sha256(key_input.encode()).hexdigest()


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


class TestCustomSchema:
    """MappingService accepts an optional TargetSchema. When provided,
    row validation uses a dynamic model built from that schema instead
    of the hardcoded RiskRecord."""

    @pytest.mark.asyncio
    async def test_validates_rows_against_custom_schema(
        self, cache: MagicMock, tmp_path: Path
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
        self, cache: MagicMock, tmp_path: Path
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
        self, cache: MagicMock, tmp_path: Path
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
    def correction_cache(self) -> MagicMock:
        mock = MagicMock()
        mock.get_corrections.return_value = {}
        return mock

    def _make_service(
        self,
        mapper: AsyncMock,
        cache: MagicMock,
        correction_cache: MagicMock,
    ) -> MappingService:
        return MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
            correction_cache=correction_cache,
        )

    @pytest.mark.asyncio
    async def test_without_cedent_id_skips_corrections(
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path)

        correction_cache.get_corrections.assert_not_called()
        mapper.map_headers.assert_called_once()

    @pytest.mark.asyncio
    async def test_with_cedent_id_checks_corrections(
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
    ) -> None:
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path, cedent_id="ABC")

        correction_cache.get_corrections.assert_called_once()
        call_args = correction_cache.get_corrections.call_args
        assert call_args[0][0] == "ABC"

    @pytest.mark.asyncio
    async def test_corrections_used_with_confidence_1(
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
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
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
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
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
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
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
    ) -> None:
        correction_cache.get_corrections.return_value = {}
        path = _write_csv(tmp_path)
        service = self._make_service(mapper, cache, correction_cache)

        await service.process_file(path, cedent_id="ABC")

        mapper.map_headers.assert_called_once()

    @pytest.mark.asyncio
    async def test_correction_with_invalid_target_raises(
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
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
        self, mapper: AsyncMock, cache: MagicMock, tmp_path: Path
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
        self, mapper: AsyncMock, cache: MagicMock, correction_cache: MagicMock, tmp_path: Path
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
        cache: MagicMock,
        correction_cache: MagicMock,
        tmp_path: Path,
        capfd: pytest.CaptureFixture[str],
    ) -> None:
        import json

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
        service = self._make_service(mapper, cache, correction_cache)

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
