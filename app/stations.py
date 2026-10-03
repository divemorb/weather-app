"""The weather stations behind the data.

Pure parsers that name the observation stations in Bright Sky payloads:

* the station a ``/current_weather`` payload's values come from (``weather
  source_id``) and, per value, the station Bright Sky took it from instead
  (``weather.fallback_source_ids``) — for ``GET /api/now``;
* the stations the ``/weather`` backfill's observations came from — for
  ``GET /api/model-accuracy``.

Payloads are untrusted: a payload may have no ``sources`` key at all (older
Bright Sky versions and the test helpers) and entries may miss keys or carry
them mistyped. A missing key is ``None`` (null in JSON), a mistyped value is
treated as missing — never an error. The Rust port mirrors these parsers.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .times import parse_iso

#: Bright Sky field -> the ``/api/now`` field it becomes; the same mapping
#: :func:`app.brightsky_client.parse_current_weather` applies. Fields the
#: API doesn't carry (``solar_60``, ``sunshine_30``, ...) are absent here,
#: so a fallback for them is left out of the response.
CURRENT_FIELDS: dict[str, str] = {
    "temperature": "temperature_c",
    "wind_speed_10": "wind_speed_ms",
    "wind_direction_10": "wind_direction_deg",
    "wind_gust_speed_60": "wind_gust_ms",
    "cloud_cover": "cloud_cover_pct",
    "relative_humidity": "humidity_pct",
    "pressure_msl": "pressure_hpa",
    "dew_point": "dew_point_c",
    "precipitation_10": "precipitation_10mm",
    "precipitation_30": "precipitation_30mm",
    "precipitation_60": "precipitation_60mm",
    "condition": "condition",
}


def _is_id(value: Any) -> bool:
    """A source id: an integer (a JSON bool is not one)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _as_number(value: Any) -> float | None:
    """A JSON number (int or float; a bool is not one) or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _as_str(value: Any) -> str | None:
    """A JSON string or None."""
    return value if isinstance(value, str) else None


def parse_station(source: dict[str, Any]) -> dict[str, Any]:
    """One listed ``sources`` entry as the API's ``station`` shape.

    ``name`` / ``dwd_station_id`` come from ``station_name`` /
    ``dwd_station_id``, ``distance_m`` / ``lat`` / ``lon`` / ``height_m``
    from ``distance`` / ``lat`` / ``lon`` / ``height``; a missing (or
    mistyped) key is None (null in JSON).
    """
    return {
        "name": _as_str(source.get("station_name")),
        "distance_m": _as_number(source.get("distance")),
        "lat": _as_number(source.get("lat")),
        "lon": _as_number(source.get("lon")),
        "height_m": _as_number(source.get("height")),
        "dwd_station_id": _as_str(source.get("dwd_station_id")),
    }


def _fallback_entry(source: dict[str, Any]) -> dict[str, Any]:
    """A fallback source as the API's ``fallback`` shape (name + distance)."""
    return {
        "name": _as_str(source.get("station_name")),
        "distance_m": _as_number(source.get("distance")),
    }


