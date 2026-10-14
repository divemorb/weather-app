//! Tests for the GET API endpoints, against a real aggregator over the
//! fake upstream.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use axum::http::{HeaderMap, StatusCode};
use chrono::TimeDelta;
use serde_json::Value;

use crate::aggregator::{
    Job,
    testkit::{self, CfgOpts},
};
use crate::geocode::Geocoder;
use crate::scheduler::Scheduler;
use crate::store::Source;
use crate::testutil::fake_upstream::FakeUpstream;
use crate::times;

use super::{AppState, httptest};

/// The test `AppState`: a real aggregator (empty cache) over the fake
/// upstream, no scheduler, the geocoder pointed at the fake, no static
/// files.
pub(crate) fn api_state(fake: &FakeUpstream, opts: CfgOpts) -> AppState {
    let cfg = testkit::make_cfg(fake, opts);
    let geocoder = Arc::new(Geocoder::new(
        &cfg.api.nominatim_base_url,
        crate::upstream::http_client(5.0).expect("the http client builds"),
    ));
    let store = testkit::memory_store();
    let aggregator = Arc::new(testkit::make_aggregator(cfg, store));
    AppState {
        extra_hosts: Arc::new(HashSet::new()),
        static_files: Arc::new(HashMap::new()),
        aggregator,
        scheduler: None,
        geocoder,
    }
}

/// `api_state` with the default config: the setup of most of these tests.
fn default_state() -> AppState {
    api_state(&FakeUpstream::start(), CfgOpts::default())
}

/// A GET request to the API (the host is the default test host, no body).
async fn call(
    state: AppState,
    uri: &str,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    httptest::call(state, "GET", uri, "127.0.0.1:8000", None, headers).await
}

fn body_json(body: &str) -> Value {
    serde_json::from_str(body).unwrap()
}

/// A GET that must answer 200 with a JSON body; returns the parsed body.
async fn get_json(state: AppState, uri: &str) -> Value {
    let (status, _headers, body) = call(state, uri, &[]).await;
    assert_eq!(status, StatusCode::OK);
    body_json(&body)
}

/// All five security headers.
fn assert_security_headers(headers: &HeaderMap) {
    httptest::assert_security_headers(headers);
}

#[tokio::test]
async fn api_config() {
    let state = default_state();
    let cfg = state.aggregator.cfg();
    let body = get_json(state, "/api/config").await;
    assert_eq!(body["configured"], Value::Bool(true));
    let location = cfg.location.as_ref().unwrap();
    assert_eq!(
        body["location"]["latitude"],
        serde_json::json!(location.latitude)
    );
    assert_eq!(
        body["location"]["longitude"],
        serde_json::json!(location.longitude)
    );
    assert_eq!(
        body["location"]["timezone"],
        serde_json::json!(location.timezone)
    );
    assert_eq!(
        body["radar_radius_km"],
        serde_json::json!(cfg.radar.radius_km)
    );
    assert_eq!(
        body["weights"]["radar"],
        serde_json::json!(cfg.probability.weight_radar)
    );
    assert_eq!(
        body["weights"]["models"],
        serde_json::json!(cfg.probability.weight_models)
    );
    assert_eq!(
        body["weights"]["ensemble"],
        serde_json::json!(cfg.probability.weight_ensemble)
    );
    assert_eq!(body["models"], Value::from(cfg.models.forecast));
}

#[tokio::test]
async fn api_config_unconfigured() {
    let fake = FakeUpstream::start();
    let state = api_state(
        &fake,
        CfgOpts {
            location: None,
            ..CfgOpts::default()
        },
    );
    let body = get_json(state, "/api/config").await;
    assert_eq!(body["configured"], Value::Bool(false));
    assert_eq!(body["location"], Value::Null);
}

#[tokio::test]
async fn api_now_empty() {
    let state = default_state();
    let body = get_json(state, "/api/now").await;
    assert_eq!(body["available"], Value::Bool(false));
    assert_eq!(body["conditions"], Value::Null);
    assert_eq!(body["age_seconds"], Value::Null);
}

#[tokio::test]
async fn api_rain_probability_no_data() {
    let state = default_state();
    let body = get_json(state, "/api/rain-probability").await;
    assert_eq!(body["probability_pct"], serde_json::json!(0.0));
    assert_eq!(body["weights_used"], serde_json::json!({}));
    assert!(body["explanation"].as_str().unwrap().contains("No data"));
}

