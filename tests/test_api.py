"""REST endpoint tests for the frontend contract (step 4).

The aggregator is faked (no network, no real scheduler/DB): we inject a fake
into ``app.state.aggregator`` and a real config into ``app.state.cfg``.

``TestClient(app)`` is used *without* entering its context manager, so the app's
lifespan (which would open a real DB, start the scheduler and hit the network
for the initial refresh) never runs — each request just reads the injected
state. This tests the routing + serialization contract in isolation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.main import app
from app.models import CurrentConditions, RainProbability


# ---------------------------------------------------------------------------
# Fake aggregator (canned read-model results)
# ---------------------------------------------------------------------------
class FakeAgg:
    """Stands in for :class:`Aggregator` for the endpoint tests."""

    def __init__(
        self,
        conditions=None,
        rain=None,
        bar=None,
        series=None,
        sources=None,
        cache_meta=None,
    ):
        self._conditions = conditions
        self._rain = rain
        self._bar = bar
        self._series = series
        self._sources = sources
        self._cache_meta = cache_meta or {
            "available": True,
            "age_seconds": 12,
            "stale": False,
        }

    async def get_current_conditions(self):
        return self._conditions

    async def get_rain_probability(self):
        return self._rain

    async def get_radar_next_hour(self):
        return self._bar

    async def get_24h_model_comparison(self):
        return self._series

    async def get_source_status(self):
        return self._sources

    async def cache_meta(self, source: str):
        return self._cache_meta


def make_conditions() -> CurrentConditions:
    return CurrentConditions(
        timestamp_utc="2025-01-01T12:00:00Z",
        source_id=96160,
        temperature_c=5.0,
        feels_like_c=3.5,
        wind_speed_ms=3.0,
        wind_direction_deg=180.0,
        wind_gust_ms=6.0,
        cloud_cover_pct=75.0,
        humidity_pct=80.0,
        pressure_hpa=1015.0,
        dew_point_c=3.0,
        precipitation_10mm=0.0,
        precipitation_30mm=0.1,
        precipitation_60mm=0.2,
        condition="Rain",
    )


def make_rain_probability() -> RainProbability:
    return RainProbability(
        probability_pct=75.0,
        radar_available=True,
        radar_raining=True,
        models_rain_count=1,
        models_total=2,
        ensemble_pct=50.0,
        weights_used={"radar": 0.5, "models": 0.3, "ensemble": 0.2},
        explanation=(
            "Radar: yes; 1 of 2 models predict > 0.1 mm in the next hour; "
            "ensemble 50 %"
        ),
    )


def make_bar(available: bool = True) -> dict:
    steps = [
        {"start_utc": "2025-01-01T12:00:00Z", "precip_mm": 0.2 if i == 0 else 0.0}
        for i in range(12)
    ]
    return {"available": available, "steps": steps}


def make_series() -> dict:
    return {
        "hours": ["2025-01-01T12:00:00Z", "2025-01-01T13:00:00Z"],
        "models": [{"name": "icon_d2", "precipitation_mm": [0.4, 0.0]}],
        "n_models": 1,
    }


def make_sources() -> dict:
    return {
        "radar": {
            "upstream": "DWD (Bright Sky)",
            "available": True,
            "age_seconds": 10,
            "stale": False,
            "last_error": None,
        },
        "current": {
            "upstream": "DWD (Bright Sky)",
            "available": True,
            "age_seconds": 10,
            "stale": False,
            "last_error": None,
        },
        "forecast": {
            "upstream": "Open-Meteo",
            "available": True,
            "age_seconds": 60,
            "stale": False,
            "last_error": None,
        },
        "ensemble": {
            "upstream": "Open-Meteo",
            "available": True,
            "age_seconds": 60,
            "stale": False,
            "last_error": None,
        },
    }


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def client(cfg):
    """TestClient with the given fakes installed on ``app.state``.

    The context manager is NOT entered, so the real lifespan (DB + scheduler +
    network) is skipped.
    """

    def _install(agg: FakeAgg) -> TestClient:
        app.state.cfg = cfg
        app.state.aggregator = agg
        return TestClient(app)

    return _install


# ---------------------------------------------------------------------------
# health + config
# ---------------------------------------------------------------------------
def test_healthz(client):
    c = client(FakeAgg())
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_config(client, cfg):
    c = client(FakeAgg())
    r = c.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["location"]["latitude"] == pytest.approx(cfg.location.latitude)
    assert body["location"]["timezone"] == cfg.location.timezone
    assert body["radar_radius_km"] == pytest.approx(cfg.radar.radius_km)
    assert body["weights"]["radar"] == pytest.approx(cfg.probability.weight_radar)
    assert body["models"] == list(cfg.models.forecast)


# ---------------------------------------------------------------------------
# /api/now
# ---------------------------------------------------------------------------
def test_api_now_with_data(client):
    c = client(FakeAgg(conditions=make_conditions()))
    r = c.get("/api/now")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["age_seconds"] == 12
    cond = body["conditions"]
    assert cond["temperature_c"] == 5.0
    assert cond["feels_like_c"] == 3.5
    assert cond["condition"] == "Rain"
    assert cond["timestamp_utc"] == "2025-01-01T12:00:00Z"


def test_api_now_empty(client):
    c = client(FakeAgg(conditions=None))
    r = c.get("/api/now")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["conditions"] is None
    assert body["age_seconds"] is None


# ---------------------------------------------------------------------------
# /api/rain-probability
# ---------------------------------------------------------------------------
def test_api_rain_probability_full(client):
    c = client(FakeAgg(rain=make_rain_probability()))
    r = c.get("/api/rain-probability")
    assert r.status_code == 200
    body = r.json()
    assert body["probability_pct"] == 75.0
    assert body["radar_available"] is True
    assert body["radar_raining"] is True
    assert (body["models_rain_count"], body["models_total"]) == (1, 2)
    assert body["ensemble_pct"] == 50.0
    assert body["weights_used"]["radar"] == pytest.approx(0.5)
    assert "Radar: yes" in body["explanation"]
    # per-signal data age is attached
    assert body["radar_age_seconds"] == 12
    assert body["models_age_seconds"] == 12


def test_api_rain_probability_no_data(client):
    rain = RainProbability(
        probability_pct=0.0,
        radar_available=False,
        radar_raining=None,
        models_rain_count=0,
        models_total=0,
        ensemble_pct=None,
        weights_used={},
        explanation="No data available yet (all sources empty or failing)",
    )
    c = client(FakeAgg(rain=rain))
    r = c.get("/api/rain-probability")
    assert r.status_code == 200
    body = r.json()
    assert body["probability_pct"] == 0.0
    assert body["weights_used"] == {}
    assert "No data" in body["explanation"]


# ---------------------------------------------------------------------------
# /api/radar/next-hour
# ---------------------------------------------------------------------------
def test_api_radar_next_hour_full(client):
    c = client(FakeAgg(bar=make_bar(available=True)))
    r = c.get("/api/radar/next-hour")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert len(body["steps"]) == 12
    assert body["steps"][0] == {"start_utc": "2025-01-01T12:00:00Z", "precip_mm": 0.2}
    assert body["steps"][1]["precip_mm"] == 0.0
    # cache freshness is attached
    assert body["age_seconds"] == 12


def test_api_radar_next_hour_unavailable(client):
    c = client(FakeAgg(bar=make_bar(available=False)))
    r = c.get("/api/radar/next-hour")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert len(body["steps"]) == 12  # still 12 buckets (all dry)


# ---------------------------------------------------------------------------
# /api/models/24h
# ---------------------------------------------------------------------------
def test_api_models_24h_full(client):
    c = client(FakeAgg(series=make_series()))
    r = c.get("/api/models/24h")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert len(body["hours"]) == 2
    assert body["n_models"] == 1
    assert body["models"][0]["name"] == "icon_d2"
    assert body["models"][0]["precipitation_mm"] == [0.4, 0.0]


def test_api_models_24h_empty(client):
    c = client(FakeAgg(series={"hours": [], "models": [], "n_models": 0}))
    r = c.get("/api/models/24h")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True  # cache exists but has no usable series
    assert body["hours"] == []
    assert body["n_models"] == 0


# ---------------------------------------------------------------------------
# /api/sources
# ---------------------------------------------------------------------------
def test_api_sources(client):
    c = client(FakeAgg(sources=make_sources()))
    r = c.get("/api/sources")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"radar", "current", "forecast", "ensemble"}
    assert body["radar"]["upstream"] == "DWD (Bright Sky)"
    assert body["forecast"]["available"] is True
    assert body["forecast"]["age_seconds"] == 60
    assert body["ensemble"]["stale"] is False
