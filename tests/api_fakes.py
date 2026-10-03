"""Fakes + builders for the REST endpoint tests (step 8a, moved out of
test_api.py).

The aggregator is faked (no network, no real scheduler/DB): we inject a fake
into ``app.state.aggregator`` and a real config into ``app.state.cfg``.
The ``cfg`` / ``client`` fixtures live in ``tests/conftest.py``.
"""
from __future__ import annotations

import dataclasses

from app.models import CurrentConditions, RainProbability


class FakeAgg:
    """Stands in for :class:`Aggregator` for the endpoint tests."""

    def __init__(
        self,
        conditions=None,
        current_payload=None,
        rain=None,
        bar=None,
        series=None,
        accuracy=None,
        sources=None,
        cache_meta=None,
        cfg=None,
    ):
        self._conditions = conditions
        self._current_payload = current_payload
        self._rain = rain
        self._bar = bar
        self._series = series
        self._accuracy = accuracy
        self._sources = sources
        self._cache_meta = cache_meta or {
            "available": True,
            "age_seconds": 12,
            "stale": False,
        }
        self._cfg = cfg
        # records of the location writes (step 8c)
        self.set_location_calls = []

    @property
    def cfg(self):
        """The effective config (step 8c: ``POST /api/location`` reads it
        back to update ``app.state.cfg``)."""
        return self._cfg

    async def set_location(self, loc) -> None:
        """Record the new location; the effective config tracks it."""
        self.set_location_calls.append(loc)
        if self._cfg is not None:
            self._cfg = dataclasses.replace(self._cfg, location=loc)

    async def refresh_radar(self) -> None:
        """No-op: the endpoint tests don't check the background refresh."""

    async def refresh_models(self) -> None:
        """No-op: the endpoint tests don't check the background refresh."""

    async def get_current_conditions(self):
        return self._conditions

    async def get_current_payload(self):
        return self._current_payload

    async def get_rain_probability(self):
        return self._rain

    async def get_radar_next_hour(self):
        return self._bar

    async def get_24h_model_comparison(self):
        return self._series

    async def get_model_accuracy(self):
        return self._accuracy

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
