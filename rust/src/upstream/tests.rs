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

#[tokio::test]
async fn fetch_parses_json_and_sends_params() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Json(json!({"a": [1, 2.5]})),
    );
    let client = http_client(5.0).unwrap();
    let params = [
        ("lat", crate::pyfmt::py_repr(52.52)),
        ("date", "2026-09-30T10:25:00+00:00".to_string()),
        ("q", "Alexanderplatz Berlin".to_string()),
    ];
    let value = fetch_json_capped(
        &client,
        &format!("{}/bs/current_weather", fake.base),
        &params,
    )
    .await
    .unwrap();
    assert_eq!(value, json!({"a": [1, 2.5]}));
    let request = fake.requests().into_iter().next().unwrap();
    assert_eq!(request.path, "/bs/current_weather");
    assert_eq!(request.param("lat"), Some("52.52"));
    assert_eq!(request.param("date"), Some("2026-09-30T10:25:00+00:00"));
    assert_eq!(request.param("q"), Some("Alexanderplatz Berlin"));
    assert_eq!(request.user_agent, USER_AGENT);
}

#[tokio::test]
async fn fetch_json_capped_roundtrips_upstream_floats() {
    // Lockstep finding: Open-Meteo sent this 17-digit generationtime; the
    // stored f64 must be exactly "0.40209293365478516".parse::<f64>().
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Raw(r#"{"generationtime_ms": 0.40209293365478516}"#.to_string()),
    );
    let client = http_client(5.0).unwrap();
    let value = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap();
    let expected: f64 = "0.40209293365478516".parse().unwrap();
    assert_eq!(value["generationtime_ms"].as_f64().unwrap(), expected);
    assert!(value.to_string().contains("0.40209293365478516"));
}

#[tokio::test]
async fn fetch_http_error_is_source_error() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set("/bs/current_weather", FakeResponse::Status(500));
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("500"), "got: {err}");
}

#[tokio::test]
async fn fetch_redirect_is_source_error() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set("/bs/current_weather", FakeResponse::Status(302));
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("302"), "got: {err}");
    assert_eq!(fake.requests().len(), 1, "a redirect must not be followed");
}

#[tokio::test]
async fn fetch_broken_json_is_source_error() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Raw("{\"weather\": ".to_string()),
    );
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("not valid JSON"), "got: {err}");
}

#[tokio::test]
async fn fetch_declared_oversize_is_source_error() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Oversize {
            bytes: 6_000_000,
            declare: true,
        },
    );
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("cap"), "got: {err}");
}

#[tokio::test]
async fn fetch_streamed_oversize_is_source_error() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Oversize {
            bytes: 6_000_000,
            declare: false,
        },
    );
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("cap"), "got: {err}");
}

#[tokio::test]
async fn fetch_deeply_nested_json_is_source_error() {
    use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
    let fake = FakeUpstream::start();
    fake.set(
        "/bs/current_weather",
        FakeResponse::Raw("[".repeat(100_000) + &"]".repeat(100_000)),
    );
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/bs/current_weather", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("not valid JSON"), "got: {err}");
}

#[tokio::test]
async fn fetch_unknown_path_is_source_error() {
    use crate::testutil::fake_upstream::FakeUpstream;
    let fake = FakeUpstream::start();
    let client = http_client(5.0).unwrap();
    let err = fetch_json_capped(&client, &format!("{}/never-set", fake.base), &[])
        .await
        .unwrap_err();
    assert!(err.to_string().contains("404"), "got: {err}");
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
