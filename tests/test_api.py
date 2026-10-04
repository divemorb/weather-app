"""REST endpoint tests for the frontend contract.

The aggregator is faked (no network, no real scheduler/DB): a fake is
injected into ``app.state.aggregator`` and a real config into
``app.state.cfg``. ``TestClient(app)`` is used *without* entering its
context manager, so the app's lifespan never runs — each request just reads
the injected state. This tests the routing + serialization contract in
isolation; the fakes/builders live in ``tests/api_fakes.py``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.main import app
from app.models import RainProbability
from tests.api_fakes import (
    FakeAgg,
    make_bar,
    make_conditions,
    make_rain_probability,
    make_series,
    make_sources,
)


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
    assert body["configured"] is True
    assert body["location"]["latitude"] == pytest.approx(cfg.location.latitude)
    assert body["location"]["timezone"] == cfg.location.timezone
    assert body["radar_radius_km"] == pytest.approx(cfg.radar.radius_km)
    assert body["weights"]["radar"] == pytest.approx(cfg.probability.weight_radar)
    assert body["models"] == list(cfg.models.forecast)


def test_api_config_unconfigured(client, cfg):
    # no location yet -> configured=false, location=null (the
    # frontend shows the setup wizard instead of calling toFixed on null)
    from dataclasses import replace

    from app.config import load_config

    c = client(FakeAgg())  # installs the configured cfg on app.state
    app.state.cfg = replace(load_config(), location=None)
    try:
        r = c.get("/api/config")
    finally:
        app.state.cfg = cfg  # restore for later tests
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["location"] is None


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
    assert body["accuracy_weighted"] is False
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
# /api/model-accuracy
# ---------------------------------------------------------------------------
def make_accuracy() -> dict:
    """Pure-scorer shape (see app.accuracy.model_accuracy)."""
    return {
        "icon_d2": {
            "n_samples": 100,
            "mae_mm": 0.205,
            "hits": 20,
            "misses": 10,
            "false_alarms": 15,
            "correct_negatives": 55,
            "event_accuracy": 0.75,
        },
        "gfs_seamless": {
            "n_samples": 10,
            "mae_mm": 0.4,
            "hits": 2,
            "misses": 3,
            "false_alarms": 2,
            "correct_negatives": 3,
            "event_accuracy": 0.5,
        },
    }


def test_api_model_accuracy_full(client, cfg):
    c = client(FakeAgg(accuracy=make_accuracy()))
    r = c.get("/api/model-accuracy")
    assert r.status_code == 200
    body = r.json()
    assert body["window_days"] == cfg.accuracy.window_days
    assert body["min_samples"] == cfg.accuracy.min_samples
    d2 = body["models"]["icon_d2"]
    assert d2["enough_data"] is True
    assert d2["n_samples"] == 100
    assert d2["event_accuracy"] == pytest.approx(0.75)
    assert d2["mae_mm"] == pytest.approx(0.205)
    assert (d2["hits"], d2["misses"], d2["false_alarms"], d2["correct_negatives"]) == (20, 10, 15, 55)
    # below min_samples -> greyed out in the UI
    assert body["models"]["gfs_seamless"]["enough_data"] is False


def test_api_model_accuracy_empty(client):
    c = client(FakeAgg(accuracy={}))
    r = c.get("/api/model-accuracy")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == {}
    assert body["window_days"] == 30
    assert body["min_samples"] == 48


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


# ---------------------------------------------------------------------------
# /api/schedule (UI countdown to the next backend refresh)
# ---------------------------------------------------------------------------
class FakeScheduler:
    def __init__(self, next_runs):
        self._next_runs = next_runs

    def get_job(self, job_id):
        from types import SimpleNamespace

        return SimpleNamespace(next_run_time=self._next_runs.get(job_id))


def test_api_schedule(client, cfg):
    c = client(FakeAgg())
    app.state.scheduler = FakeScheduler(
        {"radar_refresh": datetime(2026, 9, 29, 14, 5, 5, tzinfo=timezone.utc)}
    )
    try:
        r = c.get("/api/schedule")
    finally:
        del app.state.scheduler
    assert r.status_code == 200
    body = r.json()
    assert body["server_time_utc"].endswith("Z")
    assert body["jobs"]["radar"] == {
        "interval_minutes": cfg.scheduling.radar_interval_minutes,
        "next_run_utc": "2026-09-29T14:05:05Z",
        "sources": ["radar", "current"],
    }
    assert body["jobs"]["models"]["next_run_utc"] is None
