//! Runtime location state (Python `app/location.py`): the home location is
//! stored in the database (`app_meta` key `"location"`) and can be changed
//! from the browser. On startup the stored value wins; a configured
//! location is only *adopted* (written to the database) when nothing is
//! stored yet. This module also decodes and validates the request body of
//! `POST /api/location`.

use axum::http::{HeaderMap, header};
use serde_json::{Value, json};

use crate::config::{AppConfig, LocationConfig};
use crate::pyfmt;
use crate::store::{Store, StoreError};

/// `app_meta` key holding the JSON location (see [`location_to_json`]).
pub const LOCATION_KEY: &str = "location";

/// Two locations closer than this (degrees, ~1 km) count as "the same".
pub const MOVED_EPSILON: f64 = 0.01;

/// Serialize a location to the JSON stored in `app_meta`.
pub fn location_to_json(loc: &LocationConfig) -> String {
    json!({
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "timezone": loc.timezone,
        "label": loc.label,
    })
    .to_string()
}

/// Parse the stored JSON; bad JSON, missing keys or wrong types -> `None`.
///
/// Never panics: a corrupted value means "no stored location", which the
/// startup resolution then falls back to env/YAML (or unconfigured).
pub fn location_from_json(text: Option<&str>) -> Option<LocationConfig> {
    let text = text?;
    let value = serde_json::from_str::<Value>(text).ok()?;
    let obj = value.as_object()?;
    // A bool is not a number (serde_json keeps it out of Number).
    let latitude = obj.get("latitude")?.as_f64()?;
    let longitude = obj.get("longitude")?.as_f64()?;
    let timezone = obj.get("timezone")?.as_str()?;
    if timezone.is_empty() {
        return None;
    }
    Some(LocationConfig {
        latitude,
        longitude,
        timezone: timezone.to_string(),
        // A non-string label becomes "".
        label: obj
            .get("label")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string(),
    })
}

/// True when `new` is a *different* location than `old`. `None` (first
/// location ever) is not a move; latitude **or** longitude differing by
/// more than [`MOVED_EPSILON`] (≈1 km) counts as moved.
pub fn moved(old: Option<&LocationConfig>, new: &LocationConfig) -> bool {
    let Some(old) = old else {
        return false;
    };
    (old.latitude - new.latitude).abs() > MOVED_EPSILON
        || (old.longitude - new.longitude).abs() > MOVED_EPSILON
}

/// The location the app starts with. The stored `app_meta` location wins;
/// else the configured location is *adopted* (written to the database so
/// it survives a config file that later loses the block); else `None`
/// (unconfigured — the setup wizard will ask).
pub fn resolve_startup_location(
    store: &Store,
    cfg: &AppConfig,
) -> Result<Option<LocationConfig>, StoreError> {
    let stored = location_from_json(store.get_meta(LOCATION_KEY)?.as_deref());
    if stored.is_some() {
        return Ok(stored);
    }
    if let Some(loc) = &cfg.location {
        store.set_meta(LOCATION_KEY, &location_to_json(loc))?;
        tracing::info!(
            "adopting configured location {},{} into the database",
            pyfmt::py_repr(loc.latitude),
            pyfmt::py_repr(loc.longitude)
        );
        return Ok(Some(loc.clone()));
    }
    Ok(None)
}

/// JSON shape of a location for API responses (`/api/config` etc.).
pub fn location_payload(loc: &LocationConfig) -> Value {
    json!({
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "timezone": loc.timezone,
        "label": loc.label,
    })
}

/// True if `name` is a real IANA timezone; path-traversal or garbage names
/// are rejected, not just ignored.
pub fn valid_timezone(name: &str) -> bool {
    name.parse::<chrono_tz::Tz>().is_ok()
}

