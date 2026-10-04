//! Pure serializers that turn aggregator results into API-ready JSON
//! (Python `app/api_serializers.py`).
//!
//! All timestamps are UTC ISO-8601 (`...Z`); the frontend converts to the
//! configured display timezone.

use std::collections::BTreeMap;

use serde_json::{Map, Value, json};

use crate::accuracy::ModelAccuracy;
use crate::models::{CurrentConditions, RainProbability};
use crate::pyfmt::py_round;
use crate::series::{RadarBar, Series24h};
use crate::stations::{
    FallbackEntry, ObsStation, Station, fallback_entry_json, observation_entry_json, station_json,
};

/// Freshness of one cached source (Python `Aggregator.cache_meta`).
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CacheMeta {
    pub available: bool,
    pub age_seconds: Option<i64>,
    pub stale: bool,
}

/// Python `_cache_meta`: normalize an optional cache meta into the response
/// fields. Without a cached source at all the result is
/// `{"available": false, "age_seconds": null, "stale": false}`.
fn cache_meta(meta: Option<&CacheMeta>) -> Map<String, Value> {
    let m = meta.unwrap_or(&CacheMeta {
        available: false,
        age_seconds: None,
        stale: false,
    });
    let mut out = Map::new();
    out.insert("available".into(), Value::Bool(m.available));
    out.insert(
        "age_seconds".into(),
        m.age_seconds.map(Value::from).unwrap_or(Value::Null),
    );
    out.insert("stale".into(), Value::Bool(m.stale));
    out
}

/// Shape the 'Now' tile (`GET /api/now`).
///
/// `available` is false when there is no cached observation yet; the
/// `conditions` object is then null and the frontend renders an empty
/// state. `station` / `fallback` name the station the values come from
/// and, per value, the station Bright Sky took it from instead.
pub fn serialize_now(
    conditions: Option<&CurrentConditions>,
    meta: Option<&CacheMeta>,
    station: Option<&Station>,
    fallback: &BTreeMap<String, FallbackEntry>,
) -> Value {
    // Python returns the fixed "no cached observation" shape and ignores
    // `meta` when there are no conditions.
    let Some(conditions) = conditions else {
        return json!({
            "available": false,
            "age_seconds": null,
            "stale": false,
            "conditions": null,
        });
    };
    let mut out = cache_meta(meta);
    out.insert(
        "conditions".into(),
        conditions_json(conditions, station, fallback),
    );
    Value::Object(out)
}

fn conditions_json(
    c: &CurrentConditions,
    station: Option<&Station>,
    fallback: &BTreeMap<String, FallbackEntry>,
) -> Value {
    let fallback: Map<String, Value> = fallback
        .iter()
        .map(|(field, entry)| (field.clone(), fallback_entry_json(entry)))
        .collect();
    json!({
        "timestamp_utc": c.timestamp_utc,
        "temperature_c": c.temperature_c,
        "feels_like_c": c.feels_like_c,
        "wind_speed_ms": c.wind_speed_ms,
        "wind_direction_deg": c.wind_direction_deg,
        "wind_gust_ms": c.wind_gust_ms,
        "cloud_cover_pct": c.cloud_cover_pct,
        "humidity_pct": c.humidity_pct,
        "pressure_hpa": c.pressure_hpa,
        "dew_point_c": c.dew_point_c,
        "precipitation_10mm": c.precipitation_10mm,
        "precipitation_30mm": c.precipitation_30mm,
        "precipitation_60mm": c.precipitation_60mm,
        "condition": c.condition,
        "source_id": c.source_id,
        "station": station_json(station),
        "fallback": Value::Object(fallback),
    })
}

