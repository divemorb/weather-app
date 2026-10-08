//! User reports: what the sky really looks like ("Stimmt nicht?").
//!
//! The body is a closed set of values (unknown fields and client times are
//! refused); the *server's* clock sets the observation time (later steps
//! store and answer the reports). This step types the boundary: the request
//! body and the path id.

use serde_json::{Map, Value, json};
use std::str::FromStr;

use crate::location;

/// The closed set of report kinds (what the sky looks like).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReportKind {
    Clear,
    PartlyCloudy,
    Cloudy,
    Fog,
    Rain,
    Thunderstorm,
    Snow,
    Hail,
}

impl ReportKind {
    /// The kind's name in the API.
    pub fn as_str(self) -> &'static str {
        match self {
            ReportKind::Clear => "clear",
            ReportKind::PartlyCloudy => "partly-cloudy",
            ReportKind::Cloudy => "cloudy",
            ReportKind::Fog => "fog",
            ReportKind::Rain => "rain",
            ReportKind::Thunderstorm => "thunderstorm",
            ReportKind::Snow => "snow",
            ReportKind::Hail => "hail",
        }
    }

    /// One of the eight API names, or nothing.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "clear" => Some(ReportKind::Clear),
            "partly-cloudy" => Some(ReportKind::PartlyCloudy),
            "cloudy" => Some(ReportKind::Cloudy),
            "fog" => Some(ReportKind::Fog),
            "rain" => Some(ReportKind::Rain),
            "thunderstorm" => Some(ReportKind::Thunderstorm),
            "snow" => Some(ReportKind::Snow),
            "hail" => Some(ReportKind::Hail),
            _ => None,
        }
    }

    /// The kinds where what the user sees is wet.
    pub fn is_wet(self) -> bool {
        match self {
            ReportKind::Rain | ReportKind::Thunderstorm | ReportKind::Snow | ReportKind::Hail => {
                true
            }
            ReportKind::Clear | ReportKind::PartlyCloudy | ReportKind::Cloudy | ReportKind::Fog => {
                false
            }
        }
    }
}

/// Rain intensity; may only be reported with `kind = "rain"`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Intensity {
    Light,
    Moderate,
    Heavy,
}

impl Intensity {
    /// The intensity's name in the API.
    pub fn as_str(self) -> &'static str {
        match self {
            Intensity::Light => "light",
            Intensity::Moderate => "moderate",
            Intensity::Heavy => "heavy",
        }
    }

    /// One of the three API names, or nothing.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "light" => Some(Intensity::Light),
            "moderate" => Some(Intensity::Moderate),
            "heavy" => Some(Intensity::Heavy),
            _ => None,
        }
    }
}

/// How far back the observation is (a closed set of whole minutes).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MinutesAgo(i64);

impl MinutesAgo {
    /// The observation is right now (no offset).
    const NOW: MinutesAgo = MinutesAgo(0);

    /// Only 0, 15 and 30 minutes are accepted.
    pub fn new(minutes: i64) -> Option<Self> {
        if minutes == 0 || minutes == 15 || minutes == 30 {
            Some(MinutesAgo(minutes))
        } else {
            None
        }
    }

    /// The whole minutes.
    pub fn minutes(self) -> i64 {
        self.0
    }
}

/// The validated body of `POST /api/reports` (closed set).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReportIn {
    kind: ReportKind,
    intensity: Option<Intensity>,
    minutes_ago: MinutesAgo,
    confirms: bool,
}

impl ReportIn {
    /// The kind (what the sky looks like).
    pub fn kind(&self) -> ReportKind {
        self.kind
    }

    /// The rain intensity (only with `kind = "rain"`).
    pub fn intensity(&self) -> Option<Intensity> {
        self.intensity
    }

    /// How far back the observation is.
    pub fn minutes_ago(&self) -> MinutesAgo {
        self.minutes_ago
    }

    /// Whether the user confirms the page instead of disputing it.
    pub fn confirms(&self) -> bool {
        self.confirms
    }
}

/// One part of a 422 `loc`: `"body"`, a field name, an unknown field's name
/// (it comes from the input, hence owned) or a position.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Loc {
    Body,
    Field(&'static str),
    Extra(String),
    Pos(usize),
}

/// One entry of a 422 answer: `{"loc": [...], "msg": "..."}`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReportFieldError {
    pub loc: Vec<Loc>,
    pub msg: &'static str,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReportBodyError {
    /// 422 with these entries.
    Invalid(Vec<ReportFieldError>),
    /// 400 `{"detail": "There was an error parsing the body"}` (not UTF-8).
    Unparseable,
}

impl std::fmt::Display for ReportBodyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ReportBodyError::Invalid(errors) => {
                write!(f, "invalid report body: {} field error(s)", errors.len())
            }
            ReportBodyError::Unparseable => write!(f, "invalid report body: not valid UTF-8"),
        }
    }
}

impl std::error::Error for ReportBodyError {}

/// 422 `{"detail": [{"loc": [...], "msg": "..."}, ...]}`
pub fn errors_json(errors: &[ReportFieldError]) -> Value {
    let detail = errors
        .iter()
        .map(|e| {
            let loc = e
                .loc
                .iter()
                .map(|part| match part {
                    Loc::Body => Value::String("body".to_string()),
                    Loc::Field(name) => Value::String((*name).to_string()),
                    Loc::Extra(name) => Value::String(name.clone()),
                    Loc::Pos(pos) => Value::from(*pos),
                })
                .collect::<Vec<_>>();
            json!({ "loc": loc, "msg": e.msg })
        })
        .collect::<Vec<_>>();
    json!({ "detail": detail })
}

