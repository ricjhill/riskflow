"""Tests for column-level date format detection.

Instead of guessing the date format per-value, detect it once from
preview rows (first 5 values in a date column) and apply consistently.
This solves YYYY/MM/DD misparsing where dateutil with dayfirst=True
turns "2025/07/01" into January 7 instead of July 1.
"""

import datetime

import pytest

from src.domain.model.date_format import detect_date_format, parse_date


class TestDetectDateFormat:
    """detect_date_format identifies the column format from sample values."""

    @pytest.mark.parametrize(
        "values, expected",
        [
            # ISO 8601
            (["2025-01-15", "2024-06-30"], "iso"),
            (["2025-01-15"], "iso"),
            # YYYY/MM/DD — the format that triggers the bug
            (["2025/07/01", "2025/11/25"], "yyyy_slash"),
            (["2025/07/01"], "yyyy_slash"),
            # Named months (DD-Mon-YYYY, full month, US style)
            (["01-Jan-2025", "15-Feb-2025"], "named_month"),
            (["15 January 2025", "1 March 2025"], "named_month"),
            (["January 15, 2025", "March 1, 2025"], "named_month"),
            (["01-Jan-2025"], "named_month"),
            # DD/MM/YYYY — numeric day-first
            (["15/01/2025", "28/12/2024"], "dayfirst"),
            (["01/02/2025", "05/06/2024"], "dayfirst"),
        ],
        ids=[
            "iso-multiple",
            "iso-single",
            "yyyy-slash-multiple",
            "yyyy-slash-single",
            "dd-mon-yyyy",
            "full-month-name",
            "us-style",
            "named-month-single",
            "dd/mm/yyyy",
            "dd/mm/yyyy-ambiguous",
        ],
    )
    def test_detects_format(self, values: list[str], expected: str) -> None:
        assert detect_date_format(values) == expected

    @pytest.mark.parametrize(
        "values",
        [
            [],
            ["", "  "],
            ["not-a-date", "garbage"],
            ["2025-01-15", "01-Jan-2025"],
        ],
        ids=["empty-list", "all-empty-strings", "garbage", "mixed-formats"],
    )
    def test_undetectable_returns_none(self, values: list[str]) -> None:
        assert detect_date_format(values) is None


class TestParseDate:
    """parse_date parses a value using the detected format hint."""

    @pytest.mark.parametrize(
        "value, hint, expected",
        [
            # YYYY/MM/DD — the bug fix
            ("2025/07/01", "yyyy_slash", datetime.date(2025, 7, 1)),
            ("2025/11/25", "yyyy_slash", datetime.date(2025, 11, 25)),
            ("2025/03/05", "yyyy_slash", datetime.date(2025, 3, 5)),
            # ISO
            ("2025-01-15", "iso", datetime.date(2025, 1, 15)),
            # Named month
            ("01-Jan-2025", "named_month", datetime.date(2025, 1, 1)),
            # Day-first
            ("15/01/2025", "dayfirst", datetime.date(2025, 1, 15)),
            # None fallback — ISO-first then YYYY/MM/DD then dateutil
            ("2025-01-15", None, datetime.date(2025, 1, 15)),
            ("01-Jan-2025", None, datetime.date(2025, 1, 1)),
            ("2025/07/01", None, datetime.date(2025, 7, 1)),
        ],
        ids=[
            "yyyy-slash-july",
            "yyyy-slash-november",
            "yyyy-slash-ambiguous",
            "iso",
            "named-month",
            "dayfirst",
            "none-iso",
            "none-named",
            "none-yyyy-slash",
        ],
    )
    def test_parses_correctly(self, value: str, hint: str | None, expected: datetime.date) -> None:
        assert parse_date(value, hint) == expected

    @pytest.mark.parametrize(
        "value, hint",
        [
            ("garbage", "iso"),
            ("", "iso"),
            ("not-a-date", None),
        ],
        ids=["garbage-iso", "empty-iso", "garbage-none"],
    )
    def test_raises_on_invalid(self, value: str, hint: str | None) -> None:
        with pytest.raises(ValueError, match="(?i)date|empty"):
            parse_date(value, hint)
