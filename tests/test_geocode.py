"""Tests for the Nominatim address search (step 8c2).

Parser tests are pure (real-shaped sample from the live API); client tests
use ``httpx.MockTransport`` with a constant fake clock and a fake sleep that
records its argument, so the throttle is verified without real waiting.
"""
from __future__ import annotations

import httpx
import pytest

from app.geocode import Geocoder, parse_nominatim
from app.upstream import SourceError

#: Real-shaped Nominatim response: "lat"/"lon" are strings, no match -> [].
NOMINATIM_SAMPLE = [
    {
        "display_name": (
            "Thomass-Eck, 1, Marienplatz, …, München, Bayern, 80331, Deutschland"
        ),
        "lat": "48.1374990",
        "lon": "11.5755020",
    },
    {
        "display_name": "Marienplatz, München, Bayern, Deutschland",
        "lat": "48.1386200",
        "lon": "11.5765400",
    },
]


# ---------------------------------------------------------------------------
# parser (pure)
# ---------------------------------------------------------------------------
def test_parse_nominatim_real_shaped_sample():
    results = parse_nominatim(NOMINATIM_SAMPLE)
    assert results == [
        {
            "label": (
                "Thomass-Eck, 1, Marienplatz, …, München, Bayern, 80331, "
                "Deutschland"
            ),
            "latitude": 48.1374990,
            "longitude": 11.5755020,
        },
        {
            "label": "Marienplatz, München, Bayern, Deutschland",
            "latitude": 48.1386200,
            "longitude": 11.5765400,
        },
    ]


def test_parse_nominatim_no_match_is_empty_list():
    assert parse_nominatim([]) == []


def test_parse_nominatim_skips_malformed_entries():
    payload = [
        {"display_name": "ok"},  # missing lat/lon
        {"lat": "not-a-number", "lon": "11.0", "display_name": "bad lat"},
        {"lat": "48.0"},  # missing lon
        {"display_name": None, "lat": "48.0", "lon": "11.0"},
        "not-even-a-dict",
        {"display_name": "fine", "lat": "48.5", "lon": "11.5"},
    ]
    assert parse_nominatim(payload) == [
        {"label": "fine", "latitude": 48.5, "longitude": 11.5}
    ]


def test_parse_nominatim_non_list_is_source_error():
    for payload in ({"results": []}, "a list of results", None, 42):
        with pytest.raises(SourceError):
            parse_nominatim(payload)


def test_parse_nominatim_caps_at_five():
    payload = [
        {"display_name": f"place {i}", "lat": "48.0", "lon": "11.0"}
        for i in range(8)
    ]
    assert len(parse_nominatim(payload)) == 5


# ---------------------------------------------------------------------------
# Geocoder client (MockTransport, fake clock + sleep)
# ---------------------------------------------------------------------------
def _geocoder(handler, requests, sleeps, clock_value=1000.0):
    g = Geocoder(
        "https://nominatim.openstreetmap.org",
        transport=httpx.MockTransport(handler),
        clock=lambda: clock_value,
        sleep=lambda wait: _record(sleeps, wait),
    )
    return g


async def _record(sleeps, wait):
    sleeps.append(wait)


def _handler(payload, requests):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=payload)

    return handler


async def test_search_request_carries_user_agent_and_jsonv2_params():
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    g = _geocoder(_handler(NOMINATIM_SAMPLE, requests), requests, sleeps)
    results = await g.search("Marienplatz 1, München")
    await g.aclose()
    assert len(results) == 2
    req = requests[0]
    assert req.headers["User-Agent"] == "WetterLocal/1.0 (self-hosted home weather app)"
    assert req.url.params["format"] == "jsonv2"
    assert req.url.params["q"] == "Marienplatz 1, München"
    assert req.url.params["limit"] == "5"
    assert req.url.params["addressdetails"] == "0"


async def test_search_caches_identical_query_including_case():
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    g = _geocoder(_handler(NOMINATIM_SAMPLE, requests), requests, sleeps)
    first = await g.search("münchen")
    second = await g.search("MÜNCHEN")  # case differs -> same cache key
    await g.aclose()
    assert first == second
    assert len(requests) == 1  # the second call was a cache hit
    assert sleeps == []


async def test_search_throttles_two_different_queries():
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    g = _geocoder(_handler(NOMINATIM_SAMPLE, requests), requests, sleeps)
    await g.search("query one")
    await g.search("query two")
    await g.aclose()
    assert len(requests) == 2
    # constant clock -> the second request waited the full spacing
    assert len(sleeps) == 1
    assert sleeps[0] > 1.0
    assert sleeps[0] <= 1.1


async def test_search_first_request_never_sleeps():
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    g = _geocoder(_handler(NOMINATIM_SAMPLE, requests), requests, sleeps)
    await g.search("only one")
    await g.aclose()
    assert len(requests) == 1
    assert sleeps == []


async def test_search_upstream_error_is_source_error_and_not_cached():
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"detail": "unavailable"})

    g = _geocoder(handler, requests, sleeps)
    with pytest.raises(SourceError):
        await g.search("boom street")
    await g.aclose()
    # the failed query was not cached: a retry goes out again
    g2 = _geocoder(_handler(NOMINATIM_SAMPLE, requests), requests, sleeps)
    assert await g2.search("boom street")
    await g2.aclose()
    assert len(requests) == 2
