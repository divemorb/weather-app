//! Open-Meteo parsers: multi-model forecast + ensemble (Python
//! `app/openmeteo_client.py`: `HOURLY_VARS`, `_parse_time_list`, `_series`,
//! `parse_forecast`, `parse_ensemble`).
//!
//! Pure functions: raw upstream JSON in, normalized data out. Upstream data
//! is untrusted, so a wrong type or a missing key becomes a `SourceError`
//! (never a panic). The HTTP client itself arrives in phase 3.

use chrono::{DateTime, Utc};
use serde_json::{Map, Value};
use std::collections::BTreeMap;

use crate::models::{EnsembleData, ForecastBundle, ModelSeries};
use crate::times::parse_iso;
use crate::upstream::{SourceError, f64_list, py_str, py_truthy};

/// Variables requested hourly per model (Python `HOURLY_VARS`), mapped in
/// order onto `ModelSeries`'s hourly fields.
pub const HOURLY_VARS: [&str; 5] = [
    "precipitation",
    "temperature_2m",
    "apparent_temperature",
    "wind_speed_10m",
    "cloud_cover",
];

/// The Python `malformed_is_source_error` decorator: a payload-shape error
/// (wrong type, missing key) becomes a `SourceError` with this wording.
fn malformed(label: &str, exc: SourceError) -> SourceError {
    SourceError::new(format!("{label}: malformed payload ({exc})"))
}

/// Python `payload.get(section, {})` — a missing section is empty, but a
/// section that is *present* yet not an object (including `null`) is a
/// `SourceError`: Python crashes on `.get` and the decorator wraps it.
fn section<'a>(
    payload: &'a Map<String, Value>,
    name: &str,
    label: &str,
) -> Result<Option<&'a Map<String, Value>>, SourceError> {
    match payload.get(name) {
        None => Ok(None),
        Some(Value::Object(block)) => Ok(Some(block)),
        Some(other) => Err(malformed(
            label,
            SourceError::new(format!("'{name}' is not an object: {other}")),
        )),
    }
}

/// Python `_parse_time_list`: a missing `time` key gives an empty list; a
/// present one must be a list of ISO timestamp strings, each through
/// `parse_iso`. Anything else is a `SourceError`.
fn parse_time_list(v: Option<&Value>, label: &str) -> Result<Vec<DateTime<Utc>>, SourceError> {
    match v {
        None => Ok(Vec::new()),
        Some(Value::Array(items)) => {
            let mut out = Vec::with_capacity(items.len());
            for item in items {
                let Some(stamp) = item.as_str() else {
                    return Err(malformed(
                        label,
                        SourceError::new(format!("time entry is not a string: {item}")),
                    ));
                };
                out.push(parse_iso(stamp).map_err(|e| malformed(label, SourceError::new(e)))?);
            }
            Ok(out)
        }
        Some(other) => Err(malformed(
            label,
            SourceError::new(format!("'time' is not a list: {other}")),
        )),
    }
}

/// Python `_series`: a variable list, tolerating missing keys / null values
/// (both give an empty list); anything present must be a list of numbers and
/// nulls.
fn series(
    payload: &Map<String, Value>,
    section_name: &str,
    key: &str,
    label: &str,
) -> Result<Vec<Option<f64>>, SourceError> {
    let Some(raw) = section(payload, section_name, label)?.and_then(|block| block.get(key)) else {
        return Ok(Vec::new());
    };
    if raw.is_null() {
        return Ok(Vec::new());
    }
    f64_list(raw, key).map_err(|exc| malformed(label, exc))
}