/// A one-entry 422 error for the whole body (missing, non-object, …).
fn body_error(msg: &'static str) -> ReportFieldError {
    ReportFieldError {
        loc: vec![Loc::Body],
        msg,
    }
}

/// A one-entry 422 error for a single field.
fn field_error(name: &'static str, msg: &'static str) -> ReportFieldError {
    ReportFieldError {
        loc: vec![Loc::Body, Loc::Field(name)],
        msg,
    }
}

/// Decode and validate the report body, exactly like
/// `location::validate_location_body` (content type, BOM, UTF-8, JSON).
pub fn parse_report_body(
    content_type: Option<&str>,
    body: &[u8],
) -> Result<ReportIn, ReportBodyError> {
    if body.is_empty() || !location::is_json_content_type(content_type) {
        return Err(ReportBodyError::Invalid(vec![body_error("Field required")]));
    }
    let stripped = body.strip_prefix("\u{feff}".as_bytes()).unwrap_or(body);
    let Ok(text) = std::str::from_utf8(stripped) else {
        return Err(ReportBodyError::Unparseable);
    };
    let value = match serde_json::from_str::<Value>(text) {
        Ok(value) => value,
        Err(err) => {
            return Err(ReportBodyError::Invalid(vec![ReportFieldError {
                loc: vec![Loc::Body, Loc::Pos(location::json_error_pos(text, &err))],
                msg: "JSON decode error",
            }]));
        }
    };
    let Some(obj) = value.as_object() else {
        // JSON `null` counts as a missing body; any other non-object is
        // refused (Python's messages).
        let msg = if value.is_null() {
            "Field required"
        } else {
            "Input should be a valid dictionary or object to extract fields from"
        };
        return Err(ReportBodyError::Invalid(vec![body_error(msg)]));
    };
    check_fields(obj)
}

/// The field checks, in Python's order: kind, intensity, minutes_ago,
/// confirms, then the unknown fields.
fn check_fields(obj: &Map<String, Value>) -> Result<ReportIn, ReportBodyError> {
    let mut errors: Vec<ReportFieldError> = Vec::new();

    let kind = match obj.get("kind") {
        None => {
            errors.push(field_error("kind", "Field required"));
            None
        }
        Some(Value::String(s)) => match ReportKind::parse(s) {
            Some(kind) => Some(kind),
            None => {
                errors.push(field_error("kind", KIND_MSG));
                None
            }
        },
        Some(_) => {
            errors.push(field_error("kind", KIND_MSG));
            None
        }
    };

    let mut intensity: Option<Intensity> = None;
    match obj.get("intensity") {
        None | Some(Value::Null) => {}
        Some(Value::String(s)) => match Intensity::parse(s) {
            Some(parsed) => {
                // A valid intensity is only allowed with a valid kind of
                // `rain`; when the kind is missing or invalid, Python's
                // validator sees no kind then.
                if kind != Some(ReportKind::Rain) {
                    errors.push(field_error(
                        "intensity",
                        "Value error, intensity is only reported for rain",
                    ));
                }
                intensity = Some(parsed);
            }
            None => errors.push(field_error("intensity", INTENSITY_MSG)),
        },
        Some(_) => errors.push(field_error("intensity", INTENSITY_MSG)),
    }

    let mut minutes_ago = MinutesAgo::NOW;
    match obj.get("minutes_ago") {
        None => {}
        Some(Value::Number(n)) => match n.as_i64().and_then(MinutesAgo::new) {
            Some(minutes) => minutes_ago = minutes,
            None if n.as_i64().is_some() => {
                errors.push(field_error(
                    "minutes_ago",
                    "Value error, minutes_ago must be 0, 15 or 30",
                ));
            }
            None => errors.push(field_error(
                "minutes_ago",
                "Input should be a valid integer",
            )),
        },
        Some(_) => errors.push(field_error(
            "minutes_ago",
            "Input should be a valid integer",
        )),
    }

    let mut confirms = false;
    match obj.get("confirms") {
        None => {}
        Some(Value::Bool(b)) => confirms = *b,
        Some(_) => errors.push(field_error("confirms", "Input should be a valid boolean")),
    }

    for key in obj.keys() {
        if !["kind", "intensity", "minutes_ago", "confirms"].contains(&key.as_str()) {
            errors.push(ReportFieldError {
                loc: vec![Loc::Body, Loc::Extra(key.clone())],
                msg: "Extra inputs are not permitted",
            });
        }
    }

    // Any error (or a missing kind, which is itself an error) is a 422.
    match (kind, errors.is_empty()) {
        (Some(kind), true) => Ok(ReportIn {
            kind,
            intensity,
            minutes_ago,
            confirms,
        }),
        _ => Err(ReportBodyError::Invalid(errors)),
    }
}

const KIND_MSG: &str = "Input should be 'clear', 'partly-cloudy', 'cloudy', 'fog', 'rain', \
'thunderstorm', 'snow' or 'hail'";
const INTENSITY_MSG: &str = "Input should be 'light', 'moderate' or 'heavy'";

/// `^[1-9][0-9]{0,17}$` (Python's `Path(pattern=...)`), by hand: 1 to 18
/// ASCII digits, the first not `0` (anything else is a 422: `+5`, `05`,
/// ` 5`, 19 digits).
pub fn parse_report_id(raw: &str) -> Option<i64> {
    let bytes = raw.as_bytes();
    if bytes.is_empty() || bytes.len() > 18 {
        return None;
    }
    if !bytes.iter().all(|b| b.is_ascii_digit()) {
        return None;
    }
    if matches!(bytes.first(), Some(b'0')) {
        return None;
    }
    i64::from_str(raw).ok()
}

#[cfg(test)]
mod tests;
