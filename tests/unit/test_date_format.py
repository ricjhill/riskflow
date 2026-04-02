"""Tests for column-level date format detection.

Instead of guessing the date format per-value, detect it once from
preview rows (first 5 values in a date column) and apply consistently.
This solves YYYY/MM/DD misparsing where dateutil with dayfirst=True
turns "2025/07/01" into January 7 instead of July 1.
"""

from src.domain.model.date_format import detect_date_format


class TestDetectISO:
    """ISO 8601 (YYYY-MM-DD) detection."""

    def test_all_iso_dates(self) -> None:
        assert detect_date_format(["2025-01-15", "2024-06-30"]) == "iso"

    def test_single_iso_date(self) -> None:
        assert detect_date_format(["2025-01-15"]) == "iso"


class TestDetectYYYYSlash:
    """YYYY/MM/DD detection — the format that triggers the bug."""

    def test_all_yyyy_slash(self) -> None:
        assert detect_date_format(["2025/07/01", "2025/11/25"]) == "yyyy_slash"

    def test_single_yyyy_slash(self) -> None:
        assert detect_date_format(["2025/07/01"]) == "yyyy_slash"


class TestDetectNamedMonth:
    """DD-Mon-YYYY and similar formats with month names."""

    def test_dd_mon_yyyy(self) -> None:
        assert detect_date_format(["01-Jan-2025", "15-Feb-2025"]) == "named_month"

    def test_full_month_name(self) -> None:
        assert detect_date_format(["15 January 2025", "1 March 2025"]) == "named_month"

    def test_us_style(self) -> None:
        assert detect_date_format(["January 15, 2025", "March 1, 2025"]) == "named_month"


class TestDetectDayFirst:
    """DD/MM/YYYY — numeric day-first with slashes, year at end."""

    def test_dd_mm_yyyy(self) -> None:
        assert detect_date_format(["15/01/2025", "28/12/2024"]) == "dayfirst"

    def test_dd_mm_yyyy_with_ambiguous(self) -> None:
        """When all values have day ≤ 12, still detects as dayfirst
        because year is in the last position (not first)."""
        assert detect_date_format(["01/02/2025", "05/06/2024"]) == "dayfirst"


class TestDetectEdgeCases:
    """Edge cases: empty, garbage, mixed formats."""

    def test_empty_list(self) -> None:
        assert detect_date_format([]) is None

    def test_all_empty_strings(self) -> None:
        assert detect_date_format(["", "  "]) is None

    def test_garbage_strings(self) -> None:
        assert detect_date_format(["not-a-date", "garbage"]) is None

    def test_mixed_formats_returns_none(self) -> None:
        """If a column mixes ISO and DD-Mon-YYYY, return None (fall back)."""
        assert detect_date_format(["2025-01-15", "01-Jan-2025"]) is None

    def test_single_value(self) -> None:
        """Single value should still detect."""
        assert detect_date_format(["01-Jan-2025"]) == "named_month"
