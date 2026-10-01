//! The read model: page-load queries over the SQLite cache (Python
//! `app/aggregator.py`, part 2a).
//!
//! The refreshes (part 1a) do the network work; these methods read only
//! the database, so they are plain synchronous methods — an axum handler
//! (R28) can call them directly. A `StoreError` is the one error that
//! propagates (R28 turns it into a 500); everywhere Python catches a
//! `SourceError` and returns "no data" (empty cache, or a cached payload
//! that no longer parses) the Rust method does the same.

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
use crate::store::{Source, StoreError};
use crate::times::to_iso;

use super::Aggregator;

impl Aggregator {
    /// Python `_get_forecast_bundle`: the parsed cached forecast, or `None`
    /// when the cache is empty or no longer parses (a corrupted cache
    /// degrades to "no data", like every other `SourceError` on the read
    /// path). `pub(crate)` because `get_rain_probability` (R26b) shares it.
    pub(crate) fn forecast_bundle(&self) -> Result<Option<ForecastBundle>, StoreError> {
        let cfg = self.cfg();
        let now = self.now();
        let Some((payload, _age)) = self.store.get_cache(Source::Forecast, now)? else {
            return Ok(None);
        };
        Ok(parse_forecast(&payload, &cfg.models.forecast).ok())
    }

    /// Python `get_current_conditions`: the parsed cached Bright Sky
    /// `current_weather`. `feels_like_c` is filled from the forecast cache
    /// (apparent temperature of the current hour, first model with data).
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

    /// Python `get_radar_nowcast`: the cached radar parsed into 5-min
    /// frames. Radius filtering happens in the probability logic (cells
    /// carry full-grid coordinates; the nowcast carries bbox + location).
    pub fn get_radar_nowcast(&self) -> Result<Option<RadarNowcast>, StoreError> {
        let now = self.now();
        let Some((payload, _age)) = self.store.get_cache(Source::Radar, now)? else {
            return Ok(None);
        };
        Ok(parse_radar(&payload).ok())
    }

    /// Python `get_radar_next_hour`: 12 x 5-min local-rain bar for the
    /// next hour (radar nowcast). Radius filtering + the rain threshold
    /// come from the config, so the bar and the radar vote agree on
    /// "local rain".
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

    /// Python `get_model_votes`: each configured model's next-60-min
    /// precipitation (minutely_15).
    pub fn get_model_votes(&self) -> Result<Vec<ModelVote>, StoreError> {
        let bundle = self.forecast_bundle()?;
        Ok(model_votes(bundle.as_ref(), self.now()))
    }

    /// Python `get_ensemble_vote`: share of ensemble members with >
    /// threshold mm in the next hour. No cache or an unparseable cache
    /// give a `None` probability with no members.
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

    /// Python `get_rain_probability`: weighted combination of the radar /
    /// model / ensemble signals (README "How the rain probability is
    /// calculated"). With `use_accuracy_weights` the model signal is
    /// weighted per model by event accuracy (step 6g, with equal-weight
    /// fallback). Always returns a `RainProbability` (0 % + "no data" when
    /// every signal is missing) so the UI degrades gracefully.
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
            // step 6g: the pure function gates internally — insufficient
            // samples or a failing accuracy read ({} below) both fall back
            // to equal weights.
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
        })
    }

    /// Python `get_24h_model_comparison`: hourly precipitation per model
    /// for the next 24 h (chart data). The window is relative to *now*
    /// (first hour = current hour), not the UTC calendar day.
    pub fn get_24h_model_comparison(&self) -> Result<Series24h, StoreError> {
        let bundle = self.forecast_bundle()?;
        Ok(build_24h_series(bundle.as_ref(), self.now(), 24))
    }

    /// Python `get_model_accuracy`: per-model accuracy over the configured
    /// window (step 6e). Compares stored forecasts against the observed
    /// rain of the same hour — the same `> model_rain_threshold_mm` event
    /// the next-hour vote uses. Only moves data: raw rows come from the
    /// store, the math is the pure `model_accuracy`. Returns `{}` while
    /// nothing has been compared yet.
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
}

/// Python `_first_hour_apparent`: feels-like = the apparent temperature of
/// the current hour, from the first model with hourly data. When the
/// current hour is not on the axis, that model's first value is used (even
/// if it is null — the loop stops at the first usable model, as Python's
/// does).
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
