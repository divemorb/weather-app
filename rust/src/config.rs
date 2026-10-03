//! Application configuration: `weather.yaml` plus environment overrides
//! (Python `app/config.py`).
//!
//! Environment variables take precedence over the YAML file. All timestamps
//! are UTC; `location.timezone` is a *display* timezone only (consumed by
//! the frontend).

pub mod values;

use std::path::{Path, PathBuf};

use serde_json::{Map, Value};

use crate::pyfmt;

use values::{
    Env, env_bool, env_f64, env_i64, env_str, get_f64, get_i64, get_str, section, subsec,
};

/// The home location. `None` while unconfigured: it comes from the env vars,
/// from the YAML `location:` block, or — at runtime — from the database
/// where the app stores it (setup wizard).
#[derive(Debug, Clone, PartialEq)]
pub struct LocationConfig {
    pub latitude: f64,
    pub longitude: f64,
    pub timezone: String,
    pub label: String,
}

/// DWD radar grid around the location.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct RadarConfig {
    pub radius_km: f64,
    pub grid_size_km: f64,
    pub step_minutes: i64,
}

impl Default for RadarConfig {
    fn default() -> Self {
        Self {
            radius_km: 5.0,
            grid_size_km: 1.0,
            step_minutes: 5,
        }
    }
}

/// Weights for the combined next-hour rain probability.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct ProbabilityConfig {
    pub weight_radar: f64,
    pub weight_models: f64,
    pub weight_ensemble: f64,
    pub model_rain_threshold_mm: f64,
    pub radar_cell_rain_threshold_mm: f64,
}

impl Default for ProbabilityConfig {
    fn default() -> Self {
        Self {
            weight_radar: 0.5,
            weight_models: 0.3,
            weight_ensemble: 0.2,
            model_rain_threshold_mm: 0.1,
            radar_cell_rain_threshold_mm: 0.05,
        }
    }
}

impl ProbabilityConfig {
    /// The normalized weights for the sources that are available. Without
    /// radar coverage (outside Germany) the radar weight is dropped and the
    /// remaining weights are re-normalized to sum to 1.
    pub fn weights(&self, radar_available: bool) -> Result<Vec<(&'static str, f64)>, String> {
        let w = [
            (
                "radar",
                if radar_available {
                    self.weight_radar
                } else {
                    0.0
                },
            ),
            ("models", self.weight_models),
            ("ensemble", self.weight_ensemble),
        ];
        // A compensated sum (like Python's `sum`), not plain left-to-right
        // addition: for 0.1 + 0.2 + 0.3 it is exactly 0.6.
        let total = pyfmt::py_sum(w.iter().map(|(_, v)| *v));
        if total <= 0.0 {
            return Err("at least one probability source weight must be > 0".to_string());
        }
        Ok(w.iter()
            .filter(|(_, v)| *v > 0.0)
            .map(|(k, v)| (*k, v / total))
            .collect())
    }
}

/// Open-Meteo forecast models compared for the next 24 h.
#[derive(Debug, Clone, PartialEq)]
pub struct ModelsConfig {
    pub forecast: Vec<String>,
    pub ensemble_model: String,
}

impl Default for ModelsConfig {
    fn default() -> Self {
        Self {
            forecast: [
                "icon_d2",
                "icon_eu",
                "ecmwf_ifs025",
                "gfs_seamless",
                "arome_france",
                "ukmo_seamless",
            ]
            .map(str::to_string)
            .to_vec(),
            ensemble_model: "ecmwf_ifs025".to_string(),
        }
    }
}

/// Cache refresh cadence and stale thresholds.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SchedulingConfig {
    pub radar_interval_minutes: i64,
    pub models_interval_minutes: i64,
    pub stale_radar_minutes: i64,
    pub stale_models_minutes: i64,
}

impl Default for SchedulingConfig {
    fn default() -> Self {
        Self {
            radar_interval_minutes: 5,
            models_interval_minutes: 60,
            stale_radar_minutes: 10,
            stale_models_minutes: 120,
        }
    }
}

/// Per-model accuracy scoring: a rolling window of `window_days` and a
/// minimum of `min_samples` compared hours before the accuracy is treated
/// as reliable.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct AccuracyConfig {
    pub window_days: i64,
    pub min_samples: i64,
}

impl Default for AccuracyConfig {
    fn default() -> Self {
        Self {
            window_days: 30,
            min_samples: 48,
        }
    }
}

