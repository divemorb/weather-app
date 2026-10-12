"""Address search via OpenStreetMap Nominatim (setup wizard).

  * ``GET /search?q=<text>&format=jsonv2&limit=5&addressdetails=1`` answers
    with a JSON **list**; each entry has ``"lat"`` / ``"lon"`` as **strings**
    (e.g. ``"48.1374990"``) and a ``"display_name"``. No match -> ``[]``.
  * A **custom ``User-Agent`` is required**: the httpx2 default and an empty
    UA get a 403.
  * Usage policy: max 1 request per second, search only on an explicit
    button press (no autocomplete), cache results.

Upstream data is untrusted: a non-list payload becomes :exc:`SourceError`
(via :func:`app.upstream.malformed_is_source_error`), and the body is read
through :func:`app.upstream.stream_json_capped`.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Awaitable, Callable

import httpx2

from .upstream import (
    SourceError,
    malformed_is_source_error,
    stream_json_capped,
)

#: Required by the Nominatim usage policy (the httpx2 default UA gets 403).
USER_AGENT = "WetterLocal/1.0 (self-hosted home weather app)"

#: Nominatim usage policy: max 1 request per second; wait a little more.
_MIN_REQUEST_SPACING_SECONDS = 1.1

#: In-memory result cache size (lower-cased query -> results); cleared
#: wholesale once full (fine for a single-user app).
_MAX_CACHE_ENTRIES = 100


#: The address parts that may form the second label line, in priority order
#: (phone test P1: the city is the first present of these).
_CITY_PARTS = ("city", "town", "village", "municipality", "hamlet")


def _short_label(entry: dict[str, Any]) -> str:
    """The two-line place label (phone test P1, 2026-10-12), German order.

    Line 1: ``road`` + ``" " + house_number`` when there is a number; without
    a road, the entry's ``name`` (a number without a road is dropped). If the
    name equals the city, line 1 is empty. Line 2: ``postcode`` + city, the
    city alone, or the postcode alone. The non-empty lines are joined by a
    newline; if both are empty the ``name`` is used, and if that is missing
    too, the ``display_name`` (as before). Untrusted upstream data: a part
    counts only if it is a non-empty string, and an ``address`` that is not
    an object counts as empty.
    """
    address = entry.get("address")
    if not isinstance(address, dict):
        address = {}

    def part(key: str) -> str:
        value = address.get(key)
        return value if isinstance(value, str) and value else ""

    road = part("road")
    number = part("house_number")
    city = ""
    for key in _CITY_PARTS:
        city = part(key)
        if city:
            break
    line1 = f"{road} {number}" if road and number else (road or "")
    if not line1:
        name = entry.get("name")
        name = name if isinstance(name, str) and name else ""
        line1 = "" if name == city else name
    line2 = f"{part('postcode')} {city}".strip()
    lines = [line for line in (line1, line2) if line]
    label = "\n".join(lines)
    if not label:
        name = entry.get("name")
        label = name if isinstance(name, str) and name else entry["display_name"]
    return label


@malformed_is_source_error("Nominatim search")
def parse_nominatim(payload: Any) -> list[dict[str, Any]]:
    """Parse a Nominatim ``/search`` payload into up to 5
    ``{"label", "latitude", "longitude"}`` dicts, skipping entries with
    missing or non-numeric fields (upstream data is untrusted). The
    ``label`` is the short two-line place label (see :func:`_short_label`),
    falling back to the entry's ``display_name``. A non-list payload
    becomes :exc:`SourceError`.
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
        out.append(
            {"label": _short_label(entry), "latitude": lat, "longitude": lon}
        )
        if len(out) == 5:
            break
    return out


class Geocoder:
    """Address -> coordinates via Nominatim, throttled and cached.

    Takes a **transport** (not a client) so the custom ``User-Agent``
    header is set here, and injectable ``clock`` / ``sleep`` so the
    throttle is testable without real waiting.
    """

    def __init__(
        self,
        base_url: str,
        transport: httpx2.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._base = base_url.rstrip("/")
        self._clock = clock
        self._sleep = sleep
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._last_request_at = -math.inf  # first request never sleeps
        self._http = httpx2.AsyncClient(
            timeout=10, headers={"User-Agent": USER_AGENT}, transport=transport
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Resolve ``query`` to up to 5 ``{"label", "latitude", "longitude"}``
        dicts; ``[]`` when Nominatim has no match.

        A cache hit never sleeps; on a miss the throttle waits until
        >= 1.1 s have passed since the previous *request* (Nominatim usage
        policy).
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
                    {"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 1},
                )
            )
        if len(self._cache) >= _MAX_CACHE_ENTRIES:
            self._cache.clear()
        self._cache[key] = results
        return results