/// Parse a multi-model forecast payload into a `ForecastBundle`
/// (Python `parse_forecast`). Units are Open-Meteo's: precipitation mm,
/// temperature °C, wind km/h, cloud cover %.
pub fn parse_forecast(
    payload: &Value,
    model_names: &[String],
) -> Result<ForecastBundle, SourceError> {
    let label = "Open-Meteo forecast";
    let payload = payload
        .as_object()
        .ok_or_else(|| malformed(label, SourceError::new("payload is not an object")))?;
    if let Some(error) = payload.get("error")
        && py_truthy(error)
    {
        let reason = payload.get("reason").unwrap_or(&Value::Null);
        return Err(SourceError::new(format!(
            "{label} error: {}",
            py_str(reason)
        )));
    }

    let min15 = section(payload, "minutely_15", label)?;
    let hourly = section(payload, "hourly", label)?;
    let min15_times = parse_time_list(min15.and_then(|s| s.get("time")), label)?;
    let hourly_times = parse_time_list(hourly.and_then(|s| s.get("time")), label)?;

    let mut models: Vec<ModelSeries> = Vec::with_capacity(model_names.len());
    for name in model_names {
        let m15 = series(
            payload,
            "minutely_15",
            &format!("precipitation_{name}"),
            label,
        )?;
        // One list per HOURLY_VARS entry, in order.
        let mut hourly = [const { Vec::new() }; HOURLY_VARS.len()];
        for (slot, var) in hourly.iter_mut().zip(HOURLY_VARS.iter()) {
            *slot = series(payload, "hourly", &format!("{var}_{name}"), label)?;
        }
        let [precip, temp, apparent, wind, cloud] = hourly;
        models.push(ModelSeries {
            name: name.clone(),
            min15_time: min15_times.clone(),
            min15_precip_mm: m15,
            hourly_time: hourly_times.clone(),
            hourly_precip_mm: precip,
            hourly_temp_c: temp,
            hourly_apparent_c: apparent,
            hourly_wind_kmh: wind,
            hourly_cloud_cover_pct: cloud,
        });
    }
    Ok(ForecastBundle { models })
}

/// The Python regex `precipitation_member(\d+)$` applied with `search`:
/// the last `precipitation_member` occurrence in the key, followed by one or
/// more digits that run to the end of the key. `Ok(None)` when the key is
/// not a member key; an overflowing member number is a `SourceError`.
fn member_number(key: &str, label: &str) -> Result<Option<i64>, SourceError> {
    let Some(pos) = key.rfind("precipitation_member") else {
        return Ok(None);
    };
    let Some(digits) = key.get(pos + "precipitation_member".len()..) else {
        return Ok(None);
    };
    if digits.is_empty() || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return Ok(None);
    }
    let number = digits.parse::<i64>().map_err(|_| {
        malformed(
            label,
            SourceError::new(format!("member number {digits} out of range")),
        )
    })?;
    Ok(Some(number))
}

/// Parse an ensemble payload into `EnsembleData` (Python `parse_ensemble`).
/// Members are extracted from the `precipitation_memberNN` keys and ordered
/// by member number; the control run is `precipitation`.
pub fn parse_ensemble(payload: &Value) -> Result<EnsembleData, SourceError> {
    let label = "Open-Meteo ensemble";
    let payload = payload
        .as_object()
        .ok_or_else(|| malformed(label, SourceError::new("payload is not an object")))?;
    if let Some(error) = payload.get("error")
        && py_truthy(error)
    {
        let reason = payload.get("reason").unwrap_or(&Value::Null);
        return Err(SourceError::new(format!(
            "{label} error: {}",
            py_str(reason)
        )));
    }

    let hourly = section(payload, "hourly", label)?;
    let times = parse_time_list(hourly.and_then(|s| s.get("time")), label)?;
    let control = series(payload, "hourly", "precipitation", label)?;

    // member number -> values. BTreeMap: `insert` replaces like the Python
    // dict, and iteration is in key order.
    let mut members: BTreeMap<i64, Vec<Option<f64>>> = BTreeMap::new();
    if let Some(hourly) = hourly {
        for (key, values) in hourly {
            let Some(number) = member_number(key, label)? else {
                continue;
            };
            let list = f64_list(values, key).map_err(|exc| malformed(label, exc))?;
            // `number` was parsed from digits, so it is >= 0 and the
            // subtraction cannot underflow (member00 gives index -1).
            members.insert(number - 1, list);
        }
    }

    Ok(EnsembleData {
        hourly_time: times,
        control_precip_mm: control,
        member_precip_mm: members.into_values().collect(),
    })
}

#[cfg(test)]
mod tests;
