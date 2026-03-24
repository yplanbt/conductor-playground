import re
from datetime import date, datetime, timedelta
from typing import Optional


def parse_published_date(date_str: str) -> Optional[date]:
    """Parse a published date string into a date object.

    Handles:
    - ISO: "2026-01-15"
    - US format: "01/15/2026", "1/15/2026"
    - SerpAPI: "01/15/2026, 08:00 AM, +0000 UTC"
    - Google News: "Jan 15, 2026", "January 15, 2026", "15 Jan 2026"
    - RFC 2822: "Wed, 15 Jan 2026 12:00:00 GMT"
    - YouTube relative: "2 days ago", "1 month ago", "Streamed 5 days ago"
    - Empty/garbage: returns None
    """
    if not date_str or not isinstance(date_str, str):
        return None

    date_str = date_str.strip()
    if not date_str:
        return None

    # Try relative dates first (YouTube: "2 days ago", "Streamed 3 weeks ago")
    result = _parse_relative(date_str)
    if result:
        return result

    # Try various absolute date formats
    return _parse_absolute(date_str)


def _parse_relative(s: str) -> Optional[date]:
    """Parse relative date strings like '2 days ago', 'Streamed 1 month ago'."""
    # Strip common prefixes
    cleaned = s.lower().strip()
    for prefix in ("streamed ", "premiered ", "posted ", "published "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]

    match = re.match(r"(\d+)\s+(second|minute|hour|day|week|month|year)s?\s+ago", cleaned)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    today = date.today()

    if unit in ("second", "minute", "hour"):
        return today
    elif unit == "day":
        return today - timedelta(days=amount)
    elif unit == "week":
        return today - timedelta(weeks=amount)
    elif unit == "month":
        return today - timedelta(days=amount * 30)
    elif unit == "year":
        return today - timedelta(days=amount * 365)

    return None


def _parse_absolute(s: str) -> Optional[date]:
    """Parse absolute date strings in various formats."""
    # Clean up common suffixes/noise
    cleaned = s.strip()

    # Strip timezone info like "+0000 UTC" for easier parsing
    cleaned = re.sub(r'[,\s]+\+\d{4}\s*UTC\s*$', '', cleaned)

    # Try formats from most specific to least
    formats = [
        # ISO
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        # SerpAPI / US formats with time
        "%m/%d/%Y, %I:%M %p",
        "%m/%d/%Y, %I:%M:%S %p",
        # US date formats
        "%m/%d/%Y",
        "%m/%d/%y",
        # Google News named month
        "%b %d, %Y",
        "%B %d, %Y",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d %Y",
        # With day name
        "%a, %d %b %Y",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        # Other
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    # Last resort: try to extract a date-like pattern from the string
    # Match "Mon DD, YYYY" or "DD Mon YYYY" patterns embedded in longer strings
    month_pattern = r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*'

    # Try "Month DD, YYYY"
    m = re.search(rf'({month_pattern})\s+(\d{{1,2}}),?\s+(\d{{4}})', s, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(3)}, {m.group(4)}", "%b %d, %Y").date()
        except ValueError:
            pass

    # Try "DD Month YYYY"
    m = re.search(rf'(\d{{1,2}})\s+({month_pattern})\s+(\d{{4}})', s, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(4)}", "%d %b %Y").date()
        except ValueError:
            pass

    # Try to find YYYY-MM-DD anywhere in string
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # Try to find MM/DD/YYYY anywhere in string
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass

    return None
