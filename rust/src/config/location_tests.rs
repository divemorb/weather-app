//! The location is optional: without one the app runs unconfigured; the
//! environment (both variables) or the YAML block (both coordinates) is
//! the source, never a mix, and the timezone defaults to Europe/Berlin.

use super::tests::{env_lookup, load, make_config};

#[test]
fn no_location_in_yaml_and_no_env_is_unconfigured() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "{}\n");
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert!(cfg.location.is_none());
}

#[test]
fn yaml_location_needs_both_coordinates() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "location:\n  latitude: 52.0\n");
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    assert!(cfg.location.is_none());
}

#[test]
fn partial_env_falls_back_to_yaml() {
    // env only counts when BOTH vars are set (they are one source); with
    // only LATITUDE the YAML block is the source (no mixing of coordinates)
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(
        dir.path(),
        "location:\n  latitude: 52.0\n  longitude: 13.0\n",
    );
    let env = env_lookup(&[("LATITUDE", "52.52")]);
    let cfg = load(Some(&path), &env).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.latitude, 52.0);
}

#[test]
fn yaml_location_defaults_timezone() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(
        dir.path(),
        "location:\n  latitude: 52.0\n  longitude: 13.0\n",
    );
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.timezone, "Europe/Berlin");
}

#[test]
fn env_location_without_yaml() {
    // env vars are a source by themselves; the YAML block is not needed
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(dir.path(), "{}\n");
    let env = env_lookup(&[("LATITUDE", "52.52"), ("LONGITUDE", "13.40")]);
    let cfg = load(Some(&path), &env).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!((loc.latitude, loc.longitude), (52.52, 13.40));
    assert_eq!(loc.timezone, "Europe/Berlin");
}

#[test]
fn yaml_location_timezone_is_used() {
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(
        dir.path(),
        "location:\n  latitude: 52.0\n  longitude: 13.0\n  timezone: Europe/Paris\n",
    );
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.timezone, "Europe/Paris");
}

#[test]
fn yaml_location_empty_timezone_defaults() {
    // An empty timezone string counts as missing, so the default applies.
    let dir = tempfile::tempdir().unwrap();
    let path = make_config(
        dir.path(),
        "location:\n  latitude: 52.0\n  longitude: 13.0\n  timezone: ''\n",
    );
    let cfg = load(Some(&path), &env_lookup(&[])).unwrap();
    let loc = cfg.location.as_ref().unwrap();
    assert_eq!(loc.timezone, "Europe/Berlin");
}
