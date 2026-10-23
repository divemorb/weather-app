//! The observation stations as stored JSON: written in the canonical form
//! (sorted keys, no spaces), read back unchanged, a broken value read as none.

use serde_json::json;

use super::tests::{later, mixed_payload};
use super::*;

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
    assert_eq!(stations_from_json(Some("[]")), []);
    assert_eq!(stations_from_json(None), []);
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
