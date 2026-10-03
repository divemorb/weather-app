//! Value helpers for configuration loading: they reproduce Python's
//! `float()`, `int()`, the `_env*` functions and `raw.get(key, {}) or {}`.

use serde_json::Value;

use crate::pyfmt::f64_to_i64;

/// Environment lookup: `&|k| std::env::var(k).ok()` in production, a map in tests.
pub type Env<'a> = &'a dyn Fn(&str) -> Option<String>;

/// Unset and `""` both count as unset.
pub fn env_str(env: Env, name: &str) -> Option<String> {
    env(name).filter(|v| !v.is_empty())
}

/// Parses a float; a bad value is a startup error.
pub fn env_f64(env: Env, name: &str, default: f64) -> Result<f64, String> {
    match env_str(env, name) {
        Some(raw) => raw.trim().parse().map_err(|_| {
            format!("{name}: not a number: {raw:?} (write plain digits, e.g. 10 or 0.5)")
        }),
        None => Ok(default),
    }
}

/// Parses an integer; a bad value is a startup error.
pub fn env_i64(env: Env, name: &str, default: i64) -> Result<i64, String> {
    match env_str(env, name) {
        Some(raw) => raw
            .trim()
            .parse()
            .map_err(|_| format!("{name}: not an integer: {raw:?} (write plain digits, e.g. 10)")),
        None => Ok(default),
    }
}

/// True for "1", "true", "yes", "on" (case-insensitive); anything else
/// false.
pub fn env_bool(env: Env, name: &str, default: bool) -> bool {
    match env_str(env, name) {
        Some(raw) => matches!(
            raw.trim().to_lowercase().as_str(),
            "1" | "true" | "yes" | "on"
        ),
        None => default,
    }
}

/// A YAML value as a float: numbers, numeric strings, bools (1.0/0.0).
pub fn yaml_f64(v: &Value, what: &str) -> Result<f64, String> {
    match v {
        Value::Number(n) => n.as_f64().ok_or_else(|| format!("{what}: bad number")),
        Value::String(s) => s
            .trim()
            .parse()
            .map_err(|_| format!("{what}: not a number: {s:?}")),
        Value::Bool(b) => Ok(if *b { 1.0 } else { 0.0 }),
        _ => Err(format!("{what}: expected a number, got {v}")),
    }
}

/// A YAML value as an integer: ints, floats truncated toward zero, integer
/// strings, bools (1/0).
pub fn yaml_i64(v: &Value, what: &str) -> Result<i64, String> {
    match v {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_f64().and_then(f64_to_i64))
            .ok_or_else(|| format!("{what}: bad number")),
        Value::String(s) => s
            .trim()
            .parse()
            .map_err(|_| format!("{what}: not an integer: {s:?}")),
        Value::Bool(b) => Ok(i64::from(*b)),
        _ => Err(format!("{what}: expected an integer, got {v}")),
    }
}

/// A missing or null section is empty; a section that isn't a mapping is an
/// error.
pub fn section<'a>(
    raw: &'a Value,
    key: &str,
) -> Result<Option<&'a serde_json::Map<String, Value>>, String> {
    match raw.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Object(map)) => Ok(Some(map)),
        Some(other) => Err(format!(
            "config section {key:?} must be a mapping, got {other}"
        )),
    }
}

/// Like `section`, but for a subsection of an already resolved mapping.
pub fn subsec<'a>(
    sec: Option<&'a serde_json::Map<String, Value>>,
    key: &str,
) -> Result<Option<&'a serde_json::Map<String, Value>>, String> {
    match sec.and_then(|m| m.get(key)) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::Object(map)) => Ok(Some(map)),
        Some(other) => Err(format!(
            "config section {key:?} must be a mapping, got {other}"
        )),
    }
}

/// The section's value for `key` as a float (`default` when absent).
pub fn get_f64(
    sec: Option<&serde_json::Map<String, Value>>,
    key: &str,
    default: f64,
) -> Result<f64, String> {
    match sec.and_then(|m| m.get(key)) {
        Some(v) => yaml_f64(v, key),
        None => Ok(default),
    }
}

/// The section's value for `key` as an integer (`default` when absent).
pub fn get_i64(
    sec: Option<&serde_json::Map<String, Value>>,
    key: &str,
    default: i64,
) -> Result<i64, String> {
    match sec.and_then(|m| m.get(key)) {
        Some(v) => yaml_i64(v, key),
        None => Ok(default),
    }
}

/// The section's value for `key` as a string: a missing or null key is the
/// default, anything that is not a string is an error.
pub fn get_str(
    sec: Option<&serde_json::Map<String, Value>>,
    key: &str,
    default: &str,
) -> Result<String, String> {
    match sec.and_then(|m| m.get(key)) {
        Some(Value::String(s)) => Ok(s.clone()),
        None | Some(Value::Null) => Ok(default.to_string()),
        Some(other) => Err(format!("{key}: expected a string, got {other}")),
    }
}
