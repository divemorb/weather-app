//! The Bright Sky HTTP-layer tests (Python `tests/test_brightsky_http.py`).

use super::*;
use serde_json::json;

use crate::testutil;
use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
use crate::upstream::MAX_RESPONSE_BYTES;

/// Python `test_client_fetch_weather_payload_requests_window`.
#[tokio::test]
async fn client_fetch_weather_payload_requests_window() {
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/weather",
        FakeResponse::Json(testutil::make_weather_payload(None, None)),
    );
    let client = brightsky(&fake);
    let payload = client
        .fetch_weather_payload(stamp("2026-09-27T12:00:00Z"), stamp("2026-09-27T20:00:00Z"))
        .await
        .expect("fetch ok");
    assert_eq!(payload["weather"][0]["source_id"], json!(1002));
    let req = fake.requests().first().expect("one request").clone();
    assert!(req.path.contains("/weather"));
    assert_eq!(req.param("date"), Some("2026-09-27T12:00:00Z"));
    assert_eq!(req.param("last_date"), Some("2026-09-27T20:00:00Z"));
    assert_eq!(req.param("tz"), Some("UTC"));
    assert_eq!(req.param("lat"), Some("52.0"));
    assert_eq!(req.param("lon"), Some("13.0"));
}

/// Python `test_client_fetch_weather_payload_http_error`.
#[tokio::test]
async fn client_fetch_weather_payload_http_error() {
    let fake = FakeUpstream::start();
    fake.set("/bs/weather", FakeResponse::Status(500));
    let client = brightsky(&fake);
    let err = client
        .fetch_weather_payload(stamp("2026-09-27T12:00:00Z"), stamp("2026-09-27T20:00:00Z"))
        .await
        .expect_err("HTTP 500 is a SourceError");
    assert!(err.to_string().contains("/weather"));
}

/// Python `test_client_fetch_current_uses_correct_endpoint`.
#[tokio::test]
async fn client_fetch_current_uses_correct_endpoint() {
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Json(testutil::make_current_payload(None)),
    );
    let client = brightsky(&fake);
    let payload = client.fetch_current_payload().await.expect("fetch ok");
    assert_eq!(payload["weather"]["temperature"], json!(7.4));
    let req = fake.requests().first().expect("one request").clone();
    assert!(req.path.contains("/current_weather"));
    assert_eq!(req.param("lat"), Some("52.0"));
    assert_eq!(req.param("lon"), Some("13.0"));
}

/// Python `test_client_radar_endpoint`.
#[tokio::test]
async fn client_radar_endpoint() {
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/radar",
        FakeResponse::Json(testutil::make_radar_payload(
            &[("2026-09-25T06:45:00+00:00", testutil::grid(5, 5, 0))],
            (10, 20, 14, 24),
            (2.0, 2.0),
        )),
    );
    let client = brightsky(&fake);
    let payload = client
        .fetch_radar_payload(stamp("2026-09-25T06:23:00Z"))
        .await
        .expect("fetch ok");
    assert_eq!(payload["radar"].as_array().map(Vec::len), Some(1));
    let req = fake.requests().first().expect("one request").clone();
    assert!(req.path.contains("/radar"));
}

/// Python `test_fetch_radar_requests_next_hour_window`: the radar request
/// must cover [now, now+1h) so the response includes the nowcast (frames at
/// or after 'now'); without it Bright Sky returns the previous hour only
/// (all in the past) and the radar signal stays dry.
#[tokio::test]
async fn fetch_radar_requests_next_hour_window() {
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/radar",
        FakeResponse::Json(testutil::make_radar_payload(
            &[],
            (10, 20, 14, 24),
            (2.0, 2.0),
        )),
    );
    let client = brightsky(&fake);
    client
        .fetch_radar_payload(stamp("2026-09-25T06:23:00Z"))
        .await
        .expect("fetch ok");
    let req = fake.requests().first().expect("one request").clone();
    // 'now' = 06:23 -> floored to 06:20, window covers [06:20, 07:20]
    // which contains [06:23, 07:23).
    assert_eq!(req.param("date"), Some("2026-09-25T06:20:00+00:00"));
    assert_eq!(req.param("last_date"), Some("2026-09-25T07:20:00+00:00"));
}

/// Python `test_client_http_error_raises_source_error`.
#[tokio::test]
async fn client_http_error_raises_source_error() {
    let fake = FakeUpstream::start();
    fake.set("/bs/current_weather", FakeResponse::Status(500));
    let client = brightsky(&fake);
    let err = client
        .fetch_current_payload()
        .await
        .expect_err("HTTP 500 is a SourceError");
    assert!(err.to_string().contains("Bright Sky /current_weather"));
}

/// Python `test_client_rejects_body_over_response_size_cap`: a body above
/// MAX_RESPONSE_BYTES must be aborted with a SourceError, never fully
/// buffered (memory + SQLite cache protection).
#[tokio::test]
async fn client_rejects_body_over_response_size_cap() {
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Oversize {
            bytes: MAX_RESPONSE_BYTES + 1,
            declare: true,
        },
    );
    let client = brightsky(&fake);
    let err = client
        .fetch_current_payload()
        .await
        .expect_err("an oversized body is a SourceError");
    assert!(err.to_string().contains("cap"));
}

/// Python `test_client_deeply_nested_json_raises_source_error`: 200 KB of
/// nested brackets is far below the size cap but makes the parser fail; it
/// must surface as a SourceError.
#[tokio::test]
async fn client_deeply_nested_json_raises_source_error() {
    let fake = FakeUpstream::start();
    let body = "[".repeat(100_000) + &"]".repeat(100_000);
    fake.set("/bs/current_weather", FakeResponse::Raw(body));
    let client = brightsky(&fake);
    let err = client
        .fetch_current_payload()
        .await
        .expect_err("deeply nested JSON is a SourceError");
    assert!(err.to_string().contains("not valid JSON"));
}

/// Python `test_client_normal_body_still_parses_with_streaming`: the
/// streamed path still returns parsed objects.
#[tokio::test]
async fn client_normal_body_still_parses_with_streaming() {
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Json(testutil::make_current_payload(None)),
    );
    let client = brightsky(&fake);
    let payload = client.fetch_current_payload().await.expect("fetch ok");
    assert_eq!(payload["weather"]["temperature"], json!(7.4));
}