/// Refuse cross-site writes (CSRF): a foreign page may *send* a POST to a
/// LAN app even without CORS. No `origin` header (curl / non-browser) is
/// allowed unless `sec-fetch-site` says otherwise; otherwise the origin
/// must be this very scheme + host.
pub fn same_origin(headers: &HeaderMap) -> bool {
    let Some(raw_origin) = headers.get(header::ORIGIN) else {
        return match headers.get(header::HeaderName::from_static("sec-fetch-site")) {
            None => true,
            Some(raw) => matches!(raw.to_str(), Ok("same-origin")),
        };
    };
    let Ok(origin) = raw_origin.to_str() else {
        return false; // not valid text: a mismatch
    };
    let host = headers
        .get(header::HOST)
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");
    origin.to_lowercase() == format!("http://{}", host.to_lowercase())
}

/// The body of `POST /api/location` after the field checks. The fields are
/// private: only `validate_location_body` creates one, so holding a
/// `LocationIn` proves the checks ran.
#[derive(Clone, Debug, PartialEq)]
pub struct LocationIn {
    latitude: f64,
    longitude: f64,
    timezone: String,
    label: String,
}

impl LocationIn {
    pub fn latitude(&self) -> f64 {
        self.latitude
    }

    pub fn longitude(&self) -> f64 {
        self.longitude
    }

    pub fn timezone(&self) -> &str {
        &self.timezone
    }

    pub fn label(&self) -> &str {
        &self.label
    }

    /// Second stage, after the same-origin check: the timezone must exist,
    /// and the coordinates are rounded to 3 decimals.
    pub fn into_location(self) -> Result<LocationConfig, UnknownTimezone> {
        if !valid_timezone(&self.timezone) {
            return Err(UnknownTimezone);
        }
        Ok(LocationConfig {
            latitude: pyfmt::py_round(self.latitude, 3),
            longitude: pyfmt::py_round(self.longitude, 3),
            timezone: self.timezone,
            label: self.label,
        })
    }
}

/// 422 `{"detail": [{"loc": ["body", "timezone"], "msg": "unknown timezone"}]}`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct UnknownTimezone;

/// One part of a 422 `loc`: a name (`"body"`, `"latitude"`) or a position.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum LocPart {
    Name(&'static str),
    Pos(usize),
}

/// One entry of a 422 answer: `{"loc": [...], "msg": "..."}`.
#[derive(Clone, Debug, PartialEq)]
pub struct FieldError {
    pub loc: Vec<LocPart>,
    pub msg: &'static str,
}

/// Decode and validate the request body.
pub fn validate_location_body(
    content_type: Option<&str>,
    body: &[u8],
) -> Result<LocationIn, BodyError> {
    if body.is_empty() || !is_json_content_type(content_type) {
        return Err(BodyError::Invalid(vec![body_error("Field required")]));
    }
    let stripped = body.strip_prefix("\u{feff}".as_bytes()).unwrap_or(body);
    let Ok(text) = std::str::from_utf8(stripped) else {
        return Err(BodyError::Unparseable);
    };
    let value = match serde_json::from_str::<Value>(text) {
        Ok(value) => value,
        Err(err) => {
            return Err(BodyError::Invalid(vec![FieldError {
                loc: vec![
                    LocPart::Name("body"),
                    LocPart::Pos(json_error_pos(text, &err)),
                ],
                msg: "JSON decode error",
            }]));
        }
    };
    let Some(obj) = value.as_object() else {
        return Err(BodyError::Invalid(vec![FieldError {
            loc: vec![LocPart::Name("body")],
            msg: "Input should be a valid dictionary",
        }]));
    };

    let mut errors: Vec<FieldError> = Vec::new();
    // The field order (latitude, longitude, timezone, label) is Python's.
    let latitude = check_coordinate(obj.get("latitude"), -90.0, 90.0, "latitude", &mut errors);
    let longitude = check_coordinate(
        obj.get("longitude"),
        -180.0,
        180.0,
        "longitude",
        &mut errors,
    );

    let mut timezone: Option<String> = None;
    match obj.get("timezone") {
        None => errors.push(field_error("timezone", "Field required")),
        Some(Value::String(s)) => {
            let len = s.chars().count();
            if len == 0 || len > 64 {
                errors.push(field_error(
                    "timezone",
                    "String length must be between 1 and 64 characters",
                ));
            } else {
                timezone = Some(s.clone());
            }
        }
        Some(_) => errors.push(field_error("timezone", "Input should be a valid string")),
    }

    let mut label: Option<String> = None;
    match obj.get("label") {
        None => label = Some(String::new()),
        Some(Value::String(s)) => {
            if s.chars().count() > 200 {
                errors.push(field_error(
                    "label",
                    "String should have at most 200 characters",
                ));
            } else {
                label = Some(s.clone());
            }
        }
        Some(_) => errors.push(field_error("label", "Input should be a valid string")),
    }

    match (latitude, longitude, timezone, label) {
        (Some(latitude), Some(longitude), Some(timezone), Some(label)) => Ok(LocationIn {
            latitude,
            longitude,
            timezone,
            label,
        }),
        _ => Err(BodyError::Invalid(errors)),
    }
}

