from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def parse_any(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return _from_epoch(value)
    if isinstance(value, dict):
        date = value.get("$date")
        if isinstance(date, dict):
            n = date.get("$numberLong")
            if n is not None:
                return _from_epoch(int(n) / 1000.0)
        if isinstance(date, str):
            return _from_iso(date)
        return None
    if isinstance(value, str):
        return _from_iso(value)
    return None


def _from_iso(s: str) -> datetime | None:
    text = s.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _from_epoch(seconds: float) -> datetime:
    if seconds > 1e12:
        seconds = seconds / 1000.0
    return datetime.fromtimestamp(seconds, tz=UTC)
