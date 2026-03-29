"""Equivalence tests: dynamic model vs hardcoded RiskRecord.

Loop 18: Prove that build_record_model(DEFAULT_TARGET_SCHEMA) produces
a model that validates identically to the hardcoded RiskRecord for all
inputs. This is the safety net for the Expand and Contract migration —
if these tests pass, we can remove RiskRecord knowing the dynamic
model is a drop-in replacement.
"""

import datetime

import pytest
from pydantic import ValidationError

from src.domain.model.record_factory import build_record_model
from src.domain.model.schema import RiskRecord
from src.domain.model.target_schema import DEFAULT_TARGET_SCHEMA

DynamicRecord = build_record_model(DEFAULT_TARGET_SCHEMA)

VALID_ROW = {
    "Policy_ID": "POL-2024-001",
    "Inception_Date": datetime.date(2024, 1, 15),
    "Expiry_Date": datetime.date(2025, 1, 15),
    "Sum_Insured": 5000000.0,
    "Gross_Premium": 125000.0,
    "Currency": "USD",
}


class TestEquivalenceValidRows:
    """Both models accept the same valid inputs."""

    def test_valid_row_passes_both(self) -> None:
        """A fully valid row is accepted by both models."""
        static = RiskRecord.model_validate(VALID_ROW)
        dynamic = DynamicRecord.model_validate(VALID_ROW)

        assert static.model_dump() == dynamic.model_dump()

    def test_all_currencies_pass_both(self) -> None:
        """All 4 valid currencies pass both models."""
        for ccy in ["USD", "GBP", "EUR", "JPY"]:
            row = {**VALID_ROW, "Currency": ccy}
            static = RiskRecord.model_validate(row)
            dynamic = DynamicRecord.model_validate(row)
            assert static.Currency == dynamic.Currency == ccy

    def test_zero_sum_insured_passes_both(self) -> None:
        """Sum_Insured=0.0 is non-negative and passes both."""
        row = {**VALID_ROW, "Sum_Insured": 0.0}
        static = RiskRecord.model_validate(row)
        dynamic = DynamicRecord.model_validate(row)
        assert static.Sum_Insured == dynamic.Sum_Insured == 0.0

    def test_zero_premium_passes_both(self) -> None:
        """Gross_Premium=0.0 is non-negative and passes both."""
        row = {**VALID_ROW, "Gross_Premium": 0.0}
        static = RiskRecord.model_validate(row)
        dynamic = DynamicRecord.model_validate(row)
        assert static.Gross_Premium == dynamic.Gross_Premium == 0.0

    def test_same_day_inception_expiry_passes_both(self) -> None:
        """Expiry_Date == Inception_Date is not 'before', should pass both."""
        row = {
            **VALID_ROW,
            "Inception_Date": datetime.date(2024, 6, 1),
            "Expiry_Date": datetime.date(2024, 6, 1),
        }
        static = RiskRecord.model_validate(row)
        dynamic = DynamicRecord.model_validate(row)
        assert static.model_dump() == dynamic.model_dump()

    def test_all_fixture_rows_pass_both(self) -> None:
        """All 5 rows from sample_bordereaux.csv pass both models."""
        rows = [
            {
                "Policy_ID": "POL-2024-001",
                "Inception_Date": "2024-01-15",
                "Expiry_Date": "2025-01-15",
                "Sum_Insured": 5000000.0,
                "Gross_Premium": 125000.0,
                "Currency": "USD",
            },
            {
                "Policy_ID": "POL-2024-002",
                "Inception_Date": "2024-03-01",
                "Expiry_Date": "2025-03-01",
                "Sum_Insured": 2500000.0,
                "Gross_Premium": 75000.0,
                "Currency": "GBP",
            },
            {
                "Policy_ID": "POL-2024-003",
                "Inception_Date": "2024-06-15",
                "Expiry_Date": "2025-06-15",
                "Sum_Insured": 10000000.0,
                "Gross_Premium": 250000.0,
                "Currency": "EUR",
            },
            {
                "Policy_ID": "POL-2024-004",
                "Inception_Date": "2024-09-01",
                "Expiry_Date": "2024-12-31",
                "Sum_Insured": 1000000.0,
                "Gross_Premium": 30000.0,
                "Currency": "JPY",
            },
            {
                "Policy_ID": "POL-2024-005",
                "Inception_Date": "2024-11-01",
                "Expiry_Date": "2025-11-01",
                "Sum_Insured": 7500000.0,
                "Gross_Premium": 180000.0,
                "Currency": "USD",
            },
        ]
        for row in rows:
            static = RiskRecord.model_validate(row)
            dynamic = DynamicRecord.model_validate(row)
            assert static.model_dump() == dynamic.model_dump()


class TestEquivalenceInvalidRows:
    """Both models reject the same invalid inputs."""

    @pytest.mark.parametrize("currency", ["DOLLARS", "usd", "AUD", ""])
    def test_invalid_currency_rejected_by_both(self, currency: str) -> None:
        """Invalid currencies are rejected by both models."""
        row = {**VALID_ROW, "Currency": currency}
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)

    def test_negative_sum_insured_rejected_by_both(self) -> None:
        """Negative Sum_Insured is rejected by both."""
        row = {**VALID_ROW, "Sum_Insured": -1.0}
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)

    def test_negative_premium_rejected_by_both(self) -> None:
        """Negative Gross_Premium is rejected by both."""
        row = {**VALID_ROW, "Gross_Premium": -0.01}
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)

    def test_empty_policy_id_rejected_by_both(self) -> None:
        """Empty Policy_ID is rejected by both."""
        row = {**VALID_ROW, "Policy_ID": ""}
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)

    def test_whitespace_policy_id_rejected_by_both(self) -> None:
        """Whitespace-only Policy_ID is rejected by both."""
        row = {**VALID_ROW, "Policy_ID": "   "}
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)

    def test_missing_required_field_rejected_by_both(self) -> None:
        """Missing a required field is rejected by both."""
        row = {k: v for k, v in VALID_ROW.items() if k != "Currency"}
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)

    def test_expiry_before_inception_rejected_by_both(self) -> None:
        """Expiry_Date before Inception_Date is rejected by both."""
        row = {
            **VALID_ROW,
            "Inception_Date": datetime.date(2025, 1, 1),
            "Expiry_Date": datetime.date(2024, 1, 1),
        }
        with pytest.raises(ValidationError):
            RiskRecord.model_validate(row)
        with pytest.raises(ValidationError):
            DynamicRecord.model_validate(row)


class TestEquivalenceOutputShape:
    """Both models produce identically shaped output."""

    def test_field_names_match(self) -> None:
        """Both models have the same field names."""
        static_fields = set(RiskRecord.model_fields.keys())
        dynamic_fields = set(DynamicRecord.model_fields.keys())
        assert static_fields == dynamic_fields

    def test_dump_keys_match(self) -> None:
        """model_dump() produces the same keys."""
        static = RiskRecord.model_validate(VALID_ROW)
        dynamic = DynamicRecord.model_validate(VALID_ROW)
        assert set(static.model_dump().keys()) == set(dynamic.model_dump().keys())

    def test_dump_values_match(self) -> None:
        """model_dump() produces the same values for all fields."""
        static = RiskRecord.model_validate(VALID_ROW)
        dynamic = DynamicRecord.model_validate(VALID_ROW)
        for key in static.model_dump():
            assert static.model_dump()[key] == dynamic.model_dump()[key], (
                f"Mismatch on {key}: {static.model_dump()[key]} != {dynamic.model_dump()[key]}"
            )
