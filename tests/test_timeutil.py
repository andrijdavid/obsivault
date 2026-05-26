from __future__ import annotations

from datetime import UTC, datetime

from obsivault.core.timeutil import parse_any


def test_parse_iso_z():
    assert parse_any("2026-04-05T09:33:30Z") == datetime(2026, 4, 5, 9, 33, 30, tzinfo=UTC)


def test_parse_iso_offset():
    dt = parse_any("2026-03-21T12:48:35.034294+00:00")
    assert dt is not None and dt.tzinfo is not None


def test_parse_mongo_date():
    raw = {"$date": {"$numberLong": "1779606199902"}}
    dt = parse_any(raw)
    assert dt is not None and dt.year == 2026


def test_parse_epoch_float():
    dt = parse_any(1700000000.0)
    assert dt is not None and dt.tzinfo is UTC


def test_parse_none():
    assert parse_any(None) is None
    assert parse_any("") is None
