"""Unit tests for the pure API serializers (no I/O, no network, no FastAPI).

These pin the exact JSON contract the frontend (step 5) consumes, including
the empty/unavailable fallbacks.
"""
from __future__ import annotations

import pytest

from app.api_serializers import (
    serialize_models_24h,
    serialize_now,
    serialize_radar_next_hour,
    serialize_rain_probability,
)
from app.models import CurrentConditions, RainProbability

META_FRESH = {"available": True, "age_seconds": 12, "stale": False}


def make_conditions() -> CurrentConditions:
    return CurrentConditions(
        timestamp_utc="2025-01-01T12:00:00Z",
        temperature_c=5.0,
        feels_like_c=3.5,
        wind_speed_ms=3.0,
        cloud_cover_pct=75.0,
        condition="Rain",
        source_id=1,
    )


def make_rain() -> RainProbability:
    return RainProbability(
        probability_pct=75.0,
        radar_available=True,
        radar_raining=True,
        models_rain_count=1,
        models_total=2,
        ensemble_pct=50.0,
        weights_used={"radar": 0.5},
        explanation="Radar: yes; 1 of 2 models; ensemble 50 %",
    )


# ---------------------------------------------------------------------------
# serialize_now
# ---------------------------------------------------------------------------
def test_now_with_conditions():
    body = serialize_now(make_conditions(), META_FRESH)
    assert body["available"] is True
    assert body["age_seconds"] == 12
    assert body["stale"] is False
    c = body["conditions"]
    assert c["temperature_c"] == 5.0
    assert c["feels_like_c"] == 3.5
    assert c["condition"] == "Rain"
    assert c["timestamp_utc"] == "2025-01-01T12:00:00Z"


def test_now_missing_conditions_is_null():
    body = serialize_now(None, None)
    assert body["available"] is False
    assert body["conditions"] is None
    assert body["age_seconds"] is None


# ---------------------------------------------------------------------------
# serialize_rain_probability
# ---------------------------------------------------------------------------
def test_rain_probability_full():
    body = serialize_rain_probability(make_rain(), META_FRESH, META_FRESH)
    assert body["probability_pct"] == 75.0
    assert body["radar_available"] is True
    assert body["radar_raining"] is True
    assert (body["models_rain_count"], body["models_total"]) == (1, 2)
    assert body["ensemble_pct"] == 50.0
    assert body["weights_used"] == {"radar": 0.5}
    assert body["radar_age_seconds"] == 12
    assert body["models_age_seconds"] == 12


def test_rain_probability_none_meta_yields_none_ages():
    body = serialize_rain_probability(make_rain(), None, None)
    assert body["radar_age_seconds"] is None
    assert body["models_age_seconds"] is None


# ---------------------------------------------------------------------------
# serialize_radar_next_hour
# ---------------------------------------------------------------------------
def test_radar_bar_full():
    bar = {
        "available": True,
        "steps": [{"start_utc": "2025-01-01T12:00:00Z", "precip_mm": 0.2}],
    }
    body = serialize_radar_next_hour(bar, META_FRESH)
    assert body["available"] is True
    assert body["age_seconds"] == 12
    assert body["steps"][0]["precip_mm"] == 0.2


def test_radar_bar_unavailable():
    body = serialize_radar_next_hour({"available": False, "steps": []}, None)
    assert body["available"] is False
    assert body["age_seconds"] is None


# ---------------------------------------------------------------------------
# serialize_models_24h
# ---------------------------------------------------------------------------
def test_models_24h_full():
    series = {
        "hours": ["2025-01-01T12:00:00Z"],
        "models": [{"name": "icon_d2", "precipitation_mm": [0.4]}],
        "n_models": 1,
    }
    body = serialize_models_24h(series, META_FRESH)
    assert body["available"] is True
    assert body["n_models"] == 1
    assert body["models"][0]["name"] == "icon_d2"
    assert body["hours"][0] == "2025-01-01T12:00:00Z"


def test_models_24h_empty():
    body = serialize_models_24h({"hours": [], "models": [], "n_models": 0}, None)
    assert body["available"] is False
    assert body["hours"] == []
    assert body["n_models"] == 0
