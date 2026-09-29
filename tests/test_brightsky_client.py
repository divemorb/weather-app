"""Unit tests for the Bright Sky client (parsers + HTTP layer).

Parser tests use synthetic payloads (no network). HTTP-layer tests use
``httpx.MockTransport`` to avoid any real requests.
"""
from __future__ import annotations

import base64
import time
import zlib

import pytest
import httpx
from datetime import datetime, timezone

from app.brightsky_client import (
    BrightSkyClient,
    MAX_RADAR_CELLS,
    MAX_RESPONSE_BYTES,
    SourceError,
    parse_current_weather,
    parse_hourly_observations,
    parse_radar,
    parse_station_info,
)
from tests.helpers import (
    make_cfg,
    make_current_payload,
    make_radar_payload,
    make_weather_payload,
    grid,
)


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


def test_parse_current_weather_wrong_type_raises_source_error():
    # a string where a number belongs: untrusted payload, must be a
    # SourceError (the request path only catches that), not a TypeError
    with pytest.raises(SourceError, match="malformed"):
        parse_current_weather(make_current_payload({"temperature": "not-a-number"}))


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


def test_parse_radar_non_numeric_bbox_raises_source_error():
    # a bbox entry that is not a number: untrusted payload -> SourceError,
    # not an unhandled ValueError (500)
    g = grid(5, 5)
    payload = make_radar_payload(
        [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": g}], bbox=["a", 20, 14, 24]
    )
    with pytest.raises(SourceError, match="malformed"):
        parse_radar(payload)


def test_parse_radar_huge_bbox_raises_source_error():
    # width * height > MAX_RADAR_CELLS must be rejected BEFORE decoding,
    # otherwise the decoder would allocate an absurd grid (2.5e9 cells here)
    payload = make_radar_payload(
        [{"timestamp": "2026-09-25T06:45:00+00:00", "grid": grid(5, 5)}],
        bbox=(0, 0, 1_000_000, 1_000_000),
    )
    with pytest.raises(SourceError, match="MAX_RADAR_CELLS"):
        parse_radar(payload)


def test_parse_radar_zip_bomb_frame_raises_source_error():
    # a frame whose zlib stream expands far beyond the expected grid size
    # must be aborted at the decompression cap, not fully decompressed
    raw = zlib.compress(b"\0" * 10_000_000)  # 10 MB from a few KB
    encoded = base64.b64encode(raw).decode("ascii")
    payload = make_radar_payload([])
    payload["radar"] = [
        {"timestamp": "2026-09-25T06:45:00+00:00", "precipitation_5": encoded}
    ]
    start = time.monotonic()
    with pytest.raises(SourceError):
        parse_radar(payload)
    # the cap (100x100x2+1 bytes here) stops the stream after 20 KB of the
    # 10 MB expansion — comfortably fast even on a slow machine
    assert time.monotonic() - start < 1.0


NOW_WEATHER = datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc)


def test_parse_hourly_observations_keeps_real_past_hours():
    """Only real-observation records (observation_type != 'forecast') with a
    past timestamp and a non-null precipitation are kept, labelled by hour
    start (timestamp - 1h, since the value covers [T-1h, T))."""
    obs = parse_hourly_observations(make_weather_payload(), NOW_WEATHER)
    assert obs == [
        (datetime(2026, 9, 27, 15, 0, tzinfo=timezone.utc), 0.0),  # 16:00 stamp
        (datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc), 0.4),  # 18:00 stamp
    ]


def test_parse_hourly_observations_drops_forecast_null_and_future():
    """Forecast records, null precipitation and future timestamps are skipped
    even when their precipitation is set."""
    obs = parse_hourly_observations(make_weather_payload(), NOW_WEATHER)
    stamps = [t for t, _ in obs]
    # 17:00 (null precip), 19:00 (MOSMIX forecast), 21:00 (forecast AND future)
    assert datetime(2026, 9, 27, 16, 0, tzinfo=timezone.utc) not in stamps
    assert datetime(2026, 9, 27, 18, 0, tzinfo=timezone.utc) not in stamps
    assert datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc) not in stamps


