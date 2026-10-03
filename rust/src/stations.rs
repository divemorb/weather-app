//! The weather stations behind the data (Python `app/stations.py`).
//!
//! Pure parsers that name the observation stations in Bright Sky payloads:
//! the station a `/current_weather` payload's values come from
//! (`weather.source_id`) and, per value, the station Bright Sky took it
//! from instead (`weather.fallback_source_ids`) — for `GET /api/now` (P1);
//! and the stations the `/weather` backfill's observations came from — for
//! `GET /api/model-accuracy` (P2).
//!
//! Payloads are untrusted: entries may miss keys or carry them mistyped
//! (and older Bright Sky payloads have no `sources` key at all). A missing
//! (or mistyped) key is `None` (null in JSON) — never an error, never a panic.

use std::collections::{BTreeMap, HashMap};

use chrono::{DateTime, Utc};
use serde_json::{Map, Value, json};

use crate::times::parse_iso;

/// One listed `sources` entry as the API's `station` shape (Python
/// `parse_station`): `name` / `dwd_station_id` from `station_name` /
/// `dwd_station_id`, the rest from `distance` / `lat` / `lon` / `height`.
#[derive(Clone, Debug, PartialEq)]
pub struct Station {
    pub name: Option<String>,
    /// The number as the payload carried it (5837.0 stays a float, 5837 an
    /// int) — the contract compares types strictly.
    pub distance_m: Option<Value>,
    pub lat: Option<Value>,
    pub lon: Option<Value>,
    pub height_m: Option<Value>,
    pub dwd_station_id: Option<String>,
}

/// A fallback source as the API's `fallback` shape (name + distance,
/// Python `_fallback_entry`).
#[derive(Clone, Debug, PartialEq)]
pub struct FallbackEntry {
    pub name: Option<String>,
    pub distance_m: Option<Value>,
}

/// One backfill station as the stored entry and the API's `stations`
/// shape (Python `_observation_entry`): no `height_m`, plus `hours`.
#[derive(Clone, Debug, PartialEq)]
pub struct ObsStation {
    pub name: Option<String>,
    pub distance_m: Option<Value>,
    pub lat: Option<Value>,
    pub lon: Option<Value>,
    pub dwd_station_id: Option<String>,
    pub hours: u64,
}

/// Bright Sky field -> the `/api/now` field it becomes (Python
/// `CURRENT_FIELDS`); fields the API doesn't carry are absent, so a
/// fallback for them is left out of the response.
pub const CURRENT_FIELDS: [(&str, &str); 12] = [
    ("temperature", "temperature_c"),
    ("wind_speed_10", "wind_speed_ms"),
    ("wind_direction_10", "wind_direction_deg"),
    ("wind_gust_speed_60", "wind_gust_ms"),
    ("cloud_cover", "cloud_cover_pct"),
    ("relative_humidity", "humidity_pct"),
    ("pressure_msl", "pressure_hpa"),
    ("dew_point", "dew_point_c"),
    ("precipitation_10", "precipitation_10mm"),
    ("precipitation_30", "precipitation_30mm"),
    ("precipitation_60", "precipitation_60mm"),
    ("condition", "condition"),
];

/// The `app_meta` key holding the observation stations of the last
/// successful backfill, as canonical JSON (Python `OBSERVATION_STATIONS_KEY`).
pub const OBSERVATION_STATIONS_KEY: &str = "observation_stations";

/// A JSON string or None (Python `_as_str`).
fn as_str(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str).map(str::to_string)
}

/// A JSON number (int or float; a bool is not one) or None (Python
/// `_as_number`), kept as the payload carried it (an int stays an int).
fn as_number(v: Option<&Value>) -> Option<Value> {
    v.filter(|v| v.is_number()).cloned()
}

/// A JSON integer (a bool is not one, nor is a float) as `i128` (Python
/// `_is_id`).
fn as_int_id(v: Option<&Value>) -> Option<i128> {
    let Value::Number(n) = v? else {
        return None;
    };
    if n.is_i64() {
        n.as_i64().map(|i| i as i128)
    } else if n.is_u64() {
        n.as_u64().map(|u| u as i128)
    } else {
        None
    }
}

/// One listed `sources` entry as the API's `station` shape (Python
/// `parse_station`); a missing (or mistyped) key is None.
pub fn parse_station(source: &Value) -> Station {
    let obj = source.as_object();
    Station {
        name: as_str(obj.and_then(|o| o.get("station_name"))),
        distance_m: as_number(obj.and_then(|o| o.get("distance"))),
        lat: as_number(obj.and_then(|o| o.get("lat"))),
        lon: as_number(obj.and_then(|o| o.get("lon"))),
        height_m: as_number(obj.and_then(|o| o.get("height"))),
        dwd_station_id: as_str(obj.and_then(|o| o.get("dwd_station_id"))),
    }
}

