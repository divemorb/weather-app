//! Bright Sky (DWD) client parsers (Python `app/brightsky_client.py`).
//!
//! Pure functions: raw upstream JSON in, normalized data out. Upstream data
//! is untrusted, so a wrong type or a missing key becomes a `SourceError`
//! (never a panic).

use chrono::{DateTime, TimeDelta, Utc};
use serde_json::Value;
use std::collections::HashMap;

use crate::models::CurrentConditions;
use crate::times::parse_iso;
use crate::upstream::{SourceError, opt_f64, py_str, py_truthy};

/// A payload-shape error (wrong type, missing key) becomes a `SourceError`
/// with this wording.
fn malformed(label: &str, exc: SourceError) -> SourceError {
    SourceError::new(format!("{label}: malformed payload ({exc})"))
}

/// Parse a `/current_weather` payload.
pub fn parse_current_weather(payload: &Value) -> Result<CurrentConditions, SourceError> {
    let label = "Bright Sky current_weather";
    let w = payload
        .get("weather")
        .ok_or_else(|| SourceError::new(format!("{label}: missing 'weather'")))?
        .as_object()
        .ok_or_else(|| malformed(label, SourceError::new("'weather' is not an object")))?;
    let num = |key: &str| -> Result<Option<f64>, SourceError> {
        opt_f64(w.get(key), key).map_err(|exc| malformed(label, exc))
    };
    Ok(CurrentConditions {
        timestamp_utc: w.get("timestamp").cloned().unwrap_or(Value::Null),
        source_id: w.get("source_id").cloned().unwrap_or(Value::Null),
        temperature_c: num("temperature")?,
        feels_like_c: None, // filled by the aggregator from Open-Meteo
        wind_speed_ms: num("wind_speed_10")?,
        wind_direction_deg: num("wind_direction_10")?,
        wind_gust_ms: num("wind_gust_speed_60")?,
        cloud_cover_pct: num("cloud_cover")?,
        humidity_pct: num("relative_humidity")?,
        pressure_hpa: num("pressure_msl")?,
        dew_point_c: num("dew_point")?,
        precipitation_10mm: num("precipitation_10")?,
        precipitation_30mm: num("precipitation_30")?,
        precipitation_60mm: num("precipitation_60")?,
        condition: w.get("condition").cloned().unwrap_or(Value::Null),
    })
}

/// Extract hourly *observations*: `(hour_start, mm)` pairs in ascending
/// order, where `hour_start = timestamp - 1h` (a record stamped `T` holds
/// the rain of `[T-1h, T)`). Only records from non-forecast sources with
/// `timestamp <= now` and a non-null precipitation are kept; unknown
/// sources and bad timestamps are skipped, but a non-numeric precipitation
/// is a `SourceError`.
pub fn parse_hourly_observations(
    payload: &Value,
    now: DateTime<Utc>,
) -> Result<Vec<(DateTime<Utc>, f64)>, SourceError> {
    let label = "Bright Sky weather";
    let payload = payload
        .as_object()
        .ok_or_else(|| SourceError::new(format!("{label}: payload is not an object")))?;

    // Map source id -> observation_type. The key is the id's JSON text, so a
    // missing id matches a missing `source_id` (`null` == `null`).
    // Missing/null/non-list "sources" count as empty.
    let observation_types: HashMap<String, Value> = payload
        .get("sources")
        .and_then(Value::as_array)
        .map(|list| {
            list.iter()
                .filter(|s| s.is_object())
                .map(|s| {
                    (
                        s.get("id").unwrap_or(&Value::Null).to_string(),
                        s.get("observation_type").cloned().unwrap_or(Value::Null),
                    )
                })
                .collect()
        })
        .unwrap_or_default();

    let mut out: Vec<(DateTime<Utc>, f64)> = Vec::new();
    for rec in payload
        .get("weather")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let Some(rec) = rec.as_object() else {
            continue;
        };
        let source_id = rec.get("source_id").unwrap_or(&Value::Null).to_string();
        let Some(obs_type) = observation_types.get(&source_id) else {
            continue; // unknown source: no way to verify it is a real observation
        };
        if obs_type.as_str() == Some("forecast") {
            continue;
        }
        let Some(precip) = rec.get("precipitation") else {
            continue;
        };
        if precip.is_null() {
            continue;
        }
        let Some(ts) = rec.get("timestamp").and_then(Value::as_str) else {
            continue;
        };
        let Ok(stamp) = parse_iso(ts) else {
            continue;
        };
        if stamp > now {
            continue;
        }
        // Non-null is checked above: a number passes, a malformed value is
        // an error (not skipped).
        let mm = match opt_f64(Some(precip), "precipitation") {
            Ok(Some(mm)) => mm,
            Ok(None) => continue,
            Err(exc) => return Err(malformed(label, exc)),
        };
        out.push((stamp - TimeDelta::hours(1), mm));
    }
    out.sort_by_key(|item| item.0);
    Ok(out)
}

/// Station name + distance: prefers a source whose `observation_type` is
/// "current" or "historical" and which has a station name; falls back to
/// the first listed source (its id, stringified, when it has no name —
/// "None" when it has no id either).
pub fn parse_station_info(payload: &Value) -> Result<Option<(String, f64)>, SourceError> {
    let label = "Bright Sky weather";
    let sources: Vec<&Value> = payload
        .get("sources")
        .and_then(Value::as_array)
        .map(|list| list.iter().filter(|s| s.is_object()).collect())
        .unwrap_or_default();
    if sources.is_empty() {
        return Ok(None);
    }
    let distance = |s: &Value| -> Result<f64, SourceError> {
        // Missing, null or 0 stay 0.0.
        opt_f64(s.get("distance"), "distance")
            .map_err(|exc| malformed(label, exc))
            .map(|d| d.unwrap_or(0.0))
    };
    for s in &sources {
        if matches!(
            s.get("observation_type"),
            Some(Value::String(t)) if t == "current" || t == "historical"
        ) && let Some(name) = s.get("station_name")
            && py_truthy(name)
        {
            return Ok(Some((py_str(name), distance(s)?)));
        }
    }
    let Some(first) = sources.first() else {
        return Ok(None);
    };
    let name = match first.get("station_name") {
        Some(n) if py_truthy(n) => py_str(n),
        _ => py_str(first.get("id").unwrap_or(&Value::Null)),
    };
    Ok(Some((name, distance(first)?)))
}

#[cfg(test)]
mod tests;