#[tokio::test]
async fn api_radar_next_hour_unavailable() {
    let state = default_state();
    let body = get_json(state, "/api/radar/next-hour").await;
    assert_eq!(body["available"], Value::Bool(false));
    assert_eq!(body["steps"].as_array().unwrap().len(), 12);
}

/// empty cache: the forecast source is reported unavailable.
#[tokio::test]
async fn api_models_24h_empty() {
    let state = default_state();
    let body = get_json(state, "/api/models/24h").await;
    assert_eq!(body["available"], Value::Bool(false));
    assert_eq!(body["hours"], serde_json::json!([]));
    assert_eq!(body["models"], serde_json::json!([]));
    assert_eq!(body["n_models"], serde_json::json!(0));
}

#[tokio::test]
async fn api_model_accuracy_empty() {
    let state = default_state();
    let body = get_json(state, "/api/model-accuracy").await;
    assert_eq!(body["models"], serde_json::json!({}));
    assert_eq!(body["window_days"], serde_json::json!(30));
    assert_eq!(body["min_samples"], serde_json::json!(48));
}

#[tokio::test]
async fn api_sources() {
    let state = default_state();
    let payloads = testkit::make_payloads();
    let now = testkit::now();
    let store = state.aggregator.store();
    for (source, payload) in [
        (Source::Radar, payloads.radar.as_ref().unwrap()),
        (Source::Current, payloads.current.as_ref().unwrap()),
        (Source::Forecast, payloads.forecast.as_ref().unwrap()),
        (Source::Ensemble, payloads.ensemble.as_ref().unwrap()),
    ] {
        store
            .put_cache(source, payload, now - TimeDelta::seconds(60))
            .unwrap();
    }
    let body = get_json(state, "/api/sources").await;
    let mut keys: Vec<&str> = body
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    keys.sort_unstable();
    assert_eq!(keys, ["current", "ensemble", "forecast", "radar"]);
    assert_eq!(
        body["radar"]["upstream"],
        serde_json::json!("DWD (Bright Sky)")
    );
    assert_eq!(body["forecast"]["available"], Value::Bool(true));
    assert_eq!(body["forecast"]["age_seconds"], serde_json::json!(60));
    assert_eq!(body["ensemble"]["stale"], Value::Bool(false));
}

#[tokio::test]
async fn api_schedule() {
    let mut state = default_state();
    let scheduler = Arc::new(Scheduler::new());
    scheduler.set_next_run(
        Job::Radar,
        times::parse_iso("2026-09-29T14:05:05Z").unwrap(),
    );
    state.scheduler = Some(scheduler);
    let cfg = state.aggregator.cfg();
    let body = get_json(state, "/api/schedule").await;
    assert!(body["server_time_utc"].as_str().unwrap().ends_with('Z'));
    assert_eq!(
        body["jobs"]["radar"],
        serde_json::json!({
            "interval_minutes": cfg.scheduling.radar_interval_minutes,
            "next_run_utc": "2026-09-29T14:05:05Z",
            "sources": ["radar", "current"],
        })
    );
    assert_eq!(body["jobs"]["models"]["next_run_utc"], Value::Null);
}

#[tokio::test]
async fn no_cors_for_foreign_origin() {
    let state = default_state();
    let (status, headers, _body) =
        call(state, "/api/config", &[("origin", "https://evil.example")]).await;
    assert_eq!(status, StatusCode::OK);
    assert!(!headers.contains_key("access-control-allow-origin"));
}

/// a broken store makes `/api/now` fail with the middleware's plain-text 500.
#[tokio::test]
async fn unhandled_error_500_still_carries_security_headers() {
    let state = default_state();
    state
        .aggregator
        .store()
        .lock_for_tests()
        .execute_batch("DROP TABLE source_cache")
        .unwrap();
    let (status, headers, body) = call(state, "/api/now", &[]).await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(body, "Internal Server Error");
    assert_eq!(
        headers.get("content-type").and_then(|v| v.to_str().ok()),
        Some("text/plain; charset=utf-8")
    );
    assert_security_headers(&headers);
}
