"""Tests for domain models: RiskRecord, ColumnMapping, MappingResult."""

import datetime

import pytest

from src.domain.model.schema import (
    VALID_CURRENCIES,
    VALID_TARGET_FIELDS,
    ColumnMapping,
    MappingResult,
    RiskRecord,
)


class TestRiskRecord:
    """RiskRecord must enforce the target schema validation rules."""

    def test_valid_record(self) -> None:
        record = RiskRecord(
            Policy_ID="POL-001",
            Inception_Date=datetime.date(2024, 1, 1),
            Expiry_Date=datetime.date(2025, 1, 1),
            Sum_Insured=1_000_000.0,
            Gross_Premium=50_000.0,
            Currency="USD",
        )
        assert record.Policy_ID == "POL-001"
        assert record.Inception_Date == datetime.date(2024, 1, 1)
        assert record.Sum_Insured == 1_000_000.0
        assert record.Currency == "USD"

    # --- Financial validation ---

    def test_zero_sum_insured_is_valid(self) -> None:
        record = RiskRecord(
            Policy_ID="POL-001",
            Inception_Date=datetime.date(2024, 1, 1),
            Expiry_Date=datetime.date(2025, 1, 1),
            Sum_Insured=0.0,
            Gross_Premium=50_000.0,
            Currency="USD",
        )
        assert record.Sum_Insured == 0.0

    def test_zero_gross_premium_is_valid(self) -> None:
        record = RiskRecord(
            Policy_ID="POL-001",
            Inception_Date=datetime.date(2024, 1, 1),
            Expiry_Date=datetime.date(2025, 1, 1),
            Sum_Insured=1_000_000.0,
            Gross_Premium=0.0,
            Currency="USD",
        )
        assert record.Gross_Premium == 0.0

    def test_rejects_negative_sum_insured(self) -> None:
        with pytest.raises(ValueError, match="Sum_Insured"):
            RiskRecord(
                Policy_ID="POL-001",
                Inception_Date=datetime.date(2024, 1, 1),
                Expiry_Date=datetime.date(2025, 1, 1),
                Sum_Insured=-0.01,
                Gross_Premium=50_000.0,
                Currency="USD",
            )

    def test_rejects_negative_gross_premium(self) -> None:
        with pytest.raises(ValueError, match="Gross_Premium"):
            RiskRecord(
                Policy_ID="POL-001",
                Inception_Date=datetime.date(2024, 1, 1),
                Expiry_Date=datetime.date(2025, 1, 1),
                Sum_Insured=1_000_000.0,
                Gross_Premium=-0.01,
                Currency="USD",
            )

    # --- Currency validation ---

    @pytest.mark.parametrize("currency", ["USD", "GBP", "EUR", "JPY"])
    def test_accepts_valid_currencies(self, currency: str) -> None:
        record = RiskRecord(
            Policy_ID="POL-001",
            Inception_Date=datetime.date(2024, 1, 1),
            Expiry_Date=datetime.date(2025, 1, 1),
            Sum_Insured=1_000_000.0,
            Gross_Premium=50_000.0,
            Currency=currency,
        )
        assert record.Currency == currency

    @pytest.mark.parametrize("currency", ["DOLLARS", "usd", "Us", "", "AUD"])
    def test_rejects_invalid_currencies(self, currency: str) -> None:
        with pytest.raises(ValueError):
            RiskRecord(
                Policy_ID="POL-001",
                Inception_Date=datetime.date(2024, 1, 1),
                Expiry_Date=datetime.date(2025, 1, 1),
                Sum_Insured=1_000_000.0,
                Gross_Premium=50_000.0,
                Currency=currency,
            )

    # --- Date validation ---

    def test_rejects_expiry_before_inception(self) -> None:
        with pytest.raises(ValueError, match="Expiry_Date"):
            RiskRecord(
                Policy_ID="POL-001",
                Inception_Date=datetime.date(2025, 1, 1),
                Expiry_Date=datetime.date(2024, 1, 1),
                Sum_Insured=1_000_000.0,
                Gross_Premium=50_000.0,
                Currency="USD",
            )

    def test_same_inception_and_expiry_is_valid(self) -> None:
        record = RiskRecord(
            Policy_ID="POL-001",
            Inception_Date=datetime.date(2024, 6, 15),
            Expiry_Date=datetime.date(2024, 6, 15),
            Sum_Insured=1_000_000.0,
            Gross_Premium=50_000.0,
            Currency="USD",
        )
        assert record.Inception_Date == record.Expiry_Date

    # --- Policy ID validation ---

    def test_rejects_empty_policy_id(self) -> None:
        with pytest.raises(ValueError, match="Policy_ID"):
            RiskRecord(
                Policy_ID="",
                Inception_Date=datetime.date(2024, 1, 1),
                Expiry_Date=datetime.date(2025, 1, 1),
                Sum_Insured=1_000_000.0,
                Gross_Premium=50_000.0,
                Currency="USD",
            )

    # --- Constants ---

    def test_valid_currencies_constant(self) -> None:
        assert VALID_CURRENCIES == {"USD", "GBP", "EUR", "JPY"}


