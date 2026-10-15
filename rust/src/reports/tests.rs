//! Tests for the report body and id (the rows of the spec's "what is
//! refused" table, the defaults, and the id pattern of the reference app).

use super::*;
use serde_json::json;

const JSON_CT: Option<&str> = Some("application/json");

/// The full 422 `{"detail": [...]}` the body gets (asserts it is a 422).
fn detail(body: &str) -> Value {
    let result = parse_report_body(JSON_CT, body.as_bytes());
    assert!(
        matches!(&result, Err(ReportBodyError::Invalid(_))),
        "expected a 422 for {body:?}, got: {result:?}"
    );
    match result {
        Err(ReportBodyError::Invalid(errors)) => errors_json(&errors),
        // The assert above already failed the test; nothing is returned.
        Ok(_) | Err(ReportBodyError::Unparseable) => Value::Null,
    }
}

/// The `loc`s of the 422 the body gets.
fn locs(body: &str) -> Vec<Value> {
    let value = detail(body);
    value["detail"]
        .as_array()
        .map(|entries| entries.iter().map(|entry| entry["loc"].clone()).collect())
        .unwrap_or_default()
}

/// The report a valid body parses to (asserts it parses).
fn parsed(body: &str) -> ReportIn {
    let result = parse_report_body(JSON_CT, body.as_bytes());
    assert!(
        result.is_ok(),
        "expected a valid body for {body:?}, got: {result:?}"
    );
    match result {
        Ok(report) => report,
        // The assert above already failed the test; nothing is returned.
        Err(_) => ReportIn {
            kind: ReportKind::Fog,
            intensity: None,
            minutes_ago: MinutesAgo::NOW,
            confirms: false,
        },
    }
}

// ---------------------------------------------------------------------------
// every row of test_invalid_body_is_422_without_echo, with its loc
// ---------------------------------------------------------------------------

