use std::sync::Arc;

use axum::http::{HeaderMap, StatusCode};

use crate::aggregator::testkit::CfgOpts;

use super::{AppState, httptest};

/// All five security headers.
fn assert_security_headers(headers: &HeaderMap) {
    httptest::assert_security_headers(headers);
}

fn test_state() -> AppState {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("index.html"), "<html></html>").unwrap();
    std::fs::write(dir.path().join("app.js"), "console.log(1)").unwrap();
    let static_files = crate::static_files::load(dir.path()).unwrap();
    let fake = crate::testutil::fake_upstream::FakeUpstream::start();
    let state = super::api_tests::api_state(&fake, CfgOpts::default());
    AppState {
        static_files: Arc::new(static_files),
        ..state
    }
}

async fn call(
    method: &str,
    uri: &str,
    host: &str,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    httptest::call(test_state(), method, uri, host, None, headers).await
}

#[tokio::test]
async fn healthz_ok() {
    let (status, headers, body) = call("GET", "/healthz", "127.0.0.1:8000", &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, r#"{"status":"ok"}"#);
    assert_security_headers(&headers);
}

#[tokio::test]
async fn foreign_host_header_rejected_with_security_headers() {
    let (status, headers, body) = call("GET", "/healthz", "evil.example:8000", &[]).await;
    assert_eq!(status, StatusCode::BAD_REQUEST);
    assert_eq!(body, "Invalid host header");
    assert_eq!(
        headers.get("content-type").and_then(|v| v.to_str().ok()),
        Some("text/plain; charset=utf-8")
    );
    assert_security_headers(&headers);
}

#[tokio::test]
async fn unknown_route_404_json() {
    let (status, _headers, body) = call("GET", "/nope", "127.0.0.1:8000", &[]).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body, r#"{"detail":"Not Found"}"#);
}

#[tokio::test]
async fn post_healthz_405_no_allow() {
    let (status, headers, body) = call("POST", "/healthz", "127.0.0.1:8000", &[]).await;
    assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED);
    assert_eq!(body, r#"{"detail":"Method Not Allowed"}"#);
    assert!(!headers.contains_key("allow"));
    assert_security_headers(&headers);
}

/// the static-file leg: `/app.js` carries `Cache-Control: no-cache` and an
/// ETag, with the security headers.
#[tokio::test]
async fn responses_are_revalidated() {
    let (status, headers, _body) = call("GET", "/app.js", "127.0.0.1:8000", &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        headers.get("cache-control").and_then(|v| v.to_str().ok()),
        Some("no-cache")
    );
    assert!(headers.get("etag").and_then(|v| v.to_str().ok()).is_some());
    assert_security_headers(&headers);
}

#[tokio::test]
async fn unchanged_static_file_answers_304() {
    let (_status, headers, _body) = call("GET", "/app.js", "127.0.0.1:8000", &[]).await;
    let etag = headers.get("etag").unwrap().to_str().unwrap().to_string();
    let (status, headers, body) = call(
        "GET",
        "/app.js",
        "127.0.0.1:8000",
        &[("if-none-match", &etag)],
    )
    .await;
    assert_eq!(status, StatusCode::NOT_MODIFIED);
    assert_eq!(
        headers.get("cache-control").and_then(|v| v.to_str().ok()),
        Some("no-cache")
    );
    assert_eq!(body, "");
}
