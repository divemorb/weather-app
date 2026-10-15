use chrono::{DateTime, NaiveDateTime, Utc};

/// Parse an ISO-8601 stamp: `Z` or an offset (normalized to UTC), or a naive
/// stamp (taken as UTC), with or without seconds (Open-Meteo sends
/// "2026-09-30T00:15").
pub fn parse_iso(stamp: &str) -> Result<DateTime<Utc>, String> {
    let s = stamp.trim();
    if let Ok(t) = DateTime::parse_from_rfc3339(s) {
        return Ok(t.with_timezone(&Utc));
    }
    for fmt in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%dT%H:%M"] {
        if let Ok(naive) = NaiveDateTime::parse_from_str(s, fmt) {
            return Ok(naive.and_utc());
        }
    }
    Err(format!("not an ISO-8601 timestamp: {stamp:?}"))
}

/// Format a timestamp as "2026-09-25T06:30:00Z" (second precision, `Z`).
pub fn to_iso(t: DateTime<Utc>) -> String {
    t.format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

/// The app's clock: the real time, or a fixed instant when `WETTER_FAKE_NOW`
/// is set.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Clock {
    fixed: Option<DateTime<Utc>>,
}

impl Clock {
    /// The real system time.
    pub fn system() -> Self {
        Self { fixed: None }
    }

    /// A clock pinned to one instant (tests, `WETTER_FAKE_NOW`).
    pub fn fixed(t: DateTime<Utc>) -> Self {
        Self { fixed: Some(t) }
    }

    /// The clock from the environment: fixed when `WETTER_FAKE_NOW` is set
    /// and non-empty, the system clock otherwise.
    pub fn from_env(env: &dyn Fn(&str) -> Option<String>) -> Result<Self, String> {
        match env("WETTER_FAKE_NOW").filter(|v| !v.is_empty()) {
            Some(v) => parse_iso(&v).map(Self::fixed),
            None => Ok(Self::system()),
        }
    }

    /// Whether the clock is pinned to a fixed instant.
    pub fn is_fixed(&self) -> bool {
        self.fixed.is_some()
    }

    /// The current time as the clock sees it.
    pub fn now(&self) -> DateTime<Utc> {
        self.fixed.unwrap_or_else(Utc::now)
    }
}

#[cfg(test)]
mod tests;
