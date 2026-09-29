"""Bright Sky (DWD) client.

Verified API facts (checked live + against the official ``brightsky``
library's response models):

  * Base URL has NO version prefix: ``https://api.brightsky.dev``
  * ``GET /current_weather?lat=..&lon=..`` -> ``{"weather": {...}}``
    (units: temperature °C, wind m/s, precipitation mm, pressure hPa)
  * ``GET /radar?lat=..&lon=..&date=..&last_date=..`` ->
      ``radar``: list of 5-min frames, ``geometry`` / ``bbox`` / ``latlon_position``
    Each frame's ``precipitation_5`` is ``base64(zlib(row-major uint16 grid))``
    in units of **0.01 mm per 5 minutes** (per the library docs).
    With **no** ``date``, the server returns the previous hour (all in the past)
    — the nowcast is only returned when the requested window extends into the
    future, so ``fetch_radar_payload`` requests ``[now, now+1h)`` explicitly.
    Frames are returned oldest-first; the nowcast (frames beyond the newest
    real observation, sharing its ``source``) sits at the *tail*.
  * ``GET /weather?lat=..&lon=..&date=..&last_date=..&tz=UTC`` ->
      ``weather``: list of hourly records, ``sources``: one entry per
      ``source_id`` with ``observation_type`` — ``"current"`` /
      ``"historical"`` are real observations, ``"forecast"`` is the MOSMIX
      forecast. ``precipitation`` at timestamp ``T`` is the rain of the
      *preceding* hour ``[T-1h, T)`` (same convention as Open-Meteo hourly).
      Used for the hourly observation backfill (step 6d).

The parsers (:func:`parse_current_weather`, :func:`parse_radar`,
:func:`parse_hourly_observations`, :func:`parse_station_info`) are pure
functions so they are unit-testable without any network. The client raises
:exc:`SourceError` on any failure so the aggregator can degrade gracefully
(a failing source must never block the app). ``parse_radar`` rejects grids
above :data:`MAX_RADAR_CELLS` before decoding, and :func:`_decode_grid`
caps decompression at the expected size (zip-bomb guard).

The shared upstream plumbing (``SourceError``,
``malformed_is_source_error``, ``stream_json_capped``,
``MAX_RESPONSE_BYTES``) lives in :mod:`app.upstream` and is re-exported
from here, so existing imports keep working.
"""
from __future__ import annotations

import array
import base64
import binascii
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import AppConfig
from .models import CurrentConditions, RadarCell, RadarFrame, RadarNowcast
from .times import parse_iso, utcnow
from .upstream import (  # noqa: F401  (re-exported: existing imports keep working)
    MAX_RESPONSE_BYTES,
    SourceError,
    malformed_is_source_error,
    stream_json_capped,
)

#: Multiplier converting a raw radar uint16 value to millimetres (5-min step).
RADAR_MM_PER_UNIT = 0.01

#: Max radar sub-grid size in cells; the real grid is only a few hundred.
MAX_RADAR_CELLS = 250_000


# ---------------------------------------------------------------------------
# Pure parsers (no network) — the unit-tested contract
# ---------------------------------------------------------------------------
@malformed_is_source_error("Bright Sky current_weather")
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


def _decode_grid(encoded: str, n_cells: int) -> array.array:
    """Decode a ``precipitation_5`` frame into a flat uint16 grid.

    Decompression is capped at the expected size (``n_cells * 2`` bytes —
    one uint16 per cell) so a corrupted or malicious frame cannot expand to
    gigabytes in memory (zip bomb). A frame with extra or missing bytes is
    malformed, not just "wrong size" afterwards.
    """
    try:
        raw = base64.b64decode(encoded)
    except (binascii.Error, ValueError) as exc:
        raise SourceError(f"Bright Sky radar: cannot decode frame ({exc})") from exc
    d = zlib.decompressobj()
    try:
        data = d.decompress(raw, n_cells * 2 + 1)
    except zlib.error as exc:
        raise SourceError(f"Bright Sky radar: cannot decode frame ({exc})") from exc
    if len(data) != n_cells * 2 or d.unconsumed_tail or not d.eof:
        raise SourceError(
            f"Bright Sky radar: truncated or oversized frame ({len(data)} "
            f"bytes, expected exactly {n_cells * 2} and a complete stream)"
        )
    grid = array.array("H")
    grid.frombytes(data)
    return grid


