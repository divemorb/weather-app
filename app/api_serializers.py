"""Pure serializers that turn aggregator results into API-ready JSON dicts.

These are the *only* place where internal dataclasses become the REST
contract. They take plain values (no ``Aggregator`` / ``Store``) and return
JSON-serializable dicts, which keeps them trivially unit-testable and lets the
FastAPI routes stay thin (fetch from the aggregator, hand to a serializer).

All timestamps are UTC ISO-8601 (``...Z``); the frontend converts to the
configured display timezone.
"""
from __future__ import annotations

from typing import Any

from .models import CurrentConditions, RainProbability
from .stations import station_and_fallback


def _cache_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an optional ``_cache_meta`` dict into the response fields."""
    if meta is None:
        return {"available": False, "age_seconds": None, "stale": False}
    return {
        "available": meta.get("available", False),
        "age_seconds": meta.get("age_seconds"),
        "stale": meta.get("stale", False),
    }


def serialize_now(
    conditions: CurrentConditions | None,
    meta: dict[str, Any] | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape the 'Now' tile (``GET /api/now``).

    ``available`` is False when there is no cached observation yet; the
    ``conditions`` object is then null and the frontend renders an empty
    state.

    ``payload`` is the raw ``/current_weather`` payload; when given, its
    ``sources`` name the ``station`` the values come from and the per-value
    ``fallback`` (see :func:`app.stations.station_and_fallback`).
    """
    if conditions is None:
        return {"available": False, "age_seconds": None, "stale": False, "conditions": None}

    station, fallback = station_and_fallback(payload)
    return {
        **_cache_meta(meta),
        "conditions": {
            "timestamp_utc": conditions.timestamp_utc,
            "temperature_c": conditions.temperature_c,
            "feels_like_c": conditions.feels_like_c,
            "wind_speed_ms": conditions.wind_speed_ms,
            "wind_direction_deg": conditions.wind_direction_deg,
            "wind_gust_ms": conditions.wind_gust_ms,
            "cloud_cover_pct": conditions.cloud_cover_pct,
            "humidity_pct": conditions.humidity_pct,
            "pressure_hpa": conditions.pressure_hpa,
            "dew_point_c": conditions.dew_point_c,
            "precipitation_10mm": conditions.precipitation_10mm,
            "precipitation_30mm": conditions.precipitation_30mm,
            "precipitation_60mm": conditions.precipitation_60mm,
            "condition": conditions.condition,
            "source_id": conditions.source_id,
            "station": station,
            "fallback": fallback,
        },
    }


def serialize_rain_probability(
    rain: RainProbability,
    radar_meta: dict[str, Any] | None,
    models_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Shape the headline rain probability (``GET /api/rain-probability``).

    Includes the per-signal data age (radar + models) so the UI can show how
    fresh the underlying data is without a second round-trip to
    ``/api/sources``.
    """
    return {
        "probability_pct": rain.probability_pct,
        "explanation": rain.explanation,
        "radar_available": rain.radar_available,
        "radar_raining": rain.radar_raining,
        "models_rain_count": rain.models_rain_count,
        "models_total": rain.models_total,
        "ensemble_pct": rain.ensemble_pct,
        "weights_used": rain.weights_used,
        "radar_age_seconds": radar_meta.get("age_seconds") if radar_meta else None,
        "models_age_seconds": models_meta.get("age_seconds") if models_meta else None,
    }


def serialize_radar_next_hour(bar: dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
    """Shape the 60-minute radar bar (``GET /api/radar/next-hour``).

    Passes through the pure ``build_radar_next_hour_bar`` result and adds the
    radar cache freshness so the frontend can flag a stale nowcast.
    """
    return {
        **_cache_meta(meta),
        "available": bar.get("available", False),
        "steps": bar.get("steps", []),
    }


def serialize_models_24h(
    series: dict[str, Any],
    meta: dict[str, Any] | None,
) -> dict[str, Any]:
    """Shape the 24 h model comparison (``GET /api/models/24h``)."""
    return {
        **_cache_meta(meta),
        "hours": series.get("hours", []),
        "models": series.get("models", []),
        "n_models": series.get("n_models", 0),
    }


def serialize_model_accuracy(
    models: dict[str, dict[str, Any]],
    window_days: int,
    min_samples: int,
) -> dict[str, Any]:
    """Shape the per-model accuracy (``GET /api/model-accuracy``).

    ``models`` is the pure :func:`app.accuracy.model_accuracy` result
    (``{}`` while nothing has been compared yet); each entry gains
    ``enough_data`` = ``n_samples >= min_samples`` so the UI can grey out
    models that have not accumulated enough compared hours.
    """
    serialized: dict[str, dict[str, Any]] = {}
    for name, stats in models.items():
        n = int(stats.get("n_samples", 0))
        entry: dict[str, Any] = {
            "n_samples": n,
            "hits": int(stats["hits"]),
            "misses": int(stats["misses"]),
            "false_alarms": int(stats["false_alarms"]),
            "correct_negatives": int(stats["correct_negatives"]),
            "enough_data": n >= min_samples,
        }
        mae = stats.get("mae_mm")
        entry["mae_mm"] = round(mae, 3) if mae is not None else None
        ea = stats.get("event_accuracy")
        entry["event_accuracy"] = round(ea, 3) if ea is not None else None
        serialized[name] = entry
    return {
        "window_days": window_days,
        "min_samples": min_samples,
        "models": serialized,
    }
