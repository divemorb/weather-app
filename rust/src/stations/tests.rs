//! Unit tests for `crate::stations`.

use std::collections::BTreeMap;

use chrono::{DateTime, Utc};
use serde_json::{Value, json};

use super::*;

fn tempelhof() -> Value {
    json!({
        "id": 96160, "station_name": "Berlin-Tempelhof", "observation_type": "synop",
        "distance": 5837.0, "lat": 52.4676, "lon": 13.402, "height": 47.7,
        "dwd_station_id": "00433",
    })
}

fn potsdam() -> Value {
    json!({
        "id": 11702, "station_name": "Potsdam", "observation_type": "synop",
        "distance": 27915.0, "lat": 52.3813, "lon": 13.0622, "height": 80.9,
        "dwd_station_id": "03987",
    })
}

fn now_payload(sources: Vec<Value>, source_id: Value, fallback: Option<Value>) -> Value {
    let mut weather = json!({"source_id": source_id});
    if let Some(fallback) = fallback {
        weather["fallback_source_ids"] = fallback;
    }
    json!({"weather": weather, "sources": sources})
}

fn tempelhof_station() -> Station {
    Station {
        name: Some("Berlin-Tempelhof".to_string()),
        distance_m: Some(json!(5837.0)),
        lat: Some(json!(52.4676)),
        lon: Some(json!(13.402)),
        height_m: Some(json!(47.7)),
        dwd_station_id: Some("00433".to_string()),
    }
}

fn potsdam_fallback() -> FallbackEntry {
    FallbackEntry {
        name: Some("Potsdam".to_string()),
        distance_m: Some(json!(27915.0)),
    }
}

// /api/now station + fallback

#[test]
fn station_names_the_source_of_the_values() {
    let payload = now_payload(vec![tempelhof(), potsdam()], json!(96160), None);
    let (station, fallback) = station_and_fallback(&payload);
    assert_eq!(station, Some(tempelhof_station()));
    assert!(fallback.is_empty());
}

#[test]
fn station_is_none_without_a_listed_source() {
    // a source id no listed source carries: no station, fallback ids point nowhere
    let payload = now_payload(vec![potsdam()], json!(1), Some(json!({"cloud_cover": 7})));
    assert_eq!(station_and_fallback(&payload), (None, BTreeMap::new()));
    // no sources key at all (older payloads and the test helpers')
    let payload = json!({"weather": {"source_id": 1}});
    assert_eq!(station_and_fallback(&payload), (None, BTreeMap::new()));
    // an empty sources list
    let payload = json!({"weather": {"source_id": 1}, "sources": []});
    assert_eq!(station_and_fallback(&payload), (None, BTreeMap::new()));
}

#[test]
fn station_missing_fields_are_null() {
    let payload = now_payload(
        vec![json!({"id": 96160, "station_name": "Görlitz"})],
        json!(96160),
        None,
    );
    let (station, _) = station_and_fallback(&payload);
    assert_eq!(
        station,
        Some(Station {
            name: Some("Görlitz".to_string()),
            distance_m: None,
            lat: None,
            lon: None,
            height_m: None,
            dwd_station_id: None,
        })
    );
}

#[test]
fn fallback_is_keyed_by_the_api_field_names() {
    let fallback = json!({
        "wind_speed_10": 11702, "cloud_cover": 11702, "precipitation_60": 11702,
        "solar_60": 11702, "dew_point": 424242
    });
    let payload = now_payload(vec![tempelhof(), potsdam()], json!(96160), Some(fallback));
    let (_, fallback) = station_and_fallback(&payload);
    assert_eq!(
        fallback,
        BTreeMap::from([
            ("wind_speed_ms".to_string(), potsdam_fallback()),
            ("cloud_cover_pct".to_string(), potsdam_fallback()),
            ("precipitation_60mm".to_string(), potsdam_fallback()),
        ])
    );
    // solar_60 is not a field the API carries; 424242 is not a listed source
    assert!(!fallback.contains_key("solar_60"));
    assert!(!fallback.contains_key("dew_point_c"));
}

#[test]
fn fallback_every_carried_field_maps_to_its_api_name() {
    for (bs_key, api_key) in CURRENT_FIELDS {
        let payload = now_payload(
            vec![tempelhof(), potsdam()],
            json!(96160),
            Some(json!({bs_key: 11702})),
        );
        let (_, fallback) = station_and_fallback(&payload);
        assert_eq!(
            fallback,
            BTreeMap::from([(api_key.to_string(), potsdam_fallback())])
        );
    }
}

