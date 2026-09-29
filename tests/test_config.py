"""Unit tests for configuration loading (YAML + env overrides)."""
from __future__ import annotations

import pytest

from app.config import load_config


@pytest.fixture
def base_data() -> dict:
    return {
        "location": {"latitude": 52.0, "longitude": 13.0, "timezone": "Europe/Berlin"},
        "probability": {
            "weights": {"radar": 0.5, "models": 0.3, "ensemble": 0.2},
            "model_rain_threshold_mm": 0.1,
            "radar_cell_rain_threshold_mm": 0.05,
        },
        "models": {
            "forecast": ["icon_d2", "icon_eu"],
            "ensemble_model": "ecmwf_ifs025",
        },
        "scheduling": {
            "radar_interval_minutes": 5,
            "models_interval_minutes": 60,
            "stale_after_minutes": {"radar": 10, "models": 120},
        },
    }


def test_defaults_from_yaml(make_config, base_data):
    cfg = load_config(make_config(base_data))
    assert cfg.location.latitude == 52.0
    assert cfg.location.longitude == 13.0
    assert cfg.location.timezone == "Europe/Berlin"
    assert cfg.probability.weight_radar == 0.5
    assert cfg.models.forecast == ("icon_d2", "icon_eu")
    assert cfg.models.ensemble_model == "ecmwf_ifs025"
    assert cfg.scheduling.radar_interval_minutes == 5
    assert cfg.scheduling.models_interval_minutes == 60


def test_missing_file_uses_builtin_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("WEATHER_CONFIG", raising=False)
    cfg = load_config(tmp_path / "does_not_exist.yaml")
    # Builtin defaults so the app still boots without a config file.
    assert 0 < cfg.probability.weight_radar < 1
    assert cfg.radar.radius_km == 5.0


def test_env_overrides_yaml(make_config, base_data, monkeypatch):
    monkeypatch.setenv("LATITUDE", "52.52")
    monkeypatch.setenv("LONGITUDE", "13.40")
    monkeypatch.setenv("RADAR_RADIUS_KM", "3")
    monkeypatch.setenv("WEIGHT_RADAR", "0.7")
    monkeypatch.setenv("RADAR_INTERVAL_MINUTES", "10")

    cfg = load_config(make_config(base_data))
    assert cfg.location.latitude == 52.52
    assert cfg.location.longitude == 13.40
    assert cfg.radar.radius_km == 3.0
    assert cfg.probability.weight_radar == 0.7
    assert cfg.scheduling.radar_interval_minutes == 10


def test_accuracy_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("WEATHER_CONFIG", raising=False)
    cfg = load_config(tmp_path / "does_not_exist.yaml")
    # Builtin defaults so the app still boots without a config file.
    assert cfg.accuracy.window_days == 30
    assert cfg.accuracy.min_samples == 48


def test_accuracy_from_yaml(make_config, base_data):
    base_data["accuracy"] = {"window_days": 14, "min_samples": 24}
    cfg = load_config(make_config(base_data))
    assert cfg.accuracy.window_days == 14
    assert cfg.accuracy.min_samples == 24


def test_weight_normalization_with_radar():
    cfg = load_config(None)  # real weather.yaml at repo root
    w = cfg.probability.weights(radar_available=True)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert set(w) == {"radar", "models", "ensemble"}


def test_weight_fallback_without_radar():
    cfg = load_config(None)
    w = cfg.probability.weights(radar_available=False)
    assert "radar" not in w
    assert abs(sum(w.values()) - 1.0) < 1e-9
    # models:ensemble ratio must be preserved (0.3 : 0.2 -> 0.6 : 0.4)
    assert abs(w["models"] - 0.6) < 1e-9
    assert abs(w["ensemble"] - 0.4) < 1e-9


# ---------------------------------------------------------------------------
# location is optional (step 8b: the app runs unconfigured)
# ---------------------------------------------------------------------------
def test_no_location_in_yaml_and_no_env_is_unconfigured(make_config, monkeypatch):
    for var in ("LATITUDE", "LONGITUDE", "TIMEZONE"):
        monkeypatch.delenv(var, raising=False)
    cfg = load_config(make_config({}))
    assert cfg.location is None


def test_yaml_location_needs_both_coordinates(make_config, monkeypatch):
    monkeypatch.delenv("LATITUDE", raising=False)
    monkeypatch.delenv("LONGITUDE", raising=False)
    cfg = load_config(make_config({"location": {"latitude": 52.0}}))
    assert cfg.location is None


def test_partial_env_falls_back_to_yaml(make_config, monkeypatch):
    # env only counts when BOTH vars are set (they are one source); with
    # only LATITUDE the YAML block is the source (no mixing of coordinates)
    monkeypatch.delenv("LONGITUDE", raising=False)
    monkeypatch.setenv("LATITUDE", "52.52")
    cfg = load_config(make_config({"location": {"latitude": 52.0, "longitude": 13.0}}))
    assert cfg.location is not None
    assert cfg.location.latitude == 52.0


def test_yaml_location_defaults_timezone(make_config, monkeypatch):
    monkeypatch.delenv("TIMEZONE", raising=False)
    cfg = load_config(make_config({"location": {"latitude": 52.0, "longitude": 13.0}}))
    assert cfg.location is not None
    assert cfg.location.timezone == "Europe/Berlin"


def test_env_location_without_yaml(make_config, monkeypatch):
    # env vars are a source by themselves; the YAML block is not needed
    monkeypatch.delenv("LONGITUDE", raising=False)
    monkeypatch.setenv("LATITUDE", "52.52")
    monkeypatch.setenv("LONGITUDE", "13.40")
    cfg = load_config(make_config({}))
    assert cfg.location is not None
    assert (cfg.location.latitude, cfg.location.longitude) == (52.52, 13.40)
    assert cfg.location.timezone == "Europe/Berlin"
