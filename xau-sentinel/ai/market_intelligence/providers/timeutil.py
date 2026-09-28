"""Safe, timezone-aware timestamp parsing for external data (Stage 11) —
the one thing the spec calls out as critical: every external timestamp
must be parsed safely, end up timezone-aware, and be normalized to UTC
internally, so nothing downstream can accidentally compare a naive
datetime against an aware one (a TypeError in Python, or worse, a silently
wrong comparison if it's ever "fixed" by stripping tzinfo instead of
normalizing it).

parse_timestamp() NEVER raises and NEVER returns a naive datetime — an
unparseable value returns None (never fabricated, matching this project's
existing "explicit unavailable, never invented" convention), and a parsed
naive value (e.g. FRED's plain "YYYY-MM-DD") is assumed UTC before being
returned, exactly like this project's other internal-UTC-storage
conventions (see config.py's SESSION_TIMEZONE comment).
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Union


def parse_timestamp(value: Union[str, int, float, None]) -> Optional[datetime]:
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    text = str(value).strip()
    if not text:
        return None

    # RFC 822 (RSS <pubDate>, e.g. "Mon, 28 Sep 2026 14:12:00 GMT").
    try:
        dt = parsedate_to_datetime(text)
        if dt is not None:
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass

    # ISO 8601 (ai/market_intelligence's own convention, and FRED's
    # "YYYY-MM-DD" date-only form, which fromisoformat also accepts).
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    return None
