//! Validation tables for `validate_location_body` and
//! `LocationIn::into_location`.

use super::*;

/// `{"latitude": …, "longitude": …, "timezone": …, "label": …}` in the
/// order the pairs are given, with `": "` / `", "` separators.
fn body(pairs: &[(&str, Value)]) -> String {
    let parts = pairs
        .iter()
        .map(|(k, v)| format!("\"{k}\": {v}"))
        .collect::<Vec<_>>()
        .join(", ");
    format!("{{{parts}}}")
}

fn validate(text: &str) -> Result<LocationIn, BodyError> {
    validate_location_body(Some(JSON_CT), text.as_bytes())
}

/// The `loc` parts of an `Invalid` error (the contract ignores `msg`).
fn locs(err: BodyError) -> Vec<Vec<LocPart>> {
    match err {
        BodyError::Invalid(errors) => errors.into_iter().map(|e| e.loc).collect(),
        other => panic!("expected Invalid, got {other:?}"),
    }
}

fn field(name: &'static str) -> Vec<LocPart> {
    vec![LocPart::Name("body"), LocPart::Name(name)]
}

fn body_loc() -> Vec<LocPart> {
    vec![LocPart::Name("body")]
}

#[test]
fn validate_valid_v() {
    let in_ = validate(V).unwrap();
    assert_eq!((in_.latitude(), in_.longitude()), (52.52, 13.405));
    assert_eq!(in_.timezone(), "Europe/Berlin");
    assert_eq!(in_.label(), "Berlin");
}

#[test]
fn validate_coordinate_bounds_included() {
    let text = body(&[
        ("latitude", json!(90)),
        ("longitude", json!(-180)),
        ("timezone", json!("UTC")),
    ]);
    let in_ = validate(&text).unwrap();
    assert_eq!((in_.latitude(), in_.longitude()), (90.0, -180.0));
}

#[test]
fn validate_latitude_out_of_range() {
    let text = body(&[
        ("latitude", json!(90.0001)),
        ("longitude", json!(13.4)),
        ("timezone", json!("UTC")),
    ]);
    assert_eq!(locs(validate(&text).unwrap_err()), vec![field("latitude")]);
}

#[test]
fn validate_latitude_null() {
    let text = body(&[
        ("latitude", json!(null)),
        ("longitude", json!(13.4)),
        ("timezone", json!("UTC")),
    ]);
    assert_eq!(locs(validate(&text).unwrap_err()), vec![field("latitude")]);
}

#[test]
fn validate_latitude_numeric_strings() {
    for (raw, expected) in [
        ("52.5", 52.5),
        (" 52.5 ", 52.5),
        ("1e1", 10.0),
        ("1_0", 10.0),
        ("+5", 5.0),
    ] {
        let text = body(&[
            ("latitude", json!(raw)),
            ("longitude", json!(13.4)),
            ("timezone", json!("UTC")),
        ]);
        let in_ = validate(&text).unwrap();
        assert_eq!(in_.latitude(), expected, "raw: {raw}");
    }
}

#[test]
fn validate_latitude_bad_values() {
    for raw in [
        json!("abc"),
        json!(""),
        json!("inf"),
        json!("nan"),
        json!([1]),
        json!({}),
    ] {
        let text = body(&[
            ("latitude", raw),
            ("longitude", json!(13.4)),
            ("timezone", json!("UTC")),
        ]);
        assert_eq!(locs(validate(&text).unwrap_err()), vec![field("latitude")]);
    }
}

#[test]
fn validate_booleans_are_numbers() {
    let text = body(&[
        ("latitude", json!(true)),
        ("longitude", json!(false)),
        ("timezone", json!("UTC")),
    ]);
    let in_ = validate(&text).unwrap();
    assert_eq!((in_.latitude(), in_.longitude()), (1.0, 0.0));
}

#[test]
fn validate_timezone_not_a_string() {
    let text = body(&[
        ("latitude", json!(52.5)),
        ("longitude", json!(13.4)),
        ("timezone", json!(5)),
    ]);
    assert_eq!(locs(validate(&text).unwrap_err()), vec![field("timezone")]);
}

#[test]
fn validate_timezone_too_long() {
    let text = body(&[
        ("latitude", json!(52.5)),
        ("longitude", json!(13.4)),
        ("timezone", json!("x".repeat(65))),
    ]);
    assert_eq!(locs(validate(&text).unwrap_err()), vec![field("timezone")]);
}

#[test]
fn validate_label_not_a_string() {
    for raw in [json!(null), json!(5)] {
        let text = body(&[
            ("latitude", json!(52.5)),
            ("longitude", json!(13.4)),
            ("timezone", json!("UTC")),
            ("label", raw),
        ]);
        assert_eq!(locs(validate(&text).unwrap_err()), vec![field("label")]);
    }
}

#[test]
fn validate_label_length_limit() {
    let ok = body(&[
        ("latitude", json!(52.5)),
        ("longitude", json!(13.4)),
        ("timezone", json!("UTC")),
        ("label", json!("ü".repeat(200))),
    ]);
    let in_ = validate(&ok).unwrap();
    assert_eq!(in_.label().chars().count(), 200);
    let bad = body(&[
        ("latitude", json!(52.5)),
        ("longitude", json!(13.4)),
        ("timezone", json!("UTC")),
        ("label", json!("ü".repeat(201))),
    ]);
    assert_eq!(locs(validate(&bad).unwrap_err()), vec![field("label")]);
}

