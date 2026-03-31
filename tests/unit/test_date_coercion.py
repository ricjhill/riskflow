"""Tests for flexible date parsing in dynamic record models.

Real-world bordereaux use many date formats: DD-Mon-YYYY, DD/MM/YYYY,
Mon DD YYYY, etc. The record factory must coerce these to datetime.date
before Pydantic's strict ISO parser runs.

Tests cover:
- Common broker date formats (DD-Mon-YYYY, DD/MM/YYYY, YYYY/MM/DD, etc.)
- Passthrough for already-valid types (datetime.date, datetime.datetime, ISO strings)
- Invalid inputs still raise errors
- Coercion works with cross-field date ordering rules
- Both dynamic model and hardcoded RiskRecord accept flexible dates
"""

import datetime

import pytest
from pydantic import BaseModel, ValidationError

from src.domain.model.record_factory import build_record_model, clear_record_model_cache
from src.domain.model.schema import RiskRecord
from src.domain.model.target_schema import (
    DEFAULT_TARGET_SCHEMA,
    DateOrderingRule,
    FieldDefinition,
    FieldType,
    TargetSchema,
)


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Ensure each test gets a fresh model build."""
    clear_record_model_cache()


def _date_schema() -> TargetSchema:
    """Minimal schema with a single required date field."""
    return TargetSchema(
        name="test_dates",
        fields={"Start": FieldDefinition(type=FieldType.DATE)},
    )


class TestDateCoercionFormats:
    """Common date formats found in broker spreadsheets."""

    @pytest.mark.parametrize(
        "date_str, expected",
        [
            # ISO 8601 — already works, must not break
            ("2025-01-15", datetime.date(2025, 1, 15)),
            # DD-Mon-YYYY — the format that triggered this feature
            ("01-Jan-2025", datetime.date(2025, 1, 1)),
            ("15-Feb-2025", datetime.date(2025, 2, 15)),
            ("28-Dec-2024", datetime.date(2024, 12, 28)),
            # DD/MM/YYYY — common in London market
            ("15/01/2025", datetime.date(2025, 1, 15)),
            ("01/12/2025", datetime.date(2025, 12, 1)),
            # YYYY/MM/DD
            ("2025/01/15", datetime.date(2025, 1, 15)),
            # DD Mon YYYY (space-separated)
            ("15 January 2025", datetime.date(2025, 1, 15)),
            ("1 Mar 2025", datetime.date(2025, 3, 1)),
            # Mon DD, YYYY (US letter-style)
            ("January 15, 2025", datetime.date(2025, 1, 15)),
            ("Mar 1, 2025", datetime.date(2025, 3, 1)),
        ],
        ids=[
            "iso-8601",
            "dd-mon-yyyy-jan",
            "dd-mon-yyyy-feb",
            "dd-mon-yyyy-dec",
            "dd/mm/yyyy",
            "dd/mm/yyyy-dec",
            "yyyy/mm/dd",
            "dd-month-yyyy-full",
            "d-mon-yyyy-short",
            "month-dd-yyyy-full",
            "mon-dd-yyyy-short",
        ],
    )
    def test_accepts_common_date_format(self, date_str: str, expected: datetime.date) -> None:
        Model = build_record_model(_date_schema())
        record = Model.model_validate({"Start": date_str})
        assert record.Start == expected  # type: ignore[attr-defined]

    def test_accepts_datetime_date_object(self) -> None:
        Model = build_record_model(_date_schema())
        d = datetime.date(2025, 6, 15)
        record = Model.model_validate({"Start": d})
        assert record.Start == d  # type: ignore[attr-defined]

    def test_accepts_datetime_datetime_object(self) -> None:
        """datetime.datetime should be coerced to date (drop time component)."""
        Model = build_record_model(_date_schema())
        dt = datetime.datetime(2025, 6, 15, 14, 30, 0)
        record = Model.model_validate({"Start": dt})
        assert record.Start == datetime.date(2025, 6, 15)  # type: ignore[attr-defined]


class TestDateCoercionInvalidInput:
    """Invalid date strings must still raise validation errors."""

    @pytest.mark.parametrize(
        "bad_value",
        [
            "not-a-date",
            "2025-02-30",  # Feb 30
            "",
            "yesterday",
        ],
        ids=["garbage", "feb-30", "empty-string", "relative-word"],
    )
    def test_rejects_invalid_date_string(self, bad_value: str) -> None:
        Model = build_record_model(_date_schema())
        with pytest.raises((ValidationError, ValueError)):
            Model.model_validate({"Start": bad_value})


class TestDateCoercionWithCrossFieldRules:
    """Date coercion must work before cross-field ordering validation."""

    def _ordered_schema(self) -> TargetSchema:
        return TargetSchema(
            name="test_ordered",
            fields={
                "Start": FieldDefinition(type=FieldType.DATE),
                "End": FieldDefinition(type=FieldType.DATE),
            },
            cross_field_rules=[DateOrderingRule(earlier="Start", later="End")],
        )

    def test_cross_field_works_with_coerced_dates(self) -> None:
        Model = build_record_model(self._ordered_schema())
        record = Model.model_validate(
            {
                "Start": "01-Jan-2025",
                "End": "31-Dec-2025",
            }
        )
        assert record.Start < record.End  # type: ignore[attr-defined]

    def test_cross_field_rejects_reversed_coerced_dates(self) -> None:
        Model = build_record_model(self._ordered_schema())
        with pytest.raises((ValidationError, ValueError), match="End"):
            Model.model_validate(
                {
                    "Start": "31-Dec-2025",
                    "End": "01-Jan-2025",
                }
            )

    def test_mixed_formats_in_cross_field(self) -> None:
        """One date in ISO, one in DD-Mon-YYYY — both should coerce."""
        Model = build_record_model(self._ordered_schema())
        record = Model.model_validate(
            {
                "Start": "2025-01-01",
                "End": "31-Dec-2025",
            }
        )
        assert record.Start < record.End  # type: ignore[attr-defined]


class TestDateCoercionOptionalFields:
    """Optional date fields with None should still work."""

    def test_optional_date_none_still_accepted(self) -> None:
        schema = TargetSchema(
            name="test_optional",
            fields={
                "Start": FieldDefinition(type=FieldType.DATE, required=False),
            },
        )
        Model = build_record_model(schema)
        record = Model.model_validate({})
        assert record.Start is None  # type: ignore[attr-defined]


class TestRiskRecordDateCoercion:
    """The hardcoded RiskRecord must also accept flexible date formats,
    maintaining equivalence with the dynamic model."""

    def test_accepts_dd_mon_yyyy(self) -> None:
        record = RiskRecord.model_validate(
            {
                "Policy_ID": "P001",
                "Inception_Date": "01-Jan-2025",
                "Expiry_Date": "31-Dec-2025",
                "Sum_Insured": 1_000_000.0,
                "Gross_Premium": 50_000.0,
                "Currency": "USD",
            }
        )
        assert record.Inception_Date == datetime.date(2025, 1, 1)
        assert record.Expiry_Date == datetime.date(2025, 12, 31)

    def test_accepts_dd_slash_mm_slash_yyyy(self) -> None:
        record = RiskRecord.model_validate(
            {
                "Policy_ID": "P001",
                "Inception_Date": "15/01/2025",
                "Expiry_Date": "15/01/2026",
                "Sum_Insured": 1_000_000.0,
                "Gross_Premium": 50_000.0,
                "Currency": "USD",
            }
        )
        assert record.Inception_Date == datetime.date(2025, 1, 15)


class TestDynamicModelEquivalenceWithFlexibleDates:
    """Dynamic and static models must agree on flexible date inputs."""

    VALID_ROW_FLEXIBLE = {
        "Policy_ID": "POL-001",
        "Inception_Date": "01-Jan-2024",
        "Expiry_Date": "01-Jan-2025",
        "Sum_Insured": 1_000_000.0,
        "Gross_Premium": 50_000.0,
        "Currency": "USD",
    }

    @pytest.fixture
    def DynamicRecord(self) -> type[BaseModel]:
        return build_record_model(DEFAULT_TARGET_SCHEMA)

    def test_both_accept_flexible_dates(self, DynamicRecord: type[BaseModel]) -> None:
        static = RiskRecord.model_validate(self.VALID_ROW_FLEXIBLE)
        dynamic = DynamicRecord.model_validate(self.VALID_ROW_FLEXIBLE)

        assert static.Inception_Date == dynamic.Inception_Date  # type: ignore[attr-defined]
        assert static.Expiry_Date == dynamic.Expiry_Date  # type: ignore[attr-defined]
        assert static.Inception_Date == datetime.date(2024, 1, 1)  # type: ignore[attr-defined]