/// Upstream endpoints (overridable for tests/mocks).
#[derive(Debug, Clone, PartialEq)]
pub struct ApiConfig {
    pub brightsky_base_url: String,
    pub open_meteo_base_url: String,
    pub ensemble_base_url: String,
    pub nominatim_base_url: String,
    pub timeout_seconds: f64,
}

impl Default for ApiConfig {
    fn default() -> Self {
        Self {
            brightsky_base_url: "https://api.brightsky.dev".to_string(),
            open_meteo_base_url: "https://api.open-meteo.com/v1".to_string(),
            ensemble_base_url: "https://ensemble-api.open-meteo.com/v1".to_string(),
            nominatim_base_url: "https://nominatim.openstreetmap.org".to_string(),
            timeout_seconds: 20.0,
        }
    }
}

/// The whole application configuration.
#[derive(Debug, Clone, PartialEq)]
pub struct AppConfig {
    pub location: Option<LocationConfig>,
    pub radar: RadarConfig,
    pub probability: ProbabilityConfig,
    pub models: ModelsConfig,
    pub scheduling: SchedulingConfig,
    pub accuracy: AccuracyConfig,
    pub api: ApiConfig,
    pub database_path: String,
    pub use_accuracy_weights: bool,
}

/// A missing file is `{}`, and so is a *falsy* document; any other
/// non-mapping top level is an error.
fn load_yaml(path: &Path) -> Result<Value, String> {
    let Ok(text) = std::fs::read_to_string(path) else {
        return Ok(Value::Object(Map::new()));
    };
    let value = serde_saphyr::from_str::<Value>(&text)
        .map_err(|err| format!("invalid YAML in {path:?}: {err}"))?;
    if is_falsy(&value) {
        return Ok(Value::Object(Map::new()));
    }
    match value {
        Value::Object(_) => Ok(value),
        _ => Err(format!("config file {path:?} must contain a mapping")),
    }
}

/// Python truthiness of a YAML document: `null`, `false`, `0`, `0.0`, `""`
/// and `[]` (and `{}`) are falsy.
fn is_falsy(v: &Value) -> bool {
    match v {
        Value::Null => true,
        Value::Bool(b) => !b,
        Value::Number(n) => n.as_f64() == Some(0.0),
        Value::String(s) => s.is_empty(),
        Value::Array(items) => items.is_empty(),
        Value::Object(map) => map.is_empty(),
    }
}

/// Env vars win when *both* `LATITUDE` and `LONGITUDE` are set (they are
/// one source); otherwise the YAML `location:` block counts when both
/// coordinates are numbers. Any other mix is incomplete — `None`
/// (unconfigured; the setup wizard asks). There is no hard-coded default
/// location.
fn load_location(raw: &Value, env: Env) -> Result<Option<LocationConfig>, String> {
    let env_lat = env_str(env, "LATITUDE");
    let env_lon = env_str(env, "LONGITUDE");
    let loc = section(raw, "location")?;

    let (latitude, longitude) =
        if let (Some(lat), Some(lon)) = (env_lat.as_deref(), env_lon.as_deref()) {
            // A value that does not parse as a float means unconfigured,
            // not an error.
            match (lat.trim().parse::<f64>(), lon.trim().parse::<f64>()) {
                (Ok(latitude), Ok(longitude)) => (latitude, longitude),
                _ => return Ok(None),
            }
        } else if let (Some(Value::Number(lat)), Some(Value::Number(lon))) = (
            loc.and_then(|m| m.get("latitude")),
            loc.and_then(|m| m.get("longitude")),
        ) {
            // A bool is not a number here (serde_json keeps it out of Number);
            // numeric strings are not accepted either.
            match (lat.as_f64(), lon.as_f64()) {
                (Some(latitude), Some(longitude)) => (latitude, longitude),
                _ => return Ok(None),
            }
        } else {
            return Ok(None);
        };

    let timezone = match env_str(env, "TIMEZONE") {
        Some(timezone) => timezone,
        None => match loc.and_then(|m| m.get("timezone")) {
            Some(Value::String(s)) if !s.is_empty() => s.clone(),
            _ => "Europe/Berlin".to_string(),
        },
    };

    Ok(Some(LocationConfig {
        latitude,
        longitude,
        timezone,
        label: String::new(),
    }))
}