#[test]
fn fallback_mistyped_ids_are_left_out() {
    for bad in [json!("254907"), json!(true), json!(11702.0), json!(null)] {
        let payload = now_payload(
            vec![tempelhof(), potsdam()],
            json!(96160),
            Some(json!({"cloud_cover": bad})),
        );
        let (_, fallback) = station_and_fallback(&payload);
        assert!(fallback.is_empty(), "fallback id {bad} must be left out");
    }
}

#[test]
fn fallback_entry_missing_distance_is_null() {
    let payload = now_payload(
        vec![json!({"id": 11702, "station_name": "Potsdam"})],
        json!(96160),
        Some(json!({"cloud_cover": 11702})),
    );
    let (_, fallback) = station_and_fallback(&payload);
    assert_eq!(
        fallback,
        BTreeMap::from([(
            "cloud_cover_pct".to_string(),
            FallbackEntry {
                name: Some("Potsdam".to_string()),
                distance_m: None,
            }
        )])
    );
}

#[test]
fn station_keeps_the_payload_number_types() {
    // an int distance stays an int (the contract compares 1 and 1.0 strictly)
    let payload = json!({
        "weather": {"source_id": 1},
        "sources": [{"id": 1, "station_name": "S", "distance": 100}],
    });
    let (station, _) = station_and_fallback(&payload);
    assert_eq!(station.unwrap().distance_m, Some(json!(100)));
}

// the observation stations behind the accuracy table

fn at(hour: &str) -> String {
    format!("2025-01-01T{hour}:00Z")
}

fn record(ts: &str, sid: i64, precip: Option<f64>) -> Value {
    json!({"timestamp": at(ts), "source_id": sid, "precipitation": precip})
}

fn friedrichshain() -> Value {
    json!({
        "id": 312070, "station_name": "Berlin-Friedrichshain/Spree",
        "observation_type": "historical", "distance": 1860.0, "lat": 52.51,
        "lon": 13.427, "height": 34.91, "dwd_station_id": "17473"
    })
}

fn tempelhof_cur() -> Value {
    json!({
        "id": 6150, "station_name": "BERLIN-TEMPELHOF", "observation_type": "current",
        "distance": 5576.0, "lat": 52.47, "lon": 13.4, "height": 50.0,
        "dwd_station_id": "00433"
    })
}

fn mueggelsee() -> Value {
    json!({
        "id": 777, "station_name": "Berlin-Müggelsee", "observation_type": "historical",
        "distance": 17000.0, "lat": 52.44, "lon": 13.65, "height": 39.0,
        "dwd_station_id": "00410"
    })
}

fn alex_mosmix() -> Value {
    json!({
        "id": 2382, "station_name": "BERLIN-ALEX.", "observation_type": "forecast",
        "distance": 1016.0, "lat": 52.52, "lon": 13.42, "height": 37.0,
        "dwd_station_id": "00399"
    })
}

fn later() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2025-01-01T15:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
}

/// The mixed-source records: Friedrichshain (2 h, one without precipitation),
/// Tempelhof (3 h), MOSMIX (never an observation), Müggelsee (2 h, one after
/// `later()`), one unknown source.
fn mixed_payload() -> Value {
    let records = [
        record("09:00", 312070, Some(0.0)),
        record("10:00", 312070, Some(0.5)),
        record("11:00", 312070, None),
        record("12:00", 6150, Some(0.2)),
        record("13:00", 6150, Some(0.0)),
        record("14:00", 6150, Some(1.1)),
        record("14:00", 2382, Some(9.9)),
        record("15:00", 777, Some(0.3)),
        record("16:00", 777, Some(0.0)),
        record("12:00", 424242, Some(0.4)),
    ];
    json!({
        "weather": records,
        "sources": [mueggelsee(), tempelhof_cur(), alex_mosmix(), friedrichshain()],
    })
}

fn station_entry(
    name: &str,
    distance: f64,
    lat: f64,
    lon: f64,
    dwd: &str,
    hours: u64,
) -> ObsStation {
    ObsStation {
        name: Some(name.to_string()),
        distance_m: Some(json!(distance)),
        lat: Some(json!(lat)),
        lon: Some(json!(lon)),
        dwd_station_id: Some(dwd.to_string()),
        hours,
    }
}

#[test]
fn observation_stations_count_the_kept_records_nearest_first() {
    let stations = observation_stations(&mixed_payload(), later());
    assert_eq!(
        stations,
        vec![
            station_entry(
                "Berlin-Friedrichshain/Spree",
                1860.0,
                52.51,
                13.427,
                "17473",
                2
            ),
            station_entry("BERLIN-TEMPELHOF", 5576.0, 52.47, 13.4, "00433", 3),
            station_entry("Berlin-Müggelsee", 17000.0, 52.44, 13.65, "00410", 1),
        ]
    );
}