/// The `station` and `fallback` of a raw `/current_weather` payload
/// (Python `station_and_fallback`): `station` is the listed source whose
/// `id` equals `weather.source_id` (None when no such source is listed);
/// `fallback` maps, for each value the API carries, the API's field name
/// to the listed source Bright Sky took it from instead
/// (`weather.fallback_source_ids`, see [`CURRENT_FIELDS`]); unlisted ids
/// are left out (empty when nothing fell back).
pub fn station_and_fallback(payload: &Value) -> (Option<Station>, BTreeMap<String, FallbackEntry>) {
    let Some(obj) = payload.as_object() else {
        return (None, BTreeMap::new());
    };
    let weather = obj.get("weather").and_then(Value::as_object);
    let sources: Vec<&Value> = obj
        .get("sources")
        .and_then(Value::as_array)
        .map(|list| list.iter().filter(|s| s.is_object()).collect())
        .unwrap_or_default();
    // Python `{s["id"]: s for s in sources if _is_id(s.get("id"))}`: only
    // sources with an integer id are listed, a duplicate id keeps one entry
    // (later wins).
    let mut by_id: HashMap<i128, &Value> = HashMap::new();
    for s in &sources {
        let Some(key) = s.as_object().and_then(|o| as_int_id(o.get("id"))) else {
            continue;
        };
        by_id.insert(key, s);
    }
    let station = weather
        .and_then(|w| as_int_id(w.get("source_id")))
        .and_then(|key| by_id.get(&key).map(|s| parse_station(s)));

    let mut fallback: BTreeMap<String, FallbackEntry> = BTreeMap::new();
    let raw_fallback = weather
        .and_then(|w| w.get("fallback_source_ids"))
        .and_then(Value::as_object);
    if let Some(raw_fallback) = raw_fallback {
        for (bs_key, api_key) in CURRENT_FIELDS {
            let Some(fid) = as_int_id(raw_fallback.get(bs_key)) else {
                continue;
            };
            let Some(src) = by_id.get(&fid) else {
                continue;
            };
            let Some(o) = src.as_object() else {
                continue;
            };
            fallback.insert(
                api_key.to_string(),
                FallbackEntry {
                    name: as_str(o.get("station_name")),
                    distance_m: as_number(o.get("distance")),
                },
            );
        }
    }
    (station, fallback)
}

// P2: the observation stations behind the accuracy table

/// The `id` of a `sources` entry or a `weather` record as a lookup key:
/// the id's JSON text, so a missing id matches a missing `source_id`
/// exactly as in Python (`None == None`).
fn id_key(v: Option<&Value>) -> String {
    v.unwrap_or(&Value::Null).to_string()
}

fn observation_entry(source: &Value, hours: u64) -> ObsStation {
    let obj = source.as_object();
    ObsStation {
        name: as_str(obj.and_then(|o| o.get("station_name"))),
        distance_m: as_number(obj.and_then(|o| o.get("distance"))),
        lat: as_number(obj.and_then(|o| o.get("lat"))),
        lon: as_number(obj.and_then(|o| o.get("lon"))),
        dwd_station_id: as_str(obj.and_then(|o| o.get("dwd_station_id"))),
        hours,
    }
}

/// The stations a `/weather` payload's observations came from (Python
/// `observation_stations`).
///
/// Counts the records exactly as `parse_hourly_observations` keeps them
/// (known source, `observation_type != "forecast"`, precipitation not null,
/// `timestamp <= now`) and returns one entry per source with a kept
/// record, sorted nearest first, no-distance last, then by name. Missing
/// or mistyped entry keys are None (null in JSON); nothing raises.
pub fn observation_stations(payload: &Value, now: DateTime<Utc>) -> Vec<ObsStation> {
    let Some(obj) = payload.as_object() else {
        return Vec::new();
    };
    // Python's `by_id` is an insertion-ordered dict in which later entries
    // win (a duplicate id keeps its first position): `order` holds the
    // distinct id keys in first-seen order, `by_id` the winning entry.
    let mut order: Vec<String> = Vec::new();
    let mut by_id: HashMap<String, &Value> = HashMap::new();
    for s in obj
        .get("sources")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let Some(entry) = s.as_object() else {
            continue;
        };
        let key = id_key(entry.get("id"));
        if !by_id.contains_key(&key) {
            order.push(key.clone());
        }
        by_id.insert(key, s);
    }
    let mut hours: HashMap<String, u64> = HashMap::new();
    for rec in obj
        .get("weather")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let Some(rec) = rec.as_object() else {
            continue;
        };
        let key = id_key(rec.get("source_id"));
        let Some(source) = by_id.get(&key) else {
            continue;
        };
        if source.get("observation_type").and_then(Value::as_str) == Some("forecast") {
            continue;
        }
        // Python checks `is None` only: a mistyped precipitation still
        // counts (unlike `parse_hourly_observations`, which errors there).
        if rec.get("precipitation").is_none_or(Value::is_null) {
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
        *hours.entry(key).or_default() += 1;
    }
    let mut entries: Vec<ObsStation> = Vec::new();
    for key in &order {
        if let (Some(&h), Some(source)) = (hours.get(key), by_id.get(key)) {
            entries.push(observation_entry(source, h));
        }
    }
    // Python: sorted by (distance missing, distance or 0.0, name or "");
    // the stable sort keeps payload order for full ties.
    entries.sort_by(|a, b| {
        let key = |e: &ObsStation| {
            (
                e.distance_m.is_none(),
                e.distance_m.as_ref().and_then(Value::as_f64).unwrap_or(0.0),
                e.name.clone().unwrap_or_default(),
            )
        };
        let (a, b) = (key(a), key(b));
        a.0.cmp(&b.0)
            .then_with(|| a.1.total_cmp(&b.1))
            .then_with(|| a.2.cmp(&b.2))
    });
    entries
}

