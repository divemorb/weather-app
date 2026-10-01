//! Shared upstream plumbing (Python `app/upstream.py`). Upstream data is
//! untrusted: a wrong type or a missing key becomes a `SourceError`, never
//! a panic.

use serde_json::Value;

/// Hard cap for upstream response bodies (used by the fetch in phase 3).
pub const MAX_RESPONSE_BYTES: usize = 5 * 1024 * 1024;

/// A data source failed or returned an unusable payload.
#[derive(Clone, Debug, PartialEq)]
pub struct SourceError(pub String);

impl SourceError {
    pub fn new(msg: impl Into<String>) -> Self {
        SourceError(msg.into())
    }
}

impl std::fmt::Display for SourceError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for SourceError {}

/// Sent with every upstream request. Nominatim requires a custom
/// User-Agent (its usage policy; the default ones get a 403).
pub const USER_AGENT: &str = "WetterLocal/1.0 (self-hosted home weather app)";

/// The HTTP client for upstream requests: total timeout, our User-Agent,
/// and no redirects (httpx doesn't follow them, so a 3xx is an error).
pub fn http_client(timeout_seconds: f64) -> Result<reqwest::Client, String> {
    let timeout = std::time::Duration::try_from_secs_f64(timeout_seconds)
        .unwrap_or(std::time::Duration::from_secs(20));
    reqwest::Client::builder()
        .timeout(timeout)
        .user_agent(USER_AGENT)
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|e| format!("cannot build the HTTP client: {e}"))
}

/// Python `stream_json_capped`: GET `url` with `params` and parse the JSON
/// body, aborting above `MAX_RESPONSE_BYTES` (declared or streamed).
pub async fn fetch_json_capped(
    client: &reqwest::Client,
    url: &str,
    params: &[(&str, String)],
) -> Result<Value, SourceError> {
    let mut resp = client
        .get(url)
        .query(params)
        .send()
        .await
        .map_err(|e| SourceError::new(format!("request failed: {e}")))?;
    let status = resp.status();
    if !status.is_success() {
        return Err(SourceError::new(format!("request failed: HTTP {status}")));
    }
    if let Some(declared) = resp.content_length()
        && declared > MAX_RESPONSE_BYTES as u64
    {
        return Err(SourceError::new(format!(
            "response declares {declared} bytes, over the {MAX_RESPONSE_BYTES} byte cap"
        )));
    }
    let mut body: Vec<u8> = Vec::new();
    while let Some(chunk) = resp
        .chunk()
        .await
        .map_err(|e| SourceError::new(format!("request failed: {e}")))?
    {
        if body.len() + chunk.len() > MAX_RESPONSE_BYTES {
            return Err(SourceError::new(format!(
                "response body exceeds the {MAX_RESPONSE_BYTES} byte cap"
            )));
        }
        body.extend_from_slice(&chunk);
    }
    serde_json::from_slice(&body)
        .map_err(|e| SourceError::new(format!("response is not valid JSON: {e}")))
}

/// Python truthiness of a JSON value (`if payload.get("error"):`).
pub fn py_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64() != Some(0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

/// Python `float(v) if v is not None else None` on a payload value: a JSON
/// number, or None for a missing/null value; anything else is malformed.
pub fn opt_f64(v: Option<&Value>, what: &str) -> Result<Option<f64>, SourceError> {
    match v {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Number(n)) => n
            .as_f64()
            .map(Some)
            .ok_or_else(|| SourceError::new(format!("{what}: bad number"))),
        Some(other) => Err(SourceError::new(format!(
            "{what}: expected a number, got {other}"
        ))),
    }
}

/// Python `[None if v is None else float(v) for v in raw]`: a JSON list of
/// numbers and nulls.
pub fn f64_list(v: &Value, what: &str) -> Result<Vec<Option<f64>>, SourceError> {
    let items = v
        .as_array()
        .ok_or_else(|| SourceError::new(format!("{what}: expected a list")))?;
    items.iter().map(|item| opt_f64(Some(item), what)).collect()
}

/// Python `str(value)` for the few places that print an upstream value.
pub fn py_str(v: &Value) -> String {
    match v {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::String(s) => s.clone(),
        other => other.to_string(),
    }
}

#[cfg(test)]
mod tests;