@malformed_is_source_error("Bright Sky radar")
def parse_radar(payload: dict[str, Any]) -> RadarNowcast:
    """Parse a ``/radar`` payload into a :class:`RadarNowcast`.

    The response covers a 401x401 km sub-grid around the location with
    ``bbox`` = (top, left, bottom, right) in full-grid cell coordinates and
    ``latlon_position`` = (x, y) of the requested position within the
    sub-grid. Grid cells are ~1 km. Raw values are 0.01 mm units, converted
    to millimetres here.

    ``fetch_radar_payload`` bounds the request to the next-hour window, so we
    keep *every* frame that comes back (oldest-first). The time-aware callers
    (probability layer, UI bar) select the subset within ``[now, now + 1h)``.
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
    # Reject absurd grids (bogus or malicious bbox) before any decoding.
    if width <= 0 or height <= 0 or n_cells > MAX_RADAR_CELLS:
        raise SourceError(
            f"Bright Sky radar: bbox implies {n_cells} cells "
            f"({width}x{height}), more than MAX_RADAR_CELLS={MAX_RADAR_CELLS}"
        )

    try:
        px = float(llp["x"])
        py = float(llp["y"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError("Bright Sky radar: bad latlon_position") from exc

    # Is the requested location actually inside the returned sub-grid?
    covered = 0 <= px < width and 0 <= py < height

    frames: list[RadarFrame] = []
    for rec in frames_raw:
        grid = _decode_grid(rec["precipitation_5"], n_cells)
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


def parse_hourly_observations(
    payload: dict[str, Any], now: datetime
) -> list[tuple[datetime, float]]:
    """Extract hourly *observations* from a ``/weather`` payload.

    Returns ``(hour_start, mm)`` pairs (ascending) where ``hour_start =
    timestamp - 1h``, because a record stamped ``T`` holds the rain of the
    preceding hour ``[T-1h, T)``. Only records are kept whose source has
    ``observation_type != "forecast"`` (real observations, not MOSMIX), whose
    ``timestamp <= now`` (no future hours), and whose ``precipitation`` is not
    None. Records from unknown sources are skipped too (no way to verify they
    are real observations).
    """
    observation_types = {
        s.get("id"): s.get("observation_type")
        for s in payload.get("sources") or []
        if isinstance(s, dict)
    }
    out: list[tuple[datetime, float]] = []
    for rec in payload.get("weather") or []:
        if not isinstance(rec, dict):
            continue
        source_id = rec.get("source_id")
        if source_id not in observation_types:
            continue
        if observation_types[source_id] == "forecast":
            continue
        precip = rec.get("precipitation")
        if precip is None:
            continue
        ts = rec.get("timestamp")
        if not isinstance(ts, str):
            continue
        try:
            stamp = parse_iso(ts)
        except ValueError:
            continue
        if stamp > now:
            continue
        out.append((stamp - timedelta(hours=1), float(precip)))
    out.sort(key=lambda item: item[0])
    return out


def parse_station_info(payload: dict[str, Any]) -> tuple[str, float] | None:
    """Station name + distance of the observation source in a /weather payload.

    Prefers a source whose ``observation_type`` is ``"current"`` or
    ``"historical"`` (a real station); falls back to the first listed source.
    """
    sources = [s for s in payload.get("sources") or [] if isinstance(s, dict)]
    if not sources:
        return None
    for s in sources:
        if s.get("observation_type") in ("current", "historical") and s.get("station_name"):
            return s["station_name"], float(s.get("distance") or 0.0)
    first = sources[0]
    name = first.get("station_name") or str(first.get("id"))
    return name, float(first.get("distance") or 0.0)


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
            data = await stream_json_capped(self._http, url, params)
        except SourceError as exc:
            raise SourceError(f"Bright Sky {endpoint}: {exc}") from exc
        if not isinstance(data, dict):
            raise SourceError(f"Bright Sky {endpoint} returned unexpected payload")
        return data

    # -- raw payloads (what gets cached) ---------------------------------
    async def fetch_current_payload(self) -> dict[str, Any]:
        """Raw ``/current_weather`` JSON."""
        return await self._get("/current_weather", {"lat": self._lat, "lon": self._lon})

    async def fetch_radar_payload(self) -> dict[str, Any]:
        """Raw ``/radar`` JSON for the next-hour window.

        Requests ``date``/``last_date`` explicitly so the response contains the
        nowcast (frames at or after "now"). Without them the server returns the
        *previous* hour (all in the past), which would make the radar signal
        permanently dry.

        The window is floored to the 5-minute grid: ``date = floor(now, 5min)``,
        ``last_date = date + 60min``. This always contains ``[now, now+1h)`` (the
        probability layer's scan window) regardless of the minute — the extra
        past frame is simply filtered out downstream. Frames are returned
        oldest-first.
        """
        now = utcnow()
        # Floor to the 5-minute grid
        date = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
        last_date = date + timedelta(hours=1)
        fmt = "%Y-%m-%dT%H:%M:%S+00:00"
        return await self._get(
            "/radar",
            {
                "lat": self._lat,
                "lon": self._lon,
                "date": date.strftime(fmt),
                "last_date": last_date.strftime(fmt),
            },
        )

    async def fetch_weather_payload(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Raw ``/weather`` JSON for hourly records in ``[start, end]``.

        Used by the aggregator's observation backfill (step 6d): the response
        carries both real observations (``observation_type``
        ``"current"``/``"historical"``) and MOSMIX forecasts (``"forecast"``);
        :func:`parse_hourly_observations` keeps only the real ones.
        """
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return await self._get(
            "/weather",
            {
                "lat": self._lat,
                "lon": self._lon,
                "date": start.strftime(fmt),
                "last_date": end.strftime(fmt),
                "tz": "UTC",
            },
        )

    # -- parsed (convenience wrappers) ------------------------------------
    async def fetch_current(self) -> CurrentConditions:
        return parse_current_weather(await self.fetch_current_payload())

    async def fetch_radar(self) -> RadarNowcast:
        return parse_radar(await self.fetch_radar_payload())
