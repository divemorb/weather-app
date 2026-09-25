"""Small UTC time helpers shared by clients and the aggregator.

Everything in the app is UTC. These helpers keep "next N minutes/hours from
now" logic consistent and unit-testable (``now`` is always an explicit
argument rather than a hidden clock).
"""
from __future__ import annotations

import datetime as dt


def utcnow() -> dt.datetime:
    """Current time as a timezone-aware UTC datetime."""
    return dt.datetime.now(dt.timezone.utc)


def parse_iso(stamp: str) -> dt.datetime:
    """Parse an ISO-8601 stamp (Open-Meteo/Bright Sky use ``...Z`` or offsets).

    Returns a timezone-aware UTC datetime.
    """
    s = stamp.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    value = dt.datetime.fromisoformat(s)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def to_iso(value: dt.datetime) -> str:
    """Format a datetime as a ``...Z`` UTC ISO-8601 string."""
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def first_index_at_or_after(times: list[str], now: dt.datetime) -> int:
    """Index of the first timestamp >= ``now`` (binary search).

    ``times`` must be sorted ascending ISO-8601 strings. Returns ``len(times)``
    when every timestamp is before ``now``.
    """
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if parse_iso(times[mid]) < now:
            lo = mid + 1
        else:
            hi = mid
    return lo
