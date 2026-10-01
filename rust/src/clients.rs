//! Upstream HTTP clients: Bright Sky (DWD) and Open-Meteo (forecast and
//! ensemble). Port of the `BrightSkyClient` class in `app/brightsky_client.py`
//! and the `OpenMeteoClient` class in `app/openmeteo_client.py`.
//!
//! The clients fetch *raw* JSON payloads only (what gets cached); the pure
//! parsers live in `crate::brightsky` and `crate::openmeteo`. Every failure
//! — network, HTTP status, response-size cap, a non-object body, the API
//! `error` flag, a missing location — is a [`SourceError`], so a failing
//! source never breaks the app (the last good cache is served instead).
//!
//! The aggregator owns both clients behind an `Arc` and changes the location
//! at runtime through `set_location` (a shared reference: both clients are
//! `Sync`). The caller passes in the shared [`reqwest::Client`] (in
//! production: `upstream::http_client(cfg.api.timeout_seconds)`); every
//! request goes through [`upstream::fetch_json_capped`].
//!
//! There is no `Utc::now()` inside the clients: a request that depends on the
//! time (the radar window) takes it as a parameter, so `WETTER_FAKE_NOW` and
//! the tests control time. Query values are formatted like Python's `str()`
//! (`pyfmt::py_repr` for floats) because the contract suite compares the
//! query strings byte for byte.

use std::sync::{Arc, Mutex, PoisonError};

use chrono::{DateTime, DurationRound, TimeDelta, Utc};
use serde_json::Value;

use crate::config::AppConfig;
use crate::pyfmt;
use crate::times;
use crate::upstream::{self, SourceError};

/// The location the clients request data for (Python's `_lat`/`_lon`).
/// Runtime state: changed with `set_location` (step 8b). Named fields so the
/// two coordinates can never be swapped.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Location {
    pub latitude: f64,
    pub longitude: f64,
}

/// Variables requested hourly per model (Python `HOURLY_VARS`); in the
/// multi-model response every key is suffixed with the model name.
pub const HOURLY_VARS: [&str; 5] = [
    "precipitation",
    "temperature_2m",
    "apparent_temperature",
    "wind_speed_10m",
    "cloud_cover",
];

/// The initial location from the config; `None` while unconfigured (8b).
fn initial_location(cfg: &AppConfig) -> Option<Location> {
    cfg.location.as_ref().map(|loc| Location {
        latitude: loc.latitude,
        longitude: loc.longitude,
    })
}

/// Read the location under the lock; the guard is dropped at once, so the
/// lock is never held across an `.await`.
fn read_location(state: &Mutex<Option<Location>>) -> Option<Location> {
    *state.lock().unwrap_or_else(PoisonError::into_inner)
}

/// Python `set_location`: the location is runtime state (step 8b).
fn write_location(state: &Mutex<Option<Location>>, latitude: f64, longitude: f64) {
    *state.lock().unwrap_or_else(PoisonError::into_inner) = Some(Location {
        latitude,
        longitude,
    });
}

/// Python `strftime("%Y-%m-%dT%H:%M:%S+00:00")` (the radar window is UTC).
fn iso_offset(t: DateTime<Utc>) -> String {
    format!("{}+00:00", t.format("%Y-%m-%dT%H:%M:%S"))
}

/// Bright Sky (DWD) client (Python `app/brightsky_client.py`, class
/// `BrightSkyClient`). `Sync`, so the aggregator can share it behind an
/// `Arc` and change the location through a shared reference.
pub struct BrightSkyClient {
    base: String,
    http: reqwest::Client,
    location: Arc<Mutex<Option<Location>>>,
}

impl BrightSkyClient {
    /// Build the client from `cfg`; `http` is the shared request client
    /// (production: `upstream::http_client(cfg.api.timeout_seconds)`). The
    /// location comes from `cfg.location` and may be `None` while
    /// unconfigured (step 8b).
    pub fn new(cfg: &AppConfig, http: reqwest::Client) -> Self {
        Self {
            base: cfg.api.brightsky_base_url.trim_end_matches('/').to_string(),
            http,
            location: Arc::new(Mutex::new(initial_location(cfg))),
        }
    }

