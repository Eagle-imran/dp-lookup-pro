"""UTC timestamps and snapshot ages shared by stores and services."""

import math
import time
from datetime import UTC, datetime
from typing import Any

SECONDS_PER_DAY = 86_400.0


def utc_now() -> str:
    """Current time as an ISO 8601 string with a UTC offset."""
    return datetime.now(UTC).isoformat()


def _epoch_seconds(value: Any) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return float(text)


def age_days(value: Any, *, now: float | None = None) -> float | None:
    """Days from ``value`` to ``now`` (default: the current time), rounded to 3 places.

    ``value`` may be a ``datetime``, epoch seconds, or an ISO 8601 or numeric
    string. Unreadable or non-finite values give ``None``; future times give 0.
    """
    if value is None:
        return None
    try:
        timestamp = _epoch_seconds(value)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if timestamp is None or not math.isfinite(timestamp):
        return None
    reference = time.time() if now is None else now
    return round(max(0.0, (reference - timestamp) / SECONDS_PER_DAY), 3)