/// Shape the headline rain probability (`GET /api/rain-probability`).
///
/// Includes the per-signal data age (radar + models) so the UI can show how
/// fresh the underlying data is without a second round-trip to
/// `/api/sources`.
pub fn serialize_rain_probability(
    rain: &RainProbability,
    radar_meta: Option<&CacheMeta>,
    models_meta: Option<&CacheMeta>,
) -> Value {
    let weights = rain
        .weights_used
        .iter()
        .map(|(name, weight)| (name.clone(), Value::from(*weight)))
        .collect();
    json!({
        "probability_pct": rain.probability_pct,
        "explanation": rain.explanation,
        "radar_available": rain.radar_available,
        "radar_raining": rain.radar_raining,
        "models_rain_count": rain.models_rain_count,
        "models_total": rain.models_total,
        "ensemble_pct": rain.ensemble_pct,
        "weights_used": Value::Object(weights),
        "accuracy_weighted": rain.accuracy_weighted,
        "radar_age_seconds": radar_meta.and_then(|m| m.age_seconds),
        "models_age_seconds": models_meta.and_then(|m| m.age_seconds),
    })
}

/// Shape the 60-minute radar bar (`GET /api/radar/next-hour`).
///
/// Passes through the pure `build_radar_next_hour_bar` result and adds the
/// radar cache freshness so the frontend can flag a stale nowcast.
pub fn serialize_radar_next_hour(bar: &RadarBar, meta: Option<&CacheMeta>) -> Value {
    let mut out = cache_meta(meta);
    out.insert("available".into(), Value::Bool(bar.available));
    out.insert(
        "steps".into(),
        Value::Array(
            bar.steps
                .iter()
                .map(|s| {
                    json!({
                        "start_utc": s.start_utc,
                        "precip_mm": s.precip_mm,
                    })
                })
                .collect(),
        ),
    );
    Value::Object(out)
}

/// Shape the 24 h model comparison (`GET /api/models/24h`).
pub fn serialize_models_24h(series: &Series24h, meta: Option<&CacheMeta>) -> Value {
    let mut out = cache_meta(meta);
    out.insert(
        "hours".into(),
        Value::Array(
            series
                .hours
                .iter()
                .map(|h| Value::String(h.clone()))
                .collect(),
        ),
    );
    out.insert(
        "models".into(),
        Value::Array(
            series
                .models
                .iter()
                .map(|m| {
                    json!({
                        "name": m.name,
                        "precipitation_mm": m.precipitation_mm,
                    })
                })
                .collect(),
        ),
    );
    out.insert("n_models".into(), Value::from(series.n_models));
    Value::Object(out)
}

/// Shape the per-model accuracy (`GET /api/model-accuracy`).
///
/// Each entry gains `enough_data` = `n_samples >= min_samples` so the UI can
/// grey out models that have not accumulated enough compared hours.
/// `stations` lists the observation stations behind the table, nearest
/// first; `[]` while the backfill has not remembered any.
pub fn serialize_model_accuracy(
    models: &BTreeMap<String, ModelAccuracy>,
    window_days: i64,
    min_samples: i64,
    stations: &[ObsStation],
) -> Value {
    let mut serialized: Map<String, Value> = Map::new();
    for (name, stats) in models {
        let n = stats.n_samples;
        let mut entry: Map<String, Value> = Map::new();
        entry.insert("n_samples".into(), Value::from(n));
        entry.insert("hits".into(), Value::from(stats.hits));
        entry.insert("misses".into(), Value::from(stats.misses));
        entry.insert("false_alarms".into(), Value::from(stats.false_alarms));
        entry.insert(
            "correct_negatives".into(),
            Value::from(stats.correct_negatives),
        );
        entry.insert("enough_data".into(), Value::Bool(n >= min_samples));
        entry.insert(
            "mae_mm".into(),
            stats
                .mae_mm
                .map(|v| Value::from(py_round(v, 3)))
                .unwrap_or(Value::Null),
        );
        entry.insert(
            "event_accuracy".into(),
            stats
                .event_accuracy
                .map(|v| Value::from(py_round(v, 3)))
                .unwrap_or(Value::Null),
        );
        serialized.insert(name.clone(), Value::Object(entry));
    }
    let stations: Vec<Value> = stations.iter().map(observation_entry_json).collect();
    json!({
        "window_days": window_days,
        "min_samples": min_samples,
        "models": Value::Object(serialized),
        "stations": Value::Array(stations),
    })
}

#[cfg(test)]
mod tests;