#[test]
fn observation_stations_empty_without_any_kept_record() {
    let none = json!({"weather": [record("12:00", 2382, Some(1.0))], "sources": [alex_mosmix()]});
    assert!(observation_stations(&none, later()).is_empty());
    for payload in [
        Value::Null,
        json!({"weather": []}),
        json!({"sources": [tempelhof_cur()]}),
        json!({}),
    ] {
        assert!(observation_stations(&payload, later()).is_empty());
    }
}

#[test]
fn observation_stations_missing_distance_sorts_last() {
    let payload = json!({
        "weather": [record("12:00", 1, Some(0.1)), record("13:00", 2, Some(0.1))],
        "sources": [
            {"id": 1, "station_name": "NoDistance"},
            {"id": 2, "station_name": "Far", "distance": 9000.0},
        ],
    });
    let stations = observation_stations(&payload, later());
    assert_eq!(
        stations.iter().map(|s| s.name.clone()).collect::<Vec<_>>(),
        vec![Some("Far".to_string()), Some("NoDistance".to_string())]
    );
    assert_eq!(stations[1].distance_m, None);
}

#[test]
fn observation_stations_duplicate_id_later_entry_wins() {
    let payload = json!({
        "weather": [record("12:00", 7, Some(0.1))],
        "sources": [
            {"id": 7, "station_name": "First", "distance": 100.0},
            {"id": 7, "station_name": "Second", "distance": 200.0},
        ],
    });
    let stations = observation_stations(&payload, later());
    assert_eq!(stations.len(), 1);
    assert_eq!(stations[0].name.as_deref(), Some("Second"));
    assert_eq!(stations[0].distance_m, Some(json!(200.0)));
    assert_eq!(stations[0].hours, 1);
}

// the canonical JSON

#[test]
fn stations_to_json_is_python_canonical() {
    let stations = observation_stations(&mixed_payload(), later());
    assert_eq!(
        stations_to_json(&stations),
        r#"[{"distance_m":1860.0,"dwd_station_id":"17473","hours":2,"lat":52.51,"lon":13.427,"name":"Berlin-Friedrichshain/Spree"},{"distance_m":5576.0,"dwd_station_id":"00433","hours":3,"lat":52.47,"lon":13.4,"name":"BERLIN-TEMPELHOF"},{"distance_m":17000.0,"dwd_station_id":"00410","hours":1,"lat":52.44,"lon":13.65,"name":"Berlin-Müggelsee"}]"#
    );
}

#[test]
fn stations_roundtrip_through_the_stored_value() {
    let stations = observation_stations(&mixed_payload(), later());
    let stored = stations_to_json(&stations);
    assert_eq!(stations_from_json(Some(&stored)), stations);
    assert!(stations_from_json(Some("[]")).is_empty());
    assert!(stations_from_json(None).is_empty());
}

#[test]
fn stations_from_json_broken_value_reads_empty() {
    for bad in [
        "{not json",
        "null",
        "\"[]\"",
        "{}",
        "[1, 2]",
        "[[]]",
        "[{}]", // no hours
        r#"[{"name": "S", "distance_m": 1.0, "lat": 52.0, "lon": 13.0, "dwd_station_id": "1", "hours": -1}]"#,
        r#"[{"name": "S", "distance_m": 1.0, "lat": 52.0, "lon": 13.0, "dwd_station_id": "1", "hours": 1.5}]"#,
        r#"[{"name": "S", "distance_m": 1.0, "lat": 52.0, "lon": 13.0, "dwd_station_id": "1", "hours": true}]"#,
        r#"[{"name": 7, "distance_m": 1.0, "lat": 52.0, "lon": 13.0, "dwd_station_id": "1", "hours": 1}]"#,
        r#"[{"name": "S", "distance_m": "far", "lat": 52.0, "lon": 13.0, "dwd_station_id": "1", "hours": 1}]"#,
        r#"[{"name": "S", "distance_m": 1.0, "lat": 52.0, "lon": 13.0, "dwd_station_id": 1, "hours": 1}]"#,
    ] {
        assert!(
            stations_from_json(Some(bad)).is_empty(),
            "must read as []: {bad}"
        );
    }
}

#[test]
fn stations_from_json_missing_optional_keys_are_null() {
    let stored = r#"[{"name": "S", "hours": 3}]"#;
    let stations = stations_from_json(Some(stored));
    assert_eq!(
        stations,
        vec![ObsStation {
            name: Some("S".to_string()),
            distance_m: None,
            lat: None,
            lon: None,
            dwd_station_id: None,
            hours: 3,
        }]
    );
    // an int distance stays an int in the entry we serve
    let stored = r#"[{"name": "S", "distance_m": 100, "hours": 1}]"#;
    assert_eq!(
        stations_from_json(Some(stored))[0].distance_m,
        Some(json!(100))
    );
}
