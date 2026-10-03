use super::*;
use chrono::Datelike;
use serde_json::json;

const HOURS: [&str; 4] = [
    "2026-09-25T00:00",
    "2026-09-25T01:00",
    "2026-09-25T02:00",
    "2026-09-25T03:00",
];
const MIN15: [&str; 8] = [
    "2026-09-25T00:00",
    "2026-09-25T00:15",
    "2026-09-25T00:30",
    "2026-09-25T00:45",
    "2026-09-25T01:00",
    "2026-09-25T01:15",
    "2026-09-25T01:30",
    "2026-09-25T01:45",
];

fn nums(values: &[f64]) -> Vec<Value> {
    values.iter().map(|v| json!(v)).collect()
}

fn forecast_payload() -> Value {
    crate::testutil::make_forecast_payload(
        &["icon_d2", "icon_eu"],
        &HOURS,
        &MIN15,
        &[
            ("icon_d2", nums(&[0.0, 0.5, 0.0, 0.0])),
            ("icon_eu", nums(&[0.0, 0.0, 0.0, 0.0])),
        ],
        &[
            ("icon_d2", nums(&[0.0, 0.2, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0])),
            ("icon_eu", nums(&[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])),
        ],
        &[
            (
                "apparent_temperature",
                &[
                    ("icon_d2", nums(&[5.0, 6.0, 7.0, 8.0])),
                    ("icon_eu", nums(&[4.0, 5.0, 6.0, 7.0])),
                ],
            ),
            (
                "wind_speed_10m",
                &[
                    ("icon_d2", nums(&[10.0, 12.0, 14.0, 16.0])),
                    ("icon_eu", nums(&[8.0, 9.0, 10.0, 11.0])),
                ],
            ),
            (
                "temperature_2m",
                &[
                    ("icon_d2", nums(&[5.0, 6.0, 7.0, 8.0])),
                    ("icon_eu", nums(&[4.0, 5.0, 6.0, 7.0])),
                ],
            ),
            (
                "cloud_cover",
                &[
                    ("icon_d2", nums(&[10.0, 20.0, 30.0, 40.0])),
                    ("icon_eu", nums(&[5.0, 6.0, 7.0, 8.0])),
                ],
            ),
        ],
    )
}

#[test]
fn parse_forecast_all_models_present() {
    let bundle =
        parse_forecast(&forecast_payload(), &["icon_d2".into(), "icon_eu".into()]).unwrap();
    let names: Vec<&str> = bundle.models.iter().map(|m| m.name.as_str()).collect();
    assert_eq!(names, ["icon_d2", "icon_eu"]);
    assert_eq!(bundle.models.len(), 2);
}

#[test]
fn parse_forecast_maps_hourly_series() {
    let bundle = parse_forecast(&forecast_payload(), &["icon_d2".into()]).unwrap();
    let m = bundle.by_name("icon_d2").unwrap();
    assert_eq!(
        m.hourly_precip_mm,
        vec![Some(0.0), Some(0.5), Some(0.0), Some(0.0)]
    );
    assert_eq!(
        m.hourly_apparent_c,
        vec![Some(5.0), Some(6.0), Some(7.0), Some(8.0)]
    );
    assert_eq!(
        m.hourly_wind_kmh,
        vec![Some(10.0), Some(12.0), Some(14.0), Some(16.0)]
    );
    assert_eq!(
        m.hourly_cloud_cover_pct,
        vec![Some(10.0), Some(20.0), Some(30.0), Some(40.0)]
    );
    assert_eq!(m.hourly_time.len(), 4);
    assert_eq!(m.hourly_time[0].year(), 2026);
}

#[test]
fn parse_forecast_maps_min15_series() {
    let bundle = parse_forecast(&forecast_payload(), &["icon_d2".into()]).unwrap();
    let m = bundle.by_name("icon_d2").unwrap();
    assert_eq!(
        m.min15_precip_mm,
        vec![
            Some(0.0),
            Some(0.2),
            Some(0.3),
            Some(0.0),
            Some(0.0),
            Some(0.0),
            Some(0.0),
            Some(0.0)
        ]
    );
    assert_eq!(m.min15_time.len(), 8);
}

#[test]
fn parse_forecast_tolerance_for_nulls() {
    let mut payload = forecast_payload();
    payload["hourly"]["precipitation_icon_d2"] = json!([null, 0.5, null, 0.0]);
    let bundle = parse_forecast(&payload, &["icon_d2".into()]).unwrap();
    assert_eq!(
        bundle.by_name("icon_d2").unwrap().hourly_precip_mm,
        vec![None, Some(0.5), None, Some(0.0)]
    );
}

#[test]
fn parse_forecast_missing_model_key_gives_empty() {
    // Request a model that has no suffixed keys in the payload.
    let bundle = parse_forecast(&forecast_payload(), &["gfs_seamless".into()]).unwrap();
    let m = bundle.by_name("gfs_seamless").unwrap();
    assert!(m.hourly_precip_mm.is_empty());
    assert!(m.min15_precip_mm.is_empty());
}

#[test]
fn parse_forecast_error_flag_raises() {
    let err = parse_forecast(
        &json!({"error": true, "reason": "bad lat"}),
        &["icon_d2".into()],
    )
    .unwrap_err();
    assert_eq!(err.to_string(), "Open-Meteo forecast error: bad lat");
}

#[test]
fn parse_forecast_missing_timestamp_raises_source_error() {
    // a non-string in the time list: untrusted payload, must be a
    // SourceError (the request path only catches that), not a panic
    let payload = json!({
        "latitude": 52.0,
        "longitude": 13.0,
        "timezone": "GMT",
        "minutely_15": {"time": []},
        "hourly": {"time": [1, 2, 3, 4],
                   "precipitation_icon_d2": [0.0, 0.5, 0.0, 0.0]},
    });
    let err = parse_forecast(&payload, &["icon_d2".into()]).unwrap_err();
    assert!(err.to_string().contains("malformed"));
}

