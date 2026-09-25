"""Bright Sky (DWD) client.

Verified API facts (checked live + against the official ``brightsky``
library's response models):

  * Base URL has NO version prefix: ``https://api.brightsky.dev``
  * ``GET /current_weather?lat=..&lon=..`` -> ``{"weather": {...}}``
    (units: temperature °C, wind m/s, precipitation mm, pressure hPa)
  * ``GET /radar?lat=..&lon=..`` ->
      ``radar``: list of 25 frames (5-min steps, ~2 h nowcast)
      ``geometry`` / ``bbox`` / ``latlon_position``
    Each frame's ``precipitation_5`` is ``base64(zlib(row-major uint16 grid))``
    in units of **0.01 mm per 5 minutes** (per the library docs).

The parsers (:func:`parse_current_weather`, :func:`parse_radar`) are pure
functions so they are unit-testable without any network. The client raises
:exc:`SourceError` on any failure so the aggregator can degrade gracefully
(a failing source must never block the app).
"""
from __future__ import annotations

import array
import base64
import binascii
import zlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .config import AppConfig
from .models import CurrentConditions, RadarCell, RadarFrame, RadarNowcast

#: Multiplier converting a raw radar uint16 value to millimetres (5-min step).
RADAR_MM_PER_UNIT = 0.01

#: Number of 5-minute frames to keep from the head of the radar response
#: (the head is the "now"/nowcast — the freshest data). 12 x 5 min = 60 min.
RADAR_WINDOW_FRAMES = 12


class SourceError(Exception):
    """A data source failed or returned an unusable payload."""


# ---------------------------------------------------------------------------
# Pure parsers (no network) — the unit-tested contract
# ---------------------------------------------------------------------------
def parse_current_weather(payload: dict[str, Any]) -> CurrentConditions:
    """Parse a ``/current_weather`` payload into :class:`CurrentConditions`."""
    try:
        w = payload["weather"]
    except (KeyError, TypeError) as exc:
        raise SourceError("Bright Sky current_weather: missing 'weather'") from exc

    def _num(key: str) -> float | None:
        v = w.get(key)
        return float(v) if v is not None else None

    return CurrentConditions(
        timestamp_utc=w.get("timestamp"),
        source_id=w.get("source_id"),
        temperature_c=_num("temperature"),
        feels_like_c=None,  # filled by the aggregator from Open-Meteo
        wind_speed_ms=_num("wind_speed_10"),
        wind_direction_deg=_num("wind_direction_10"),
        wind_gust_ms=_num("wind_gust_speed_60"),
        cloud_cover_pct=_num("cloud_cover"),
        humidity_pct=_num("relative_humidity"),
        pressure_hpa=_num("pressure_msl"),
        dew_point_c=_num("dew_point"),
        precipitation_10mm=_num("precipitation_10"),
        precipitation_30mm=_num("precipitation_30"),
        precipitation_60mm=_num("precipitation_60"),
        condition=w.get("condition"),
        raw=w,
    )


def _decode_grid(encoded: str) -> array.array:
    """Decode a ``precipitation_5`` frame into a flat uint16 grid."""
    try:
        raw = base64.b64decode(encoded)
        data = zlib.decompress(raw)
    except (binascii.Error, zlib.error, ValueError) as exc:
        raise SourceError(f"Bright Sky radar: cannot decode frame ({exc})") from exc
    grid = array.array("H")
    grid.frombytes(data)
    return grid


def parse_radar(
    payload: dict[str, Any],
    window_frames: int = RADAR_WINDOW_FRAMES,
) -> RadarNowcast:
    """Parse a ``/radar`` payload into a :class:`RadarNowcast`.

    The response covers a 401x401 km sub-grid around the location with
    ``bbox`` = (top, left, bottom, right) in full-grid cell coordinates and
    ``latlon_position`` = (x, y) of the requested position within the
    sub-grid. Grid cells are ~1 km. Raw values are 0.01 mm units, converted
    to millimetres here.
    """
    frames_raw = payload.get("radar")
    if not isinstance(frames_raw, list) or not frames_raw:
        raise SourceError("Bright Sky radar: missing/empty 'radar' list")

    bbox = payload.get("bbox")
    llp = payload.get("latlon_position")
    if not (isinstance(bbox, list) and len(bbox) == 4) or not isinstance(llp, dict):
        raise SourceError("Bright Sky radar: missing bbox/latlon_position")
    top, left, bottom, right = (int(v) for v in bbox)
    width = right - left + 1
    height = bottom - top + 1
    n_cells = width * height

    try:
        px = float(llp["x"])
        py = float(llp["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("Bright Sky radar: bad latlon_position") from exc

    # Is the requested location actually inside the returned sub-grid?
    covered = 0 <= px < width and 0 <= py < height

    frames: list[RadarFrame] = []
    for rec in frames_raw[:window_frames]:
        grid = _decode_grid(rec["precipitation_5"])
        if len(grid) != n_cells:
            raise SourceError(
                f"Bright Sky radar: frame size {len(grid)} != expected {n_cells}"
            )
        cells: list[RadarCell] = []
        max_mm = 0.0
        for row in range(height):
            y = top + row
            base = row * width
            for col in range(width):
                mm = grid[base + col] * RADAR_MM_PER_UNIT
                if mm > 0.0:
                    if mm > max_mm:
                        max_mm = mm
                    cells.append(RadarCell(x=left + col, y=y, mm=mm))
        ts = rec["timestamp"]
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        frames.append(
            RadarFrame(
                time_utc=datetime.fromisoformat(ts).astimezone(timezone.utc),
                cells=cells,
                max_mm=max_mm,
            )
        )

    return RadarNowcast(
        frames=frames,
        covered=covered,
        grid_width=width,
        grid_height=height,
        bbox=(top, left, bottom, right),
        location_xy=(px, py),
    )


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
class BrightSkyClient:
    def __init__(self, cfg: AppConfig, client: httpx.AsyncClient | None = None):
        self._base = cfg.api.brightsky_base_url.rstrip("/")
        self._timeout = cfg.api.timeout_seconds
        self._lat = cfg.location.latitude
        self._lon = cfg.location.longitude
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base}{endpoint}"
        try:
            resp = await self._http.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"Bright Sky {endpoint} failed: {exc}") from exc
        if not isinstance(data, dict):
            raise SourceError(f"Bright Sky {endpoint} returned unexpected payload")
        return data

    # -- raw payloads (what gets cached) ---------------------------------
    async def fetch_current_payload(self) -> dict[str, Any]:
        """Raw ``/current_weather`` JSON."""
        return await self._get("/current_weather", {"lat": self._lat, "lon": self._lon})

    async def fetch_radar_payload(self) -> dict[str, Any]:
        """Raw ``/radar`` JSON (25 frames incl. ~2 h nowcast)."""
        return await self._get("/radar", {"lat": self._lat, "lon": self._lon})

    # -- parsed (convenience wrappers) ------------------------------------
    async def fetch_current(self) -> CurrentConditions:
        return parse_current_weather(await self.fetch_current_payload())

    async def fetch_radar(self) -> RadarNowcast:
        return parse_radar(await self.fetch_radar_payload())
