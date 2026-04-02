"""Column-level date format detection.

Detects the date format from a sample of values in a single column,
returning a format identifier that parse_date() can use for consistent
parsing across all rows. This avoids the per-value guessing that causes
dateutil with dayfirst=True to misparse YYYY/MM/DD dates.
"""

import re

# Regex patterns for format detection
_ISO_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def detect_date_format(values: list[str]) -> str | None:
    """Detect the date format from sample column values.

    Returns a format identifier or None if undetectable.
    """
    if not values:
        return None

    if all(_ISO_PATTERN.match(v.strip()) for v in values if v.strip()):
        return "iso"

    return None
