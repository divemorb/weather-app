use axum::body::Body;
use axum::http::{HeaderMap, Request, StatusCode};
use tower::ServiceExt;

use super::*;

fn test_router() -> Router {
    build_router(AppState {
        extra_hosts: Arc::new(HashSet::new()),
    })
}

async fn call(method: &str, uri: &str, host: &str) -> (StatusCode, HeaderMap, String) {
    let res = test_router()
        .oneshot(
            Request::builder()
                .method(method)
                .uri(uri)
                .header("host", host)
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    let status = res.status();
    let headers = res.headers().clone();
    let bytes = axum::body::to_bytes(res.into_body(), usize::MAX)
        .await
        .unwrap();
    (status, headers, String::from_utf8(bytes.to_vec()).unwrap())
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

#[tokio::test]
async fn healthz_ok() {
    let (status, headers, body) = call("GET", "/healthz", "127.0.0.1:8000").await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body, r#"{"status":"ok"}"#);
    assert_security_headers(&headers);
}

/// `test_foreign_host_header_rejected_with_security_headers`.
#[tokio::test]
async fn foreign_host_header_rejected_with_security_headers() {
    let (status, headers, body) = call("GET", "/healthz", "evil.example:8000").await;
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
    let (status, _headers, body) = call("GET", "/nope", "127.0.0.1:8000").await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body, r#"{"detail":"Not Found"}"#);
}

#[tokio::test]
async fn post_healthz_405_no_allow() {
    let (status, headers, body) = call("POST", "/healthz", "127.0.0.1:8000").await;
    assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED);
    assert_eq!(body, r#"{"detail":"Method Not Allowed"}"#);
    assert!(!headers.contains_key("allow"));
    assert_security_headers(&headers);
}
