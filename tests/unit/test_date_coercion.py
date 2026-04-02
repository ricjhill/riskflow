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
            # ISO 8601 where both month and day are valid months (1-12).
            # Without ISO-first parsing, dayfirst=True swaps these:
            # "2024-04-02" becomes Feb 4 instead of April 2.
            ("2024-04-02", datetime.date(2024, 4, 2)),
            ("2024-09-06", datetime.date(2024, 9, 6)),
            # DD-Mon-YYYY — the format that triggered this feature
            ("01-Jan-2025", datetime.date(2025, 1, 1)),
            ("15-Feb-2025", datetime.date(2025, 2, 15)),
            ("28-Dec-2024", datetime.date(2024, 12, 28)),
            # DD/MM/YYYY — common in London market
            ("15/01/2025", datetime.date(2025, 1, 15)),
            ("01/12/2025", datetime.date(2025, 12, 1)),
            # DD/MM/YYYY where both day and month are valid months (1-12).
            # Proves dayfirst=True correctly assigns 02 as day, 04 as month.
            ("02/04/2024", datetime.date(2024, 4, 2)),
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
            "iso-ambiguous-april",
            "iso-ambiguous-september",
            "dd-mon-yyyy-jan",
            "dd-mon-yyyy-feb",
            "dd-mon-yyyy-dec",
            "dd/mm/yyyy",
            "dd/mm/yyyy-dec",
            "dd/mm/yyyy-ambiguous-dayfirst",
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
        with pytest.raises((ValidationError, ValueError), match="(?i)date|empty"):
            Model.model_validate({"Start": bad_value})

    def test_non_string_non_date_falls_through_to_pydantic(self) -> None:
        """An integer like 20250115 is not a date — coerce_date passes it
        through unchanged and Pydantic's type check rejects it."""
        Model = build_record_model(_date_schema())
        with pytest.raises(ValidationError, match="Start"):
            Model.model_validate({"Start": 20250115})


class TestDateCoercionLenientBehavior:
    """Document dateutil's known lenient behavior.

    dateutil accepts partial date strings and fills in missing components
    from today's date. These tests document this behavior so future changes
    can make informed decisions about tightening validation.
    """

    def test_partial_month_year_produces_a_date(self) -> None:
        """'Jan 2025' is accepted by dateutil (fills in day). This is lenient
        but documenting the behavior prevents surprise regressions."""
        Model = build_record_model(_date_schema())
        record = Model.model_validate({"Start": "Jan 2025"})
        assert record.Start.year == 2025  # type: ignore[attr-defined]
        assert record.Start.month == 1  # type: ignore[attr-defined]

    def test_bare_iso_no_separators_produces_a_date(self) -> None:
        """'20250115' is accepted by dateutil as a compact ISO date."""
        Model = build_record_model(_date_schema())
        record = Model.model_validate({"Start": "20250115"})
        assert record.Start == datetime.date(2025, 1, 15)  # type: ignore[attr-defined]

    def test_invalid_month_13_silently_reinterpreted(self) -> None:
        """'2025-13-05' has month 13 which is invalid. fromisoformat rejects
        it, but dateutil with dayfirst=True silently interprets it as day=13,
        month=05 — producing May 13, 2025 instead of raising an error.

        This documents a data integrity risk: if a source system produces
        month-13 dates (e.g. off-by-one bug), coerce_date will silently
        accept them as valid dates with wrong values."""
        Model = build_record_model(_date_schema())
        record = Model.model_validate({"Start": "2025-13-05"})
        # dateutil with dayfirst=True: day=13, month=05 → May 13
        assert record.Start == datetime.date(2025, 5, 13)  # type: ignore[attr-defined]


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
