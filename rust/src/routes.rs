use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use axum::extract::State;
use axum::handler::Handler;
use axum::http::StatusCode;
use axum::response::Response;
use axum::routing::{MethodRouter, any};
use axum::{Json, Router};
use serde_json::{Value, json};

#[derive(Clone)]
pub struct AppState {
    pub extra_hosts: Arc<HashSet<String>>,
    pub static_files: Arc<HashMap<String, crate::static_files::StaticFile>>,
    pub aggregator: Arc<crate::aggregator::Aggregator>,
    /// None when no scheduler runs (tests; Python: no `app.state.scheduler`).
    pub scheduler: Option<Arc<crate::scheduler::Scheduler>>,
    pub geocoder: Arc<crate::geocode::Geocoder>,
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get_only(healthz))
        .route("/api/config", get_only(api::api_config))
        .route("/api/now", get_only(api::api_now))
        .route("/api/rain-probability", get_only(api::api_rain_probability))
        .route("/api/radar/next-hour", get_only(api::api_radar_next_hour))
        .route("/api/models/24h", get_only(api::api_models_24h))
        .route("/api/model-accuracy", get_only(api::api_model_accuracy))
        .route("/api/sources", get_only(api::api_sources))
        .route("/api/schedule", get_only(api::api_schedule))
        .fallback(fallback)
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            crate::security::guard,
        ))
        .with_state(state)
}

/// A GET route whose other methods get Python's JSON 405. Built from
/// `any(...)` because axum adds an `Allow` header to its own 405s (the
/// Python app sends none), and `any` routes skip that.
pub fn get_only<H, T>(handler: H) -> MethodRouter<AppState>
where
    H: Handler<T, AppState>,
    T: 'static,
{
    any(method_not_allowed).get(handler)
}

/// Same for POST routes (used later for POST /api/location).
pub fn post_only<H, T>(handler: H) -> MethodRouter<AppState>
where
    H: Handler<T, AppState>,
    T: 'static,
{
    any(method_not_allowed).post(handler)
}

async fn method_not_allowed() -> Response {
    crate::security::json_error(StatusCode::METHOD_NOT_ALLOWED, "Method Not Allowed")
}

async fn healthz() -> Json<Value> {
    Json(json!({"status": "ok"}))
}

async fn fallback(
    State(state): State<AppState>,
    method: axum::http::Method,
    uri: axum::http::Uri,
    headers: axum::http::HeaderMap,
) -> Response {
    crate::static_files::respond(&state.static_files, &method, &uri, &headers)
}

mod api;

#[cfg(test)]
mod api_tests;

#[cfg(test)]
mod tests;