def test_parse_hourly_observations_at_boundary_timestamp():
    """A record stamped exactly ``now`` covers [now-1h, now): it is complete
    and must be kept."""
    payload = make_weather_payload(
        weather=[{"timestamp": "2026-09-27T20:00:00+00:00",
                  "source_id": 1002, "precipitation": 0.2}],
    )
    obs = parse_hourly_observations(payload, NOW_WEATHER)
    assert obs == [(datetime(2026, 9, 27, 19, 0, tzinfo=timezone.utc), 0.2)]


def test_parse_hourly_observations_unknown_source_and_bad_timestamp():
    payload = make_weather_payload(
        weather=[
            {"timestamp": "2026-09-27T16:00:00+00:00", "source_id": 999,
             "precipitation": 1.0},
            {"timestamp": "not-a-timestamp", "source_id": 1002,
             "precipitation": 1.0},
        ]
    )
    assert parse_hourly_observations(payload, NOW_WEATHER) == []


def test_parse_hourly_observations_empty_payload():
    assert parse_hourly_observations({}, NOW_WEATHER) == []
    assert parse_hourly_observations({"weather": None, "sources": None}, NOW_WEATHER) == []


def test_parse_station_info_prefers_real_observation_source():
    """A source with observation_type 'current'/'historical' beats a forecast
    source even when the latter is listed first."""
    payload = make_weather_payload(
        sources=[
            {"id": 1001, "observation_type": "forecast",
             "station_name": "MOSMIX", "distance": 3000.0},
            {"id": 1002, "observation_type": "historical",
             "station_name": "BERLIN", "distance": 5000.0},
        ]
    )
    assert parse_station_info(payload) == ("BERLIN", 5000.0)
    payload["sources"][1]["observation_type"] = "current"
    assert parse_station_info(payload) == ("BERLIN", 5000.0)


def test_parse_station_info_falls_back_to_first_source():
    """Without a real-observation source (e.g. MOSMIX only), the first listed
    source is reported; a missing station_name falls back to its id."""
    payload = make_weather_payload(
        sources=[
            {"id": 1001, "observation_type": "forecast",
             "station_name": "MOSMIX", "distance": 3000.0},
            {"id": 77, "observation_type": "forecast"},
        ]
    )
    assert parse_station_info(payload) == ("MOSMIX", 3000.0)
    assert parse_station_info({"sources": [{"id": 77, "observation_type": "forecast"}]}) == (
        "77", 0.0
    )


def test_parse_station_info_no_sources_returns_none():
    assert parse_station_info({}) is None
    assert parse_station_info({"sources": None}) is None
    assert parse_station_info({"sources": []}) is None


async def test_client_fetch_weather_payload_requests_window():
    cfg = make_cfg()
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=make_weather_payload())

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    payload = await client.fetch_weather_payload(
        datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc),
    )
    await client.aclose()
    assert payload["weather"][0]["source_id"] == 1002
    assert "/weather" in seen["url"]
    assert "date=2026-09-27T12%3A00%3A00Z" in seen["url"]
    assert "last_date=2026-09-27T20%3A00%3A00Z" in seen["url"]
    assert "tz=UTC" in seen["url"]
    assert "lat=52.0" in seen["url"] and "lon=13.0" in seen["url"]


async def test_client_fetch_weather_payload_http_error():
    cfg = make_cfg()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SourceError):
        await client.fetch_weather_payload(
            datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc),
            datetime(2026, 9, 27, 20, 0, tzinfo=timezone.utc),
        )
    await client.aclose()


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


async def test_client_rejects_body_over_response_size_cap():
    # a body above MAX_RESPONSE_BYTES must be aborted with a SourceError,
    # never fully buffered (memory + SQLite cache protection)
    cfg = make_cfg()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SourceError, match="cap"):
        await client.fetch_current_payload()
    await client.aclose()


async def test_client_deeply_nested_json_raises_source_error():
    # 200 KB of nested brackets is far below the size cap but makes
    # json.loads raise RecursionError; it must surface as a SourceError, or
    # it escapes _fetch_into_cache and skips the rest of the refresh
    cfg = make_cfg()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"[" * 100_000 + b"]" * 100_000)

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SourceError, match="not valid JSON"):
        await client.fetch_current_payload()
    await client.aclose()


async def test_client_normal_body_still_parses_with_streaming():
    # regression guard: the streamed path still returns parsed dicts
    cfg = make_cfg()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_current_payload())

    client = BrightSkyClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    payload = await client.fetch_current_payload()
    assert payload["weather"]["temperature"] == 7.4
    await client.aclose()
