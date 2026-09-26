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
) -> dict[str, Any]:
    """Shape the 'Now' tile (``GET /api/now``).

    ``available`` is False when there is no cached observation yet; the
    ``conditions`` object is then null and the frontend renders an empty
    state.
    """
    if conditions is None:
        return {"available": False, "age_seconds": None, "stale": False, "conditions": None}

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