#[test]
fn parse_forecast_null_section_raises_source_error() {
    // a section present but not an object (null included) is a SourceError
    let payload = json!({"minutely_15": null, "hourly": {"time": HOURS}});
    assert!(parse_forecast(&payload, &["icon_d2".into()]).is_err());
    let payload = json!({"minutely_15": {"time": MIN15}, "hourly": [1, 2]});
    assert!(parse_forecast(&payload, &["icon_d2".into()]).is_err());
}

#[test]
fn parse_forecast_unparseable_timestamp_raises_source_error() {
    let payload = json!({"hourly": {"time": ["2026-09-25T00:00", "not-a-time"]}});
    let err = parse_forecast(&payload, &[]).unwrap_err();
    assert!(err.to_string().contains("malformed"));
    // a null time list is malformed too
    let payload = json!({"hourly": {"time": null}});
    assert!(parse_forecast(&payload, &[]).is_err());
}

#[test]
fn parse_forecast_non_object_payload_raises_source_error() {
    assert!(parse_forecast(&json!([1, 2]), &[]).is_err());
}

fn ensemble_payload() -> Value {
    // 4 hours, control + 3 members (member01..03)
    crate::testutil::make_ensemble_payload(
        &HOURS,
        nums(&[0.0, 0.1, 0.2, 0.3]),
        &[
            nums(&[0.0, 0.5, 0.0, 0.0]),
            nums(&[0.0, 0.0, 0.0, 0.0]),
            nums(&[0.2, 0.2, 0.2, 0.2]),
        ],
    )
}

#[test]
fn parse_ensemble_member_count_and_order() {
    let data = parse_ensemble(&ensemble_payload()).unwrap();
    assert_eq!(data.n_members(), 3);
    assert_eq!(
        data.control_precip_mm,
        vec![Some(0.0), Some(0.1), Some(0.2), Some(0.3)]
    );
    // members are ordered by number
    assert_eq!(
        data.member_precip_mm[0],
        vec![Some(0.0), Some(0.5), Some(0.0), Some(0.0)]
    );
    assert_eq!(
        data.member_precip_mm[2],
        vec![Some(0.2), Some(0.2), Some(0.2), Some(0.2)]
    );
    assert_eq!(data.hourly_time.len(), 4);
}

#[test]
fn parse_ensemble_zero_members() {
    let payload = crate::testutil::make_ensemble_payload(&HOURS, nums(&[0.0, 0.0]), &[]);
    let data = parse_ensemble(&payload).unwrap();
    assert_eq!(data.n_members(), 0);
    assert!(data.member_precip_mm.is_empty());
}

#[test]
fn parse_ensemble_error_flag_raises() {
    let err = parse_ensemble(&json!({"error": true, "reason": "no ensemble"})).unwrap_err();
    assert_eq!(err.to_string(), "Open-Meteo ensemble error: no ensemble");
}

#[test]
fn parse_ensemble_wrong_type_raises_source_error() {
    // a string where a number belongs in the control series -> SourceError
    let payload = crate::testutil::make_ensemble_payload(
        &HOURS,
        vec![json!("a"), json!(0.1), json!(0.2), json!(0.3)],
        &[],
    );
    let err = parse_ensemble(&payload).unwrap_err();
    assert!(err.to_string().contains("malformed"));
}

#[test]
fn parse_ensemble_missing_hourly_gives_empty() {
    // a missing section is empty
    let data = parse_ensemble(&json!({"latitude": 52.0, "longitude": 13.0})).unwrap();
    assert!(data.hourly_time.is_empty());
    assert!(data.control_precip_mm.is_empty());
    assert!(data.member_precip_mm.is_empty());
}

#[test]
fn parse_ensemble_member_key_matching() {
    // Only a trailing run of digits after (the last) `precipitation_member`
    // counts; the control key `precipitation` is not a member key.
    let payload = json!({"hourly": {
        "time": HOURS,
        "precipitation": [0.0, 0.0, 0.0, 0.0],
        "precipitation_member": [1.0, 1.0, 1.0, 1.0],      // no digits: skipped
        "precipitation_member01x": [1.0, 1.0, 1.0, 1.0],   // not trailing: skipped
        "xprecipitation_member00": [0.9, 0.9, 0.9, 0.9],   // member00 -> index -1
        "precipitation_member02": [0.8, 0.8, 0.8, 0.8],
    }});
    let data = parse_ensemble(&payload).unwrap();
    assert_eq!(data.n_members(), 2);
    // ordered by member number: -1 (member00) before 0 (member01)
    assert_eq!(
        data.member_precip_mm[0],
        vec![Some(0.9), Some(0.9), Some(0.9), Some(0.9)]
    );
    assert_eq!(
        data.member_precip_mm[1],
        vec![Some(0.8), Some(0.8), Some(0.8), Some(0.8)]
    );
}

#[test]
fn parse_ensemble_member_number_overflow_raises_source_error() {
    let payload = json!({"hourly": {
        "time": HOURS,
        "precipitation_member99999999999999999999": [0.0, 0.0, 0.0, 0.0],
    }});
    let err = parse_ensemble(&payload).unwrap_err();
    assert!(err.to_string().contains("malformed"));
}

#[test]
fn parse_ensemble_null_time_raises_source_error() {
    let payload = json!({"hourly": {"time": null, "precipitation": [0.0]}});
    assert!(parse_ensemble(&payload).is_err());
    let payload = json!({"hourly": null});
    assert!(parse_ensemble(&payload).is_err());
}