/// One stored entry as its JSON object (all six keys, a missing field as
/// null) — the shape both the stored value and the API answer in.
pub fn observation_entry_json(e: &ObsStation) -> Value {
    json!({
        "name": e.name,
        "distance_m": e.distance_m,
        "lat": e.lat,
        "lon": e.lon,
        "dwd_station_id": e.dwd_station_id,
        "hours": e.hours,
    })
}

/// The canonical JSON stored under [`OBSERVATION_STATIONS_KEY`] (Python
/// `stations_to_json`): sorted keys, compact separators, raw UTF-8 — the
/// Python backend writes the same bytes.
pub fn stations_to_json(stations: &[ObsStation]) -> String {
    let list: Vec<Value> = stations.iter().map(observation_entry_json).collect();
    Value::Array(list).to_string()
}

/// One stored entry: the six keys with their types (Python
/// `_stored_entry_ok`; a missing key is null, extra keys are ignored).
fn stored_entry_ok(e: &Map<String, Value>) -> bool {
    if e.get("name")
        .is_some_and(|v| !v.is_null() && !v.is_string())
    {
        return false;
    }
    for k in ["distance_m", "lat", "lon"] {
        if matches!(e.get(k), Some(v) if !v.is_null() && !v.is_number()) {
            return false;
        }
    }
    if e.get("dwd_station_id")
        .is_some_and(|v| !v.is_null() && !v.is_string())
    {
        return false;
    }
    match e.get("hours") {
        Some(Value::Number(n)) if n.is_i64() && n.as_i64().is_some_and(|i| i >= 0) => true,
        Some(Value::Number(n)) if n.is_u64() => true,
        _ => false,
    }
}

/// The stored value back to a list, or `[]` (Python `stations_from_json`).
///
/// A JSON list of stored entries (name / dwd_station_id: string or null;
/// distance_m / lat / lon: number or null; hours: non-negative integer);
/// anything else — bad JSON, wrong shape, a mistyped field — reads as
/// `[]` so a broken value never breaks the page.
pub fn stations_from_json(text: Option<&str>) -> Vec<ObsStation> {
    let Some(text) = text else {
        return Vec::new();
    };
    let Ok(data) = serde_json::from_str::<Value>(text) else {
        return Vec::new();
    };
    let Some(list) = data.as_array() else {
        return Vec::new();
    };
    let mut out: Vec<ObsStation> = Vec::new();
    for e in list {
        let Some(obj) = e.as_object() else {
            return Vec::new();
        };
        if !stored_entry_ok(obj) {
            return Vec::new();
        }
        out.push(ObsStation {
            name: as_str(obj.get("name")),
            distance_m: as_number(obj.get("distance_m")),
            lat: as_number(obj.get("lat")),
            lon: as_number(obj.get("lon")),
            dwd_station_id: as_str(obj.get("dwd_station_id")),
            hours: obj.get("hours").and_then(Value::as_u64).unwrap_or(0),
        });
    }
    out
}

/// The `station` field of `GET /api/now` as JSON (all six keys, a missing
/// field as null), or null.
pub fn station_json(s: Option<&Station>) -> Value {
    let Some(s) = s else {
        return Value::Null;
    };
    json!({
        "name": s.name,
        "distance_m": s.distance_m,
        "lat": s.lat,
        "lon": s.lon,
        "height_m": s.height_m,
        "dwd_station_id": s.dwd_station_id,
    })
}

/// One `fallback` entry as JSON (name + distance, a missing field as
/// null).
pub fn fallback_entry_json(e: &FallbackEntry) -> Value {
    json!({
        "name": e.name,
        "distance_m": e.distance_m,
    })
}

#[cfg(test)]
mod tests;
