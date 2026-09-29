"""HTTP-layer tests for the Bright Sky client (step 8a, moved out of
test_brightsky_client.py).

Uses ``httpx.MockTransport`` to avoid any real requests. The parser tests
stay in ``test_brightsky_client.py``.
"""
from __future__ import annotations

import base64
import time
import zlib
from datetime import datetime, timezone

import httpx
import pytest

from app.brightsky_client import BrightSkyClient, MAX_RESPONSE_BYTES, SourceError
from tests.helpers import (
    make_cfg,
    make_current_payload,
    make_radar_payload,
    make_weather_payload,
    grid,
)


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
    with pytest.raises(SourceError, match="Bright Sky /current_weather"):
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
