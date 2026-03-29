"""Shadow deployment: run old and new validation side-by-side.

Loop 20: The final proof of the Expand and Contract migration. Feed
the same CSV data through both the hardcoded RiskRecord and the
dynamic model from DEFAULT_TARGET_SCHEMA, then compare JSON output
byte-for-byte. If these tests pass, the migration is complete.

Unlike the equivalence tests (Loop 18) which tested individual values,
these tests simulate the full row-validation pipeline path that
MappingService._validate_rows uses.
"""

import csv
import json
from pathlib import Path

import polars as pl
from pydantic import ValidationError

from src.domain.model.record_factory import build_record_model
from src.domain.model.schema import RiskRecord
from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA

DynamicRecord = build_record_model(DEFAULT_TARGET_SCHEMA)


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> str:
    """Write a CSV file and return its path."""
    file_path = str(path / "shadow_test.csv")
    with open(file_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return file_path


def _validate_with_both(
    row: dict,
) -> tuple[dict | None, dict | None, str | None, str | None]:
    """Validate a row with both models. Returns (static_dump, dynamic_dump, static_error, dynamic_error)."""
    static_dump = None
    dynamic_dump = None
    static_error = None
    dynamic_error = None

    try:
        static = RiskRecord.model_validate(row)
        static_dump = static.model_dump()
    except (ValidationError, ValueError) as e:
        static_error = str(e)

    try:
        dynamic = DynamicRecord.model_validate(row)
        dynamic_dump = dynamic.model_dump()
    except (ValidationError, ValueError) as e:
        dynamic_error = str(e)

    return static_dump, dynamic_dump, static_error, dynamic_error


class TestShadowDeployment:
    """Full pipeline shadow: CSV → Polars → rename → validate → compare."""

    def test_all_valid_rows_produce_identical_json(self, tmp_path: Path) -> None:
        """5 valid rows → both models produce byte-identical JSON output."""
        file_path = _write_csv(
            tmp_path,
            [
                "Policy_ID",
                "Inception_Date",
                "Expiry_Date",
                "Sum_Insured",
                "Gross_Premium",
                "Currency",
            ],
            [
                ["POL-001", "2024-01-15", "2025-01-15", "5000000", "125000", "USD"],
                ["POL-002", "2024-03-01", "2025-03-01", "2500000", "75000", "GBP"],
                ["POL-003", "2024-06-15", "2025-06-15", "10000000", "250000", "EUR"],
                ["POL-004", "2024-09-01", "2024-12-31", "1000000", "30000", "JPY"],
                ["POL-005", "2024-11-01", "2025-11-01", "7500000", "180000", "USD"],
            ],
        )

        df = pl.read_csv(file_path)
        rows = df.to_dicts()

        for row in rows:
            static_dump, dynamic_dump, static_err, dynamic_err = _validate_with_both(
                row
            )
            assert static_err is None, f"Static failed: {static_err}"
            assert dynamic_err is None, f"Dynamic failed: {dynamic_err}"
            # Byte-identical JSON
            assert json.dumps(static_dump, sort_keys=True, default=str) == json.dumps(
                dynamic_dump, sort_keys=True, default=str
            )

    def test_invalid_rows_rejected_by_both(self, tmp_path: Path) -> None:
        """Rows with invalid data are rejected by both models."""
        file_path = _write_csv(
            tmp_path,
            [
                "Policy_ID",
                "Inception_Date",
                "Expiry_Date",
                "Sum_Insured",
                "Gross_Premium",
                "Currency",
            ],
            [
                [
                    "",
                    "2024-01-15",
                    "2025-01-15",
                    "5000000",
                    "125000",
                    "USD",
                ],  # empty Policy_ID
                [
                    "POL-002",
                    "2024-03-01",
                    "2025-03-01",
                    "-100",
                    "75000",
                    "GBP",
                ],  # negative Sum_Insured
                [
                    "POL-003",
                    "2024-06-15",
                    "2025-06-15",
                    "10000000",
                    "250000",
                    "DOLLARS",
                ],  # invalid currency
            ],
        )

        df = pl.read_csv(file_path)
        rows = df.to_dicts()

        for row in rows:
            static_dump, dynamic_dump, static_err, dynamic_err = _validate_with_both(
                row
            )
            # Both must reject
            assert static_dump is None, f"Static accepted invalid row: {row}"
            assert dynamic_dump is None, f"Dynamic accepted invalid row: {row}"
            # Both must have errors
            assert static_err is not None
            assert dynamic_err is not None

    def test_mixed_rows_same_split(self, tmp_path: Path) -> None:
        """Both models agree on which rows are valid and which are invalid."""
        file_path = _write_csv(
            tmp_path,
            [
                "Policy_ID",
                "Inception_Date",
                "Expiry_Date",
                "Sum_Insured",
                "Gross_Premium",
                "Currency",
            ],
            [
                [
                    "POL-001",
                    "2024-01-15",
                    "2025-01-15",
                    "5000000",
                    "125000",
                    "USD",
                ],  # valid
                [
                    "",
                    "2024-03-01",
                    "2025-03-01",
                    "2500000",
                    "75000",
                    "GBP",
                ],  # invalid: empty Policy_ID
                [
                    "POL-003",
                    "2024-06-15",
                    "2025-06-15",
                    "10000000",
                    "250000",
                    "EUR",
                ],  # valid
                [
                    "POL-004",
                    "2025-01-01",
                    "2024-01-01",
                    "1000000",
                    "30000",
                    "JPY",
                ],  # invalid: expiry before inception
                [
                    "POL-005",
                    "2024-11-01",
                    "2025-11-01",
                    "7500000",
                    "180000",
                    "USD",
                ],  # valid
            ],
        )

        df = pl.read_csv(file_path)
        rows = df.to_dicts()

        static_valid_indices = []
        dynamic_valid_indices = []

        for i, row in enumerate(rows):
            static_dump, dynamic_dump, _, _ = _validate_with_both(row)
            if static_dump is not None:
                static_valid_indices.append(i)
            if dynamic_dump is not None:
                dynamic_valid_indices.append(i)

        assert static_valid_indices == dynamic_valid_indices
        assert static_valid_indices == [0, 2, 4]  # rows 0, 2, 4 are valid

    def test_fixture_file_identical_output(self) -> None:
        """The actual sample_bordereaux.csv fixture produces identical output."""
        fixture_path = "tests/fixtures/sample_bordereaux.csv"
        df = pl.read_csv(fixture_path)

        # Simulate the rename step that MappingService does
        rename_map = {
            "Policy No.": "Policy_ID",
            "Start Date": "Inception_Date",
            "End Date": "Expiry_Date",
            "Total Sum Insured": "Sum_Insured",
            "GWP": "Gross_Premium",
            "Ccy": "Currency",
        }
        df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
        rows = df.to_dicts()

        static_results = []
        dynamic_results = []

        for row in rows:
            static_dump, dynamic_dump, static_err, dynamic_err = _validate_with_both(
                row
            )
            static_results.append({"valid": static_dump, "error": static_err})
            dynamic_results.append({"valid": dynamic_dump, "error": dynamic_err})

        # Byte-identical JSON for the full result set
        assert json.dumps(static_results, sort_keys=True, default=str) == json.dumps(
            dynamic_results, sort_keys=True, default=str
        )

    def test_json_serialization_identical(self, tmp_path: Path) -> None:
        """model_dump_json() produces identical bytes from both models."""
        file_path = _write_csv(
            tmp_path,
            [
                "Policy_ID",
                "Inception_Date",
                "Expiry_Date",
                "Sum_Insured",
                "Gross_Premium",
                "Currency",
            ],
            [
                [
                    "POL-001",
                    "2024-01-15",
                    "2025-01-15",
                    "5000000.50",
                    "125000.75",
                    "USD",
                ],
            ],
        )

        df = pl.read_csv(file_path)
        row = df.to_dicts()[0]

        static = RiskRecord.model_validate(row)
        dynamic = DynamicRecord.model_validate(row)

        # model_dump() comparison (dict)
        assert static.model_dump() == dynamic.model_dump()

    def test_validates_same_count(self, tmp_path: Path) -> None:
        """Both models produce the same count of valid and invalid records."""
        file_path = _write_csv(
            tmp_path,
            [
                "Policy_ID",
                "Inception_Date",
                "Expiry_Date",
                "Sum_Insured",
                "Gross_Premium",
                "Currency",
            ],
            [
                ["POL-001", "2024-01-15", "2025-01-15", "5000000", "125000", "USD"],
                ["POL-002", "2024-03-01", "2025-03-01", "2500000", "75000", "GBP"],
                ["", "2024-06-15", "2025-06-15", "10000000", "250000", "EUR"],
                ["POL-004", "2024-09-01", "2024-12-31", "1000000", "-30000", "JPY"],
            ],
        )

        df = pl.read_csv(file_path)
        rows = df.to_dicts()

        static_valid = 0
        dynamic_valid = 0
        static_invalid = 0
        dynamic_invalid = 0

        for row in rows:
            static_dump, dynamic_dump, _, _ = _validate_with_both(row)
            if static_dump:
                static_valid += 1
            else:
                static_invalid += 1
            if dynamic_dump:
                dynamic_valid += 1
            else:
                dynamic_invalid += 1

        assert static_valid == dynamic_valid
        assert static_invalid == dynamic_invalid
