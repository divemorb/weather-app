use super::*;
use crate::models::{CurrentConditions, RainProbability};
use crate::series::{ModelHours, RadarBar, RadarStep, Series24h};

/// The Python tests' `META_FRESH`.
fn meta_fresh() -> CacheMeta {
    CacheMeta {
        available: true,
        age_seconds: Some(12),
        stale: false,
    }
}

/// The Python tests' `make_conditions`.
fn make_conditions() -> CurrentConditions {
    CurrentConditions {
        timestamp_utc: json!("2025-01-01T12:00:00Z"),
        source_id: json!(1),
        temperature_c: Some(5.0),
        feels_like_c: Some(3.5),
        wind_speed_ms: Some(3.0),
        wind_direction_deg: None,
        wind_gust_ms: None,
        cloud_cover_pct: Some(75.0),
        humidity_pct: None,
        pressure_hpa: None,
        dew_point_c: None,
        precipitation_10mm: None,
        precipitation_30mm: None,
        precipitation_60mm: None,
        condition: json!("Rain"),
    }
}

/// The Python tests' `make_rain`.
fn make_rain() -> RainProbability {
    RainProbability {
        probability_pct: 75.0,
        radar_available: true,
        radar_raining: Some(true),
        models_rain_count: 1,
        models_total: 2,
        ensemble_pct: Some(50.0),
        weights_used: vec![("radar".to_string(), 0.5)],
        explanation: "Radar: yes; 1 of 2 models; ensemble 50 %".to_string(),
    }
}

// ---------------------------------------------------------------------------
// serialize_now
// ---------------------------------------------------------------------------
#[test]
fn now_with_conditions() {
    let conditions = make_conditions();
    let meta = meta_fresh();
    assert_eq!(
        serialize_now(Some(&conditions), Some(&meta)),
        json!({
            "available": true,
            "age_seconds": 12,
            "stale": false,
            "conditions": {
                "timestamp_utc": "2025-01-01T12:00:00Z",
                "temperature_c": 5.0,
                "feels_like_c": 3.5,
                "wind_speed_ms": 3.0,
                "wind_direction_deg": null,
                "wind_gust_ms": null,
                "cloud_cover_pct": 75.0,
                "humidity_pct": null,
                "pressure_hpa": null,
                "dew_point_c": null,
                "precipitation_10mm": null,
                "precipitation_30mm": null,
                "precipitation_60mm": null,
                "condition": "Rain",
                "source_id": 1,
            },
        })
    );
}

#[test]
fn now_missing_conditions_is_null() {
    assert_eq!(
        serialize_now(None, None),
        json!({
            "available": false,
            "age_seconds": null,
            "stale": false,
            "conditions": null,
        })
    );
}

/// Python `serialize_now(None, meta)` ignores `meta` and always answers the
/// fixed "no cached observation" shape (review R17b).
#[test]
fn now_missing_conditions_ignores_meta() {
    assert_eq!(
        serialize_now(
            None,
            Some(&CacheMeta {
                available: true,
                age_seconds: Some(42),
                stale: false,
            })
        ),
        json!({
            "available": false,
            "age_seconds": null,
            "stale": false,
            "conditions": null,
        })
    );
}

// ---------------------------------------------------------------------------
// serialize_rain_probability
// ---------------------------------------------------------------------------
#[test]
fn rain_probability_full() {
    let rain = make_rain();
    let meta = meta_fresh();
    assert_eq!(
        serialize_rain_probability(&rain, Some(&meta), Some(&meta)),
        json!({
            "probability_pct": 75.0,
            "explanation": "Radar: yes; 1 of 2 models; ensemble 50 %",
            "radar_available": true,
            "radar_raining": true,
            "models_rain_count": 1,
            "models_total": 2,
            "ensemble_pct": 50.0,
            "weights_used": {"radar": 0.5},
            "radar_age_seconds": 12,
            "models_age_seconds": 12,
        })
    );
}

