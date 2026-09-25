"""Unit tests for the UTC time helpers."""
from __future__ import annotations

from datetime import datetime, timezone

from app.times import first_index_at_or_after, parse_iso, to_iso


def test_parse_iso_z_suffix():
    value = parse_iso("2026-09-25T06:00:00Z")
    assert value.tzinfo is not None
    assert value == datetime(2026, 9, 25, 6, 0, 0, tzinfo=timezone.utc)


def test_parse_iso_offset_normalized_to_utc():
    value = parse_iso("2026-09-25T08:00:00+02:00")
    assert value == datetime(2026, 9, 25, 6, 0, 0, tzinfo=timezone.utc)


def test_parse_iso_naive_assumed_utc():
    value = parse_iso("2026-09-25T06:00:00")
    assert value.tzinfo is not None
    assert value.hour == 6


def test_to_iso_roundtrip():
    original = datetime(2026, 9, 25, 6, 30, 0, tzinfo=timezone.utc)
    assert to_iso(original) == "2026-09-25T06:30:00Z"


def test_first_index_at_or_after_basic():
    times = [
        "2026-09-25T06:00:00Z",
        "2026-09-25T06:15:00Z",
        "2026-09-25T06:30:00Z",
    ]
    now = datetime(2026, 9, 25, 6, 20, 0, tzinfo=timezone.utc)
    assert first_index_at_or_after(times, now) == 2  # 06:30 is first >= 06:20


def test_first_index_at_or_after_before_first():
    times = ["2026-09-25T06:00:00Z", "2026-09-25T06:15:00Z"]
    now = datetime(2026, 9, 25, 5, 59, 0, tzinfo=timezone.utc)
    assert first_index_at_or_after(times, now) == 0


def test_first_index_at_or_after_after_last():
    times = ["2026-09-25T06:00:00Z", "2026-09-25T06:15:00Z"]
    now = datetime(2026, 9, 25, 6, 16, 0, tzinfo=timezone.utc)
    assert first_index_at_or_after(times, now) == len(times)


def test_first_index_at_or_after_exact_match():
    times = ["2026-09-25T06:00:00Z", "2026-09-25T06:15:00Z"]
    now = parse_iso(times[1])
    assert first_index_at_or_after(times, now) == 1