def station_and_fallback(
    payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
    """The ``station`` and ``fallback`` of a raw ``/current_weather`` payload.

    ``station`` is the listed source whose ``id`` equals ``weather.source_id``
    (None when no such source is listed — or there is no ``sources`` key at
    all). ``fallback`` maps, for each value the API carries, the API's own
    field name to the listed source Bright Sky took that value from instead
    (``weather.fallback_source_ids``, see :data:`CURRENT_FIELDS`); fields the
    API doesn't carry and ids of unlisted sources are left out ({} when
    nothing fell back).
    """
    if not isinstance(payload, dict):
        return None, {}
    weather = payload.get("weather")
    weather = weather if isinstance(weather, dict) else {}
    raw_sources = payload.get("sources")
    sources = (
        [s for s in raw_sources if isinstance(s, dict)] if isinstance(raw_sources, list) else []
    )
    by_id = {s["id"]: s for s in sources if _is_id(s.get("id"))}

    source_id = weather.get("source_id")
    station = None
    main = by_id.get(source_id) if _is_id(source_id) else None
    if main is not None:
        station = parse_station(main)

    fallback: dict[str, dict[str, Any]] = {}
    raw_fallback = weather.get("fallback_source_ids")
    if isinstance(raw_fallback, dict):
        for bs_key, api_key in CURRENT_FIELDS.items():
            fid = raw_fallback.get(bs_key)
            if not _is_id(fid):
                continue
            src = by_id.get(fid)
            if src is not None:
                fallback[api_key] = _fallback_entry(src)
    return station, fallback


# ---------------------------------------------------------------------------
# The observation stations behind the accuracy table
# ---------------------------------------------------------------------------

#: The ``app_meta`` key holding the observation stations of the last
#: successful backfill, as canonical JSON (sorted keys, compact separators,
#: raw UTF-8 — the Rust backend writes the same bytes).
OBSERVATION_STATIONS_KEY = "observation_stations"


def _is_int(value: Any) -> bool:
    """A JSON integer (a bool is not one)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number_or_null(value: Any) -> bool:
    """A JSON number (int or float; a bool is not one) or null."""
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _observation_entry(source: dict[str, Any], hours: int) -> dict[str, Any]:
    """One backfill station as the stored entry (see :func:`observation_stations`)."""
    return {
        "name": _as_str(source.get("station_name")),
        "distance_m": _as_number(source.get("distance")),
        "lat": _as_number(source.get("lat")),
        "lon": _as_number(source.get("lon")),
        "dwd_station_id": _as_str(source.get("dwd_station_id")),
        "hours": hours,
    }


def observation_stations(payload: dict[str, Any] | None, now: datetime) -> list[dict[str, Any]]:
    """The stations a ``/weather`` payload's observations came from.

    Counts the records exactly as
    :func:`app.brightsky_client.parse_hourly_observations` keeps them (known
    source, ``observation_type != "forecast"``, precipitation not None,
    ``timestamp <= now``) and returns one entry per source with at least
    one kept record (``hours`` = how many): ``name``, ``distance_m``,
    ``lat``, ``lon``, ``dwd_station_id`` — sorted nearest first, a source
    without a usable distance last, then by name, then payload order. A
    missing or mistyped field is None (null in JSON); nothing raises. The
    Rust port mirrors this.
    """
    if not isinstance(payload, dict):
        return []
    sources_raw = payload.get("sources")
    by_id: dict[Any, dict[str, Any]] = {}
    if isinstance(sources_raw, list):
        for s in sources_raw:
            if not isinstance(s, dict):
                continue
            sid = s.get("id")
            try:
                by_id[sid] = s  # later entries win, as in parse_hourly_observations
            except TypeError:
                pass  # unhashable id: no record can match it
    hours: dict[Any, int] = {}
    records_raw = payload.get("weather")
    if isinstance(records_raw, list):
        for rec in records_raw:
            if not isinstance(rec, dict):
                continue
            sid = rec.get("source_id")
            try:
                source = by_id.get(sid)
            except TypeError:
                continue  # unhashable id: no source can match it
            if source is None or source.get("observation_type") == "forecast":
                continue
            if rec.get("precipitation") is None:
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
            hours[sid] = hours.get(sid, 0) + 1
    entries = [_observation_entry(s, hours[sid]) for sid, s in by_id.items() if sid in hours]
    entries.sort(key=lambda e: (e["distance_m"] is None, e["distance_m"] or 0.0, e["name"] or ""))
    return entries


def stations_to_json(stations: list[dict[str, Any]]) -> str:
    """The canonical JSON stored under :data:`OBSERVATION_STATIONS_KEY`."""
    return json.dumps(stations, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stored_entry_ok(entry: dict[str, Any]) -> bool:
    """One stored entry: the six keys with their types (a missing key is null)."""
    if (name := entry.get("name")) is not None and not isinstance(name, str):
        return False
    if not all(_is_number_or_null(entry.get(k)) for k in ("distance_m", "lat", "lon")):
        return False
    if (dwd := entry.get("dwd_station_id")) is not None and not isinstance(dwd, str):
        return False
    hours = entry.get("hours")
    return _is_int(hours) and hours >= 0


def stations_from_json(text: str | None) -> list[dict[str, Any]]:
    """The stored value back to a list, or ``[]``.

    ``text`` must be a JSON list of the stored entries (name /
    dwd_station_id: string or null; distance_m / lat / lon: number or null;
    hours: non-negative integer); anything else — no value, bad JSON, wrong
    shape, a mistyped field — reads as ``[]``: a broken value must not break
    the page. A surviving entry is returned in the full six-key shape (a
    missing optional key as null). The Rust port decodes the same bytes.
    """
    if text is None:
        return []
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list) or not all(
        isinstance(e, dict) and _stored_entry_ok(e) for e in data
    ):
        return []
    return [
        {
            "name": e.get("name"),
            "distance_m": e.get("distance_m"),
            "lat": e.get("lat"),
            "lon": e.get("lon"),
            "dwd_station_id": e.get("dwd_station_id"),
            "hours": e.get("hours"),
        }
        for e in data
    ]
