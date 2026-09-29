"""Address search via OpenStreetMap Nominatim (step 8c2, setup wizard).

The user types an address or place into the wizard; this module resolves it
to coordinates. Verified against the live API:

  * ``GET /search?q=<text>&format=jsonv2&limit=5&addressdetails=0`` answers
    with a JSON **list**; each entry has ``"lat"`` / ``"lon"`` as **strings**
    (e.g. ``"48.1374990"``) and a ``"display_name"``. No match -> ``[]``.
  * A **custom ``User-Agent`` is required**: the httpx default
    (``python-httpx/...``) and an empty UA get a 403.
  * Usage policy: max 1 request per second, search only on an explicit
    button press (no autocomplete), cache results.

Upstream data is untrusted: a non-list payload becomes
:exc:`SourceError` (via :func:`app.upstream.malformed_is_source_error`), and
the body is read through :func:`app.upstream.stream_json_capped`.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Awaitable, Callable

import httpx

from .upstream import (
    SourceError,
    malformed_is_source_error,
    stream_json_capped,
)

#: Required by the Nominatim usage policy (the httpx default UA gets 403).
USER_AGENT = "WetterLocal/1.0 (self-hosted home weather app)"

#: Nominatim usage policy: max 1 request per second; wait a little more.
_MIN_REQUEST_SPACING_SECONDS = 1.1

#: In-memory result cache size (lower-cased query -> results); cleared
#: before a new entry once full. Good enough for a single-user app.
_MAX_CACHE_ENTRIES = 100


@malformed_is_source_error("Nominatim search")
def parse_nominatim(payload: Any) -> list[dict[str, Any]]:
    """Parse a Nominatim ``/search`` payload into wizard result dicts.

    Up to 5 ``{"label", "latitude", "longitude"}`` dicts. Entries with
    missing or non-numeric fields are skipped (upstream data is
    untrusted); a non-list payload (or any shape error) becomes
    :exc:`SourceError`.
    """
    if not isinstance(payload, list):
        raise SourceError("Nominatim search: expected a JSON list")
    out: list[dict[str, Any]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        label = entry.get("display_name")
        if not isinstance(label, str) or not label:
            continue
        try:
            lat = float(entry.get("lat"))
            lon = float(entry.get("lon"))
        except (TypeError, ValueError):
            continue
        out.append({"label": label, "latitude": lat, "longitude": lon})
        if len(out) == 5:
            break
    return out


class Geocoder:
    """Address -> coordinates via Nominatim, throttled and cached.

    The constructor takes a **transport** (not a client) so the custom
    ``User-Agent`` is set in tests too, and injectable ``clock`` / ``sleep``
    so the throttle is testable without real waiting.
    """

    def __init__(
        self,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._base = base_url.rstrip("/")
        self._clock = clock
        self._sleep = sleep
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._last_request_at = -math.inf  # first request never sleeps
        self._http = httpx.AsyncClient(
            timeout=10, headers={"User-Agent": USER_AGENT}, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Resolve ``query`` to up to 5 ``{"label", "latitude", "longitude"}``
        dicts; ``[]`` when Nominatim has no match.

        A cache hit returns before taking the lock and never sleeps. On a
        miss the throttle guarantees >= 1.1 s since the previous *request*
        (Nominatim usage policy: max 1 request per second).
        """
        key = query.lower()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        async with self._lock:
            wait = _MIN_REQUEST_SPACING_SECONDS - (self._clock() - self._last_request_at)
            if wait > 0:
                await self._sleep(wait)
            self._last_request_at = self._clock()
            results = parse_nominatim(
                await stream_json_capped(
                    self._http,
                    f"{self._base}/search",
                    {"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 0},
                )
            )
        if len(self._cache) >= _MAX_CACHE_ENTRIES:
            self._cache.clear()
        self._cache[key] = results
        return results
