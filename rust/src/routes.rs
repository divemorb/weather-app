use std::collections::HashSet;
use std::sync::Arc;

use axum::handler::Handler;
use axum::http::StatusCode;
use axum::response::Response;
use axum::routing::{MethodRouter, any};
use axum::{Json, Router};
use serde_json::{Value, json};

#[derive(Clone)]
pub struct AppState {
    pub extra_hosts: Arc<HashSet<String>>,
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get_only(healthz))
        .fallback(not_found)
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

async fn not_found() -> Response {
    crate::security::json_error(StatusCode::NOT_FOUND, "Not Found")
}

#[cfg(test)]
mod tests;
