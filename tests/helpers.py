"""Builders for synthetic API payloads used by the unit tests (no network).

They mirror the real response shapes of Bright Sky and Open-Meteo, including
the base64+zlib radar grid encoding (uint16, 0.01 mm per 5 min units).
"""
from __future__ import annotations

import array
import base64
import zlib
from typing import Any

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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def make_cfg(
    forecast: tuple[str, ...] = ("icon_d2", "icon_eu"),
    ensemble_model: str = "ecmwf_ifs025",
) -> AppConfig:
    """A minimal in-memory AppConfig pointing at fake base URLs."""
    return AppConfig(
        location=LocationConfig(latitude=52.0, longitude=13.0, timezone="Europe/Berlin"),
        radar=RadarConfig(),
        probability=ProbabilityConfig(),
        models=ModelsConfig(forecast=forecast, ensemble_model=ensemble_model),
        scheduling=SchedulingConfig(),
        accuracy=AccuracyConfig(),
        api=ApiConfig(
            brightsky_base_url="http://bs.test",
            open_meteo_base_url="http://om.test/v1",
            ensemble_base_url="http://ens.test/v1",
        ),
        database_path=":memory:",
    )


# ---------------------------------------------------------------------------
# Bright Sky
# ---------------------------------------------------------------------------
def make_current_payload(weather: dict[str, Any] | None = None) -> dict[str, Any]:
    w = {
        "source_id": 96160,
        "timestamp": "2026-09-25T06:00:00+00:00",
        "condition": "dry",
        "dew_point": 3.5,
        "precipitation_10": 0.0,
        "precipitation_30": 0.4,
        "precipitation_60": 0.8,
        "pressure_msl": 1026.0,
        "relative_humidity": 87,
        "visibility": 34801,
        "wind_direction_10": 260,
        "wind_speed_10": 5.0,
        "wind_speed_60": 6.2,
        "wind_gust_speed_60": 11.0,
        "cloud_cover": 88,
        "temperature": 7.4,
        "fallback_source_ids": {"wind_speed_10": 11702},
    }
    if weather is not None:
        w.update(weather)
    return {"weather": w, "sources": []}


def make_weather_payload(
    weather: list[dict[str, Any]] | None = None,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A /weather payload mirroring the verified response shape.

    Default data: observation station 1002 ("current") with a dry hour at
    16:00, a null-precipitation hour at 17:00 and 0.4 mm at 18:00 (covering
    [17:00, 18:00)); MOSMIX source 1001 ("forecast") with 19:00 and 21:00
    records that must never be treated as observations.
    """
    w = [
        {"timestamp": "2026-09-27T16:00:00+00:00", "source_id": 1002, "precipitation": 0.0},
        {"timestamp": "2026-09-27T17:00:00+00:00", "source_id": 1002, "precipitation": None},
        {"timestamp": "2026-09-27T18:00:00+00:00", "source_id": 1002, "precipitation": 0.4},
        {"timestamp": "2026-09-27T19:00:00+00:00", "source_id": 1001, "precipitation": 1.2},
        {"timestamp": "2026-09-27T21:00:00+00:00", "source_id": 1001, "precipitation": 2.0},
    ]
    s = [
        {"id": 1002, "observation_type": "current",
         "station_name": "BERLIN", "distance": 5000.0},
        {"id": 1001, "observation_type": "forecast",
         "station_name": "BERLIN", "distance": 3000.0},
    ]
    return {"weather": w if weather is None else weather,
            "sources": s if sources is None else sources}


def _encode_grid(grid: list[list[int]]) -> str:
    """Row-major uint16 grid -> base64(zlib(bytes)), as Bright Sky sends it."""
    flat = array.array("H")
    for row in grid:
        flat.extend(row)
    return base64.b64encode(zlib.compress(flat.tobytes())).decode("ascii")


def make_radar_payload(
    frames: list[dict[str, Any]],
    bbox: tuple[int, int, int, int] = (10, 20, 14, 24),  # top,left,bottom,right
    latlon_position: dict[str, float] = {"x": 2.0, "y": 2.0},
) -> dict[str, Any]:
    """Assemble a /radar payload. ``frames`` are dicts with 'timestamp' and
    a 'grid' of raw uint16 values; the grid is encoded into precipitation_5."""
    out = []
    for i, fr in enumerate(frames):
        out.append(
            {
                "timestamp": fr["timestamp"],
                "source": f"RADOLAN::RV::frame{i}",
                "precipitation_5": _encode_grid(fr["grid"]),
            }
        )
    return {
        "radar": out,
        "bbox": list(bbox),
        "latlon_position": latlon_position,
        "geometry": {"type": "Polygon", "coordinates": []},
    }


def grid(width: int, height: int, value: int = 0) -> list[list[int]]:
    """A width x height grid filled with ``value``."""
    return [[value] * width for _ in range(height)]


# ---------------------------------------------------------------------------
# Open-Meteo forecast (multi-model, suffixed keys)
# ---------------------------------------------------------------------------
def make_forecast_payload(
    model_names: list[str],
    hours: list[str],
    min15: list[str],
    precip_per_model: dict[str, list[float]],
    min15_precip_per_model: dict[str, list[float]],
    extra_hourly: dict[str, dict[str, list[float]]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "latitude": 52.0,
        "longitude": 13.0,
        "timezone": "GMT",
        "minutely_15": {"time": min15},
        "hourly": {"time": hours},
    }
    for name in model_names:
        payload["minutely_15"][f"precipitation_{name}"] = min15_precip_per_model[name]
        payload["hourly"][f"precipitation_{name}"] = precip_per_model[name]
        for var, series in (extra_hourly or {}).items():
            payload["hourly"][f"{var}_{name}"] = series[name]
    return payload


# ---------------------------------------------------------------------------
# Open-Meteo ensemble
# ---------------------------------------------------------------------------
def make_ensemble_payload(
    hours: list[str],
    control: list[float],
    members: list[list[float]],
) -> dict[str, Any]:
    hourly: dict[str, Any] = {
        "time": hours,
        "precipitation": control,
    }
    for i, member in enumerate(members, start=1):
        hourly[f"precipitation_member{i:02d}"] = member
    return {
        "latitude": 52.0,
        "longitude": 13.0,
        "timezone": "GMT",
        "hourly_units": {"precipitation": "mm"},
        "hourly": hourly,
    }
