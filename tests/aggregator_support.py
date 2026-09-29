"""Shared helpers and stub clients for the aggregator integration tests.

Not a test module (no ``test_`` prefix): the payload builders and stubs here
are used by ``test_aggregator.py`` and ``test_backfill.py``. The fixtures
built from them (``all_payloads``, ``store``, ``frozen_now``) live in
``conftest.py``.
"""
from __future__ import annotations

import base64
import zlib
from array import array
from datetime import datetime, timedelta, timezone

from app.aggregator import Aggregator
from app.brightsky_client import SourceError
from app.config import (
    AccuracyConfig,
    ApiConfig,
    AppConfig,
    LocationConfig,
    ModelsConfig,
    ProbabilityConfig,
    RadarConfig,
    SchedulingConfig,
)
from app.store import Store

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_cfg(
    stale_radar: int = 10,
    stale_models: int = 120,
    use_accuracy_weights: bool = False,
    min_samples: int = 48,
    location: LocationConfig | None = LocationConfig(latitude=52.0, longitude=13.0),
) -> AppConfig:
    return AppConfig(
        location=location,
        radar=RadarConfig(radius_km=5.0, grid_size_km=1.0, step_minutes=5),
        probability=ProbabilityConfig(
            weight_radar=0.5,
            weight_models=0.3,
            weight_ensemble=0.2,
            model_rain_threshold_mm=0.1,
            radar_cell_rain_threshold_mm=0.05,
        ),
        models=ModelsConfig(
            forecast=("icon_d2", "icon_eu"), ensemble_model="ecmwf_ifs025"
        ),
        scheduling=SchedulingConfig(stale_radar_minutes=stale_radar, stale_models_minutes=stale_models),
        accuracy=AccuracyConfig(window_days=30, min_samples=min_samples),
        api=ApiConfig(),
        database_path=":memory:",
        use_accuracy_weights=use_accuracy_weights,
    )


class StubBrightSky:
    """Bright Sky stand-in: canned payloads, optional forced failures."""

    def __init__(self, payloads: dict, errors: tuple = ()):
        self._p = payloads
        self._e = set(errors)
        self._lat: float | None = None
        self._lon: float | None = None

    def set_location(self, latitude: float, longitude: float) -> None:
        self._lat = latitude
        self._lon = longitude

    async def fetch_current_payload(self):
        if "current" in self._e:
            raise SourceError("current down")
        return self._p["current"]

    async def fetch_radar_payload(self):
        if "radar" in self._e:
            raise SourceError("radar down")
        return self._p["radar"]

    async def fetch_weather_payload(self, start, end):
        if "weather" in self._e:
            raise SourceError("weather down")
        if "weather" in self._p:
            return self._p["weather"]
        raise SourceError("weather not configured")


class StubOpenMeteo:
    def __init__(self, payloads: dict, errors: tuple = ()):
        self._p = payloads
        self._e = set(errors)
        self._lat: float | None = None
        self._lon: float | None = None

    def set_location(self, latitude: float, longitude: float) -> None:
        self._lat = latitude
        self._lon = longitude

    async def fetch_forecast_payload(self):
        if "forecast" in self._e:
            raise SourceError("forecast down")
        return self._p["forecast"]

    async def fetch_ensemble_payload(self):
        if "ensemble" in self._e:
            raise SourceError("ensemble down")
        return self._p["ensemble"]


def radar_payload(frames: list[tuple[str, list[tuple[int, int, int]]]]) -> dict:
    """Bright Sky /radar payload; frames = (iso, [(x, y, raw 0.01mm), ...])."""
    w = h = 10
    out = []
    for iso, cells in frames:
        grid = [0] * (w * h)
        for x, y, v in cells:
            grid[y * w + x] = v
        enc = base64.b64encode(zlib.compress(array("H", grid).tobytes())).decode()
        out.append({"timestamp": iso, "precipitation_5": enc})
    return {"radar": out, "bbox": [0, 0, h - 1, w - 1], "latlon_position": {"x": 5.0, "y": 5.0}}


def current_payload() -> dict:
    return {"weather": {
        "timestamp": "2025-01-01T12:00:00Z", "source_id": 1,
        "temperature": 5.0, "wind_speed_10": 3.0, "wind_direction_10": 180.0,
        "wind_gust_speed_60": 6.0, "cloud_cover": 75.0, "relative_humidity": 80.0,
        "pressure_msl": 1015.0, "dew_point": 3.0,
        "precipitation_10": 0.0, "precipitation_30": 0.1, "precipitation_60": 0.2,
        "condition": "Rain",
    }}


def forecast_payload() -> dict:
    """icon_d2 rains 0.4 mm in the next hour; icon_eu stays dry; gfs null.

    The minutely_15 steps are stamped 12:15..13:00, i.e. strictly inside
    ``[NOW, NOW+1h)`` (a minutely_15 value at t covers [t-15min, t)), so at
    now = 12:00 all four steps fall in the next-hour window.

    The hourly axis is stamped NOW..NOW+71h (3-day fetch, see step 6b): with
    now = 12:00 the first *future* stamp is 13:00 (rain of 12:00-13:00), so
    icon_d2's 0.4 mm lands in the chart's first hour (labelled 12:00) and in
    the next-hour sum. gfs carries all-null precipitation to cover the
    "model with null data is skipped" path.
    """
    m15 = [
        (NOW + timedelta(minutes=15 + 15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(4)
    ]
    h72 = [(NOW + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(72)]
    return {
        "minutely_15": {
            "time": m15,
            "precipitation_icon_d2": [0.1, 0.1, 0.1, 0.1],
            "precipitation_icon_eu": [0.0, 0.0, 0.0, 0.0],
        },
        "hourly": {
            "time": h72,
            "precipitation_icon_d2": [0.0] + [0.4] + [0.0] * 70,
            "precipitation_icon_eu": [0.0] * 72,
            "precipitation_gfs": [None] * 72,
            "temperature_2m_icon_d2": [5.0] * 72,
            "apparent_temperature_icon_d2": [3.5] * 72,
            "wind_speed_10m_icon_d2": [10.0] * 72,
            "cloud_cover_icon_d2": [70.0] * 72,
            "temperature_2m_icon_eu": [4.0] * 72,
            "apparent_temperature_icon_eu": [2.0] * 72,
            "wind_speed_10m_icon_eu": [8.0] * 72,
            "cloud_cover_icon_eu": [60.0] * 72,
        },
    }


def ensemble_payload() -> dict:
    """member01 rains (1 mm) in the next hour; member02 stays dry. The steps
    are stamped 13:00..16:00, so at now = 12:00 the first step after now
    (13:00, covering 12:00-13:00) is the next hour."""
    h4 = [(NOW + timedelta(hours=1 + i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(4)]
    return {"hourly": {
        "time": h4,
        "precipitation": [0.5, 0.0, 0.0, 0.0],
        "precipitation_member01": [1.0, 0.0, 0.0, 0.0],
        "precipitation_member02": [0.0, 0.0, 0.0, 0.0],
    }}


def make_payloads() -> dict:
    """All four cache payloads (same as the ``all_payloads`` fixture)."""
    return {
        "current": current_payload(),
        "radar": radar_payload([("2025-01-01T12:00:00Z", [(5, 5, 20)])]),
        "forecast": forecast_payload(),
        "ensemble": ensemble_payload(),
    }


def make_aggregator(cfg, store, bs=None, om=None, errors=()) -> Aggregator:
    return Aggregator(cfg, store, StubBrightSky(bs or {}, errors), StubOpenMeteo(om or {}, errors))