class TestColumnMapping:
    """ColumnMapping must constrain target_field and confidence."""

    def test_valid_mapping(self) -> None:
        mapping = ColumnMapping(
            source_header="GWP",
            target_field="Gross_Premium",
            confidence=0.95,
        )
        assert mapping.source_header == "GWP"
        assert mapping.target_field == "Gross_Premium"
        assert mapping.confidence == 0.95

    # --- target_field validation ---

    @pytest.mark.parametrize("field", VALID_TARGET_FIELDS)
    def test_accepts_all_valid_target_fields(self, field: str) -> None:
        mapping = ColumnMapping(
            source_header="Header",
            target_field=field,
            confidence=0.9,
        )
        assert mapping.target_field == field

    @pytest.mark.parametrize("field", ["gross_premium", "Amount", "ID", ""])
    def test_rejects_invalid_target_fields(self, field: str) -> None:
        with pytest.raises(ValueError, match="target_field"):
            ColumnMapping(
                source_header="Header",
                target_field=field,
                confidence=0.9,
            )

    # --- confidence validation ---

    def test_confidence_zero_is_valid(self) -> None:
        mapping = ColumnMapping(
            source_header="Header",
            target_field="Policy_ID",
            confidence=0.0,
        )
        assert mapping.confidence == 0.0

    def test_confidence_one_is_valid(self) -> None:
        mapping = ColumnMapping(
            source_header="Header",
            target_field="Policy_ID",
            confidence=1.0,
        )
        assert mapping.confidence == 1.0

    def test_rejects_confidence_above_one(self) -> None:
        with pytest.raises(ValueError):
            ColumnMapping(
                source_header="Header",
                target_field="Policy_ID",
                confidence=1.01,
            )

    def test_rejects_confidence_below_zero(self) -> None:
        with pytest.raises(ValueError):
            ColumnMapping(
                source_header="Header",
                target_field="Policy_ID",
                confidence=-0.01,
            )


class TestMappingResult:
    """MappingResult must track mappings and unmapped headers."""

    def test_valid_result(self) -> None:
        result = MappingResult(
            mappings=[
                ColumnMapping(
                    source_header="GWP",
                    target_field="Gross_Premium",
                    confidence=0.95,
                ),
                ColumnMapping(
                    source_header="Policy No.",
                    target_field="Policy_ID",
                    confidence=0.99,
                ),
            ],
            unmapped_headers=["Extra Column"],
        )
        assert len(result.mappings) == 2
        assert result.unmapped_headers == ["Extra Column"]

    def test_empty_result(self) -> None:
        result = MappingResult(mappings=[], unmapped_headers=[])
        assert len(result.mappings) == 0
        assert len(result.unmapped_headers) == 0

    def test_rejects_duplicate_target_fields(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            MappingResult(
                mappings=[
                    ColumnMapping(
                        source_header="GWP",
                        target_field="Gross_Premium",
                        confidence=0.95,
                    ),
                    ColumnMapping(
                        source_header="Premium",
                        target_field="Gross_Premium",
                        confidence=0.80,
                    ),
                ],
                unmapped_headers=[],
            )

    # --- Constants ---

    def test_valid_target_fields_constant(self) -> None:
        assert VALID_TARGET_FIELDS == {
            "Policy_ID",
            "Inception_Date",
            "Expiry_Date",
            "Sum_Insured",
            "Gross_Premium",
            "Currency",
        }
