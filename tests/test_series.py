"""Unit tests for the pure API-series helpers (no I/O, no network).

Covers ``build_24h_series`` (the 24 h model chart) and the new
``build_radar_next_hour_bar`` (the 60-minute local-rain bar) — including the
5-minute grid alignment and the unavailable / partial-coverage fallbacks.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    ForecastBundle,
    ModelSeries,
    RadarCell,
    RadarFrame,
    RadarNowcast,
)
from app.series import build_24h_series, build_radar_next_hour_bar

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def _model(name: str, hourly: list[float | None]) -> ModelSeries:
    base = NOW.replace(minute=0, second=0)
    return ModelSeries(
        name=name,
        hourly_time=[base + timedelta(hours=i) for i in range(len(hourly))],
        hourly_precip_mm=hourly,
    )


# ---------------------------------------------------------------------------
# build_24h_series
# ---------------------------------------------------------------------------
def test_24h_series_empty_bundle():
    out = build_24h_series(None, n_hours=24)
    assert out == {"hours": [], "models": [], "n_models": 0}


def test_24h_series_shapes_hours_and_models():
    bundle = ForecastBundle(
        models=[
            _model("icon_d2", [0.4, 0.0, 0.2] + [0.0] * 21),
            _model("gfs", [0.1, 0.3, 0.0] + [0.0] * 21),
        ]
    )
    out = build_24h_series(bundle, n_hours=24)
    assert len(out["hours"]) == 24
    assert out["n_models"] == 2
    assert out["hours"][0] == "2025-01-01T12:00:00Z"
    by_name = {m["name"]: m["precipitation_mm"] for m in out["models"]}
    assert by_name["icon_d2"][0] == 0.4
    assert by_name["gfs"][1] == 0.3


def test_24h_series_truncates_to_n_hours():
    bundle = ForecastBundle(models=[_model("icon_d2", [1.0, 2.0, 3.0, 4.0])])
    out = build_24h_series(bundle, n_hours=3)
    assert len(out["hours"]) == 3
    assert out["models"][0]["precipitation_mm"] == [1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# build_radar_next_hour_bar
# ---------------------------------------------------------------------------
def _cell(x: int, y: int, mm: float) -> RadarCell:
    return RadarCell(x=x, y=y, mm=mm)


def _frame(offset_min: int, cells: list[RadarCell]) -> RadarFrame:
    return RadarFrame(
        time_utc=NOW + timedelta(minutes=offset_min),
        cells=cells,
        max_mm=max((c.mm for c in cells), default=0.0),
    )


def _nowcast(frames, covered: bool = True) -> RadarNowcast:
    return RadarNowcast(frames=frames, covered=covered, bbox=(0, 0, 10, 10), location_xy=(5.0, 5.0))


def test_bar_none_nowcast_is_unavailable():
    out = build_radar_next_hour_bar(None, NOW, 5.0, 1.0, 0.05)
    assert out["available"] is False
    assert len(out["steps"]) == 12
    assert all(s["precip_mm"] == 0.0 for s in out["steps"])


def test_bar_not_covered_is_unavailable():
    out = build_radar_next_hour_bar(
        _nowcast([_frame(0, [_cell(5, 5, 0.3)])], covered=False), NOW, 5.0, 1.0, 0.05
    )
    assert out["available"] is False


def test_bar_matches_frames_on_grid():
    # frames at +0, +5, +10 min; rain only in the +5 bucket at the location
    nc = _nowcast(
        [
            _frame(0, []),
            _frame(5, [_cell(5, 5, 0.3)]),
            _frame(10, []),
        ]
    )
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05)
    assert out["available"] is True
    steps = out["steps"]
    assert steps[0]["start_utc"] == "2025-01-01T12:00:00Z"
    assert steps[0]["precip_mm"] == 0.0
    assert steps[1]["start_utc"] == "2025-01-01T12:05:00Z"
    assert steps[1]["precip_mm"] == 0.3
    assert steps[2]["precip_mm"] == 0.0
    # the remaining 9 buckets have no radar frame yet -> dry
    assert all(s["precip_mm"] == 0.0 for s in steps[3:])


def test_bar_ignores_cells_outside_radius():
    # 0.5 mm 15 km away (outside the 5 km radius) must not show in the bar
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.1), _cell(20, 5, 0.5)])])
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05)
    assert out["steps"][0]["precip_mm"] == 0.1  # only the local cell


def test_bar_ignores_below_threshold():
    # 0.04 mm at the location is below the 0.05 mm threshold -> not rain
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.04)])])
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05)
    assert out["steps"][0]["precip_mm"] == 0.0


def test_bar_floors_now_to_grid():
    # now = 12:03 -> floored to 12:00; a frame at 12:00 lands in bucket 0
    now = NOW + timedelta(minutes=3)
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.2)])])  # frame at 12:00
    out = build_radar_next_hour_bar(nc, now, 5.0, 1.0, 0.05)
    assert out["steps"][0]["start_utc"] == "2025-01-01T12:00:00Z"
    assert out["steps"][0]["precip_mm"] == 0.2


def test_bar_custom_step_count():
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.2)])])
    out = build_radar_next_hour_bar(nc, NOW, 5.0, 1.0, 0.05, n_steps=4)
    assert len(out["steps"]) == 4
    assert out["steps"][0]["precip_mm"] == 0.2
    assert all(s["precip_mm"] == 0.0 for s in out["steps"][1:])
