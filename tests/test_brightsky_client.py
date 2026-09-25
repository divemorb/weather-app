"""Unit tests for the Bright Sky client (parsers + HTTP layer).

Parser tests use synthetic payloads (no network). HTTP-layer tests use
``httpx.MockTransport`` to avoid any real requests.
"""
from __future__ import annotations

import pytest
import httpx

from app.brightsky_client import (
    BrightSkyClient,
    SourceError,
    parse_current_weather,
    parse_radar,
)
from tests.helpers import make_cfg, make_current_payload, make_radar_payload, grid


# ---------------------------------------------------------------------------
# parse_current_weather
# ---------------------------------------------------------------------------
def test_parse_current_weather_maps_fields():
    cond = parse_current_weather(make_current_payload())
    assert cond.temperature_c == 7.4
    assert cond.wind_speed_ms == 5.0
    assert cond.wind_direction_deg == 260
    assert cond.wind_gust_ms == 11.0
    assert cond.cloud_cover_pct == 88
    assert cond.humidity_pct == 87
    assert cond.pressure_hpa == 1026.0
    assert cond.dew_point_c == 3.5
    assert cond.precipitation_60mm == 0.8
    assert cond.condition == "dry"
    assert cond.source_id == 96160
    assert cond.feels_like_c is None  # filled later from Open-Meteo


def test_parse_current_weather_handles_nulls():
    cond = parse_current_weather(
        make_current_payload({"temperature": None, "cloud_cover": None})
    )
    assert cond.temperature_c is None
    assert cond.cloud_cover_pct is None


def test_parse_current_weather_missing_weather_raises():
    with pytest.raises(SourceError):
        parse_current_weather({"sources": []})


# ---------------------------------------------------------------------------
# parse_radar
# ---------------------------------------------------------------------------
def test_parse_radar_decodes_grid_and_unit():
    g = grid(5, 5)
    g[1][1] = 38  # 0.38 mm
    payload = make_radar_payload(
        [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": g}]
    )
    nc = parse_radar(payload)
    assert len(nc.frames) == 1
    frame = nc.frames[0]
    assert frame.max_mm == pytest.approx(0.38)
    assert len(frame.cells) == 1
    cell = frame.cells[0]
    # sub-grid origin (top,left)=(10,20); row1,col1 -> y=11, x=21
    assert (cell.x, cell.y) == (21, 11)
    assert cell.mm == pytest.approx(0.38)
    assert nc.grid_width == 5
    assert nc.grid_height == 5
    assert nc.bbox == (10, 20, 14, 24)
    assert nc.covered is True


def test_parse_radar_keeps_only_requested_window():
    frames = [
        {"timestamp": f"2026-09-25T06:{m:02d}:00+00:00", "grid": grid(5, 5)}
        for m in range(0, 30, 5)  # 6 frames
    ]
    payload = make_radar_payload(frames)
    nc = parse_radar(payload, window_frames=2)
    assert len(nc.frames) == 2


def test_parse_radar_empty_frames_raises():
    with pytest.raises(SourceError):
        parse_radar(
            {
                "radar": [],
                "bbox": [0, 0, 1, 1],
                "latlon_position": {"x": 0, "y": 0},
            }
        )


def test_parse_radar_missing_bbox_raises():
    with pytest.raises(SourceError):
        parse_radar({"radar": [{"timestamp": "t", "precipitation_5": ""}]})


def test_parse_radar_bad_frame_size_raises():
    # grid is 4x4 but bbox implies 3x3 -> mismatch
    g = grid(4, 4)
    payload = make_radar_payload(
        [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": g}],
        bbox=(10, 20,

