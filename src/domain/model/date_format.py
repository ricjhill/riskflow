"""Column-level date format detection and parsing.

Detects the date format from a sample of values in a single column,
returning a format identifier that parse_date() can use for consistent
parsing across all rows. This avoids the per-value guessing that causes
dateutil with dayfirst=True to misparse YYYY/MM/DD dates.
"""

import datetime
import re

from dateutil import parser as dateutil_parser

# Regex patterns for format detection
_ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YYYY_SLASH_PATTERN = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")
_DAYFIRST_SLASH_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
_MONTH_NAME_RE = re.compile(
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|"
    r"January|February|March|April|June|July|August|September|October|November|December)",
    re.IGNORECASE,
)


def detect_date_format(values: list[str]) -> str | None:
    """Detect the date format from sample column values.

    Returns a format identifier:
    - "iso" — YYYY-MM-DD
    - "yyyy_slash" — YYYY/MM/DD
    - "named_month" — contains month names (Jan, January, etc.)
    - "dayfirst" — DD/MM/YYYY (numeric, year at end)
    - None — undetectable or mixed formats
    """
    if not values:
        return None

    stripped = [v.strip() for v in values if v.strip()]
    if not stripped:
        return None

    if all(_ISO_PATTERN.match(v) for v in stripped):
        return "iso"

    if all(_YYYY_SLASH_PATTERN.match(v) for v in stripped):
        return "yyyy_slash"

    if all(_MONTH_NAME_RE.search(v) for v in stripped):
        return "named_month"

    if all(_DAYFIRST_SLASH_PATTERN.match(v) for v in stripped):
        return "dayfirst"

    return None


def parse_date(value: str, format_hint: str | None) -> datetime.date:
    """Parse a date string using the detected format hint.

    If format_hint is None, falls back to the ISO-first then dateutil
    logic used by coerce_date().
    """
    stripped = value.strip()
    if not stripped:
        msg = "Date string must not be empty"
        raise ValueError(msg)

    if format_hint == "iso":
        try:
            return datetime.date.fromisoformat(stripped)
        except ValueError as e:
            msg = f"Could not parse date as ISO: '{value}'"
            raise ValueError(msg) from e

    if format_hint == "yyyy_slash":
        m = _YYYY_SLASH_PATTERN.match(stripped)
        if m:
            parts = stripped.split("/")
            try:
                return datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            except ValueError as e:
                msg = f"Could not parse date as YYYY/MM/DD: '{value}'"
                raise ValueError(msg) from e
        msg = f"Could not parse date as YYYY/MM/DD: '{value}'"
        raise ValueError(msg)

    if format_hint in ("named_month", "dayfirst"):
        try:
            return dateutil_parser.parse(stripped, dayfirst=True).date()
        except (ValueError, OverflowError) as e:
            msg = f"Could not parse date: '{value}'"
            raise ValueError(msg) from e

    # None hint: ISO-first, then dateutil fallback (same as coerce_date)
    try:
        return datetime.date.fromisoformat(stripped)
    except ValueError:
        pass
    try:
        return dateutil_parser.parse(stripped, dayfirst=True).date()
    except (ValueError, OverflowError) as e:
        msg = f"Could not parse date: '{value}'"
        raise ValueError(msg) from e
