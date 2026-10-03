//! Address search via OpenStreetMap Nominatim (Python `app/geocode.py`).
//!
//! The user types an address or place into the setup wizard; this module
//! resolves it to coordinates. Upstream data is untrusted: a non-list
//! payload is a [`SourceError`], and entries with missing, non-numeric or
//! non-finite coordinates are skipped.
//!
//! Nominatim usage policy: at most one request per second. [`Geocoder`]
//! therefore spaces requests by [`MIN_REQUEST_SPACING`]: the throttle lock
//! is held across the wait *and* the request, so two concurrent searches
//! are serialized and each still waits for the spacing. Results are cached
//! per lower-cased query (cleared before a new entry once full) — good
//! enough for a single-user app.

use std::collections::HashMap;
#[cfg(test)]
use std::sync::Arc;
use std::sync::{Mutex, OnceLock, PoisonError};
use std::time::{Duration, Instant};

use serde_json::{Value, json};

use crate::pyfmt;
use crate::upstream::{self, SourceError};

/// Nominatim usage policy: max 1 request per second; wait a little more.
const MIN_REQUEST_SPACING: f64 = 1.1;

/// In-memory result cache size (lower-cased query -> results); cleared
/// before a new entry once full. Good enough for a single-user app.
const MAX_CACHE_ENTRIES: usize = 100;

/// Parse a Nominatim `/search` payload into up to 5 wizard results.
///
/// Entries with a missing or non-string `display_name`, or with missing or
/// non-numeric `lat`/`lon`, are skipped (upstream data is untrusted); a
/// non-list payload is a [`SourceError`]. Entries whose coordinates are not
/// finite (`"nan"`, `"inf"`) are skipped too — they would end up as
/// invalid JSON downstream.
pub fn parse_nominatim(payload: &Value) -> Result<Vec<GeocodeResult>, SourceError> {
    let entries = payload
        .as_array()
        .ok_or_else(|| SourceError::new("Nominatim search: expected a JSON list"))?;
    let mut out = Vec::new();
    for entry in entries {
        let Some(fields) = entry.as_object() else {
            continue;
        };
        let Some(label) = fields.get("display_name").and_then(Value::as_str) else {
            continue;
        };
        if label.is_empty() {
            continue;
        }
        let Some(latitude) = fields.get("lat").and_then(pyfmt::py_float) else {
            continue;
        };
        let Some(longitude) = fields.get("lon").and_then(pyfmt::py_float) else {
            continue;
        };
        if !latitude.is_finite() || !longitude.is_finite() {
            continue;
        }
        out.push(GeocodeResult {
            label: label.to_string(),
            latitude,
            longitude,
        });
        if out.len() == 5 {
            break;
        }
    }
    Ok(out)
}

/// One Nominatim match: the display name and the coordinates. Named fields
/// so the two coordinates can never be swapped.
#[derive(Clone, Debug, PartialEq)]
pub struct GeocodeResult {
    pub label: String,
    pub latitude: f64,
    pub longitude: f64,
}

impl GeocodeResult {
    /// The wire form in the `GET /api/geocode` answer.
    pub fn to_json(&self) -> Value {
        json!({
            "label": self.label,
            "latitude": self.latitude,
            "longitude": self.longitude,
        })
    }
}

/// The `GET /api/geocode` answer: `{"results": [...]}`.
pub fn search_response(results: &[GeocodeResult]) -> Value {
    let results = results
        .iter()
        .map(GeocodeResult::to_json)
        .collect::<Vec<_>>();
    json!({"results": results})
}

/// A monotonic clock in seconds, for the throttle.
#[derive(Clone, Copy, Debug)]
enum Monotonic {
    /// Seconds since a process-global start instant.
    System,
    /// Tests: a constant value, so the throttle is checked without real
    /// waiting.
    #[cfg(test)]
    Fixed(f64),
}

impl Monotonic {
    fn now(&self) -> f64 {
        match self {
            Monotonic::System => start_instant().elapsed().as_secs_f64(),
            #[cfg(test)]
            Monotonic::Fixed(v) => *v,
        }
    }
}

fn start_instant() -> &'static Instant {
    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now)
}

/// How the throttle waits: real time in production, a recording stub in
/// tests.
#[derive(Clone, Debug)]
enum ThrottleSleep {
    /// `tokio::time::sleep`.
    Tokio,
    /// Tests: record the requested wait (no real waiting).
    #[cfg(test)]
    Record(Arc<Mutex<Vec<f64>>>),
}