#[test]
fn invalid_bodies_are_422_with_python_locs() {
    let cases: &[(&str, Value)] = &[
        (r#"{"kind": "sunny"}"#, json!([["body", "kind"]])),
        (r#"{"kind": "Rain"}"#, json!([["body", "kind"]])),
        (r#"{"kind": 1}"#, json!([["body", "kind"]])),
        (r"{}", json!([["body", "kind"]])),
        (
            r#"{"kind": "rain", "intensity": "huge"}"#,
            json!([["body", "intensity"]]),
        ),
        (
            r#"{"kind": "fog", "intensity": "light"}"#,
            json!([["body", "intensity"]]),
        ),
        (
            r#"{"kind": "snow", "intensity": "heavy"}"#,
            json!([["body", "intensity"]]),
        ),
        (
            r#"{"kind": "rain", "minutes_ago": 10}"#,
            json!([["body", "minutes_ago"]]),
        ),
        (
            r#"{"kind": "rain", "minutes_ago": -15}"#,
            json!([["body", "minutes_ago"]]),
        ),
        (
            r#"{"kind": "rain", "minutes_ago": "15"}"#,
            json!([["body", "minutes_ago"]]),
        ),
        (
            r#"{"kind": "rain", "minutes_ago": 15.0}"#,
            json!([["body", "minutes_ago"]]),
        ),
        (
            r#"{"kind": "rain", "minutes_ago": false}"#,
            json!([["body", "minutes_ago"]]),
        ),
        (
            r#"{"kind": "rain", "minutes_ago": null}"#,
            json!([["body", "minutes_ago"]]),
        ),
        (
            r#"{"kind": "rain", "confirms": "yes"}"#,
            json!([["body", "confirms"]]),
        ),
        (
            r#"{"kind": "rain", "confirms": 1}"#,
            json!([["body", "confirms"]]),
        ),
        (
            r#"{"kind": "rain", "observed_at": "2025-01-01T08:00:00Z"}"#,
            json!([["body", "observed_at"]]),
        ),
        (
            r#"{"kind": "rain", "extra": 1}"#,
            json!([["body", "extra"]]),
        ),
    ];
    for (body, expected) in cases {
        assert_eq!(Value::Array(locs(body)), *expected, "body: {body}");
    }
    // a JSON array is not an object: the whole body is refused
    assert_eq!(locs("[1]"), vec![json!(["body"])]);
}

#[test]
fn the_msgs_match_python() {
    let entries = |body: &str| -> Vec<Value> {
        let value = detail(body);
        value["detail"].as_array().cloned().unwrap_or_default()
    };
    assert_eq!(
        entries(r#"{"kind": "sunny"}"#),
        vec![json!({"loc": ["body", "kind"], "msg": KIND_MSG})]
    );
    assert_eq!(
        entries(r"{}"),
        vec![json!({"loc": ["body", "kind"], "msg": "Field required"})]
    );
    assert_eq!(
        entries(r#"{"kind": "rain", "intensity": "huge"}"#),
        vec![json!({"loc": ["body", "intensity"], "msg": INTENSITY_MSG})]
    );
    assert_eq!(
        entries(r#"{"kind": "fog", "intensity": "light"}"#),
        vec![json!({
            "loc": ["body", "intensity"],
            "msg": "Value error, intensity is only reported for rain"
        })]
    );
    assert_eq!(
        entries(r#"{"intensity": "light"}"#),
        vec![
            json!({"loc": ["body", "kind"], "msg": "Field required"}),
            json!({
                "loc": ["body", "intensity"],
                "msg": "Value error, intensity is only reported for rain"
            })
        ]
    );
    assert_eq!(
        entries(r#"{"kind": "rain", "minutes_ago": 10}"#),
        vec![json!({
            "loc": ["body", "minutes_ago"],
            "msg": "Value error, minutes_ago must be 0, 15 or 30"
        })]
    );
    assert_eq!(
        entries(r#"{"kind": "rain", "minutes_ago": 15.0}"#),
        vec![json!({"loc": ["body", "minutes_ago"], "msg": "Input should be a valid integer"})]
    );
    assert_eq!(
        entries(r#"{"kind": "rain", "confirms": 1}"#),
        vec![json!({"loc": ["body", "confirms"], "msg": "Input should be a valid boolean"})]
    );
    assert_eq!(
        entries(r#"{"kind": "rain", "extra": 1}"#),
        vec![json!({"loc": ["body", "extra"], "msg": "Extra inputs are not permitted"})]
    );
}

#[test]
fn field_errors_come_before_the_extra_fields() {
    // The reference app reports the field errors in the model's order, then
    // the unknown fields; the extras follow the map's (sorted) order here.
    assert_eq!(
        locs(r#"{"zeta": 1, "kind": "sunny", "alpha": 2}"#),
        vec![
            json!(["body", "kind"]),
            json!(["body", "alpha"]),
            json!(["body", "zeta"])
        ]
    );
}

#[test]
fn a_not_json_body_is_refused_at_its_error_position() {
    assert_eq!(locs("abc"), vec![json!(["body", 0])]);
    assert_eq!(locs(r#"{"kind": "rain""#), vec![json!(["body", 15])]);
}

#[test]
fn an_empty_body_or_a_wrong_content_type_is_field_required() {
    let expected = json!({"detail": [{"loc": ["body"], "msg": "Field required"}]});
    for content_type in [None, Some("text/plain"), Some("application/xml")] {
        let result = parse_report_body(content_type, br#"{"kind": "rain"}"#);
        assert!(
            matches!(&result, Err(ReportBodyError::Invalid(errors)) if errors_json(errors) == expected),
            "content type {content_type:?}"
        );
    }
    let result = parse_report_body(JSON_CT, b"");
    assert!(
        matches!(&result, Err(ReportBodyError::Invalid(errors)) if errors_json(errors) == expected)
    );
    // a JSON content type with parameters or a vendor subtype is still JSON
    let report = parsed(r#"{"kind": "rain"}"#);
    let with_params = parse_report_body(
        Some("application/json; charset=UTF-8"),
        br#"{"kind": "rain"}"#,
    );
    assert_eq!(with_params, Ok(report.clone()));
    let vendor = parse_report_body(Some("application/vnd.api+json"), br#"{"kind": "rain"}"#);
    assert_eq!(vendor, Ok(report));
}

#[test]
fn a_bom_is_stripped_and_non_utf8_is_unparseable() {
    let with_bom = "\u{feff}{\"kind\": \"fog\"}".to_string();
    let report = parsed(&with_bom);
    assert_eq!(report.kind(), ReportKind::Fog);

    assert!(matches!(
        parse_report_body(JSON_CT, b"\xff\xfe\xfd{}"),
        Err(ReportBodyError::Unparseable)
    ));
}

#[test]
fn json_null_is_a_missing_body_and_other_scalars_are_not_objects() {
    assert_eq!(locs("null"), vec![json!(["body"])]);
    assert_eq!(locs("123"), vec![json!(["body"])]);
    assert_eq!(locs("true"), vec![json!(["body"])]);
}

// ---------------------------------------------------------------------------
// the valid bodies
// ---------------------------------------------------------------------------

#[test]
fn the_defaults_are_none_false_and_zero_minutes() {
    let report = parsed(r#"{"kind": "fog"}"#);
    assert_eq!(report.kind(), ReportKind::Fog);
    assert_eq!(report.intensity(), None);
    assert_eq!(report.minutes_ago().minutes(), 0);
    assert!(!report.confirms());

    let report = parsed(r#"{"kind": "rain", "intensity": null}"#);
    assert_eq!(report.intensity(), None);
}

#[test]
fn every_kind_parses_and_round_trips() {
    let kinds = [
        ("clear", ReportKind::Clear),
        ("partly-cloudy", ReportKind::PartlyCloudy),
        ("cloudy", ReportKind::Cloudy),
        ("fog", ReportKind::Fog),
        ("rain", ReportKind::Rain),
        ("thunderstorm", ReportKind::Thunderstorm),
        ("snow", ReportKind::Snow),
        ("hail", ReportKind::Hail),
    ];
    for (name, kind) in kinds {
        assert_eq!(ReportKind::parse(name), Some(kind));
        assert_eq!(kind.as_str(), name);
        let body = format!("{{\"kind\": \"{name}\"}}");
        let report = parsed(&body);
        assert_eq!(report.kind(), kind);
    }
    for bad in ["", "Rain", "rainy", "RAIN", " clear"] {
        assert_eq!(ReportKind::parse(bad), None);
    }
}

#[test]
fn the_intensities_parse_and_round_trip() {
    let intensities = [
        ("light", Intensity::Light),
        ("moderate", Intensity::Moderate),
        ("heavy", Intensity::Heavy),
    ];
    for (name, intensity) in intensities {
        assert_eq!(Intensity::parse(name), Some(intensity));
        assert_eq!(intensity.as_str(), name);
        let body = format!("{{\"kind\": \"rain\", \"intensity\": \"{name}\"}}");
        let report = parsed(&body);
        assert_eq!(report.intensity(), Some(intensity));
    }
    for bad in ["", "LIGHT", "huge", "wet"] {
        assert_eq!(Intensity::parse(bad), None);
    }
}

#[test]
fn every_minutes_ago_value_is_accepted() {
    for minutes in [0, 15, 30] {
        assert_eq!(MinutesAgo::new(minutes), Some(MinutesAgo(minutes)));
        let body = format!("{{\"kind\": \"snow\", \"minutes_ago\": {minutes}}}");
        let report = parsed(&body);
        assert_eq!(report.minutes_ago().minutes(), minutes);
    }
    for bad in [1, 10, 45, -15, -30] {
        assert_eq!(MinutesAgo::new(bad), None);
    }
}

#[test]
fn a_confirmation_is_stored() {
    let report = parsed(r#"{"kind": "cloudy", "confirms": true}"#);
    assert!(report.confirms());
}

#[test]
fn the_wet_kinds_are_rain_thunderstorm_snow_and_hail() {
    assert!(ReportKind::Rain.is_wet());
    assert!(ReportKind::Thunderstorm.is_wet());
    assert!(ReportKind::Snow.is_wet());
    assert!(ReportKind::Hail.is_wet());
    assert!(!ReportKind::Clear.is_wet());
    assert!(!ReportKind::PartlyCloudy.is_wet());
    assert!(!ReportKind::Cloudy.is_wet());
    assert!(!ReportKind::Fog.is_wet());
}

#[test]
fn errors_json_is_the_422_shape() {
    let value = errors_json(&[
        ReportFieldError {
            loc: vec![Loc::Body, Loc::Field("kind")],
            msg: "Field required",
        },
        ReportFieldError {
            loc: vec![Loc::Body, Loc::Extra("extra".to_string())],
            msg: "Extra inputs are not permitted",
        },
        ReportFieldError {
            loc: vec![Loc::Body, Loc::Pos(0)],
            msg: "JSON decode error",
        },
    ]);
    assert_eq!(
        value,
        json!({"detail": [
            {"loc": ["body", "kind"], "msg": "Field required"},
            {"loc": ["body", "extra"], "msg": "Extra inputs are not permitted"},
            {"loc": ["body", 0], "msg": "JSON decode error"},
        ]})
    );
}

// ---------------------------------------------------------------------------
// the path id: ^[1-9][0-9]{0,17}$
// ---------------------------------------------------------------------------

#[test]
fn the_id_must_be_plain_digits() {
    // every raw of test_delete_id_must_be_plain_digits ("%205" arrives as " 5")
    for bad in [
        "abc",
        "0",
        "-1",
        "+5",
        "5.0",
        "05",
        " 5",
        "1234567890123456789",
        "",
        "00",
        "1.0",
        "1e2",
    ] {
        assert_eq!(parse_report_id(bad), None, "id: {bad:?}");
    }
    assert_eq!(parse_report_id("1"), Some(1));
    assert_eq!(
        parse_report_id("123456789012345678"),
        Some(123_456_789_012_345_678)
    );
    assert_eq!(
        parse_report_id("999999999999999999"),
        Some(999_999_999_999_999_999)
    );
}