#[test]
fn rain_probability_none_meta_yields_none_ages() {
    let rain = make_rain();
    let body = serialize_rain_probability(&rain, None, None);
    assert_eq!(body["radar_age_seconds"], json!(null));
    assert_eq!(body["models_age_seconds"], json!(null));
}

// ---------------------------------------------------------------------------
// serialize_radar_next_hour
// ---------------------------------------------------------------------------
#[test]
fn radar_bar_full() {
    let bar = RadarBar {
        available: true,
        steps: vec![RadarStep {
            start_utc: "2025-01-01T12:00:00Z".to_string(),
            precip_mm: 0.2,
        }],
    };
    assert_eq!(
        serialize_radar_next_hour(&bar, Some(&meta_fresh())),
        json!({
            "available": true,
            "age_seconds": 12,
            "stale": false,
            "steps": [{"start_utc": "2025-01-01T12:00:00Z", "precip_mm": 0.2}],
        })
    );
}

#[test]
fn radar_bar_unavailable() {
    let bar = RadarBar {
        available: false,
        steps: vec![],
    };
    assert_eq!(
        serialize_radar_next_hour(&bar, None),
        json!({
            "available": false,
            "age_seconds": null,
            "stale": false,
            "steps": [],
        })
    );
}

// ---------------------------------------------------------------------------
// serialize_models_24h
// ---------------------------------------------------------------------------
#[test]
fn models_24h_full() {
    let series = Series24h {
        hours: vec!["2025-01-01T12:00:00Z".to_string()],
        models: vec![ModelHours {
            name: "icon_d2".to_string(),
            precipitation_mm: vec![Some(0.4)],
        }],
        n_models: 1,
    };
    assert_eq!(
        serialize_models_24h(&series, Some(&meta_fresh())),
        json!({
            "available": true,
            "age_seconds": 12,
            "stale": false,
            "hours": ["2025-01-01T12:00:00Z"],
            "models": [{"name": "icon_d2", "precipitation_mm": [0.4]}],
            "n_models": 1,
        })
    );
}

#[test]
fn models_24h_empty() {
    assert_eq!(
        serialize_models_24h(&Series24h::default(), None),
        json!({
            "available": false,
            "age_seconds": null,
            "stale": false,
            "hours": [],
            "models": [],
            "n_models": 0,
        })
    );
}

// ---------------------------------------------------------------------------
// serialize_model_accuracy
// ---------------------------------------------------------------------------
#[test]
fn model_accuracy_full() {
    let mut models: BTreeMap<String, ModelAccuracy> = BTreeMap::new();
    models.insert(
        "icon_d2".to_string(),
        ModelAccuracy {
            n_samples: 100,
            mae_mm: Some(0.205),
            hits: 20,
            misses: 10,
            false_alarms: 15,
            correct_negatives: 55,
            event_accuracy: Some(0.75),
        },
    );
    models.insert(
        "gfs_seamless".to_string(),
        ModelAccuracy {
            n_samples: 10,
            mae_mm: Some(0.4),
            hits: 2,
            misses: 3,
            false_alarms: 2,
            correct_negatives: 3,
            event_accuracy: Some(0.5),
        },
    );
    assert_eq!(
        serialize_model_accuracy(&models, 30, 48),
        json!({
            "window_days": 30,
            "min_samples": 48,
            "models": {
                "icon_d2": {
                    "n_samples": 100,
                    "hits": 20,
                    "misses": 10,
                    "false_alarms": 15,
                    "correct_negatives": 55,
                    "enough_data": true,
                    "mae_mm": 0.205,
                    "event_accuracy": 0.75,
                },
                "gfs_seamless": {
                    "n_samples": 10,
                    "hits": 2,
                    "misses": 3,
                    "false_alarms": 2,
                    "correct_negatives": 3,
                    "enough_data": false,
                    "mae_mm": 0.4,
                    "event_accuracy": 0.5,
                },
            },
        })
    );
}

#[test]
fn model_accuracy_empty() {
    assert_eq!(
        serialize_model_accuracy(&BTreeMap::new(), 30, 48),
        json!({"window_days": 30, "min_samples": 48, "models": {}})
    );
}
