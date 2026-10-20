//! Scheduler-driven cache refreshes: the scheduler fetches upstream payloads
//! into the SQLite cache; the decisions are pure functions in `crate::probability`.
//! A failing source never breaks the app: the last good cache is served with
//! its age, and the error is recorded for `/api/sources`.

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, RwLock};

use chrono::{DateTime, Utc};
use serde_json::{Map, Value, json};

use crate::clients::{BrightSkyClient, OpenMeteoClient};
use crate::config::{AppConfig, LocationConfig};
use crate::location;
use crate::openmeteo::parse_forecast;
use crate::pyfmt::py_round_int;
use crate::serializers::CacheMeta;
use crate::series::build_forecast_history_rows;
use crate::store::{Source, Store, StoreError};
use crate::times::Clock;
use crate::upstream::SourceError;

/// The two scheduled refresh jobs.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Job {
    Radar,
    Models,
}

impl Job {
    /// Both jobs, in refresh order.
    pub const ALL: [Self; 2] = [Self::Radar, Self::Models];

    /// "radar" / "models" (log texts, keys of /api/schedule)
    pub fn key(self) -> &'static str {
        match self {
            Self::Radar => "radar",
            Self::Models => "models",
        }
    }

    /// [Radar, Current] / [Forecast, Ensemble]
    pub fn sources(self) -> [Source; 2] {
        match self {
            Self::Radar => [Source::Radar, Source::Current],
            Self::Models => [Source::Forecast, Source::Ensemble],
        }
    }
}

/// The runtime state shared by the scheduler, the routes and the
/// background refresh. Every method takes `&self`; the locks are held only
/// for a copy or a small change, never across an `.await`.
pub struct Aggregator {
    cfg: RwLock<AppConfig>,
    store: Store,
    brightsky: BrightSkyClient,
    openmeteo: OpenMeteoClient,
    clock: Mutex<Clock>,
    last_error: Mutex<HashMap<Source, String>>,
    skips_logged: Mutex<HashSet<Job>>,
}

impl Aggregator {
    /// Build the aggregator from the loaded config and store.
    pub fn new(
        cfg: AppConfig,
        store: Store,
        brightsky: BrightSkyClient,
        openmeteo: OpenMeteoClient,
        clock: Clock,
    ) -> Self {
        Self {
            cfg: RwLock::new(cfg),
            store,
            brightsky,
            openmeteo,
            clock: Mutex::new(clock),
            last_error: Mutex::new(HashMap::new()),
            skips_logged: Mutex::new(HashSet::new()),
        }
    }

