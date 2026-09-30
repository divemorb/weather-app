use chrono::{DateTime, NaiveDateTime, Utc};

/// Python `parse_iso`: `Z` or an offset (normalized to UTC), or a naive stamp
/// (taken as UTC), with or without seconds (Open-Meteo sends "2026-09-30T00:15").
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

/// Python `to_iso`: "2026-09-25T06:30:00Z".
pub fn to_iso(t: DateTime<Utc>) -> String {
    t.format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

/// The app's clock: the real time, or a fixed instant when `WETTER_FAKE_NOW`
/// is set (contract tests only; `main` logs a warning).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Clock {
    fixed: Option<DateTime<Utc>>,
}

impl Clock {
    pub fn system() -> Self {
        Clock { fixed: None }
    }

    pub fn fixed(t: DateTime<Utc>) -> Self {
        Clock { fixed: Some(t) }
    }

    pub fn from_env(env: &dyn Fn(&str) -> Option<String>) -> Result<Self, String> {
        match env("WETTER_FAKE_NOW").filter(|v| !v.is_empty()) {
            Some(v) => parse_iso(&v).map(Clock::fixed),
            None => Ok(Clock::system()),
        }
    }

    pub fn is_fixed(&self) -> bool {
        self.fixed.is_some()
    }

    pub fn now(&self) -> DateTime<Utc> {
        self.fixed.unwrap_or_else(Utc::now)
    }
}

#[cfg(test)]
mod tests;
