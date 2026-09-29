"""Application configuration.

Loads ``weather.yaml`` from the repo root (override with ``WEATHER_CONFIG``
env var). Environment variables take precedence over the YAML file, so the
same deployment can be tuned without rebuilding the image.

All timestamps in the app are UTC; ``location.timezone`` is a *display*
timezone only (consumed by the frontend).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "weather.yaml"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LocationConfig:
    latitude: float
    longitude: float
    timezone: str = "Europe/Berlin"
    label: str = ""


@dataclass(frozen=True)
class RadarConfig:
    radius_km: float = 5.0
    grid_size_km: float = 1.0
    step_minutes: int = 5


@dataclass(frozen=True)
class ProbabilityConfig:
    weight_radar: float = 0.5
    weight_models: float = 0.3
    weight_ensemble: float = 0.2
    model_rain_threshold_mm: float = 0.1
    radar_cell_rain_threshold_mm: float = 0.05

    def weights(self, radar_available: bool) -> dict[str, float]:
        """Return the normalized weights for the sources that are available.

        Without radar coverage (outside Germany) the radar weight is dropped
        and the remaining weights are re-normalized to sum to 1.
        """
        w = {
            "radar": self.weight_radar if radar_available else 0.0,
            "models": self.weight_models,
            "ensemble": self.weight_ensemble,
        }
        total = sum(w.values())
        if total <= 0:
            raise ValueError("at least one probability source weight must be > 0")
        return {k: v / total for k, v in w.items() if v > 0}


@dataclass(frozen=True)
class ModelsConfig:
    forecast: tuple[str, ...] = (
        "icon_d2",
        "icon_eu",
        "ecmwf_ifs025",
        "gfs_seamless",
        "arome_france",
        "ukmo_seamless",
    )
    ensemble_model: str = "ecmwf_ifs025"


@dataclass(frozen=True)
class SchedulingConfig:
    radar_interval_minutes: int = 5
    models_interval_minutes: int = 60
    stale_radar_minutes: int = 10
    stale_models_minutes: int = 120


@dataclass(frozen=True)
class AccuracyConfig:
    """Per-model accuracy scoring (step 6e).

    Forecasts are compared against observations over a rolling window
    (``window_days``); a model needs at least ``min_samples`` compared
    hours before its accuracy is treated as reliable (``enough_data``).
    """

    window_days: int = 30
    min_samples: int = 48


@dataclass(frozen=True)
class ApiConfig:
    brightsky_base_url: str = "https://api.brightsky.dev"
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    ensemble_base_url: str = "https://ensemble-api.open-meteo.com/v1"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    timeout_seconds: float = 20.0


@dataclass(frozen=True)
class AppConfig:
    #: The home location. ``None`` while unconfigured (step 8b): it comes
    #: from the env vars, from the YAML ``location:`` block, or — at
    #: runtime — from the database where the app stores it (setup wizard).
    location: LocationConfig | None
    radar: RadarConfig
    probability: ProbabilityConfig
    models: ModelsConfig
    scheduling: SchedulingConfig
    accuracy: AccuracyConfig
    api: ApiConfig
    database_path: str = "/data/weather.db"
    use_accuracy_weights: bool = False


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw is not None else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw is not None else default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} must contain a mapping")
    return data


def _load_location(raw: dict) -> LocationConfig | None:
    """Build the location from env vars (win) or the YAML ``location:`` block.

    Both coordinates must come from the same source: only when *both*
    ``LATITUDE`` and ``LONGITUDE`` are set do they count; otherwise the YAML
    block counts when *both* keys are present. Any other mix is incomplete —
    ``None`` (unconfigured; the setup wizard asks for the location, step 8).
    There is no hard-coded default location: the repo must not contain one.
    ``TIMEZONE`` / ``location.timezone`` still default to ``Europe/Berlin``.
    """
    env_lat = _env("LATITUDE")
    env_lon = _env("LONGITUDE")
    loc = raw.get("location", {}) or {}
    y_lat = loc.get("latitude")
    y_lon = loc.get("longitude")
    if env_lat is not None and env_lon is not None:
        try:
            latitude, longitude = float(env_lat), float(env_lon)
        except ValueError:
            return None
    elif isinstance(y_lat, (int, float)) and isinstance(y_lon, (int, float)) and not (
        isinstance(y_lat, bool) or isinstance(y_lon, bool)
    ):
        latitude, longitude = float(y_lat), float(y_lon)
    else:
        return None
    timezone = _env("TIMEZONE", loc.get("timezone", "Europe/Berlin")) or "Europe/Berlin"
    return LocationConfig(latitude=latitude, longitude=longitude, timezone=timezone)


def load_config(path: Path | None = None) -> AppConfig:
    """Load configuration from YAML, with environment overrides."""
    path = path or Path(_env("WEATHER_CONFIG") or _DEFAULT_CONFIG_PATH)
    raw = _load_yaml(path)

    location = _load_location(raw)

    rad = raw.get("radar", {}) or {}
    radar = RadarConfig(
        radius_km=_env_float("RADAR_RADIUS_KM", float(rad.get("radius_km", 5.0))),
        grid_size_km=float(rad.get("grid_size_km", 1.0)),
        step_minutes=int(rad.get("step_minutes", 5)),
    )

    prob = raw.get("probability", {}) or {}
    weights = prob.get("weights", {}) or {}
    probability = ProbabilityConfig(
        weight_radar=_env_float("WEIGHT_RADAR", float(weights.get("radar", 0.5))),
        weight_models=_env_float("WEIGHT_MODELS", float(weights.get("models", 0.3))),
        weight_ensemble=_env_float("WEIGHT_ENSEMBLE", float(weights.get("ensemble", 0.2))),
        model_rain_threshold_mm=float(prob.get("model_rain_threshold_mm", 0.1)),
        radar_cell_rain_threshold_mm=float(prob.get("radar_cell_rain_threshold_mm", 0.05)),
    )

    models_raw = raw.get("models", {}) or {}
    models = ModelsConfig(
        forecast=tuple(models_raw.get("forecast") or ()),
        ensemble_model=models_raw.get("ensemble_model", "ecmwf_ifs025"),
    )

    sched = raw.get("scheduling", {}) or {}
    stale = sched.get("stale_after_minutes", {}) or {}
    scheduling = SchedulingConfig(
        radar_interval_minutes=_env_int(
            "RADAR_INTERVAL_MINUTES", int(sched.get("radar_interval_minutes", 5))
        ),
        models_interval_minutes=_env_int(
            "MODELS_INTERVAL_MINUTES", int(sched.get("models_interval_minutes", 60))
        ),
        stale_radar_minutes=int(stale.get("radar", 10)),
        stale_models_minutes=int(stale.get("models", 120)),
    )

    acc_raw = raw.get("accuracy", {}) or {}
    accuracy = AccuracyConfig(
        window_days=int(acc_raw.get("window_days", 30)),
        min_samples=int(acc_raw.get("min_samples", 48)),
    )

    api_raw = raw.get("api", {}) or {}
    api = ApiConfig(
        brightsky_base_url=api_raw.get("brightsky_base_url", "https://api.brightsky.dev"),
        open_meteo_base_url=api_raw.get(
            "open_meteo_base_url", "https://api.open-meteo.com/v1"
        ),
        ensemble_base_url=api_raw.get(
            "ensemble_base_url", "https://ensemble-api.open-meteo.com/v1"
        ),
        nominatim_base_url=api_raw.get(
            "nominatim_base_url", "https://nominatim.openstreetmap.org"
        ),
        timeout_seconds=float(api_raw.get("timeout_seconds", 20.0)),
    )

    return AppConfig(
        location=location,
        radar=radar,
        probability=probability,
        models=models,
        scheduling=scheduling,
        accuracy=accuracy,
        api=api,
        database_path=_env("DATABASE_PATH", "/data/weather.db") or "/data/weather.db",
        use_accuracy_weights=_env_bool("USE_ACCURACY_WEIGHTS", False),
    )
