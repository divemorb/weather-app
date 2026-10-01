//! Endpoint tests for `POST /api/location` and `GET /api/geocode`: ports of
//! all 14 tests in `tests/test_api_location.py`, against a real aggregator
//! over the fake upstream (Python's `FakeAgg`/`FakeGeocoder` become
//! `agg.cfg().location` and the fake's `/nom/search` answer). A successful
//! save spawns a background refresh, which tolerates the fake's 404s.

use std::sync::Arc;

use axum::body::Body;
use axum::http::{HeaderMap, Request, StatusCode};
use serde_json::Value;
use tower::ServiceExt;

use crate::aggregator::testkit::{CfgOpts, FakeResponse, FakeUpstream};

use super::api_tests::api_state;
use super::{AppState, build_router};

fn default_body() -> &'static str {
    r#"{"latitude": 48.13749, "longitude": 11.57552, "timezone": "Europe/Berlin", "label": "München"}"#
}

async fn call(
    state: AppState,
    method: &str,
    uri: &str,
    body: Option<&str>,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("host", "127.0.0.1:8000");
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

fn body_json(body: &str) -> Value {
    serde_json::from_str(body).unwrap()
}

fn assert_security_headers(headers: &HeaderMap) {
    assert_eq!(
        headers
            .get("x-content-type-options")
            .and_then(|v| v.to_str().ok()),
        Some("nosniff")
    );
    assert_eq!(
        headers
            .get("content-security-policy")
            .and_then(|v| v.to_str().ok()),
        Some(crate::security::CSP)
    );
}

/// `test_post_location_ok_rounds_and_updates_cfg`.
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
    // 48.13749 -> 48.137, 11.57552 -> 11.576 (verified rounding)
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

/// `test_post_location_empty_label_defaults`.
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

/// `test_post_location_foreign_origin_is_403`.
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

/// `test_post_location_null_origin_is_403`: `Origin: null` counts as cross-site.
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

/// `test_post_location_cross_site_fetch_is_403`: no Origin, `Sec-Fetch-Site: cross-site`.
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

/// `test_post_location_same_origin_headers_allowed`: the normal same-origin wizard request.
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

/// `test_post_location_nan_is_422_not_500`: NaN is a JSON decode error (status-only compare).
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
    assert!(!detail.is_empty());
    assert_eq!(detail[0]["loc"][0], Value::String("body".to_string()));
    // the rejected input (NaN) must not be echoed back
    assert!(!body.contains("NaN"));
    assert_eq!(agg.cfg().location, CfgOpts::default().location);
}

/// `test_post_location_out_of_range_is_422`.
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

/// `test_post_location_bad_timezone_is_422`.
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

/// `test_post_location_text_plain_body_is_422`: a cross-site form posts text/plain.
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

/// `test_post_location_security_headers_still_present_on_403_and_422`.
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
    assert_security_headers(&headers);
    let (status, headers, _body) = call(
        api_state(&fake, CfgOpts::default()),
        "POST",
        "/api/location",
        Some("latitude=48.137&longitude=11.576"),
        &[("content-type", "text/plain")],
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_security_headers(&headers);
}

/// `test_get_geocode_returns_results`: the fake geocoder is the fake's `/nom/search`.
#[tokio::test]
async fn get_geocode_returns_results() {
    let fake = FakeUpstream::start();
    fake.set(
        "/nom/search",
        FakeResponse::Json(serde_json::json!([
            {"display_name": "Marienplatz, München", "lat": 48.138, "lon": 11.577},
        ])),
    );
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(
        state,
        "GET",
        "/api/geocode?q=Marienplatz%20M%C3%BCnchen",
        None,
        &[],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body_json(&body),
        serde_json::json!({
            "results": [
                {"label": "Marienplatz, München", "latitude": 48.138, "longitude": 11.577}
            ]
        })
    );
    // the query reached the geocoder, percent-decoded
    let requests = fake.requests_to("/nom/search");
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].param("q"), Some("Marienplatz München"));
}

/// `test_get_geocode_source_error_is_502`: a failed lookup is a 502, never a 500.
#[tokio::test]
async fn get_geocode_source_error_is_502() {
    let fake = FakeUpstream::start();
    fake.set("/nom/search", FakeResponse::Status(500));
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(
        state,
        "GET",
        "/api/geocode?q=Marienplatz%20M%C3%BCnchen",
        None,
        &[],
    )
    .await;
    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "address lookup failed"})
    );
}

/// `test_get_geocode_query_too_short_is_422`: no request goes out.
#[tokio::test]
async fn get_geocode_query_too_short_is_422() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "GET", "/api/geocode?q=ab", None, &[]).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body_json(&body)["detail"][0]["loc"],
        serde_json::json!(["query", "q"])
    );
    assert!(fake.requests_to("/nom/search").is_empty());
}
