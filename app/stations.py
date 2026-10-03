"""The weather stations behind the data (station steps P1, P2).

Pure parsers that name the observation stations in Bright Sky payloads:

* the station a ``/current_weather`` payload's values come from (``weather
  source_id``) and, per value, the station Bright Sky took it from instead
  (``weather.fallback_source_ids``) — for ``GET /api/now`` (P1);
* the stations the ``/weather`` backfill's observations came from — for
  ``GET /api/model-accuracy`` (P2).

Payloads are untrusted: a payload may have no ``sources`` key at all (older
Bright Sky versions and the test helpers) and entries may miss keys or carry
them mistyped. A missing key is ``None`` (null in JSON), a mistyped value is
treated as missing — never an error. The Rust port mirrors these parsers.
"""
from __future__ import annotations

from typing import Any

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
