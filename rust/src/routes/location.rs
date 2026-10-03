//! `POST /api/location` and `GET /api/geocode` (Python `app/main.py`):
//! the setup-wizard write and the address search.
//!
//! The checks run in Python's order: the body must be valid JSON in the
//! wizard shape first (pydantic runs before the handler, i.e. before the
//! origin check), then the same-origin check (CSRF), then the timezone.
//! A `StoreError` becomes the unhandled-exception answer (a plain-text
//! 500); a failed address lookup is a 502, never a 500.

use std::sync::Arc;

use axum::Json;
use axum::body::Bytes;
use axum::extract::{Query, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde_json::json;

use crate::location::{self, BodyError, UnknownTimezone};
use crate::scheduler::initial_refresh;
use crate::security::json_error;
use crate::store::StoreError;

use super::AppState;

/// `POST /api/location`: set the home location (setup wizard).
pub(crate) async fn post_location(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    // 1. validate the body first (Python's pydantic runs before the
    //    handler): an invalid body is a 422 even for a foreign origin.
    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok());
    let location_in = match location::validate_location_body(content_type, &body) {
        Ok(location_in) => location_in,
        Err(BodyError::Invalid(errors)) => {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(location::errors_json(&errors)),
            )
                .into_response();
        }
        Err(BodyError::Unparseable) => {
            return json_error(
                StatusCode::BAD_REQUEST,
                "There was an error parsing the body",
            );
        }
    };
    // 2. a foreign page may *send* a POST even without CORS (CSRF): refuse.
    if !location::same_origin(&headers) {
        return json_error(StatusCode::FORBIDDEN, "cross-site request refused");
    }
    // 3. the timezone must exist; the coordinates are rounded to 3 decimals
    //    (~100 m: enough for the 1 km radar grid).
    let loc = match location_in.into_location() {
        Ok(loc) => loc,
        Err(UnknownTimezone) => {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(json!({
                    "detail": [{ "loc": ["body", "timezone"], "msg": "unknown timezone" }]
                })),
            )
                .into_response();
        }
    };
    // 4. persist and make the location effective (a move of more than ~1 km
    //    clears the old location's data first).
    if let Err(err) = state.aggregator.set_location(loc.clone()) {
        return store_error(err);
    }
    // 5. one background refresh so data appears within seconds; the runtime
    //    owns the task, nothing to hold onto.
    let agg = Arc::clone(&state.aggregator);
    let scheduler = state.scheduler.clone();
    tokio::spawn(async move {
        initial_refresh(&agg).await;
        if let Some(scheduler) = scheduler {
            scheduler.schedule_models_retry(&agg);
        }
    });
    // 6. the saved (rounded) location.
    (
        StatusCode::OK,
        Json(json!({
            "ok": true,
            "location": location::location_payload(&loc),
        })),
    )
        .into_response()
}

/// `GET /api/geocode`: address search for the setup wizard (Nominatim).
///
/// The typed text goes to OpenStreetMap Nominatim *from the app's server*.
/// `q` is the **last** `q` value of the raw query pairs (Python's `Query`
/// takes the last of a repeated parameter); fewer than 3 or more than 200
/// characters is a 422. A failed lookup is a 502, never a 500.
pub(crate) async fn get_geocode(
    State(state): State<AppState>,
    Query(pairs): Query<Vec<(String, String)>>,
) -> Response {
    let q = pairs
        .iter()
        .rev()
        .find_map(|(key, value)| (key == "q").then_some(value.as_str()));
    let Some(q) = q else {
        return query_error("Field required");
    };
    let characters = q.chars().count();
    if characters < 3 {
        return query_error("String should have at least 3 characters");
    }
    if characters > 200 {
        return query_error("String should have at most 200 characters");
    }
    match state.geocoder.search(q).await {
        Ok(results) => (
            StatusCode::OK,
            Json(crate::geocode::search_response(&results)),
        )
            .into_response(),
        Err(err) => {
            let preview: String = q.chars().take(50).collect();
            tracing::warn!("address lookup failed for {preview:?}: {err}");
            json_error(StatusCode::BAD_GATEWAY, "address lookup failed")
        }
    }
}

/// A `StoreError` on the write path (Python: the exception escapes the
/// endpoint and the security middleware answers a plain-text 500, as on
/// the read path).
fn store_error(err: StoreError) -> Response {
    tracing::error!("saving the location failed: {err}");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        "Internal Server Error",
    )
        .into_response()
}

/// A 422 for the `q` query parameter.
fn query_error(msg: &str) -> Response {
    (
        StatusCode::UNPROCESSABLE_ENTITY,
        Json(json!({
            "detail": [{ "loc": ["query", "q"], "msg": msg }]
        })),
    )
        .into_response()
}
