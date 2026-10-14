//! `POST /api/reports`, `GET /api/reports/current` and
//! `DELETE /api/reports/{id}` (Python `app/main.py`): the user reports what
//! the sky really looks like — or confirms the page when it is right.
//!
//! The checks run in Python's order: the body (or the path id) is validated
//! first (pydantic runs before the handler, i.e. before the origin check),
//! then the same-origin check (CSRF), then (POST only) a location must be
//! configured. The *server's* clock sets the observation time. A
//! `StoreError` becomes the unhandled-exception answer (a plain-text 500,
//! as in `routes/location.rs`).

use axum::Json;
use axum::body::Bytes;
use axum::extract::{Path, State};
use axum::http::{HeaderMap, StatusCode, header};
use axum::response::{IntoResponse, Response};
use chrono::TimeDelta;
use serde_json::json;

use crate::location;
use crate::reports::{self, Intensity};
use crate::security::json_error;
use crate::store::StoreError;
use crate::times;

use super::AppState;

/// A report is *fresh* (the current one) while observed within these
/// minutes (Python `reports.FRESH_MINUTES`), both ends inclusive.
const FRESH_MINUTES: i64 = 30;
/// At most this many reports are kept (Python `reports.MAX_REPORTS`).
const MAX_REPORTS: i64 = 500;

/// `POST /api/reports`: store what the sky really looks like.
pub(crate) async fn post_report(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    // 1. validate the body first (Python's pydantic runs before the
    //    handler): an invalid body is a 422 even for a foreign origin.
    let content_type = headers
        .get(header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok());
    let report_in = match reports::parse_report_body(content_type, &body) {
        Ok(report_in) => report_in,
        Err(reports::ReportBodyError::Invalid(errors)) => {
            return (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(reports::errors_json(&errors)),
            )
                .into_response();
        }
        Err(reports::ReportBodyError::Unparseable) => {
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
    // 3. the reports compare against a location's forecast: without one
    //    there is nothing to report about.
    let cfg = state.aggregator.cfg();
    if cfg.location.is_none() {
        return json_error(StatusCode::CONFLICT, "no location configured");
    }
    // 4. the server's clock sets the observation time (one `now` for both
    //    the new row and the prune, as in Python's `save_report`).
    let now = state.aggregator.now();
    let observed_at = times::to_iso(now - TimeDelta::minutes(report_in.minutes_ago().minutes()));
    let store = state.aggregator.store();
    let id = match store.add_report(
        report_in.kind(),
        report_in.intensity(),
        report_in.confirms(),
        &observed_at,
    ) {
        Ok(id) => id,
        Err(err) => return store_error(&err),
    };
    // 5. every save prunes: older than the accuracy window, then all but
    //    the newest MAX_REPORTS.
    let window_cut = times::to_iso(now - TimeDelta::days(cfg.accuracy.window_days));
    if let Err(err) = store.prune_reports(&window_cut, MAX_REPORTS) {
        return store_error(&err);
    }
    (
        StatusCode::CREATED,
        Json(json!({
            "report": {
                "id": id,
                "kind": report_in.kind().as_str(),
                "intensity": report_in.intensity().map(Intensity::as_str),
                "confirms": report_in.confirms(),
                "observed_at": observed_at,
            }
        })),
    )
        .into_response()
}

/// `GET /api/reports/current`: the fresh report, `null` when there is none.
pub(crate) async fn current_report(State(state): State<AppState>) -> Response {
    let now = state.aggregator.now();
    let row = match state.aggregator.store().newest_report(&times::to_iso(now)) {
        Ok(row) => row,
        Err(err) => return store_error(&err),
    };
    // The newest report decides; it is current while observed within the
    // last FRESH_MINUTES minutes (both ends inclusive — `newest_report`
    // already excludes anything after `now`).
    let fresh_until = times::to_iso(now - TimeDelta::minutes(FRESH_MINUTES));
    let report = match row {
        Some(row) if (row.observed_at >= fresh_until) => row,
        _ => {
            return (StatusCode::OK, Json(json!({ "report": null }))).into_response();
        }
    };
    (
        StatusCode::OK,
        Json(json!({
            "report": {
                "id": report.id,
                "kind": report.kind,
                "intensity": report.intensity,
                "confirms": report.confirms,
                "observed_at": report.observed_at,
            }
        })),
    )
        .into_response()
}

/// `DELETE /api/reports/{report_id}`: undo a report.
pub(crate) async fn delete_report(
    State(state): State<AppState>,
    headers: HeaderMap,
    Path(raw): Path<String>,
) -> Response {
    delete_report_inner(&state, &raw, &headers)
}

/// `DELETE /api/reports/current`: Python answers this from the id route
/// (`"current"` fails the id pattern), so it is the id's 422.
pub(crate) async fn delete_current(State(state): State<AppState>, headers: HeaderMap) -> Response {
    delete_report_inner(&state, "current", &headers)
}

fn delete_report_inner(state: &AppState, raw: &str, headers: &HeaderMap) -> Response {
    // 1. the id is validated first (Python's `Path(pattern=...)` runs
    //    before the handler): anything but `^[1-9][0-9]{0,17}$` is a 422.
    let Some(id) = reports::parse_report_id(raw) else {
        return (
            StatusCode::UNPROCESSABLE_ENTITY,
            Json(json!({
                "detail": [{
                    "loc": ["path", "report_id"],
                    "msg": "String should match pattern '^[1-9][0-9]{0,17}$'",
                }]
            })),
        )
            .into_response();
    };
    // 2. a foreign page may *send* a DELETE even without CORS (CSRF):
    //    refuse.
    if !location::same_origin(headers) {
        return json_error(StatusCode::FORBIDDEN, "cross-site request refused");
    }
    // 3. undo it (a missing id is a 404, not an error).
    match state.aggregator.store().delete_report(id) {
        Ok(true) => (StatusCode::OK, Json(json!({ "deleted": id }))).into_response(),
        Ok(false) => json_error(StatusCode::NOT_FOUND, "report not found"),
        Err(err) => store_error(&err),
    }
}

/// A `StoreError` on the report paths (Python: the exception escapes the
/// endpoint and the security middleware answers a plain-text 500, as in
/// `routes/location.rs`).
fn store_error(err: &StoreError) -> Response {
    tracing::error!("the user report write failed: {err}");
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        "Internal Server Error",
    )
        .into_response()
}
