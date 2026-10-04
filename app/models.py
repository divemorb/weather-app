"""Normalized data models shared between clients, aggregation and the API:
the internal contract (clients parse into them, the REST layer serializes
them)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Current conditions ("Now" tile)
# ---------------------------------------------------------------------------
@dataclass
class CurrentConditions:
    """'Now' tile, primarily from Bright Sky ``/current_weather`` (DWD).

    ``feels_like_c`` is None from Bright Sky (no such field); the aggregator
    fills it from Open-Meteo's ``apparent_temperature``.
    """

    timestamp_utc: str | None = None
    source_id: int | None = None
    temperature_c: float | None = None
    feels_like_c: float | None = None
    wind_speed_ms: float | None = None
    wind_direction_deg: float | None = None
    wind_gust_ms: float | None = None
    cloud_cover_pct: float | None = None
    humidity_pct: float | None = None
    pressure_hpa: float | None = None
    dew_point_c: float | None = None
    precipitation_10mm: float | None = None
    precipitation_30mm: float | None = None
    precipitation_60mm: float | None = None
    condition: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


# ---------------------------------------------------------------------------
# Radar nowcast (DWD, via Bright Sky)
# ---------------------------------------------------------------------------
@dataclass
class RadarCell:
    """One raining grid cell (value already in millimetres)."""

    x: int      # column, in full radar-grid coordinates
    y: int      # row, in full radar-grid coordinates
    mm: float   # 5-minute precipitation (mm)


@dataclass
class RadarFrame:
    """One 5-minute step of the radar nowcast."""

    time_utc: datetime                       # aware UTC datetime
    cells: list[RadarCell] = field(default_factory=list)  # raining cells only
    max_mm: float = 0.0                      # strongest cell in this step


@dataclass
class RadarNowcast:
    """5-minute frames spanning the next ~60 minutes, oldest first."""

    frames: list[RadarFrame]
    covered: bool = True          # False when location is outside the grid
    grid_width: int = 0
    grid_height: int = 0
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # top, left, bottom, right
    location_xy: tuple[float, float] = (0.0, 0.0)


# ---------------------------------------------------------------------------
# Open-Meteo normalized series (parsed, network-free)
# ---------------------------------------------------------------------------
@dataclass
class ModelSeries:
    """One model's normalized time series (units already converted)."""

    name: str
    min15_time: list[datetime] = field(default_factory=list)
    min15_precip_mm: list[float | None] = field(default_factory=list)
    hourly_time: list[datetime] = field(default_factory=list)
    hourly_precip_mm: list[float | None] = field(default_factory=list)
    hourly_temp_c: list[float | None] = field(default_factory=list)
    hourly_apparent_c: list[float | None] = field(default_factory=list)
    hourly_wind_kmh: list[float | None] = field(default_factory=list)
    hourly_cloud_cover_pct: list[float | None] = field(default_factory=list)


@dataclass
class ForecastBundle:
    """All configured models, aligned to a common time axis."""

    models: list[ModelSeries] = field(default_factory=list)

    def by_name(self, name: str) -> "ModelSeries | None":
        for m in self.models:
            if m.name == name:
                return m
        return None


@dataclass
class EnsembleData:
    """Ensemble precipitation (mm per hour), control run + members."""

    hourly_time: list[datetime] = field(default_factory=list)
    control_precip_mm: list[float | None] = field(default_factory=list)
    # member index 0..n_members-1, each a per-hour list
    member_precip_mm: list[list[float | None]] = field(default_factory=list)

    @property
    def n_members(self) -> int:
        return len(self.member_precip_mm)


# ---------------------------------------------------------------------------
# Rain-probability votes
# ---------------------------------------------------------------------------
@dataclass
class ModelVote:
    """One model's vote on rain in the next 60 minutes."""

    name: str
    precip_next_hour_mm: float | None  # sum of the four 15-min steps


@dataclass
class EnsembleVote:
    """Ensemble rain probability: share of members > threshold (0..100)."""

    probability_pct: float | None
    n_members: int = 0
    n_rain_members: int = 0


@dataclass
class RainProbability:
    """Combined next-hour rain probability + human-readable derivation."""

    probability_pct: float
    radar_available: bool
    radar_raining: bool | None
    models_rain_count: int
    models_total: int
    ensemble_pct: float | None
    weights_used: dict[str, float]
    explanation: str
    # True only when the accuracy weights were applied (the gate passed)
    accuracy_weighted: bool = False


# ---------------------------------------------------------------------------
# 24 h model comparison
# ---------------------------------------------------------------------------
@dataclass
class Model24hSeries:
    """Hourly precipitation for one model over the next 24 h."""

    name: str
    hours: list[datetime] = field(default_factory=list)
    precipitation_mm: list[float | None] = field(default_factory=list)
