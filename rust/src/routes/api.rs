//! The GET API endpoints (Python `app/main.py`, `api_config` … `api_schedule`).
//!
//! Every handler is thin: read from the aggregator (the read model in
//! `crate::aggregator::read`), hand the result to the matching serializer.
//! A `StoreError` becomes Python's unhandled-exception answer: a 500 with
//! the plain-text body "Internal Server Error" (the security guard adds the
//! security headers, as to every response).

use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::{Json, http::header};
use serde_json::Value;

use crate::aggregator::Aggregator;
use crate::location::location_payload;
use crate::scheduler::schedule_status;
use crate::serializers::{
    serialize_model_accuracy, serialize_models_24h, serialize_now, serialize_radar_next_hour,
    serialize_rain_probability,
};
use crate::store::{Source, StoreError};

use super::AppState;

/// A database problem on the read path (Python: the exception escapes the
/// endpoint and the security-header middleware answers a 500).
pub(crate) struct ApiError(StoreError);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        tracing::error!("request failed: {}", self.0);
        (
            StatusCode::INTERNAL_SERVER_ERROR,
            [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
            "Internal Server Error",
        )
            .into_response()
    }
}

impl From<StoreError> for ApiError {
    fn from(err: StoreError) -> Self {
        ApiError(err)
    }
}

/// `GET /api/config`: configured flag + location, radar radius, weights and
/// the compared forecast models.
pub(crate) async fn api_config(State(state): State<AppState>) -> Json<Value> {
    let cfg = state.aggregator.cfg();
    Json(serde_json::json!({
        "configured": cfg.location.is_some(),
        "location": cfg.location.as_ref().map(location_payload),
        "radar_radius_km": cfg.radar.radius_km,
        "weights": {
            "radar": cfg.probability.weight_radar,
            "models": cfg.probability.weight_models,
            "ensemble": cfg.probability.weight_ensemble,
        },
        "models": cfg.models.forecast,
    }))
}

/// `GET /api/now`: the current conditions tile plus the current-weather
/// data age.
pub(crate) async fn api_now(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let agg: &Aggregator = &state.aggregator;
    let conditions = agg.get_current_conditions()?;
    let meta = agg.cache_meta(Source::Current)?;
    Ok(Json(serialize_now(conditions.as_ref(), Some(&meta))))
}

/// `GET /api/rain-probability`: the combined % with the per-signal data age
/// (radar + models) attached.
pub(crate) async fn api_rain_probability(
    State(state): State<AppState>,
) -> Result<Json<Value>, ApiError> {
    let agg: &Aggregator = &state.aggregator;
    let rain = agg.get_rain_probability()?;
    let radar_meta = agg.cache_meta(Source::Radar)?;
    let models_meta = agg.cache_meta(Source::Forecast)?;
    Ok(Json(serialize_rain_probability(
        &rain,
        Some(&radar_meta),
        Some(&models_meta),
    )))
}

/// `GET /api/radar/next-hour`: the 12 x 5-min local-rain bar plus the radar
/// cache freshness.
pub(crate) async fn api_radar_next_hour(
    State(state): State<AppState>,
) -> Result<Json<Value>, ApiError> {
    let agg: &Aggregator = &state.aggregator;
    let bar = agg.get_radar_next_hour()?;
    let meta = agg.cache_meta(Source::Radar)?;
    Ok(Json(serialize_radar_next_hour(&bar, Some(&meta))))
}

/// `GET /api/models/24h`: hourly precipitation per model plus the forecast
/// cache freshness.
pub(crate) async fn api_models_24h(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    let agg: &Aggregator = &state.aggregator;
    let series = agg.get_24h_model_comparison()?;
    let meta = agg.cache_meta(Source::Forecast)?;
    Ok(Json(serialize_models_24h(&series, Some(&meta))))
}

/// `GET /api/model-accuracy`: per-model accuracy over the configured window
/// (an empty `models` object while nothing has been compared yet).
pub(crate) async fn api_model_accuracy(
    State(state): State<AppState>,
) -> Result<Json<Value>, ApiError> {
    let agg: &Aggregator = &state.aggregator;
    let cfg = agg.cfg();
    let models = agg.get_model_accuracy()?;
    Ok(Json(serialize_model_accuracy(
        &models,
        cfg.accuracy.window_days,
        cfg.accuracy.min_samples,
    )))
}

/// `GET /api/sources`: per-source age / staleness / last error.
pub(crate) async fn api_sources(State(state): State<AppState>) -> Result<Json<Value>, ApiError> {
    Ok(Json(state.aggregator.source_status()?))
}

/// `GET /api/schedule`: the next backend refresh per job (UI countdown).
pub(crate) async fn api_schedule(State(state): State<AppState>) -> Json<Value> {
    let cfg = state.aggregator.cfg();
    let now = state.aggregator.now();
    Json(schedule_status(state.scheduler.as_deref(), &cfg, now))
}
