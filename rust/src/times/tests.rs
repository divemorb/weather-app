use super::*;
use chrono::{NaiveDate, Timelike};
use std::collections::HashMap;

fn at(y: i32, mo: u32, d: u32, h: u32, mi: u32, s: u32) -> DateTime<Utc> {
    NaiveDate::from_ymd_opt(y, mo, d)
        .unwrap()
        .and_hms_opt(h, mi, s)
        .unwrap()
        .and_utc()
}

#[test]
fn parse_iso_z_suffix() {
    let value = parse_iso("2026-09-25T06:00:00Z").unwrap();
    assert_eq!(value, at(2026, 9, 25, 6, 0, 0));
}

#[test]
fn parse_iso_offset_normalized_to_utc() {
    let value = parse_iso("2026-09-25T08:00:00+02:00").unwrap();
    assert_eq!(value, at(2026, 9, 25, 6, 0, 0));
}

#[test]
fn parse_iso_naive_assumed_utc() {
    let value = parse_iso("2026-09-25T06:00:00").unwrap();
    assert_eq!(value, at(2026, 9, 25, 6, 0, 0));
}

#[test]
fn to_iso_roundtrip() {
    let original = at(2026, 9, 25, 6, 30, 0);
    assert_eq!(to_iso(original), "2026-09-25T06:30:00Z");
}

#[test]
fn parse_iso_without_seconds() {
    // Open-Meteo sends minute-precision stamps.
    let value = parse_iso("2026-09-30T00:15").unwrap();
    assert_eq!(value, at(2026, 9, 30, 0, 15, 0));
}

#[test]
fn parse_iso_trims_surrounding_whitespace() {
    let value = parse_iso(" 2026-09-25T06:00:00Z\n").unwrap();
    assert_eq!(value, at(2026, 9, 25, 6, 0, 0));
}

#[test]
fn parse_iso_fractional_seconds() {
    let value = parse_iso("2026-09-25T06:00:00.5Z").unwrap();
    assert_eq!(value.hour(), 6);
    assert_eq!(value.timestamp_subsec_micros(), 500_000);
}

#[test]
fn parse_iso_rejects_garbage() {
    assert!(parse_iso("garbage").is_err());
}

#[test]
fn parse_iso_rejects_date_only() {
    assert!(parse_iso("2026-09-25").is_err());
}

fn env_lookup(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<String> {
    let env: HashMap<String, String> = pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect();
    move |k| env.get(k).cloned()
}

#[test]
fn clock_from_env_unset_is_system_clock() {
    let lookup = env_lookup(&[]);
    let clock = Clock::from_env(&lookup).unwrap();
    assert!(!clock.is_fixed());
}

#[test]
fn clock_from_env_empty_is_system_clock() {
    let lookup = env_lookup(&[("WETTER_FAKE_NOW", "")]);
    let clock = Clock::from_env(&lookup).unwrap();
    assert!(!clock.is_fixed());
}

#[test]
fn clock_from_env_stamp_is_fixed_clock() {
    let lookup = env_lookup(&[("WETTER_FAKE_NOW", "2026-09-25T06:00:00Z")]);
    let clock = Clock::from_env(&lookup).unwrap();
    assert!(clock.is_fixed());
    assert_eq!(clock.now(), at(2026, 9, 25, 6, 0, 0));
}

#[test]
fn clock_from_env_bad_stamp_is_an_error() {
    let lookup = env_lookup(&[("WETTER_FAKE_NOW", "not a timestamp")]);
    assert!(Clock::from_env(&lookup).is_err());
}
