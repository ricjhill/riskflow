"""Column-level date format detection.

Detects the date format from a sample of values in a single column,
returning a format identifier that parse_date() can use for consistent
parsing across all rows. This avoids the per-value guessing that causes
dateutil with dayfirst=True to misparse YYYY/MM/DD dates.
"""

import re

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