/// Load configuration from YAML, with environment overrides. The file is
/// `path`, else `WEATHER_CONFIG`, else `/app/weather.yaml` (the image puts
/// the file there; the Python repo-root default does not apply in the
/// image). A missing file counts as `{}` (all defaults).
pub fn load_config(path: Option<&Path>, env: Env) -> Result<AppConfig, String> {
    let path = path
        .map(PathBuf::from)
        .or_else(|| env_str(env, "WEATHER_CONFIG").map(PathBuf::from))
        .unwrap_or_else(|| PathBuf::from("/app/weather.yaml"));
    let raw = load_yaml(&path)?;

    let location = load_location(&raw, env)?;

    let rad = section(&raw, "radar")?;
    let radar = RadarConfig {
        radius_km: env_f64(env, "RADAR_RADIUS_KM", get_f64(rad, "radius_km", 5.0)?)?,
        grid_size_km: get_f64(rad, "grid_size_km", 1.0)?,
        step_minutes: get_i64(rad, "step_minutes", 5)?,
    };

    let prob = section(&raw, "probability")?;
    let weights = subsec(prob, "weights")?;
    let probability = ProbabilityConfig {
        weight_radar: env_f64(env, "WEIGHT_RADAR", get_f64(weights, "radar", 0.5)?)?,
        weight_models: env_f64(env, "WEIGHT_MODELS", get_f64(weights, "models", 0.3)?)?,
        weight_ensemble: env_f64(env, "WEIGHT_ENSEMBLE", get_f64(weights, "ensemble", 0.2)?)?,
        model_rain_threshold_mm: get_f64(prob, "model_rain_threshold_mm", 0.1)?,
        radar_cell_rain_threshold_mm: get_f64(prob, "radar_cell_rain_threshold_mm", 0.05)?,
    };

    let models_raw = section(&raw, "models")?;
    let forecast = match models_raw.and_then(|m| m.get("forecast")) {
        None | Some(Value::Null) => Vec::new(),
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| match item {
                Value::String(s) => Ok(s.clone()),
                other => Err(format!("models.forecast: expected strings, got {other}")),
            })
            .collect::<Result<Vec<String>, String>>()?,
        Some(other) => return Err(format!("models.forecast: expected a list, got {other}")),
    };
    let models = ModelsConfig {
        forecast,
        ensemble_model: get_str(models_raw, "ensemble_model", "ecmwf_ifs025")?,
    };

    let sched = section(&raw, "scheduling")?;
    let stale = subsec(sched, "stale_after_minutes")?;
    let scheduling = SchedulingConfig {
        radar_interval_minutes: env_i64(
            env,
            "RADAR_INTERVAL_MINUTES",
            get_i64(sched, "radar_interval_minutes", 5)?,
        )?,
        models_interval_minutes: env_i64(
            env,
            "MODELS_INTERVAL_MINUTES",
            get_i64(sched, "models_interval_minutes", 60)?,
        )?,
        stale_radar_minutes: get_i64(stale, "radar", 10)?,
        stale_models_minutes: get_i64(stale, "models", 120)?,
    };

    let acc_raw = section(&raw, "accuracy")?;
    let accuracy = AccuracyConfig {
        window_days: get_i64(acc_raw, "window_days", 30)?,
        min_samples: get_i64(acc_raw, "min_samples", 48)?,
    };

    let api_raw = section(&raw, "api")?;
    let api = ApiConfig {
        brightsky_base_url: get_str(api_raw, "brightsky_base_url", "https://api.brightsky.dev")?,
        open_meteo_base_url: get_str(
            api_raw,
            "open_meteo_base_url",
            "https://api.open-meteo.com/v1",
        )?,
        ensemble_base_url: get_str(
            api_raw,
            "ensemble_base_url",
            "https://ensemble-api.open-meteo.com/v1",
        )?,
        nominatim_base_url: get_str(
            api_raw,
            "nominatim_base_url",
            "https://nominatim.openstreetmap.org",
        )?,
        timeout_seconds: get_f64(api_raw, "timeout_seconds", 20.0)?,
    };

    Ok(AppConfig {
        location,
        radar,
        probability,
        models,
        scheduling,
        accuracy,
        api,
        database_path: env_str(env, "DATABASE_PATH")
            .unwrap_or_else(|| "/data/weather.db".to_string()),
        use_accuracy_weights: env_bool(env, "USE_ACCURACY_WEIGHTS", false),
    })
}

#[cfg(test)]
mod tests;
