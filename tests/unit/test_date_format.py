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
