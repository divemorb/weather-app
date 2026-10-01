//! Tests for the GET API endpoints (ports of `tests/test_api.py` and two
//! of `tests/test_api_security.py`), against a real aggregator over the
//! fake upstream instead of Python's `FakeAgg`.

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

use axum::body::Body;
use axum::http::{HeaderMap, Request, StatusCode};
use chrono::TimeDelta;
use serde_json::Value;
use tower::ServiceExt;

use crate::aggregator::{
    Job,
    testkit::{self, CfgOpts},
};
use crate::geocode::Geocoder;
use crate::scheduler::Scheduler;
use crate::store::Source;
use crate::testutil::fake_upstream::FakeUpstream;
use crate::times;

use super::{AppState, build_router};

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

async fn call(
    state: AppState,
    uri: &str,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    let mut builder = Request::builder()
        .method("GET")
        .uri(uri)
        .header("host", "127.0.0.1:8000");
    for (name, value) in headers.iter().copied() {
        builder = builder.header(name, value);
    }
    let res = build_router(state)
        .oneshot(builder.body(Body::empty()).unwrap())
        .await
        .unwrap();
    let status = res.status();
    let headers = res.headers().clone();
    let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();
    (status, headers, String::from_utf8(bytes.to_vec()).unwrap())
}

fn body_json(body: &str) -> Value {
    serde_json::from_str(body).unwrap()
}

fn assert_security_headers(headers: &HeaderMap) {
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

/// `test_api_config`.
#[tokio::test]
async fn api_config() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let cfg = state.aggregator.cfg();
    let (status, _headers, body) = call(state, "/api/config", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
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

/// `test_api_config_unconfigured` (Python: `cfg` replaced by
/// `replace(load_config(), location=None)`).
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
    let (status, _headers, body) = call(state, "/api/config", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["configured"], Value::Bool(false));
    assert_eq!(body["location"], Value::Null);
}

/// `test_api_now_empty`: an aggregator with an empty cache.
#[tokio::test]
async fn api_now_empty() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "/api/now", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["available"], Value::Bool(false));
    assert_eq!(body["conditions"], Value::Null);
    assert_eq!(body["age_seconds"], Value::Null);
}

/// `test_api_rain_probability_no_data`.
#[tokio::test]
async fn api_rain_probability_no_data() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "/api/rain-probability", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["probability_pct"], serde_json::json!(0.0));
    assert_eq!(body["weights_used"], serde_json::json!({}));
    assert!(body["explanation"].as_str().unwrap().contains("No data"));
}

/// `test_api_radar_next_hour_unavailable`: still 12 buckets, all dry.
#[tokio::test]
async fn api_radar_next_hour_unavailable() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "/api/radar/next-hour", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["available"], Value::Bool(false));
    assert_eq!(body["steps"].as_array().unwrap().len(), 12);
}

/// `test_api_models_24h_empty`. The Python test's `available is True`
/// comes from its `FakeAgg`'s canned meta; the real app (empty cache)
/// reports the forecast source as unavailable.
#[tokio::test]
async fn api_models_24h_empty() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "/api/models/24h", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["available"], Value::Bool(false));
    assert_eq!(body["hours"], serde_json::json!([]));
    assert_eq!(body["models"], serde_json::json!([]));
    assert_eq!(body["n_models"], serde_json::json!(0));
}

/// `test_api_model_accuracy_empty`.
#[tokio::test]
async fn api_model_accuracy_empty() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "/api/model-accuracy", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
    assert_eq!(body["models"], serde_json::json!({}));
    assert_eq!(body["window_days"], serde_json::json!(30));
    assert_eq!(body["min_samples"], serde_json::json!(48));
}

/// `test_api_sources`: all four payloads cached 60 s ago, so every
/// `age_seconds` is 60 and nothing is stale.
#[tokio::test]
async fn api_sources() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
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
    let (status, _headers, body) = call(state, "/api/sources", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
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

/// `test_api_schedule`: the radar job has a next run, the models job not.
#[tokio::test]
async fn api_schedule() {
    let fake = FakeUpstream::start();
    let mut state = api_state(&fake, CfgOpts::default());
    let scheduler = Arc::new(Scheduler::new());
    scheduler.set_next_run(
        Job::Radar,
        times::parse_iso("2026-09-29T14:05:05Z").unwrap(),
    );
    state.scheduler = Some(scheduler);
    let cfg = state.aggregator.cfg();
    let (status, _headers, body) = call(state, "/api/schedule", &[]).await;
    assert_eq!(status, StatusCode::OK);
    let body = body_json(&body);
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

/// `test_no_cors_for_foreign_origin`.
#[tokio::test]
async fn no_cors_for_foreign_origin() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, headers, _body) =
        call(state, "/api/config", &[("origin", "https://evil.example")]).await;
    assert_eq!(status, StatusCode::OK);
    assert!(!headers.contains_key("access-control-allow-origin"));
}

/// `test_unhandled_error_500_still_carries_security_headers`: a broken
/// store makes `/api/now` fail with the middleware's plain-text 500.
#[tokio::test]
async fn unhandled_error_500_still_carries_security_headers() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
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