/// 422 `{"detail": [{"loc": [...], "msg": "..."}, ...]}`
pub fn errors_json(errors: &[FieldError]) -> Value {
    let detail = errors
        .iter()
        .map(|e| {
            let loc = e
                .loc
                .iter()
                .map(|part| match part {
                    LocPart::Name(name) => Value::String(name.to_string()),
                    LocPart::Pos(pos) => Value::from(*pos),
                })
                .collect::<Vec<_>>();
            json!({ "loc": loc, "msg": e.msg })
        })
        .collect::<Vec<_>>();
    json!({ "detail": detail })
}

/// A one-entry 422 error for the whole body (missing, non-object, …).
fn body_error(msg: &'static str) -> FieldError {
    FieldError {
        loc: vec![LocPart::Name("body")],
        msg,
    }
}

/// A one-entry 422 error for a single field.
fn field_error(name: &'static str, msg: &'static str) -> FieldError {
    FieldError {
        loc: vec![LocPart::Name("body"), LocPart::Name(name)],
        msg,
    }
}

/// Coordinate check: missing, not a number (or not finite) or out of range
/// are errors; the bounds are included.
fn check_coordinate(
    raw: Option<&Value>,
    min: f64,
    max: f64,
    name: &'static str,
    errors: &mut Vec<FieldError>,
) -> Option<f64> {
    let Some(raw) = raw else {
        errors.push(field_error(name, "Field required"));
        return None;
    };
    let Some(x) = pyfmt::py_float(raw).filter(|x| x.is_finite()) else {
        errors.push(field_error(name, "Input should be a valid number"));
        return None;
    };
    if x < min || x > max {
        errors.push(field_error(
            name,
            "Input should be a number between the allowed bounds",
        ));
        return None;
    }
    Some(x)
}

#[derive(Clone, Debug, PartialEq)]
pub enum BodyError {
    /// 422 with these entries.
    Invalid(Vec<FieldError>),
    /// 400 `{"detail": "There was an error parsing the body"}` (not UTF-8).
    Unparseable,
}

impl std::fmt::Display for BodyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BodyError::Invalid(errors) => {
                write!(f, "invalid request body: {} field error(s)", errors.len())
            }
            BodyError::Unparseable => write!(f, "invalid request body: not valid UTF-8"),
        }
    }
}

impl std::error::Error for BodyError {}

/// The character offset where a serde_json error occurred (serde counts
/// lines and byte columns; at the end of the input the offset is one past
/// the last character).
fn json_error_pos(text: &str, err: &serde_json::Error) -> usize {
    if err.is_eof() {
        return text.chars().count();
    }
    let line_start: usize = text
        .split_inclusive('\n')
        .take(err.line().saturating_sub(1))
        .map(str::len)
        .sum();
    let byte = line_start + err.column().saturating_sub(1);
    text.char_indices().take_while(|(i, _)| *i < byte).count()
}

/// JSON content type: `application/json` or `application/<something>+json`
/// (any case, parameters ignored).
fn is_json_content_type(value: Option<&str>) -> bool {
    let Some(value) = value else {
        return false;
    };
    let media = value
        .split(';')
        .next()
        .unwrap_or("")
        .trim()
        .to_ascii_lowercase();
    match media.strip_prefix("application/") {
        Some(sub) => sub == "json" || sub.ends_with("+json"),
        None => false,
    }
}

#[cfg(test)]
mod tests;
