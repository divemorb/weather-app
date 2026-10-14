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

/// A POST route whose other methods get Python's JSON 405.
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

/// Shared HTTP helpers for the route tests: one request against a fresh
/// router, plus the security-header assertions every response must carry.
#[cfg(test)]
pub(crate) mod httptest {
    use axum::body::Body;
    use axum::http::{HeaderMap, Request, StatusCode};
    use tower::ServiceExt;

    use super::{AppState, build_router};

    /// One request (method, uri, host, optional body, extra headers) against
    /// a fresh router; the response comes back as (status, headers, body).
    pub(crate) async fn call(
        state: AppState,
        method: &str,
        uri: &str,
        host: &str,
        body: Option<&str>,
        headers: &[(&str, &str)],
    ) -> (StatusCode, HeaderMap, String) {
        let mut builder = Request::builder()
            .method(method)
            .uri(uri)
            .header("host", host);
        for (name, value) in headers.iter().copied() {
            builder = builder.header(name, value);
        }
        let bytes = body.map(str::as_bytes).unwrap_or_default().to_vec();
        let res = build_router(state)
            .oneshot(builder.body(Body::from(bytes)).unwrap())
            .await
            .unwrap();
        let status = res.status();
        let headers = res.headers().clone();
        let body = axum::body::to_bytes(res.into_body(), usize::MAX)
            .await
            .unwrap();
        (status, headers, String::from_utf8(body.to_vec()).unwrap())
    }

    /// The five security headers the middleware sets on every response.
    pub(crate) fn assert_security_headers(headers: &HeaderMap) {
        assert_eq!(
            headers
                .get("content-security-policy")
                .and_then(|v| v.to_str().ok()),
            Some(crate::security::CSP)
        );
        assert_eq!(
            headers
                .get("x-content-type-options")
                .and_then(|v| v.to_str().ok()),
            Some("nosniff")
        );
        assert_eq!(
            headers.get("referrer-policy").and_then(|v| v.to_str().ok()),
            Some("no-referrer")
        );
        assert_eq!(
            headers
                .get("cross-origin-resource-policy")
                .and_then(|v| v.to_str().ok()),
            Some("same-origin")
        );
        assert_eq!(
            headers.get("cache-control").and_then(|v| v.to_str().ok()),
            Some("no-cache")
        );
    }
}

#[cfg(test)]
mod api_tests;

#[cfg(test)]
mod location_tests;

#[cfg(test)]
mod reports_tests;

#[cfg(test)]
mod tests;