impl ThrottleSleep {
    async fn sleep(&self, wait: f64) {
        match self {
            ThrottleSleep::Tokio => {
                tokio::time::sleep(wait_duration(wait)).await;
            }
            #[cfg(test)]
            ThrottleSleep::Record(log) => {
                log.lock()
                    .unwrap_or_else(PoisonError::into_inner)
                    .push(wait);
            }
        }
    }
}

/// The throttle's sleep duration; clamped so a clock that jumps backwards
/// can never make it invalid.
fn wait_duration(wait: f64) -> Duration {
    Duration::try_from_secs_f64(wait.max(0.0)).unwrap_or(Duration::ZERO)
}

fn cached_result(
    cache: &Mutex<HashMap<String, Vec<GeocodeResult>>>,
    key: &str,
) -> Option<Vec<GeocodeResult>> {
    let cache = cache.lock().unwrap_or_else(PoisonError::into_inner);
    cache.get(key).cloned()
}

/// Clear the cache once full, then store (the guard is dropped at once, so
/// the lock is never held across an `.await`).
fn cache_result(
    cache: &Mutex<HashMap<String, Vec<GeocodeResult>>>,
    key: String,
    results: &[GeocodeResult],
) {
    let mut cache = cache.lock().unwrap_or_else(PoisonError::into_inner);
    if cache.len() >= MAX_CACHE_ENTRIES {
        cache.clear();
    }
    cache.insert(key, results.to_vec());
}

/// Address -> coordinates via Nominatim, throttled and cached. `Sync`, so
/// the routes share one instance as `Arc<Geocoder>` and `search` works
/// through `&self`.
pub struct Geocoder {
    base: String,
    http: reqwest::Client,
    clock: Monotonic,
    sleep: ThrottleSleep,
    /// The monotonic time of the last request, or `None` while none went
    /// out (the first request never sleeps).
    throttle: tokio::sync::Mutex<Option<f64>>,
    /// Lower-cased query -> results.
    cache: Mutex<HashMap<String, Vec<GeocodeResult>>>,
}

impl Geocoder {
    /// Build the geocoder from the Nominatim base URL and the shared
    /// request client (production: `upstream::http_client(10.0)`; it
    /// already sends the User-Agent Nominatim requires).
    pub fn new(base_url: &str, http: reqwest::Client) -> Self {
        Self {
            base: base_url.trim_end_matches('/').to_string(),
            http,
            clock: Monotonic::System,
            sleep: ThrottleSleep::Tokio,
            throttle: tokio::sync::Mutex::new(None),
            cache: Mutex::new(HashMap::new()),
        }
    }

    /// Tests: a constant clock and a sleep that only records, so the
    /// throttle is verified without real waiting.
    #[cfg(test)]
    fn new_for_test(
        base_url: &str,
        http: reqwest::Client,
        clock: Monotonic,
        sleeps: Arc<Mutex<Vec<f64>>>,
    ) -> Self {
        Self {
            base: base_url.trim_end_matches('/').to_string(),
            http,
            clock,
            sleep: ThrottleSleep::Record(sleeps),
            throttle: tokio::sync::Mutex::new(None),
            cache: Mutex::new(HashMap::new()),
        }
    }

    /// Resolve `query` to up to 5 [`GeocodeResult`]s; `[]` when Nominatim
    /// has no match.
    ///
    /// A cache hit returns before taking the throttle lock and never
    /// sleeps. On a miss the throttle guarantees at least
    /// [`MIN_REQUEST_SPACING`] seconds since the previous *request*; it is
    /// held across the wait and the request, so concurrent searches are
    /// serialized too. A failed lookup is a [`SourceError`] and is not
    /// cached.
    pub async fn search(&self, query: &str) -> Result<Vec<GeocodeResult>, SourceError> {
        let key = query.to_lowercase();
        if let Some(cached) = cached_result(&self.cache, &key) {
            return Ok(cached);
        }
        let payload = {
            let mut last_request_at = self.throttle.lock().await;
            let wait = last_request_at.map(|last| MIN_REQUEST_SPACING - (self.clock.now() - last));
            if let Some(wait) = wait
                && wait > 0.0
            {
                self.sleep.sleep(wait).await;
            }
            *last_request_at = Some(self.clock.now());
            upstream::fetch_json_capped(
                &self.http,
                &format!("{}/search", self.base),
                &[
                    ("q", query.to_string()),
                    ("format", "jsonv2".to_string()),
                    ("limit", "5".to_string()),
                    ("addressdetails", "0".to_string()),
                ],
            )
            .await?
        };
        let results = parse_nominatim(&payload)?;
        cache_result(&self.cache, key, &results);
        Ok(results)
    }
}

#[cfg(test)]
mod tests;
