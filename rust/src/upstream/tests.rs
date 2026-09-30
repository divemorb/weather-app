use super::*;
use serde_json::json;

#[test]
fn py_truthy_null_is_false() {
    assert!(!py_truthy(&Value::Null));
}

#[test]
fn py_truthy_bools() {
    assert!(!py_truthy(&json!(false)));
    assert!(py_truthy(&json!(true)));
}

#[test]
fn py_truthy_numbers() {
    assert!(!py_truthy(&json!(0)));
    assert!(!py_truthy(&json!(0.0)));
    assert!(py_truthy(&json!(1.5)));
    assert!(py_truthy(&json!(-0.1)));
}

#[test]
fn py_truthy_strings_empty_and_non_empty() {
    assert!(!py_truthy(&json!("")));
    assert!(py_truthy(&json!("x")));
}

#[test]
fn py_truthy_arrays_empty_and_non_empty() {
    assert!(!py_truthy(&json!([])));
    assert!(py_truthy(&json!([null])));
}

#[test]
fn py_truthy_objects_empty_and_non_empty() {
    assert!(!py_truthy(&json!({})));
    assert!(py_truthy(&json!({"a": null})));
}

#[test]
fn opt_f64_missing_and_null_are_none() {
    assert_eq!(opt_f64(None, "x").unwrap(), None);
    assert_eq!(opt_f64(Some(&Value::Null), "x").unwrap(), None);
}

#[test]
fn opt_f64_numbers() {
    assert_eq!(opt_f64(Some(&json!(1.5)), "x").unwrap(), Some(1.5));
    assert_eq!(opt_f64(Some(&json!(3)), "x").unwrap(), Some(3.0));
}

#[test]
fn opt_f64_rejects_strings_and_bools() {
    // Approved difference: Python's float() would accept these.
    assert!(opt_f64(Some(&json!("1.5")), "x").is_err());
    assert!(opt_f64(Some(&json!(true)), "x").is_err());
}

#[test]
fn f64_list_numbers_with_nulls() {
    let list = json!([1.0, null, 2]);
    assert_eq!(
        f64_list(&list, "x").unwrap(),
        vec![Some(1.0), None, Some(2.0)]
    );
}

#[test]
fn f64_list_rejects_non_list() {
    assert!(f64_list(&json!(5), "x").is_err());
    assert!(f64_list(&json!("nope"), "x").is_err());
}

#[test]
fn f64_list_rejects_string_inside() {
    assert!(f64_list(&json!([1.0, "2.0"]), "x").is_err());
}

#[test]
fn py_str_null_bools_strings_and_numbers() {
    assert_eq!(py_str(&Value::Null), "None");
    assert_eq!(py_str(&json!(1002)), "1002");
    assert_eq!(py_str(&json!(1.0)), "1.0");
    assert_eq!(py_str(&json!("x")), "x");
}

#[test]
fn current_payload_defaults_and_override() {
    let payload = crate::testutil::make_current_payload(None);
    assert_eq!(payload["weather"]["temperature"], json!(7.4));
    assert_eq!(payload["weather"]["source_id"], json!(96160));
    assert_eq!(payload["sources"], json!([]));

    let payload = crate::testutil::make_current_payload(Some(json!({"temperature": 9.9})));
    assert_eq!(payload["weather"]["temperature"], json!(9.9));
    assert_eq!(payload["weather"]["dew_point"], json!(3.5));
}

#[test]
fn weather_payload_defaults_and_override() {
    let payload = crate::testutil::make_weather_payload(None, None);
    assert_eq!(payload["weather"].as_array().unwrap().len(), 5);
    assert_eq!(payload["sources"].as_array().unwrap().len(), 2);

    let payload = crate::testutil::make_weather_payload(Some(json!([])), None);
    assert_eq!(payload["weather"], json!([]));
}

#[test]
fn radar_payload_encodes_grids() {
    let g = crate::testutil::grid(4, 4, 0);
    let payload = crate::testutil::make_radar_payload(
        &[("2026-09-25T06:00:00+00:00", g)],
        (10, 20, 14, 24),
        (2.0, 2.0),
    );
    assert_eq!(payload["radar"][0]["source"], json!("RADOLAN::RV::frame0"));
    assert_eq!(payload["bbox"], json!([10, 20, 14, 24]));
    assert_eq!(payload["latlon_position"], json!({"x": 2.0, "y": 2.0}));

    // The encoded grid decodes back to the same uint16 bytes.
    use base64::Engine as _;
    use std::io::Read as _;
    let encoded = payload["radar"][0]["precipitation_5"].as_str().unwrap();
    let raw = base64::engine::general_purpose::STANDARD
        .decode(encoded.as_bytes())
        .unwrap();
    let mut dec = flate2::read::ZlibDecoder::new(&raw[..]);
    let mut out = Vec::new();
    dec.read_to_end(&mut out).unwrap();
    assert_eq!(out, vec![0u8; 4 * 4 * 2]);
}

#[test]
fn forecast_payload_puts_suffixed_series() {
    let payload = crate::testutil::make_forecast_payload(
        &["icon_d2"],
        &["2026-09-25T06:00"],
        &["2026-09-25T06:00", "2026-09-25T06:15"],
        &[("icon_d2", vec![json!(0.4)])],
        &[("icon_d2", vec![json!(0.1), Value::Null])],
        &[],
    );
    assert_eq!(payload["hourly"]["precipitation_icon_d2"], json!([0.4]));
    assert_eq!(
        payload["minutely_15"]["precipitation_icon_d2"],
        json!([0.1, null])
    );
    assert_eq!(payload["latitude"], json!(52.0));
}

#[test]
fn ensemble_payload_names_members() {
    let payload = crate::testutil::make_ensemble_payload(
        &["2026-09-25T06:00"],
        vec![json!(0.0)],
        &[vec![json!(0.1)], vec![Value::Null]],
    );
    assert_eq!(payload["hourly"]["precipitation"], json!([0.0]));
    assert_eq!(payload["hourly"]["precipitation_member01"], json!([0.1]));
    assert_eq!(payload["hourly"]["precipitation_member02"], json!([null]));
    assert_eq!(payload["hourly_units"]["precipitation"], json!("mm"));
}
