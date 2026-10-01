//! The Open-Meteo HTTP-layer tests (the HTTP tests of Python
//! `tests/test_openmeteo_client.py`).

use super::*;
use serde_json::{Value, json};

use crate::testutil;
use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
use crate::upstream::MAX_RESPONSE_BYTES;

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

/// Python `_forecast_payload()`.
fn forecast_payload() -> Value {
    testutil::make_forecast_payload(
        &["icon_d2", "icon_eu"],
        &HOURS,
        &MIN15,
        &[
            (
                "icon_d2",
                vec![json!(0.0), json!(0.5), json!(0.0), json!(0.0)],
            ),
            ("icon_eu", vec![json!(0.0); 4]),
        ],
        &[
            (
                "icon_d2",
                vec![
                    json!(0.0),
                    json!(0.2),
                    json!(0.3),
                    json!(0.0),
                    json!(0.0),
                    json!(0.0),
                    json!(0.0),
                    json!(0.0),
                ],
            ),
            ("icon_eu", vec![json!(0.0); 8]),
        ],
        &[
            (
                "apparent_temperature",
                &[
                    (
                        "icon_d2",
                        vec![json!(5.0), json!(6.0), json!(7.0), json!(8.0)],
                    ),
                    (
                        "icon_eu",
                        vec![json!(4.0), json!(5.0), json!(6.0), json!(7.0)],
                    ),
                ],
            ),
            (
                "wind_speed_10m",
                &[
                    (
                        "icon_d2",
                        vec![json!(10.0), json!(12.0), json!(14.0), json!(16.0)],
                    ),
                    (
                        "icon_eu",
                        vec![json!(8.0), json!(9.0), json!(10.0), json!(11.0)],
                    ),
                ],
            ),
            (
                "temperature_2m",
                &[
                    (
                        "icon_d2",
                        vec![json!(5.0), json!(6.0), json!(7.0), json!(8.0)],
                    ),
                    (
                        "icon_eu",
                        vec![json!(4.0), json!(5.0), json!(6.0), json!(7.0)],
                    ),
                ],
            ),
            (
                "cloud_cover",
                &[
                    (
                        "icon_d2",
                        vec![json!(10.0), json!(20.0), json!(30.0), json!(40.0)],
                    ),
                    (
                        "icon_eu",
                        vec![json!(5.0), json!(6.0), json!(7.0), json!(8.0)],
                    ),
                ],
            ),
        ],
    )
}

/// Python `_ensemble_payload()`: 4 hours, control + 3 members
/// (member01..03).
fn ensemble_payload() -> Value {
    testutil::make_ensemble_payload(
        &HOURS,
        vec![json!(0.0), json!(0.1), json!(0.2), json!(0.3)],
        &[
            vec![json!(0.0), json!(0.5), json!(0.0), json!(0.0)],
            vec![json!(0.0); 4],
            vec![json!(0.2); 4],
        ],
    )
}

/// Python `test_client_forecast_builds_correct_params`.
#[tokio::test]
async fn client_forecast_builds_correct_params() {
    let fake = FakeUpstream::start();
    fake.set("/om/v1/forecast", FakeResponse::Json(forecast_payload()));
    let client = openmeteo(&fake);
    let payload = client.fetch_forecast_payload().await.expect("fetch ok");
    assert!(payload["hourly"].get("precipitation_icon_d2").is_some());
    assert!(payload["hourly"].get("precipitation_icon_eu").is_some());
    let req = fake.requests().first().expect("one request").clone();
    assert!(req.path.contains("/forecast"));
    assert_eq!(req.param("models"), Some("icon_d2,icon_eu"));
    assert_eq!(req.param("timezone"), Some("UTC"));
    // 3 days so 24 *future* hours remain even late in the UTC day (step 6b)
    assert_eq!(req.param("forecast_days"), Some("3"));
}

/// Python `test_client_ensemble_builds_correct_params`.
#[tokio::test]
async fn client_ensemble_builds_correct_params() {
    let fake = FakeUpstream::start();
    fake.set("/ens/v1/ensemble", FakeResponse::Json(ensemble_payload()));
    let client = openmeteo(&fake);
    let payload = client.fetch_ensemble_payload().await.expect("fetch ok");
    let members = payload["hourly"].as_object().map(|h| {
        h.keys()
            .filter(|k| k.starts_with("precipitation_member"))
            .count()
    });
    assert_eq!(members, Some(3));
    let req = fake.requests().first().expect("one request").clone();
    assert!(req.path.contains("/ensemble"));
    assert_eq!(req.param("models"), Some("ecmwf_ifs025"));
}

/// Python `test_client_api_error_json_raises_source_error`.
#[tokio::test]
async fn client_api_error_json_raises_source_error() {
    let fake = FakeUpstream::start();
    fake.set(
        "/om/v1/forecast",
        FakeResponse::Json(json!({"error": true, "reason": "invalid model"})),
    );
    let client = openmeteo(&fake);
    let err = client
        .fetch_forecast_payload()
        .await
        .expect_err("an API error body is a SourceError");
    assert_eq!(err.to_string(), "Open-Meteo error: invalid model");
}

/// Python `test_client_rejects_body_over_response_size_cap` (Open-Meteo):
/// the same cap as the Bright Sky client.
#[tokio::test]
async fn client_rejects_body_over_response_size_cap() {
    let fake = FakeUpstream::start();
    fake.set(
        "/om/v1/forecast",
        FakeResponse::Oversize {
            bytes: MAX_RESPONSE_BYTES + 1,
            declare: true,
        },
    );
    let client = openmeteo(&fake);
    let err = client
        .fetch_forecast_payload()
        .await
        .expect_err("an oversized body is a SourceError");
    assert!(err.to_string().contains("cap"));
}
