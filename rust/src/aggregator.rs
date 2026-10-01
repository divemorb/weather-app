//! Scheduler-driven cache refreshes (Python `app/aggregator.py`, part 1a).
//!
//! The *decisions* (radar vote, model votes, ensemble share, weighted
//! combination) are pure functions in `crate::probability`; this module only
//! moves data: the scheduler fetches the upstream payloads into the SQLite
//! cache, and `cache_meta` / `source_status` report per-source freshness.
//! A failing source never breaks the app — the last good cache is served
//! (with its age) and the error is recorded for `/api/sources`.
//!
//! R25b adds `_record_forecast_history` and `backfill_observations` at the
//! end of `refresh_models`.

use std::collections::{HashMap, HashSet};
use std::sync::{Mutex, RwLock};

use chrono::{DateTime, TimeDelta, Utc};
use serde_json::{Map, Value, json};

use crate::brightsky::{parse_hourly_observations, parse_station_info};
use crate::clients::{BrightSkyClient, OpenMeteoClient};
use crate::config::{AppConfig, LocationConfig};
use crate::location;
use crate::openmeteo::parse_forecast;
use crate::pyfmt::py_round_int;
use crate::serializers::CacheMeta;
use crate::series::build_forecast_history_rows;
use crate::store::{Source, Store, StoreError};
use crate::times::{Clock, to_iso};
use crate::upstream::SourceError;

/// The two scheduled refresh jobs (Python's job ids and log names).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Job {
    Radar,
    Models,
}

impl Job {
    pub const ALL: [Job; 2] = [Job::Radar, Job::Models];

    /// "radar" / "models" (log texts, keys of /api/schedule)
    pub fn key(self) -> &'static str {
        match self {
            Job::Radar => "radar",
            Job::Models => "models",
        }
    }

    /// "radar_refresh" / "models_refresh" (Python's scheduler job ids)
    pub fn id(self) -> &'static str {
        match self {
            Job::Radar => "radar_refresh",
            Job::Models => "models_refresh",
        }
    }

    /// [Radar, Current] / [Forecast, Ensemble]
    pub fn sources(self) -> [Source; 2] {
        match self {
            Job::Radar => [Source::Radar, Source::Current],
            Job::Models => [Source::Forecast, Source::Ensemble],
        }
    }
}

/// The runtime state the scheduler, the routes and the background refresh
/// share (later as `Arc<Aggregator>`). Every method takes `&self`; the locks
/// are held only for a copy or a small change, never across an `.await`.
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

    /// Tests move the clock (Python monkeypatches `utcnow`).
    #[cfg(test)]
    pub fn set_clock(&self, clock: Clock) {
        *self
            .clock
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = clock;
    }

    pub fn store(&self) -> &Store {
        &self.store
    }

    pub fn brightsky(&self) -> &BrightSkyClient {
        &self.brightsky
    }

    pub fn openmeteo(&self) -> &OpenMeteoClient {
        &self.openmeteo
    }

    /// Python `apply_location` + `Aggregator.set_location` (step 8b). When
    /// the location moved more than ~1 km, all data belonging to the old
    /// location is deleted first; then the location is persisted, pushed to
    /// both clients and made effective. A first location stores without
    /// clearing. The skip flags are reset so the next refresh fetches again.
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

    // -- refresh (called by the scheduler, never per page load) ------------

    /// Python `skip_without_location`: no location configured yet -> the
    /// refresh is skipped, logged once per job; the flag is cleared by
    /// `set_location` (location deleted, step 8d).
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

    /// Python `_fetch_into_cache`: store the payload and drop the last error
    /// (log `cache refreshed: {key}`), or record the error and keep the
    /// stale cache (a warning). A `StoreError` from `put_cache` is an
    /// internal failure: it is logged and the refresh goes on (Python would
    /// abort the rest of that refresh).
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
    /// once per job) while no location is configured (8b).
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
    /// location is configured (step 8b).
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

    /// Python `_record_forecast_history`: append this hour's model
    /// forecasts to `forecast_history`. History is a nicety: every failure
    /// (a missing or unparseable cache, a database error) is logged or
    /// swallowed and never breaks the refresh.
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

    /// Python `backfill_observations`: fill `observed_mm` in
    /// `forecast_history` from DWD observations.
    ///
    /// Fetches the last 48 h of Bright Sky `/weather` hourly records and
    /// writes each real observation (`observation_type != "forecast"`) for
    /// its hour start (`timestamp - 1h`). Run from the hourly model refresh
    /// — never on a page load; failures are logged and swallowed (a
    /// failing source never breaks a refresh).
    pub async fn backfill_observations(&self) {
        let now = self.now();
        let payload = match self
            .brightsky
            .fetch_weather_payload(now - TimeDelta::hours(48), now)
            .await
        {
            Ok(payload) => payload,
            Err(err) => {
                tracing::error!("observation backfill fetch failed: {err}");
                return;
            }
        };
        let station = match parse_station_info(&payload) {
            Ok(station) => station,
            Err(err) => {
                tracing::error!("observation backfill fetch failed: {err}");
                return;
            }
        };
        if let Some((name, distance)) = station {
            tracing::info!(
                "observation backfill: station {name} ({} m away)",
                crate::pyfmt::py_repr(distance)
            );
        }
        let observations = match parse_hourly_observations(&payload, now) {
            Ok(observations) => observations,
            Err(err) => {
                tracing::error!("observation backfill fetch failed: {err}");
                return;
            }
        };
        if observations.is_empty() {
            tracing::info!("observation backfill: no observation records in the last 48 h");
            return;
        }
        for (hour_start, mm) in &observations {
            if let Err(err) = self.store.set_observation(&to_iso(*hour_start), *mm) {
                tracing::error!("observation backfill: writing observations failed: {err}");
                return;
            }
        }
        let count = observations.len();
        tracing::info!("observation backfill: {count} hourly observations written");
    }

    // -- read model (page loads) --------------------------------------------

    /// Python `Aggregator.cache_meta`: `available` / `age_seconds` / `stale`
    /// for one source. `age_seconds` is None when the source has never been
    /// fetched. Used by `source_status` and by the API endpoints that attach
    /// a data-age badge to a single source's payload.
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

    /// Python `get_source_status`: per-source `upstream` / `last_error` /
    /// `available` / `age_seconds` / `stale`, for the UI.
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

mod read;

#[cfg(test)]
pub(crate) mod testkit;

#[cfg(test)]
mod backfill_tests;

#[cfg(test)]
mod read_tests;

#[cfg(test)]
mod tests;
