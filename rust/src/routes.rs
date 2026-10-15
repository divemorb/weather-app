use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use axum::extract::State;
use axum::handler::Handler;
use axum::http::StatusCode;
use axum::response::Response;
use axum::routing::{MethodRouter, any};
use axum::{Json, Router};
use serde_json::{Value, json};

/// Shared state handed to every route handler.
#[derive(Clone)]
pub struct AppState {
    pub extra_hosts: Arc<HashSet<String>>,
    pub static_files: Arc<HashMap<String, crate::static_files::StaticFile>>,
    pub aggregator: Arc<crate::aggregator::Aggregator>,
    /// None when no scheduler runs (tests).
    pub scheduler: Option<Arc<crate::scheduler::Scheduler>>,
    pub geocoder: Arc<crate::geocode::Geocoder>,
}

/// Build the router with all API routes and the security middleware.
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
        .route("/api/geocode", get_only(location::get_geocode))
        .route("/api/location", post_only(location::post_location))
        .route(
            "/api/reports",
            any(method_not_allowed)
                .post(reports::post_report)
                .get(fallback),
        )
        .route(
            "/api/reports/current",
            any(method_not_allowed)
                .get(reports::current_report)
                .delete(reports::delete_current),
        )
        .route(
            "/api/reports/{report_id}",
            any(method_not_allowed)
                .delete(reports::delete_report)
                .get(fallback),
        )
        .fallback(fallback)
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            crate::security::guard,
        ))
        .with_state(state)
}

/// A GET route whose other methods get the plain JSON 405. Built from
/// `any(...)` because axum adds an `Allow` header to its own 405s (the
/// API sends none), and `any` routes skip that.
pub fn get_only<H, T>(handler: H) -> MethodRouter<AppState>
where
    H: Handler<T, AppState>,
    T: 'static,
{
    any(method_not_allowed).get(handler)
}

/// A POST route whose other methods get the plain JSON 405.
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
mod location;
mod reports;

/// Shared HTTP helpers for the route tests.
#[cfg(test)]
pub(crate) mod httptest;

#[cfg(test)]
mod api_tests;

#[cfg(test)]
mod location_tests;

#[cfg(test)]
mod reports_tests;

#[cfg(test)]
mod tests;
