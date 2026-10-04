use super::*;
use serde_json::json;

fn now_weather() -> DateTime<Utc> {
    parse_iso("2026-09-27T20:00:00Z").unwrap()
}

fn default_current_payload() -> Value {
    crate::testutil::make_current_payload(None)
}

fn default_weather_payload() -> Value {
    crate::testutil::make_weather_payload(None, None)
}

#[test]
fn parse_current_weather_maps_fields() {
    let cond = parse_current_weather(&default_current_payload()).unwrap();
    assert_eq!(cond.temperature_c, Some(7.4));
    assert_eq!(cond.wind_speed_ms, Some(5.0));
    assert_eq!(cond.wind_direction_deg, Some(260.0));
    assert_eq!(cond.wind_gust_ms, Some(11.0));
    assert_eq!(cond.cloud_cover_pct, Some(88.0));
    assert_eq!(cond.humidity_pct, Some(87.0));
    assert_eq!(cond.pressure_hpa, Some(1026.0));
    assert_eq!(cond.dew_point_c, Some(3.5));
    assert_eq!(cond.precipitation_60mm, Some(0.8));
    assert_eq!(cond.condition, json!("dry"));
    assert_eq!(cond.source_id, json!(96160));
    assert_eq!(cond.feels_like_c, None); // filled later from Open-Meteo
}

#[test]
fn parse_current_weather_handles_nulls() {
    let cond = parse_current_weather(&crate::testutil::make_current_payload(Some(json!({
        "temperature": null,
        "cloud_cover": null,
    }))))
    .unwrap();
    assert_eq!(cond.temperature_c, None);
    assert_eq!(cond.cloud_cover_pct, None);
}

#[test]
fn parse_current_weather_passes_every_documented_icon() {
    for icon in WEATHER_ICONS {
        let cond = parse_current_weather(&crate::testutil::make_current_payload(Some(json!({
            "icon": icon,
        }))))
        .unwrap();
        assert_eq!(cond.icon.as_deref(), Some(icon), "{icon}");
        // the icon rides along without touching the other fields
        assert_eq!(cond.condition, json!("dry"));
    }
}

#[test]
fn parse_current_weather_icon_none_when_missing_or_invalid() {
    // missing, null, unknown, wrong case, not a string -> None
    let cases = [
        None,
        Some(json!(null)),
        Some(json!("")),
        Some(json!("tornado")),
        Some(json!("Rain")),
        Some(json!("CLEAR-DAY")),
        Some(json!(5)),
        Some(json!(["rain"])),
        Some(json!({"icon": "rain"})),
    ];
    for icon in &cases {
        let mut extra = Map::new();
        if let Some(value) = icon {
            extra.insert("icon".to_string(), value.clone());
        }
        let cond = parse_current_weather(&crate::testutil::make_current_payload(Some(
            Value::Object(extra.clone()),
        )))
        .unwrap();
        assert_eq!(cond.icon, None, "{icon:?}");
    }
}

#[test]
fn parse_current_weather_missing_weather_raises() {
    let err = parse_current_weather(&json!({"sources": []})).unwrap_err();
    assert!(err.to_string().contains("missing 'weather'"));
}

#[test]
fn parse_current_weather_wrong_type_raises_source_error() {
    // a string where a number belongs: untrusted payload, must be a
    // SourceError (the request path only catches that), not a panic
    let err = parse_current_weather(&crate::testutil::make_current_payload(Some(json!({
        "temperature": "not-a-number",
    }))))
    .unwrap_err();
    assert!(err.to_string().contains("malformed"));
}

#[test]
fn parse_hourly_observations_keeps_real_past_hours() {
    // Only real-observation records (observation_type != 'forecast') with a
    // past timestamp and a non-null precipitation are kept, labelled by hour
    // start (timestamp - 1h, since the value covers [T-1h, T)).
    let obs = parse_hourly_observations(&default_weather_payload(), now_weather()).unwrap();
    assert_eq!(
        obs,
        vec![
            (parse_iso("2026-09-27T15:00:00Z").unwrap(), 0.0), // 16:00 stamp
            (parse_iso("2026-09-27T17:00:00Z").unwrap(), 0.4), // 18:00 stamp
        ]
    );
}