#[test]
fn validate_missing_label_defaults_empty() {
    let text = body(&[
        ("latitude", json!(52.5)),
        ("longitude", json!(13.4)),
        ("timezone", json!("UTC")),
    ]);
    let in_ = validate(&text).unwrap();
    assert_eq!(in_.label(), "");
}

#[test]
fn validate_empty_object_missing_required() {
    assert_eq!(
        locs(validate("{}").unwrap_err()),
        vec![field("latitude"), field("longitude"), field("timezone")]
    );
}

#[test]
fn validate_all_fields_bad_in_order() {
    let text = body(&[
        ("latitude", json!("x")),
        ("longitude", json!(200)),
        ("timezone", json!(3)),
        ("label", json!(4)),
    ]);
    assert_eq!(
        locs(validate(&text).unwrap_err()),
        vec![
            field("latitude"),
            field("longitude"),
            field("timezone"),
            field("label")
        ]
    );
}

#[test]
fn validate_not_an_object() {
    for text in [r#"null"#, r#""x""#, "5", "[1, 2]"] {
        assert_eq!(locs(validate(text).unwrap_err()), vec![body_loc()]);
    }
}

#[test]
fn validate_empty_body() {
    assert_eq!(locs(validate("").unwrap_err()), vec![body_loc()]);
}

#[test]
fn validate_json_error_positions() {
    // The bodies use `", "` / `": "` separators.
    for (text, pos) in [
        ("abc".to_string(), 0usize),
        (r#"{"a": }"#.to_string(), 6),
        (r#"{"latitude": 1,"#.to_string(), 15),
        ("{\n  \"a\": x}".to_string(), 9),
        (format!("{V} x"), 89),
        ("{\"ü\": x}".to_string(), 6),
    ] {
        assert_eq!(
            locs(validate(&text).unwrap_err()),
            vec![vec![LocPart::Name("body"), LocPart::Pos(pos)]],
            "text: {text:?}"
        );
    }
}

#[test]
fn validate_duplicate_keys_last_wins() {
    let text = r#"{"latitude": 1, "latitude": 2, "longitude": 1, "timezone": "UTC"}"#;
    let in_ = validate(text).unwrap();
    assert_eq!((in_.latitude(), in_.longitude()), (2.0, 1.0));
}

#[test]
fn validate_content_type_not_json() {
    for content_type in [
        Some("text/plain"),
        Some("application/x-www-form-urlencoded"),
        None,
    ] {
        let err = validate_location_body(content_type, V.as_bytes()).unwrap_err();
        assert_eq!(locs(err), vec![body_loc()]);
    }
}

#[test]
fn validate_json_content_type_variants() {
    for content_type in [
        "application/json; charset=utf-8",
        "APPLICATION/JSON",
        "application/vnd.api+json",
    ] {
        let in_ = validate_location_body(Some(content_type), V.as_bytes()).unwrap();
        assert_eq!(in_.latitude(), 52.52, "content type: {content_type}");
    }
}

#[test]
fn validate_invalid_utf8_is_unparseable() {
    let mut raw = V.as_bytes().to_vec();
    let marker = b"\"Berlin\"";
    let start = raw.windows(marker.len()).position(|w| w == marker).unwrap();
    raw[start + 1] = 0xFF;
    let err = validate_location_body(Some(JSON_CT), &raw).unwrap_err();
    assert!(matches!(err, BodyError::Unparseable));
}

#[test]
fn validate_utf8_bom_is_stripped() {
    let text = "\u{feff}{\"latitude\": 1, \"longitude\": 1, \"timezone\": \"UTC\"}";
    let in_ = validate(text).unwrap();
    assert_eq!((in_.latitude(), in_.longitude()), (1.0, 1.0));
    assert_eq!(in_.label(), "");
}

/// Build a `LocationIn` the only way there is: through the validation.
fn location_in(latitude: f64, longitude: f64, timezone: &str) -> LocationIn {
    let text = body(&[
        ("latitude", json!(latitude)),
        ("longitude", json!(longitude)),
        ("timezone", json!(timezone)),
    ]);
    validate(&text).unwrap()
}

#[test]
fn into_location_rounds_to_three_decimals() {
    for (lat, lon, expected_lat, expected_lon) in [
        (48.13749, 11.57552, 48.137, 11.576),
        (0.0005, 0.0005, 0.001, 0.001),
        (-0.0005, -0.0005, -0.001, -0.001),
        (1.0005, 1.0005, 1.0, 1.0),
        (2.675, 2.675, 2.675, 2.675),
    ] {
        let loc = location_in(lat, lon, "Europe/Berlin")
            .into_location()
            .unwrap();
        assert_eq!(loc.latitude, expected_lat, "lat: {lat}");
        assert_eq!(loc.longitude, expected_lon, "lon: {lon}");
    }
}

#[test]
fn into_location_unknown_timezone_is_an_error() {
    let in_ = location_in(52.0, 13.0, "Mars/X");
    assert_eq!(in_.into_location(), Err(UnknownTimezone));
}
