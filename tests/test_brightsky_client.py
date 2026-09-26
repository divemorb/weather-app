"""Unit tests for the Bright Sky client (parsers + HTTP layer).

Parser tests use synthetic payloads (no network). HTTP-layer tests use
``httpx.MockTransport`` to avoid any real requests.
"""
from __future__ import annotations

import pytest
import httpx
from datetime import datetime, timezone

from app.brightsky_client import (
    BrightSkyClient,
    SourceError,
    parse_current_weather,
    parse_radar,
)
from tests.helpers import make_cfg, make_current_payload, make_radar_payload, grid


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


def test_parse_radar_keeps_all_frames_in_window():
    """The request window is bounded upstream (fetch_radar_payload), so the
    parser keeps every frame it receives (oldest-first)."""
    frames = [
        {"timestamp": f"2026-09-25T06:{m:02d}:00+00:00", "grid": grid(5, 5)}
        for m in range(0, 30, 5)  # 6 frames
    ]
    payload = make_radar_payload(frames)
    nc = parse_radar(payload)
    assert len(nc.frames) == 6
    assert [f.time_utc for f in nc.frames] == sorted(f.time_utc for f in nc.frames)


def test_parse_radar_empty_frames_raises():
    with pytest.raises(SourceError):
        parse_radar(
            {"radar": [], "bbox": [0, 0, 1, 1], "latlon_position": {"x": 0, "y": 0}}
        )


def test_parse_radar_missing_bbox_raises():
    with pytest.raises(SourceError):
        parse_radar({"radar": [{"timestamp": "t", "precipitation_5": ""}]})


def test_parse_radar_bad_frame_size_raises():
    # grid is 4x4 but bbox implies 3x3 -> mismatch
    g = grid(4, 4)
    payload = make_radar_payload(
        [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": g}],
        bbox=(10, 20, 12, 22),
    )
    with pytest.raises(SourceError):
        parse_radar(payload)


def test_parse_radar_location_outside_grid_marks_uncovered():
    g = grid(5, 5)
    payload = make_radar_payload(
        [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": g}],
        latlon_position={"x": 99.0, "y": 99.0},
    )
    nc = parse_radar(payload)
    assert nc.covered is False


async def test_client_fetch_current_uses_correct_endpoint():
    cfg = make_cfg()
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=make_current_payload())

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    got = await client.fetch_current()
    assert got.temperature_c == 7.4
    assert "/current_weather" in seen["url"]
    assert "lat=52.0" in seen["url"] and "lon=13.0" in seen["url"]
    await client.aclose()


async def test_client_radar_endpoint():
    cfg = make_cfg()
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        g = grid(5, 5)
        return httpx.Response(
            200,
            json=make_radar_payload(
                [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": g}]
            ),
        )

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    nc = await client.fetch_radar()
    assert len(nc.frames) == 1
    assert "/radar" in seen["url"]
    await client.aclose()


async def test_fetch_radar_requests_next_hour_window(monkeypatch):
    """The radar request must cover [now, now+1h) so the response includes the
    nowcast (frames at or after 'now'). Without it Bright Sky returns the
    previous hour only (all in the past) and the radar signal stays dry."""
    cfg = make_cfg()
    monkeypatch.setattr(
        "app.brightsky_client.utcnow",
        lambda: datetime(2026, 9, 25, 6, 23, tzinfo=timezone.utc),
    )
    params: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        params.update(request.url.params)
        return httpx.Response(200, json=make_radar_payload([]))

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    await client.fetch_radar_payload()
    await client.aclose()
    # 'now' = 06:23 -> floored to 06:20, window covers [06:20, 07:20] which
    # contains [06:23, 07:23).
    assert params["date"] == "2026-09-25T06:20:00+00:00"
    assert params["last_date"] == "2026-09-25T07:20:00+00:00"


async def test_client_http_error_raises_source_error():
    cfg = make_cfg()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SourceError):
        await client.fetch_current()
    await client.aclose()