    /// A copy of the effective config (its `location` tracks the database).
    pub fn cfg(&self) -> AppConfig {
        self.cfg
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// The app's "now" (the clock may be fixed by `WETTER_FAKE_NOW` or tests).
    pub fn now(&self) -> DateTime<Utc> {
        self.clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .now()
    }

    /// Tests move the clock.
    #[cfg(test)]
    pub fn set_clock(&self, clock: Clock) {
        *self
            .clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = clock;
    }

    /// The SQLite cache (read model, `/api/sources`).
    pub fn store(&self) -> &Store {
        &self.store
    }

    /// The Bright Sky client.
    pub fn brightsky(&self) -> &BrightSkyClient {
        &self.brightsky
    }

    /// The Open-Meteo client.
    pub fn openmeteo(&self) -> &OpenMeteoClient {
        &self.openmeteo
    }

    /// When the location moved more than ~1 km, all data for the old
    /// location is deleted first. Then the location is persisted and pushed
    /// to both clients. A first location stores without clearing. The skip
    /// flags are reset so the next refresh fetches again.
    pub fn set_location(&self, loc: LocationConfig) -> Result<(), StoreError> {
        if location::moved(self.cfg().location.as_ref(), &loc) {
            self.store.clear_location_data()?;
        }
        self.store
            .set_meta(location::LOCATION_KEY, &location::location_to_json(&loc))?;
        self.brightsky.set_location(loc.latitude, loc.longitude);
        self.openmeteo.set_location(loc.latitude, loc.longitude);
        self.cfg
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .location = Some(loc);
        self.skips_logged
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clear();
        Ok(())
    }

    // -- refresh (called by the scheduler, never per page load) --

    /// No location configured yet -> the refresh is skipped, logged once
    /// per job; the flag is cleared by `set_location`.
    fn skip_without_location(&self, job: Job) -> bool {
        let has_location = self.cfg().location.is_some();
        let mut skips = self
            .skips_logged
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if has_location {
            skips.remove(&job);
            return false;
        }
        if skips.insert(job) {
            tracing::info!("no location configured yet; skipping {} refresh", job.key());
            true
        } else {
            false
        }
    }

    /// Whether the last models refresh failed for the forecast or the
    /// ensemble.
    pub fn models_failed(&self) -> bool {
        let errors = self
            .last_error
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        errors.contains_key(&Source::Forecast) || errors.contains_key(&Source::Ensemble)
    }

    /// Store the payload and drop the last error, or record the error and
    /// keep the stale cache. A `StoreError` from `put_cache` is an internal
    /// failure: it is logged and the refresh goes on.
    fn store_fetched(&self, source: Source, fetched: Result<Value, SourceError>) {
        let key = source.key();
        match fetched {
            Ok(payload) => {
                if let Err(err) = self.store.put_cache(source, &payload, self.now()) {
                    tracing::warn!("storing the {key} cache failed: {err}");
                }
                self.last_error
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .remove(&source);
                tracing::info!("cache refreshed: {key}");
            }
            Err(err) => {
                self.last_error
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .insert(source, err.to_string());
                tracing::warn!("refresh {key} failed (keeping stale cache): {err}");
            }
        }
    }

    /// Fetch Bright Sky `current_weather` + radar into the cache. Each
    /// endpoint is fetched independently so one failure does not discard the
    /// other; failures keep the stale cache and are recorded. No-op (logged
    /// once per job) while no location is configured.
    pub async fn refresh_radar(&self) {
        if self.skip_without_location(Job::Radar) {
            return;
        }
        let current = self.brightsky.fetch_current_payload().await;
        self.store_fetched(Source::Current, current);
        let radar = self.brightsky.fetch_radar_payload(self.now()).await;
        self.store_fetched(Source::Radar, radar);
    }

    /// Fetch Open-Meteo forecast + ensemble into the cache (failures keep
    /// the stale cache and are recorded). No-op (logged once) while no
    /// location is configured.
    pub async fn refresh_models(&self) {
        if self.skip_without_location(Job::Models) {
            return;
        }
        let forecast = self.openmeteo.fetch_forecast_payload().await;
        self.store_fetched(Source::Forecast, forecast);
        let ensemble = self.openmeteo.fetch_ensemble_payload().await;
        self.store_fetched(Source::Ensemble, ensemble);
        self.record_forecast_history();
        self.backfill_observations().await;
    }

    /// Append this hour's model forecasts to `forecast_history`. History
    /// is a nicety: every failure (a missing or unparseable cache, a
    /// database error) is logged or swallowed and never breaks the refresh.
    fn record_forecast_history(&self) {
        let now = self.now();
        let cached = match self.store.get_cache(Source::Forecast, now) {
            Ok(cached) => cached,
            Err(err) => {
                tracing::warn!("reading the forecast cache failed: {err}");
                return;
            }
        };
        let Some((payload, _age)) = cached else {
            return; // no cached forecast: nothing to record
        };
        let Ok(bundle) = parse_forecast(&payload, &self.cfg().models.forecast) else {
            return;
        };
        if let Err(err) = self
            .store
            .add_forecasts(&build_forecast_history_rows(&bundle, now, 24))
        {
            tracing::error!("storing forecast history failed: {err}");
        }
    }

    // -- read model (page loads) --

    /// `available` / `age_seconds` / `stale` for one source. `age_seconds`
    /// is None when the source has never been fetched.
    #[expect(
        clippy::cast_precision_loss,
        reason = "stale minutes from config times 60, far below 2^52"
    )]
    /// `available` / `age_seconds` / `stale` for one source. `age_seconds`
    /// is None when the source has never been fetched.
    pub fn cache_meta(&self, source: Source) -> Result<CacheMeta, StoreError> {
        let cfg = self.cfg();
        let age = self
            .store
            .get_cache(source, self.now())?
            .map(|(_, age)| age);
        let stale_minutes = match source {
            Source::Radar | Source::Current => cfg.scheduling.stale_radar_minutes,
            Source::Forecast | Source::Ensemble => cfg.scheduling.stale_models_minutes,
        };
        Ok(CacheMeta {
            available: age.is_some(),
            age_seconds: age.map(py_round_int),
            stale: age.is_none_or(|a| a > stale_minutes.saturating_mul(60) as f64),
        })
    }

    /// Per-source `upstream` / `last_error` / `available` / `age_seconds` /
    /// `stale`, for the UI.
    pub fn source_status(&self) -> Result<Value, StoreError> {
        let last_error = self
            .last_error
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone();
        let mut out = Map::new();
        for source in Source::ALL {
            let meta = self.cache_meta(source)?;
            out.insert(
                source.key().to_string(),
                json!({
                    "upstream": source.upstream(),
                    "last_error": last_error.get(&source),
                    "available": meta.available,
                    "age_seconds": meta.age_seconds,
                    "stale": meta.stale,
                }),
            );
        }
        Ok(Value::Object(out))
    }
}

mod backfill;
mod read;

#[cfg(test)]
pub(crate) mod testkit;

#[cfg(test)]
mod backfill_tests;

#[cfg(test)]
mod rain_tests;

#[cfg(test)]
mod read_tests;

#[cfg(test)]
mod tests;
