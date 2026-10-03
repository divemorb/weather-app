//! Tests for the runtime location state.

use super::*;

/// `V` from the validation tables: the "valid" body.
const V: &str =
    r#"{"latitude": 52.52, "longitude": 13.405, "timezone": "Europe/Berlin", "label": "Berlin"}"#;
const JSON_CT: &str = "application/json";

fn loc(latitude: f64, longitude: f64, timezone: &str, label: &str) -> LocationConfig {
    LocationConfig {
        latitude,
        longitude,
        timezone: timezone.to_string(),
        label: label.to_string(),
    }
}

// JSON round trip (app_meta value)
#[test]
fn location_json_round_trip() {
    let l = loc(52.52, 13.405, "Europe/Berlin", "Berlin");
    assert_eq!(location_from_json(Some(&location_to_json(&l))), Some(l));
}

#[test]
fn location_json_garbage_returns_none_never_raises() {
    for bad in [
        None,
        Some(""),
        Some("not json"),
        Some("[1, 2]"),
        Some("\"str\""),
        Some("42"),
        Some(r#"{"latitude": 52.0}"#), // missing longitude
        Some(r#"{"latitude": 52.0, "longitude": "x"}"#), // wrong type
        Some(r#"{"latitude": true, "longitude": 13.0}"#), // bool is not a number
        Some(r#"{"latitude": 52.0, "longitude": 13.0}"#), // missing timezone
    ] {
        assert_eq!(location_from_json(bad), None);
    }
}

#[test]
fn location_json_defaults_missing_label() {
    let l = location_from_json(Some(
        r#"{"latitude": 52.0, "longitude": 13.0, "timezone": "UTC"}"#,
    ))
    .unwrap();
    assert_eq!(l.label, "");
    assert_eq!((l.latitude, l.longitude), (52.0, 13.0));
}

#[test]
fn moved_none_old_is_not_a_move() {
    assert!(!moved(None, &loc(52.0, 13.0, "Europe/Berlin", "")));
}

#[test]
fn moved_same_location_is_not_a_move() {
    assert!(!moved(
        Some(&loc(52.0, 13.0, "", "")),
        &loc(52.0, 13.0, "", "")
    ));
}

#[test]
fn moved_within_epsilon_is_not_a_move() {
    // 0.005 degrees ~ 550 m: the same place, e.g. a re-pick from a search
    assert!(!moved(
        Some(&loc(52.0, 13.0, "", "")),
        &loc(52.005, 13.005, "", "")
    ));
}

#[test]
fn moved_beyond_epsilon_is_a_move() {
    // 0.02 degrees ~ 2 km: a different place, data must be cleared
    let old = loc(52.0, 13.0, "", "");
    assert!(moved(Some(&old), &loc(52.02, 13.0, "", "")));
    assert!(moved(Some(&old), &loc(52.0, 13.02, "", "")));
}

fn fresh_store() -> (tempfile::TempDir, Store) {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    let store = Store::open(&db.to_string_lossy()).unwrap();
    (dir, store)
}

fn make_cfg() -> AppConfig {
    let mut cfg = crate::config::load_config(None, &|_| None).unwrap();
    cfg.location = Some(loc(52.0, 13.0, "Europe/Berlin", ""));
    cfg
}

#[test]
fn startup_stored_location_wins_over_cfg() {
    let (_dir, store) = fresh_store();
    let stored = loc(52.52, 13.405, "Europe/Berlin", "");
    store
        .set_meta(LOCATION_KEY, &location_to_json(&stored))
        .unwrap();
    let cfg = make_cfg();
    let got = resolve_startup_location(&store, &cfg).unwrap();
    assert_eq!(got, Some(stored.clone()));
    // the stored value must not have been overwritten by the cfg one
    assert_eq!(
        location_from_json(store.get_meta(LOCATION_KEY).unwrap().as_deref()),
        Some(stored)
    );
}

#[test]
fn startup_adopts_cfg_location_into_db() {
    let (_dir, store) = fresh_store();
    let cfg = make_cfg();
    let got = resolve_startup_location(&store, &cfg).unwrap();
    assert_eq!(got, cfg.location.clone());
    assert_eq!(
        location_from_json(store.get_meta(LOCATION_KEY).unwrap().as_deref()),
        cfg.location
    );
}

#[test]
fn startup_nothing_everywhere_is_unconfigured() {
    let (_dir, store) = fresh_store();
    let mut cfg = make_cfg();
    cfg.location = None;
    assert_eq!(resolve_startup_location(&store, &cfg).unwrap(), None);
    assert_eq!(store.get_meta(LOCATION_KEY).unwrap(), None);
}

mod misc;
mod validate;
