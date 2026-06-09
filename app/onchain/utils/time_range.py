"""Shared time-window helpers for on-chain queries."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def parse_date_param(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    """Parse YYYY-MM-DD or ISO datetime string to naive UTC datetime."""
    if not value or not str(value).strip():
        return None

    raw = str(value).strip()
    try:
        if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
            dt = datetime.strptime(raw, "%Y-%m-%d")
            if end_of_day:
                return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            return dt

        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or ISO datetime.") from exc


def resolve_time_range(
    *,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    hours: Optional[int] = 24,
) -> tuple[datetime, datetime]:
    """Return (since, until) for filtering on-chain data."""
    until = end or datetime.utcnow()
    if start is not None:
        since = start
    elif hours is not None:
        since = until - timedelta(hours=hours)
    else:
        since = until - timedelta(hours=24)

    if since > until:
        since, until = until, since

    return since, until
