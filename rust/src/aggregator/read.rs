//! The read model: page-load queries over the SQLite cache (Python
//! `app/aggregator.py`).
//!
//! These methods read only the database, so they are plain synchronous
//! methods. A `StoreError` is the one error that propagates (the routes
//! turn it into a 500); an empty cache, or a cached payload that no longer
//! parses, degrades to "no data".

use std::collections::BTreeMap;

use chrono::{DateTime, TimeDelta, Utc};

use crate::accuracy::{ModelAccuracy, model_accuracy};
use crate::brightsky::parse_current_weather;
use crate::models::{
    CurrentConditions, EnsembleVote, ForecastBundle, ModelVote, RadarNowcast, RainProbability,
};
use crate::openmeteo::{parse_ensemble, parse_forecast};
use crate::probability::{
    build_explanation, combine_signals, ensemble_vote, model_rain_signal, model_votes,
    radar_rain_signal, weighted_model_signal,
};
use crate::pyfmt::py_round;
use crate::radar::parse_radar;
use crate::series::{RadarBar, Series24h, build_24h_series, build_radar_next_hour_bar};
use crate::stations::{
    FallbackEntry, OBSERVATION_STATIONS_KEY, ObsStation, Station, station_and_fallback,
    stations_from_json,
};
use crate::store::{Source, StoreError};
use crate::times::to_iso;

use super::Aggregator;

impl Aggregator {
    /// The parsed cached forecast, or `None` when the cache is empty or no
    /// longer parses (a corrupted cache degrades to "no data").
    pub(crate) fn forecast_bundle(&self) -> Result<Option<ForecastBundle>, StoreError> {
        let cfg = self.cfg();
        let now = self.now();
        let Some((payload, _age)) = self.store.get_cache(Source::Forecast, now)? else {
            return Ok(None);
        };
        Ok(parse_forecast(&payload, &cfg.models.forecast).ok())
    }

    /// The parsed cached Bright Sky `current_weather`. `feels_like_c` is
    /// filled from the forecast cache (apparent temperature of the current
    /// hour, first model with data).
    pub fn get_current_conditions(&self) -> Result<Option<CurrentConditions>, StoreError> {
        let now = self.now();
        let Some((payload, _age)) = self.store.get_cache(Source::Current, now)? else {
            return Ok(None);
        };
        let Ok(mut cond) = parse_current_weather(&payload) else {
            return Ok(None);
        };
        let bundle = self.forecast_bundle()?;
        cond.feels_like_c = first_hour_apparent(bundle.as_ref(), now);
        Ok(Some(cond))
    }

    /// The station the cached `current_weather` values come from and, per
    /// value, the station Bright Sky took it from instead (None / `{}`
    /// while nothing is cached or nothing is listed).
    pub fn current_station_and_fallback(
        &self,
    ) -> Result<(Option<Station>, BTreeMap<String, FallbackEntry>), StoreError> {
        let Some((payload, _age)) = self.store.get_cache(Source::Current, self.now())? else {
            return Ok((None, BTreeMap::new()));
        };
        Ok(station_and_fallback(&payload))
    }

    /// The cached radar parsed into 5-min frames. Radius filtering happens
    /// in the probability logic (cells carry full-grid coordinates; the
    /// nowcast carries bbox + location).
    pub fn get_radar_nowcast(&self) -> Result<Option<RadarNowcast>, StoreError> {
        let now = self.now();
        let Some((payload, _age)) = self.store.get_cache(Source::Radar, now)? else {
            return Ok(None);
        };
        Ok(parse_radar(&payload).ok())
    }

    /// 12 x 5-min local-rain bar for the next hour (radar nowcast). Radius
    /// filtering + the rain threshold come from the config, so the bar and
    /// the radar vote agree on "local rain".
    pub fn get_radar_next_hour(&self) -> Result<RadarBar, StoreError> {
        let cfg = self.cfg();
        let nowcast = self.get_radar_nowcast()?;
        Ok(build_radar_next_hour_bar(
            nowcast.as_ref(),
            self.now(),
            cfg.radar.radius_km,
            cfg.radar.grid_size_km,
            cfg.probability.radar_cell_rain_threshold_mm,
            12,
        ))
    }

    /// Each configured model's next-60-min precipitation (minutely_15).
    pub fn get_model_votes(&self) -> Result<Vec<ModelVote>, StoreError> {
        let bundle = self.forecast_bundle()?;
        Ok(model_votes(bundle.as_ref(), self.now()))
    }

    /// Share of ensemble members with > threshold mm in the next hour. No
    /// cache or an unparseable cache give a `None` probability with no
    /// members.
    pub fn get_ensemble_vote(&self) -> Result<EnsembleVote, StoreError> {
        let cfg = self.cfg();
        let now = self.now();
        let data = match self.store.get_cache(Source::Ensemble, now)? {
            Some((payload, _age)) => parse_ensemble(&payload).ok(),
            None => None,
        };
        Ok(ensemble_vote(
            data.as_ref(),
            cfg.probability.model_rain_threshold_mm,
            now,
        ))
    }

