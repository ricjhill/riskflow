"""Tests for row-level validation after column mapping.

After the SLM maps headers, the service should:
1. Read the full dataframe
2. Rename columns according to the mapping
3. Validate each row against the schema's record model
4. Return valid records, invalid records with errors
"""

import csv
import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.model.schema import (
    ColumnMapping,
    ConfidenceReport,
    FieldError,
    MappingResult,
    ProcessingResult,
    RowError,
)
from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA  # noqa: F401
from src.domain.service.mapping_service import MappingService


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> str:
    file_path = str(path / "test.csv")
    with open(file_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return file_path


def _full_mapping() -> MappingResult:
    """A mapping that covers all 6 target fields."""
    return MappingResult(
        mappings=[
            ColumnMapping(source_header="Policy No.", target_field="Policy_ID", confidence=0.95),
            ColumnMapping(source_header="Start", target_field="Inception_Date", confidence=0.95),
            ColumnMapping(source_header="End", target_field="Expiry_Date", confidence=0.95),
            ColumnMapping(source_header="TSI", target_field="Sum_Insured", confidence=0.95),
            ColumnMapping(source_header="GWP", target_field="Gross_Premium", confidence=0.95),
            ColumnMapping(source_header="Ccy", target_field="Currency", confidence=0.95),
        ],
        unmapped_headers=[],
    )


class TestProcessingResult:
    def test_valid_processing_result(self) -> None:
        mapping = _full_mapping()
        result = ProcessingResult(
            mapping=mapping,
            confidence_report=ConfidenceReport.from_mapping_result(
                mapping, valid_fields=DEFAULT_TARGET_SCHEMA.field_names
            ),
            valid_records=[
                {
                    "Policy_ID": "P001",
                    "Inception_Date": datetime.date(2024, 1, 1),
                    "Expiry_Date": datetime.date(2025, 1, 1),
                    "Sum_Insured": 1000000.0,
                    "Gross_Premium": 50000.0,
                    "Currency": "USD",
                },
            ],
            invalid_records=[],
            errors=[],
        )
        assert len(result.valid_records) == 1
        assert len(result.invalid_records) == 0

    def test_row_error_model(self) -> None:
        err = RowError(row=2, error="Currency 'DOLLARS' not in ISO 4217")
        assert err.row == 2
        assert "DOLLARS" in err.error

    def test_row_error_with_field_errors(self) -> None:
        err = RowError(
            row=2,
            error="validation failed",
            field_errors=[
                FieldError(field="Currency", message="not in ISO 4217", value="DOLLARS"),
            ],
        )
        assert len(err.field_errors) == 1
        assert err.field_errors[0].field == "Currency"
        assert err.field_errors[0].message == "not in ISO 4217"
        assert err.field_errors[0].value == "DOLLARS"

    def test_row_error_field_errors_defaults_to_empty(self) -> None:
        err = RowError(row=1, error="some error")
        assert err.field_errors == []


class TestRowValidation:
    """Test that process_file validates rows after mapping."""

    @pytest.mark.asyncio
    async def test_valid_rows_become_records(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy No.", "Start", "End", "TSI", "GWP", "Ccy"],
            [
                ["P001", "2024-01-01", "2025-01-01", "1000000", "50000", "USD"],
                ["P002", "2024-06-15", "2025-06-15", "2000000", "75000", "GBP"],
            ],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = _full_mapping()
        cache = AsyncMock()
        cache.get_mapping.return_value = None

        from src.adapters.parsers.ingestor import PolarsIngestor

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )

        result = await service.process_file(path)
        assert isinstance(result, ProcessingResult)
        assert len(result.valid_records) == 2
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_invalid_currency_captured_as_error(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy No.", "Start", "End", "TSI", "GWP", "Ccy"],
            [
                ["P001", "2024-01-01", "2025-01-01", "1000000", "50000", "USD"],
                ["P002", "2024-06-15", "2025-06-15", "2000000", "75000", "DOLLARS"],
            ],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = _full_mapping()
        cache = AsyncMock()
        cache.get_mapping.return_value = None

        from src.adapters.parsers.ingestor import PolarsIngestor

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )

        result = await service.process_file(path)
        assert len(result.valid_records) == 1
        assert len(result.errors) == 1
        assert result.errors[0].row == 2
        assert len(result.errors[0].field_errors) >= 1
        currency_err = [fe for fe in result.errors[0].field_errors if fe.field == "Currency"]
        assert len(currency_err) == 1
        assert "DOLLARS" in (currency_err[0].value or "")

    @pytest.mark.asyncio
    async def test_negative_premium_captured_as_error(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy No.", "Start", "End", "TSI", "GWP", "Ccy"],
            [
                ["P001", "2024-01-01", "2025-01-01", "1000000", "-100", "USD"],
            ],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = _full_mapping()
        cache = AsyncMock()
        cache.get_mapping.return_value = None

        from src.adapters.parsers.ingestor import PolarsIngestor

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )

        result = await service.process_file(path)
        assert len(result.valid_records) == 0
        assert len(result.errors) == 1

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy No.", "Start", "End", "TSI", "GWP", "Ccy"],
            [
                ["P001", "2024-01-01", "2025-01-01", "1000000", "50000", "USD"],
                ["P002", "2024-06-15", "2025-06-15", "2000000", "75000", "INVALID"],
                ["P003", "2024-03-01", "2025-03-01", "500000", "25000", "EUR"],
            ],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = _full_mapping()
        cache = AsyncMock()
        cache.get_mapping.return_value = None

        from src.adapters.parsers.ingestor import PolarsIngestor

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )

        result = await service.process_file(path)
        assert len(result.valid_records) == 2
        assert len(result.errors) == 1
        assert result.errors[0].row == 2

    @pytest.mark.asyncio
    async def test_all_rows_invalid(self, tmp_path: Path) -> None:
        path = _write_csv(
            tmp_path,
            ["Policy No.", "Start", "End", "TSI", "GWP", "Ccy"],
            [
                ["P001", "2024-01-01", "2025-01-01", "1000000", "50000", "BAD"],
                ["P002", "2024-06-15", "2025-06-15", "-100", "75000", "USD"],
            ],
        )

        mapper = AsyncMock()
        mapper.map_headers.return_value = _full_mapping()
        cache = AsyncMock()
        cache.get_mapping.return_value = None

        from src.adapters.parsers.ingestor import PolarsIngestor

        service = MappingService(
            ingestor=PolarsIngestor(),
            mapper=mapper,
            cache=cache,
        )

        result = await service.process_file(path)
        assert len(result.valid_records) == 0
        assert len(result.errors) == 2