#[test]
fn parse_hourly_observations_drops_forecast_null_and_future() {
    // Forecast records, null precipitation and future timestamps are skipped
    // even when their precipitation is set.
    let obs = parse_hourly_observations(&default_weather_payload(), now_weather()).unwrap();
    let stamps: Vec<DateTime<Utc>> = obs.iter().map(|(t, _)| *t).collect();
    // 17:00 (null precip), 19:00 (MOSMIX forecast), 21:00 (forecast AND future)
    assert!(!stamps.contains(&parse_iso("2026-09-27T16:00:00Z").unwrap()));
    assert!(!stamps.contains(&parse_iso("2026-09-27T18:00:00Z").unwrap()));
    assert!(!stamps.contains(&parse_iso("2026-09-27T20:00:00Z").unwrap()));
}

#[test]
fn parse_hourly_observations_at_boundary_timestamp() {
    // A record stamped exactly `now` covers [now-1h, now): it is complete
    // and must be kept.
    let payload = crate::testutil::make_weather_payload(
        Some(json!([
            {"timestamp": "2026-09-27T20:00:00+00:00",
             "source_id": 1002, "precipitation": 0.2},
        ])),
        None,
    );
    let obs = parse_hourly_observations(&payload, now_weather()).unwrap();
    assert_eq!(obs, vec![(parse_iso("2026-09-27T19:00:00Z").unwrap(), 0.2)]);
}

#[test]
fn parse_hourly_observations_unknown_source_and_bad_timestamp() {
    let payload = crate::testutil::make_weather_payload(
        Some(json!([
            {"timestamp": "2026-09-27T16:00:00+00:00", "source_id": 999,
             "precipitation": 1.0},
            {"timestamp": "not-a-timestamp", "source_id": 1002,
             "precipitation": 1.0},
        ])),
        None,
    );
    assert!(
        parse_hourly_observations(&payload, now_weather())
            .unwrap()
            .is_empty()
    );
}

#[test]
fn parse_hourly_observations_empty_payload() {
    assert!(
        parse_hourly_observations(&json!({}), now_weather())
            .unwrap()
            .is_empty()
    );
    assert!(
        parse_hourly_observations(&json!({"weather": null, "sources": null}), now_weather())
            .unwrap()
            .is_empty()
    );
}

#[test]
fn parse_hourly_observations_non_numeric_precipitation_raises() {
    // A record that passes every skip check but carries a non-numeric
    // precipitation is a SourceError for the whole call.
    let payload = crate::testutil::make_weather_payload(
        Some(json!([
            {"timestamp": "2026-09-27T16:00:00+00:00", "source_id": 1002,
             "precipitation": "wet"},
        ])),
        None,
    );
    assert!(parse_hourly_observations(&payload, now_weather()).is_err());
}

#[test]
fn parse_hourly_observations_non_object_payload_raises() {
    assert!(parse_hourly_observations(&json!([1, 2]), now_weather()).is_err());
}

#[test]
fn parse_station_info_prefers_real_observation_source() {
    // A source with observation_type 'current'/'historical' beats a forecast
    // source even when the latter is listed first.
    let mut payload = crate::testutil::make_weather_payload(
        None,
        Some(json!([
            {"id": 1001, "observation_type": "forecast",
             "station_name": "MOSMIX", "distance": 3000.0},
            {"id": 1002, "observation_type": "historical",
             "station_name": "BERLIN", "distance": 5000.0},
        ])),
    );
    assert_eq!(
        parse_station_info(&payload).unwrap(),
        Some(("BERLIN".to_string(), 5000.0))
    );
    payload["sources"][1]["observation_type"] = json!("current");
    assert_eq!(
        parse_station_info(&payload).unwrap(),
        Some(("BERLIN".to_string(), 5000.0))
    );
}

#[test]
fn parse_station_info_falls_back_to_first_source() {
    // Without a real-observation source (e.g. MOSMIX only), the first listed
    // source is reported; a missing station_name falls back to its id.
    let payload = crate::testutil::make_weather_payload(
        None,
        Some(json!([
            {"id": 1001, "observation_type": "forecast",
             "station_name": "MOSMIX", "distance": 3000.0},
            {"id": 77, "observation_type": "forecast"},
        ])),
    );
    assert_eq!(
        parse_station_info(&payload).unwrap(),
        Some(("MOSMIX".to_string(), 3000.0))
    );
    assert_eq!(
        parse_station_info(&json!({"sources": [{"id": 77, "observation_type": "forecast"}]}))
            .unwrap(),
        Some(("77".to_string(), 0.0))
    );
}

#[test]
fn parse_station_info_no_sources_returns_none() {
    assert_eq!(parse_station_info(&json!({})).unwrap(), None);
    assert_eq!(parse_station_info(&json!({"sources": null})).unwrap(), None);
    assert_eq!(parse_station_info(&json!({"sources": []})).unwrap(), None);
}
