"""Security endpoint tests (step 8a, moved out of test_api.py).

Covers: no CORS, the security headers on 200/400/500 responses, API docs
off by default (step 7b) and the Host-header check against DNS rebinding
(step 7g).
"""
from __future__ import annotations

import pytest

from app.main import host_allowed
from tests.api_fakes import FakeAgg, make_sources

# ---------------------------------------------------------------------------
# security: no CORS, security headers, docs off (step 7b)
# ---------------------------------------------------------------------------
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def test_no_cors_for_foreign_origin(client):
    """A cross-origin request gets no access-control-allow-origin back
    (the frontend is same-origin; without CORS it can't read the answer,
    which protects /api/config's home location)."""
    c = client(FakeAgg())
    r = c.get(
        "/api/config",
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


@pytest.mark.parametrize("url", ["/api/sources", "/"])
def test_security_headers_on_api_and_static(client, url):
    c = client(FakeAgg(sources=make_sources()))
    r = c.get(url)
    assert r.status_code == 200
    for name, value in _SECURITY_HEADERS.items():
        assert r.headers.get(name) == value


@pytest.mark.parametrize("url", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_off_by_default(client, url):
    """/docs, /redoc and /openapi.json are 404 unless ENABLE_API_DOCS=true
    (they are also 404 for any other URL, so this is the default contract)."""
    c = client(FakeAgg())
    assert c.get(url).status_code == 404


def test_unhandled_error_500_still_carries_security_headers(client):
    """A raising endpoint yields a 500 (caught inside the security-header
    middleware), and that 500 must carry all the security headers too."""

    class BoomAgg(FakeAgg):
        async def get_current_conditions(self):
            raise RuntimeError("boom")

    c = client(BoomAgg())
    r = c.get("/api/now")
    assert r.status_code == 500
    for name, value in _SECURITY_HEADERS.items():
        assert r.headers.get(name) == value


# ---------------------------------------------------------------------------
# security: Host header check against DNS rebinding (step 7g)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "host",
    [
        "192.168.1.5:8000",
        "[::1]:8000",
        "::1",
        "localhost:8000",
        "raspberrypi.local:8000",
        "PI.FRITZ.BOX:8000",
    ],
)
def test_host_allowed_accepted(host):
    assert host_allowed(host, frozenset({"pi.fritz.box"})) is True


@pytest.mark.parametrize(
    "host",
    [
        "evil.example",
        "evil.example:8000",
        "testserver",
        "",
        "localhost.evil.com",
        "1.2.3.4.nip.io",
    ],
)
def test_host_allowed_rejected(host):
    assert host_allowed(host, frozenset({"pi.fritz.box"})) is False


def test_foreign_host_header_rejected_with_security_headers(client):
    """A rebinding attack (Host: evil.example) is answered 400, and that
    400 still carries all the security headers."""
    c = client(FakeAgg())
    r = c.get("/api/config", headers={"host": "evil.example:8000"})
    assert r.status_code == 400
    assert r.text == "Invalid host header"
    for name, value in _SECURITY_HEADERS.items():
        assert r.headers.get(name) == value
