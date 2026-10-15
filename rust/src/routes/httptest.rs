//! Shared HTTP helpers for the route tests: one request against a fresh
//! router, plus the security-header assertions every response must carry.

use axum::body::Body;
use axum::http::{HeaderMap, Request, StatusCode};
use tower::ServiceExt;

use super::{AppState, build_router};

/// One request (method, uri, host, optional body, extra headers) against
/// a fresh router; the response comes back as (status, headers, body).
pub(crate) async fn call(
    state: AppState,
    method: &str,
    uri: &str,
    host: &str,
    body: Option<&str>,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    let mut builder = Request::builder()
        .method(method)
        .uri(uri)
        .header("host", host);
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

/// The five security headers the middleware sets on every response.
pub(crate) fn assert_security_headers(headers: &HeaderMap) {
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