    /// Change the location (step 8b: it is runtime state).
    pub fn set_location(&self, latitude: f64, longitude: f64) {
        write_location(&self.location, latitude, longitude);
    }

    /// The current location (`None` while unconfigured); the Python tests
    /// read `_lat`/`_lon` back this way.
    pub fn location(&self) -> Option<Location> {
        read_location(&self.location)
    }

    /// Python `_location_params`; an unset location is a `SourceError`.
    fn location_params(&self) -> Result<Vec<(&'static str, String)>, SourceError> {
        let Some(loc) = read_location(&self.location) else {
            return Err(SourceError::new("Bright Sky: no location configured"));
        };
        Ok(vec![
            ("lat", pyfmt::py_repr(loc.latitude)),
            ("lon", pyfmt::py_repr(loc.longitude)),
        ])
    }

    /// Python `_get`: GET through the capped JSON reader and require an
    /// object payload; failures carry the endpoint in the message.
    async fn get(
        &self,
        endpoint: &str,
        params: &[(&'static str, String)],
    ) -> Result<Value, SourceError> {
        let url = format!("{}{}", self.base, endpoint);
        let data = match upstream::fetch_json_capped(&self.http, &url, params).await {
            Ok(data) => data,
            Err(err) => return Err(SourceError::new(format!("Bright Sky {endpoint}: {err}"))),
        };
        if !data.is_object() {
            return Err(SourceError::new(format!(
                "Bright Sky {endpoint} returned unexpected payload"
            )));
        }
        Ok(data)
    }

    /// Raw `/current_weather` JSON.
    pub async fn fetch_current_payload(&self) -> Result<Value, SourceError> {
        let params = self.location_params()?;
        self.get("/current_weather", &params).await
    }

    /// Raw `/radar` JSON for the next-hour window.
    ///
    /// Requests `date`/`last_date` explicitly so the response contains the
    /// nowcast (frames at or after `now`); without them the server returns
    /// the *previous* hour (all in the past) and the radar signal would stay
    /// dry. The window is floored to the 5-minute grid: `date =
    /// floor(now, 5min)`, `last_date = date + 60min`, which always contains
    /// `[now, now+1h)` (the probability layer's scan window) regardless of
    /// the minute — the extra past frame is filtered out downstream.
    pub async fn fetch_radar_payload(&self, now: DateTime<Utc>) -> Result<Value, SourceError> {
        let date = now.duration_trunc(TimeDelta::minutes(5)).unwrap_or(now);
        let last_date = date + TimeDelta::hours(1);
        let mut params = self.location_params()?;
        params.push(("date", iso_offset(date)));
        params.push(("last_date", iso_offset(last_date)));
        self.get("/radar", &params).await
    }

    /// Raw `/weather` JSON for hourly records in `[start, end]`.
    ///
    /// Used by the aggregator's observation backfill: the response carries
    /// both real observations (`observation_type` "current"/"historical") and
    /// MOSMIX forecasts ("forecast"); `crate::brightsky::parse_hourly_observations`
    /// keeps only the real ones.
    pub async fn fetch_weather_payload(
        &self,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
    ) -> Result<Value, SourceError> {
        let mut params = self.location_params()?;
        params.push(("date", times::to_iso(start)));
        params.push(("last_date", times::to_iso(end)));
        params.push(("tz", "UTC".to_string()));
        self.get("/weather", &params).await
    }
}

/// Open-Meteo client: multi-model forecast + ensemble (Python
/// `app/openmeteo_client.py`, class `OpenMeteoClient`). `Sync`, so the
/// aggregator can share it behind an `Arc` and change the location through a
/// shared reference.
pub struct OpenMeteoClient {
    forecast_base: String,
    ensemble_base: String,
    forecast_models: Vec<String>,
    ensemble_model: String,
    http: reqwest::Client,
    location: Arc<Mutex<Option<Location>>>,
}

impl OpenMeteoClient {
    /// Build the client from `cfg`; `http` is the shared request client
    /// (production: `upstream::http_client(cfg.api.timeout_seconds)`). The
    /// location comes from `cfg.location` and may be `None` while
    /// unconfigured (step 8b).
    pub fn new(cfg: &AppConfig, http: reqwest::Client) -> Self {
        Self {
            forecast_base: cfg
                .api
                .open_meteo_base_url
                .trim_end_matches('/')
                .to_string(),
            ensemble_base: cfg.api.ensemble_base_url.trim_end_matches('/').to_string(),
            forecast_models: cfg.models.forecast.clone(),
            ensemble_model: cfg.models.ensemble_model.clone(),
            http,
            location: Arc::new(Mutex::new(initial_location(cfg))),
        }
    }

    /// Change the location (step 8b: it is runtime state).
    pub fn set_location(&self, latitude: f64, longitude: f64) {
        write_location(&self.location, latitude, longitude);
    }

    /// The current location (`None` while unconfigured); the Python tests
    /// read `_lat`/`_lon` back this way.
    pub fn location(&self) -> Option<Location> {
        read_location(&self.location)
    }

    /// Python `_location_params`; an unset location is a `SourceError`.
    fn location_params(&self) -> Result<Vec<(&'static str, String)>, SourceError> {
        let Some(loc) = read_location(&self.location) else {
            return Err(SourceError::new("Open-Meteo: no location configured"));
        };
        Ok(vec![
            ("latitude", pyfmt::py_repr(loc.latitude)),
            ("longitude", pyfmt::py_repr(loc.longitude)),
        ])
    }

    /// Python `_get`: GET through the capped JSON reader; an object body with
    /// a truthy `error` flag is an API error carrying the `reason`.
    async fn get(
        &self,
        url: &str,
        params: &[(&'static str, String)],
    ) -> Result<Value, SourceError> {
        let data = match upstream::fetch_json_capped(&self.http, url, params).await {
            Ok(data) => data,
            Err(err) => return Err(SourceError::new(format!("Open-Meteo: {err}"))),
        };
        if !data.is_object() || data.get("error").is_some_and(upstream::py_truthy) {
            let reason = if data.is_object() {
                data.get("reason")
                    .map(upstream::py_str)
                    .unwrap_or_else(|| "None".to_string())
            } else {
                "bad payload".to_string()
            };
            return Err(SourceError::new(format!("Open-Meteo error: {reason}")));
        }
        Ok(data)
    }

    /// Multi-model forecast: 15-min precipitation + hourly model vars.
    pub async fn fetch_forecast_payload(&self) -> Result<Value, SourceError> {
        let mut params = self.location_params()?;
        params.push(("models", self.forecast_models.join(",")));
        params.push(("minutely_15", "precipitation".to_string()));
        params.push(("hourly", HOURLY_VARS.join(",")));
        // 3 days: with 2, fewer than 24 *future* hours (t > now) would
        // remain late in the UTC day, shortening the 24 h chart.
        params.push(("forecast_days", "3".to_string()));
        params.push(("timezone", "UTC".to_string()));
        let url = format!("{}/forecast", self.forecast_base);
        self.get(&url, &params).await
    }

    /// Ensemble precipitation per member (hourly), next 2 days.
    pub async fn fetch_ensemble_payload(&self) -> Result<Value, SourceError> {
        let mut params = self.location_params()?;
        params.push(("models", self.ensemble_model.clone()));
        params.push(("hourly", "precipitation".to_string()));
        params.push(("forecast_days", "2".to_string()));
        params.push(("timezone", "UTC".to_string()));
        let url = format!("{}/ensemble", self.ensemble_base);
        self.get(&url, &params).await
    }
}

#[cfg(test)]
mod tests;
