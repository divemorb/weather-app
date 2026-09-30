use std::collections::HashSet;
use std::net::IpAddr;

use axum::Json;
use axum::extract::{Request, State};
use axum::http::StatusCode;
use axum::http::header::{self, HeaderName, HeaderValue};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use serde_json::json;

use crate::routes::AppState;

pub const CSP: &str = "default-src 'self'; img-src 'self' data:; object-src 'none'; \
base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

/// Python `host_allowed`: an IP literal, localhost, a .local name, or one of
/// ALLOWED_HOSTS (port ignored). Also IPv6 with a zone id, like Python's
/// `ipaddress`.
pub fn host_allowed(host_header: &str, extra: &HashSet<String>) -> bool {
    let lower = host_header.trim().to_lowercase();
    let host = if let Some(rest) = lower.strip_prefix('[') {
        rest.split(']').next().unwrap_or("").to_string()
    } else if lower.matches(':').count() == 1 {
        lower
            .rsplit_once(':')
            .map(|(h, _)| h.to_string())
            .unwrap_or_default()
    } else {
        lower
    };
    if host.is_empty() {
        return false;
    }
    if host.parse::<IpAddr>().is_ok() {
        return true;
    }
    if let Some((addr, zone)) = host.split_once('%')
        && !zone.is_empty()
        && addr.parse::<std::net::Ipv6Addr>().is_ok()
    {
        return true;
    }
    host == "localhost" || host.ends_with(".local") || extra.contains(&host)
}

/// Python `ALLOWED_HOSTS` parsing: `h.strip().lower() for h in raw.split(",")
/// if h.strip()`.
pub fn parse_allowed_hosts(raw: &str) -> HashSet<String> {
    raw.split(',')
        .map(str::trim)
        .filter(|h| !h.is_empty())
        .map(str::to_lowercase)
        .collect()
}

/// FastAPI's error shape: `{"detail": "..."}` with that status.
pub fn json_error(status: StatusCode, detail: &str) -> Response {
    (status, Json(json!({"detail": detail}))).into_response()
}

/// Python `add_security_headers`: the Host check first, then the security
/// headers and `Cache-Control: no-cache` on every response.
pub async fn guard(State(state): State<AppState>, req: Request, next: Next) -> Response {
    let host = req
        .headers()
        .get(header::HOST)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    let mut res = if !host_allowed(host, &state.extra_hosts) {
        (
            StatusCode::BAD_REQUEST,
            [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
            "Invalid host header",
        )
            .into_response()
    } else {
        next.run(req).await
    };
    let h = res.headers_mut();
    h.insert(
        header::CONTENT_SECURITY_POLICY,
        HeaderValue::from_static(CSP),
    );
    h.insert(
        header::X_CONTENT_TYPE_OPTIONS,
        HeaderValue::from_static("nosniff"),
    );
    h.insert(
        header::REFERRER_POLICY,
        HeaderValue::from_static("no-referrer"),
    );
    h.insert(
        HeaderName::from_static("cross-origin-resource-policy"),
        HeaderValue::from_static("same-origin"),
    );
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    res
}

#[cfg(test)]
mod tests;
