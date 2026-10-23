//! Endpoint tests for `POST /api/location`, against a real aggregator over
//! the fake upstream. A successful save spawns a background refresh, which
//! tolerates the fake's 404s.

use std::sync::Arc;

use axum::http::{HeaderMap, StatusCode};
use serde_json::Value;

use crate::aggregator::testkit::{CfgOpts, FakeUpstream};

use super::api_tests::api_state;
use super::{AppState, httptest};

fn default_body() -> &'static str {
    r#"{"latitude": 48.13749, "longitude": 11.57552, "timezone": "Europe/Berlin", "label": "München"}"#
}

/// A request to the location endpoints (the host is the default test host).
pub(super) async fn call(
    state: AppState,
    method: &str,
    uri: &str,
    body: Option<&str>,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    httptest::call(state, method, uri, "127.0.0.1:8000", body, headers).await
}

/// The response body as JSON.
pub(super) fn body_json(body: &str) -> Value {
    serde_json::from_str(body).unwrap()
}

#[tokio::test]
async fn post_location_ok_rounds_and_updates_cfg() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(
        state.clone(),
        "POST",
        "/api/location",
        Some(default_body()),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["ok"], Value::Bool(true));
    // 48.13749 -> 48.137, 11.57552 -> 11.576
    assert_eq!(
        body["location"],
        serde_json::json!({
            "latitude": 48.137,
            "longitude": 11.576,
            "timezone": "Europe/Berlin",
            "label": "München",
        })
    );
    // ... and /api/config now reports the (rounded) new location
    let (status, _headers, body) = call(state, "GET", "/api/config", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["configured"], Value::Bool(true));
    assert_eq!(body["location"]["latitude"], serde_json::json!(48.137));
}

/// a broken store makes the save fail with the plain-text 500.
#[tokio::test]
async fn post_location_store_error_is_500() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    state
        .aggregator
        .store()
        .lock_for_tests()
        .execute_batch("DROP TABLE app_meta")
        .unwrap();
    let (status, headers, body) = call(
        state,
        "POST",
        "/api/location",
        Some(default_body()),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(body, "Internal Server Error");
    assert_eq!(
        headers.get("content-type").and_then(|v| v.to_str().ok()),
        Some("text/plain; charset=utf-8")
    );
}

#[tokio::test]
async fn post_location_empty_label_defaults() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let body = r#"{"latitude": 48.13749, "longitude": 11.57552, "timezone": "Europe/Berlin", "label": ""}"#;
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/location",
        Some(body),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body_json(&body)["location"]["label"],
        Value::String(String::new())
    );
}

#[tokio::test]
async fn post_location_foreign_origin_is_403() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/location",
        Some(default_body()),
        &[
            ("content-type", "application/json"),
            ("origin", "https://evil.example"),
        ],
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "cross-site request refused"})
    );
    // the location was NOT written
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

/// `Origin: null` counts as cross-site.
#[tokio::test]
async fn post_location_null_origin_is_403() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let (status, _headers, _body) = call(
        state,
        "POST",
        "/api/location",
        Some(default_body()),
        &[("content-type", "application/json"), ("origin", "null")],
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

/// no Origin, `Sec-Fetch-Site: cross-site`.
#[tokio::test]
async fn post_location_cross_site_fetch_is_403() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let (status, _headers, _body) = call(
        state,
        "POST",
        "/api/location",
        Some(default_body()),
        &[
            ("content-type", "application/json"),
            ("sec-fetch-site", "cross-site"),
        ],
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

/// the normal same-origin request.
#[tokio::test]
async fn post_location_same_origin_headers_allowed() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, _body) = call(
        state,
        "POST",
        "/api/location",
        Some(default_body()),
        &[
            ("content-type", "application/json"),
            ("origin", "http://127.0.0.1:8000"),
            ("sec-fetch-site", "same-origin"),
        ],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
}

/// NaN is a JSON decode error (status-only compare).
#[tokio::test]
async fn post_location_nan_is_422_not_500() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let raw = r#"{"latitude": NaN, "longitude": 13.0, "timezone": "Europe/Berlin"}"#;
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/location",
        Some(raw),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let parsed = body_json(&body);
    let detail = parsed["detail"].as_array().unwrap();
    assert_ne!(detail, &[] as &[Value]);
    assert_eq!(detail[0]["loc"][0], Value::String("body".to_string()));
    // the rejected input (NaN) must not be echoed back
    assert!(!body.contains("NaN"));
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

#[tokio::test]
async fn post_location_out_of_range_is_422() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let body = r#"{"latitude": 91.0, "longitude": 11.57552, "timezone": "Europe/Berlin", "label": "München"}"#;
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/location",
        Some(body),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body_json(&body)["detail"][0]["loc"],
        serde_json::json!(["body", "latitude"])
    );
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

#[tokio::test]
async fn post_location_bad_timezone_is_422() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let body = r#"{"latitude": 48.13749, "longitude": 11.57552, "timezone": "Not/AZone", "label": "München"}"#;
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/location",
        Some(body),
        &[("content-type", "application/json")],
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body_json(&body)["detail"][0]["loc"],
        serde_json::json!(["body", "timezone"])
    );
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

/// a cross-site form posts text/plain.
#[tokio::test]
async fn post_location_text_plain_body_is_422() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let agg = Arc::clone(&state.aggregator);
    let (status, _headers, _body) = call(
        state,
        "POST",
        "/api/location",
        Some("latitude=48.137&longitude=11.576"),
        &[("content-type", "text/plain")],
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

#[tokio::test]
async fn post_location_security_headers_still_present_on_403_and_422() {
    let fake = FakeUpstream::start();
    let (status, headers, _body) = call(
        api_state(&fake, CfgOpts::default()),
        "POST",
        "/api/location",
        Some(default_body()),
        &[
            ("content-type", "application/json"),
            ("origin", "https://evil.example"),
        ],
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    httptest::assert_security_headers(&headers);
    let (status, headers, _body) = call(
        api_state(&fake, CfgOpts::default()),
        "POST",
        "/api/location",
        Some("latitude=48.137&longitude=11.576"),
        &[("content-type", "text/plain")],
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    httptest::assert_security_headers(&headers);
}
