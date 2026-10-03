"""Endpoint tests for POST /api/location and GET /api/geocode.

Covers: a valid same-origin save (values rounded to 3 decimals, the
effective config updated on ``app.state``), the CSRF refusal for foreign
origins (403), and the validation layer (422, never 500, no echo of the
rejected input — NaN/Infinity included). The geocode tests use a small
fake geocoder installed on ``app.state.geocoder``: a lookup failure is a
502, never a 500.
"""
from __future__ import annotations

import pytest

from app.config import LocationConfig
from app.upstream import SourceError
from tests.api_fakes import FakeAgg


class FakeGeocoder:
    """Stands in for :class:`app.geocode.Geocoder` in the endpoint tests."""

    def __init__(self, results=None, error=False):
        self._results = results or []
        self._error = error
        self.queries = []

    async def search(self, query):
        self.queries.append(query)
        if self._error:
            raise SourceError("upstream down")
        return self._results

    async def aclose(self):
        pass


def _body(lat=48.13749, lon=11.57552, tz="Europe/Berlin", label="München"):
    return {"latitude": lat, "longitude": lon, "timezone": tz, "label": label}


# ---------------------------------------------------------------------------
# valid save
# ---------------------------------------------------------------------------
def test_post_location_ok_rounds_and_updates_cfg(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    r = c.post("/api/location", json=_body())
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    # 48.13749 -> 48.137, 11.57552 -> 11.576 (verified rounding)
    assert body["location"] == {
        "latitude": 48.137,
        "longitude": 11.576,
        "timezone": "Europe/Berlin",
        "label": "München",
    }
    # the fake aggregator recorded the (rounded) location ...
    assert c.app.state.aggregator.set_location_calls[0] == LocationConfig(
        latitude=48.137, longitude=11.576, timezone="Europe/Berlin", label="München"
    )
    # ... and app.state.cfg was updated to the effective config
    assert c.app.state.cfg.location == LocationConfig(
        latitude=48.137, longitude=11.576, timezone="Europe/Berlin", label="München"
    )
    # /api/config now reports the new location
    cfg_resp = c.get("/api/config").json()
    assert cfg_resp["configured"] is True
    assert cfg_resp["location"]["latitude"] == 48.137


def test_post_location_empty_label_defaults(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    r = c.post("/api/location", json={**_body(), "label": ""})
    assert r.status_code == 200
    assert r.json()["location"]["label"] == ""


# ---------------------------------------------------------------------------
# CSRF: cross-site writes refused
# ---------------------------------------------------------------------------
def test_post_location_foreign_origin_is_403(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    r = c.post(
        "/api/location",
        json=_body(),
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "cross-site request refused"}
    # the location was NOT written
    assert c.app.state.aggregator.set_location_calls == []
    assert c.app.state.cfg.location == cfg.location


def test_post_location_null_origin_is_403(client, cfg):
    """Origin: null (sandboxed iframe) is cross-site as far as the check
    is concerned — no Sec-Fetch-Site header to vouch for it."""
    c = client(FakeAgg(cfg=cfg))
    r = c.post("/api/location", json=_body(), headers={"Origin": "null"})
    assert r.status_code == 403
    assert c.app.state.aggregator.set_location_calls == []


def test_post_location_cross_site_fetch_is_403(client, cfg):
    """curl-like request (no Origin) but Sec-Fetch-Site: cross-site."""
    c = client(FakeAgg(cfg=cfg))
    r = c.post(
        "/api/location",
        json=_body(),
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert r.status_code == 403
    assert c.app.state.aggregator.set_location_calls == []


def test_post_location_same_origin_headers_allowed(client, cfg):
    """A browser on the same page sends Origin + Sec-Fetch-Site:
    same-origin — that is the normal wizard request."""
    c = client(FakeAgg(cfg=cfg))
    r = c.post(
        "/api/location",
        json=_body(),
        headers={
            "Origin": "http://127.0.0.1:8000",
            "Sec-Fetch-Site": "same-origin",
        },
    )
    assert r.status_code == 200
    assert c.app.state.aggregator.set_location_calls


# ---------------------------------------------------------------------------
# validation: 422, never 500, no echo of the input
# ---------------------------------------------------------------------------
def test_post_location_nan_is_422_not_500(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    # NaN is not valid JSON; a raw (non-strict) parse accepts it
    r = c.post(
        "/api/location",
        content='{"latitude": NaN, "longitude": 13.0, "timezone": "Europe/Berlin"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail and "finite" in detail[0]["msg"].lower()
    # the rejected input (NaN) must not be echoed back
    assert "NaN" not in r.text
    assert c.app.state.aggregator.set_location_calls == []


def test_post_location_out_of_range_is_422(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    r = c.post("/api/location", json={**_body(), "latitude": 91.0})
    assert r.status_code == 422
    assert c.app.state.aggregator.set_location_calls == []


def test_post_location_bad_timezone_is_422(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    r = c.post("/api/location", json={**_body(), "timezone": "Not/AZone"})
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "timezone"]
    assert c.app.state.aggregator.set_location_calls == []


def test_post_location_text_plain_body_is_422(client, cfg):
    """A cross-site HTML form posts text/plain / form-encoded — that must
    not be accepted (the body must be JSON)."""
    c = client(FakeAgg(cfg=cfg))
    r = c.post(
        "/api/location",
        content="latitude=48.137&longitude=11.576",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 422
    assert c.app.state.aggregator.set_location_calls == []


def test_post_location_security_headers_still_present_on_403_and_422(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    r = c.post(
        "/api/location", json=_body(), headers={"Origin": "https://evil.example"}
    )
    assert     r.headers.get("x-content-type-options") == "nosniff"
    assert (
        r.headers.get("content-security-policy")
        .startswith("default-src 'self'")
    )
    r = c.post("/api/location", json=_body(), headers={"Content-Type": "text/plain"})
    assert r.status_code == 422
    assert r.headers.get("x-content-type-options") == "nosniff"


# ---------------------------------------------------------------------------
# GET /api/geocode
# ---------------------------------------------------------------------------
def test_get_geocode_returns_results(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    c.app.state.geocoder = FakeGeocoder(
        results=[
            {"label": "Marienplatz, München", "latitude": 48.138, "longitude": 11.577}
        ]
    )
    r = c.get("/api/geocode", params={"q": "Marienplatz München"})
    assert r.status_code == 200
    assert r.json() == {
        "results": [
            {"label": "Marienplatz, München", "latitude": 48.138, "longitude": 11.577}
        ]
    }
    assert c.app.state.geocoder.queries == ["Marienplatz München"]


def test_get_geocode_source_error_is_502(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    c.app.state.geocoder = FakeGeocoder(error=True)
    r = c.get("/api/geocode", params={"q": "Marienplatz München"})
    assert r.status_code == 502
    assert r.json() == {"detail": "address lookup failed"}


def test_get_geocode_query_too_short_is_422(client, cfg):
    c = client(FakeAgg(cfg=cfg))
    c.app.state.geocoder = FakeGeocoder()
    r = c.get("/api/geocode", params={"q": "ab"})
    assert r.status_code == 422
    assert c.app.state.geocoder.queries == []