    /// Weighted combination of the radar / model / ensemble signals (README
    /// "How the rain probability is calculated"). With `use_accuracy_weights`
    /// the model signal is weighted per model by event accuracy (with
    /// equal-weight fallback). Always returns a `RainProbability` (0 % +
    /// "no data" when every signal is missing).
    pub fn get_rain_probability(&self) -> Result<RainProbability, StoreError> {
        let cfg = self.cfg();
        let now = self.now();
        let nowcast = self.get_radar_nowcast()?;
        let votes = self.get_model_votes()?;
        let evote = self.get_ensemble_vote()?;

        let (radar_available, radar_raining) = radar_rain_signal(
            nowcast.as_ref(),
            now,
            &cfg.radar,
            &cfg.probability,
            TimeDelta::hours(1),
        );
        let (model_pct, n_rain, n_total, accuracy_weighted) = if cfg.use_accuracy_weights {
            // The pure function gates internally — insufficient samples or
            // a failing accuracy read ({} below) both fall back to equal
            // weights.
            let accuracy = match self.get_model_accuracy() {
                Ok(accuracy) => accuracy,
                Err(err) => {
                    tracing::error!("model accuracy read failed; using equal weights: {err}");
                    BTreeMap::new()
                }
            };
            weighted_model_signal(
                &votes,
                &accuracy,
                cfg.probability.model_rain_threshold_mm,
                cfg.accuracy.min_samples,
            )
        } else {
            let (model_pct, n_rain, n_total) =
                model_rain_signal(&votes, cfg.probability.model_rain_threshold_mm);
            (model_pct, n_rain, n_total, false)
        };
        let (prob, weights_used) = combine_signals(
            &cfg.probability,
            radar_available,
            radar_raining,
            model_pct,
            evote.probability_pct,
        );
        let explanation = if weights_used.is_empty() {
            "No data available yet (all sources empty or failing)".to_string()
        } else {
            build_explanation(
                radar_available,
                radar_raining,
                n_rain,
                n_total,
                evote.probability_pct,
                cfg.probability.model_rain_threshold_mm,
                accuracy_weighted,
            )
        };
        Ok(RainProbability {
            probability_pct: py_round(prob, 1),
            radar_available,
            radar_raining,
            models_rain_count: n_rain,
            models_total: n_total,
            ensemble_pct: evote.probability_pct.map(|p| py_round(p, 1)),
            weights_used,
            explanation,
            accuracy_weighted,
        })
    }

    /// Hourly precipitation per model for the next 24 h (chart data). The
    /// window is relative to *now* (first hour = current hour), not the UTC
    /// calendar day.
    pub fn get_24h_model_comparison(&self) -> Result<Series24h, StoreError> {
        let bundle = self.forecast_bundle()?;
        Ok(build_24h_series(bundle.as_ref(), self.now(), 24))
    }

    /// Per-model accuracy over the configured window. Compares stored
    /// forecasts against the observed rain of the same hour — the same
    /// `> model_rain_threshold_mm` event the next-hour vote uses. Returns
    /// `{}` while nothing has been compared yet.
    pub fn get_model_accuracy(&self) -> Result<BTreeMap<String, ModelAccuracy>, StoreError> {
        let cfg = self.cfg();
        let now = self.now();
        let since = to_iso(now - TimeDelta::days(cfg.accuracy.window_days));
        let rows = self.store.compared_forecasts(&since)?;
        Ok(model_accuracy(
            &rows,
            cfg.probability.model_rain_threshold_mm,
        ))
    }

    /// The observation stations of the last backfill, `[]` when none is
    /// stored or the stored value is broken (a broken value must not break
    /// the page).
    pub fn get_observation_stations(&self) -> Result<Vec<ObsStation>, StoreError> {
        let stored = self.store.get_meta(OBSERVATION_STATIONS_KEY)?;
        Ok(stations_from_json(stored.as_deref()))
    }
}

/// Feels-like = the apparent temperature of the current hour, from the
/// first model with hourly data. When the current hour is not on the axis,
/// that model's first value is used (even if it is null — the loop stops
/// at the first usable model).
fn first_hour_apparent(bundle: Option<&ForecastBundle>, now: DateTime<Utc>) -> Option<f64> {
    let bundle = bundle?;
    for m in &bundle.models {
        if m.hourly_time.is_empty() || m.hourly_apparent_c.is_empty() {
            continue;
        }
        for (t, v) in m.hourly_time.iter().zip(&m.hourly_apparent_c) {
            if let Some(value) = *v
                && *t <= now
                && now < *t + TimeDelta::hours(1)
            {
                return Some(value);
            }
        }
        return m.hourly_apparent_c.first().copied().flatten();
    }
    None
}
