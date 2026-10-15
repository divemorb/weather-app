//! Endpoint tests for the user report routes (`POST /api/reports`,
//! `GET /api/reports/current`, `DELETE /api/reports/{id}`), against a real
//! aggregator over the fake upstream. The clock is fixed at `testkit::NOW`.

use axum::http::{HeaderMap, StatusCode};
use chrono::TimeDelta;
use serde_json::Value;

use crate::aggregator::testkit::{CfgOpts, FakeUpstream, now};
use crate::reports::ReportKind;
use crate::times;

use super::api_tests::api_state;
use super::{AppState, httptest};

/// The same-origin headers (the contract's `SAME_ORIGIN`).
const SAME_ORIGIN: &[(&str, &str)] = &[
    ("content-type", "application/json"),
    ("origin", "http://127.0.0.1:8000"),
];
const FOREIGN: &[(&str, &str)] = &[
    ("content-type", "application/json"),
    ("origin", "http://evil.example"),
];

/// A request to the report endpoints (the host is the default test host).
async fn call(
    state: AppState,
    method: &str,
    uri: &str,
    body: Option<&str>,
    headers: &[(&str, &str)],
) -> (StatusCode, HeaderMap, String) {
    httptest::call(state, method, uri, "127.0.0.1:8000", body, headers).await
}

fn body_json(body: &str) -> Value {
    serde_json::from_str(body).unwrap()
}

/// A state with a configured location (the `CfgOpts` default).
fn state_with_location() -> AppState {
    let fake = FakeUpstream::start();
    api_state(&fake, CfgOpts::default())
}

// -- POST /api/reports ------------------------------------------------------

#[tokio::test]
async fn post_report_ok_201_server_time() {
    let state = state_with_location();
    let (status, _headers, body) = call(
        state.clone(),
        "POST",
        "/api/reports",
        Some(r#"{"kind": "rain", "intensity": "heavy"}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(
        body_json(&body),
        serde_json::json!({
            "report": {
                "id": 1,
                "kind": "rain",
                "intensity": "heavy",
                "confirms": false,
                "observed_at": times::to_iso(now()),
            }
        })
    );
}

#[tokio::test]
async fn post_report_minutes_ago_moves_observed_back() {
    let state = state_with_location();
    let (status, _headers, body) = call(
        state.clone(),
        "POST",
        "/api/reports",
        Some(r#"{"kind": "fog", "minutes_ago": 15, "confirms": true}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    let report = &body_json(&body)["report"];
    assert_eq!(report["id"], Value::from(1));
    assert_eq!(report["intensity"], Value::Null);
    assert_eq!(report["confirms"], Value::Bool(true));
    // 15 whole minutes back: the server's clock, not the client's.
    assert_eq!(
        report["observed_at"],
        Value::from(times::to_iso(now() - TimeDelta::minutes(15)))
    );
    // ... and /api/reports/current now answers it
    let (status, _headers, body) = call(state, "GET", "/api/reports/current", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body_json(&body)["report"]["id"], Value::from(1));
}

#[tokio::test]
async fn post_report_invalid_body_422() {
    let state = state_with_location();
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/reports",
        Some(r#"{"kind": "sunny"}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let detail = &body_json(&body)["detail"];
    assert_eq!(detail[0]["loc"], serde_json::json!(["body", "kind"]));
}

#[tokio::test]
async fn post_report_422_before_403() {
    let state = state_with_location();
    let (status, _headers, _body) = call(
        state,
        "POST",
        "/api/reports",
        Some(r#"{"kind": "sunny"}"#),
        FOREIGN,
    )
    .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY); // validation first
}

#[tokio::test]
async fn post_report_foreign_origin_403() {
    let state = state_with_location();
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/reports",
        Some(r#"{"kind": "rain"}"#),
        FOREIGN,
    )
    .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "cross-site request refused"})
    );
}

#[tokio::test]
async fn post_report_unconfigured_409() {
    let fake = FakeUpstream::start();
    let state = api_state(
        &fake,
        CfgOpts {
            location: None,
            ..CfgOpts::default()
        },
    );
    let (status, _headers, body) = call(
        state,
        "POST",
        "/api/reports",
        Some(r#"{"kind": "rain"}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CONFLICT);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "no location configured"})
    );
}

// -- GET /api/reports/current ------------------------------------------------

#[tokio::test]
async fn current_report_null_when_empty() {
    let state = state_with_location();
    let (status, _headers, body) = call(state, "GET", "/api/reports/current", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body_json(&body), serde_json::json!({"report": null}));
}

#[tokio::test]
async fn current_report_newest_fresh_wins_until_undone() {
    let state = state_with_location();
    // fog 15 min back, then rain now: the newest report decides.
    let (status, _headers, _body) = call(
        state.clone(),
        "POST",
        "/api/reports",
        Some(r#"{"kind": "fog", "minutes_ago": 15}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    let (status, _headers, _body) = call(
        state.clone(),
        "POST",
        "/api/reports",
        Some(r#"{"kind": "rain", "intensity": "heavy"}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    let (status, _headers, body) =
        call(state.clone(), "GET", "/api/reports/current", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body_json(&body)["report"]["id"], Value::from(2));
    // undo the rain: the fog is still fresh (15 min old) and becomes current
    let (status, _headers, _body) =
        call(state.clone(), "DELETE", "/api/reports/2", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    let (status, _headers, body) = call(state, "GET", "/api/reports/current", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body_json(&body)["report"]["id"], Value::from(1));
}

#[tokio::test]
async fn current_report_freshness_bounds_inclusive_future_ignored() {
    let state = state_with_location();
    let store = state.aggregator.store();
    // exactly 30 min back: still fresh (both ends inclusive)
    let at_30 = times::to_iso(now() - TimeDelta::minutes(30));
    let at_31 = times::to_iso(now() - TimeDelta::minutes(31));
    store
        .add_report(ReportKind::Cloudy, None, false, &at_31)
        .unwrap();
    store
        .add_report(ReportKind::Fog, None, false, &at_30)
        .unwrap();
    // a report after "now" (the clock jumped back) must not hide the fresh one
    let future = times::to_iso(now() + TimeDelta::minutes(1));
    store
        .add_report(ReportKind::Hail, None, false, &future)
        .unwrap();
    let (status, _headers, body) = call(state, "GET", "/api/reports/current", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    let report = &body_json(&body)["report"];
    assert_eq!(report["kind"], Value::from("fog"));
    assert_eq!(report["observed_at"], Value::from(at_30));
}

// -- DELETE /api/reports/{id} ------------------------------------------------

#[tokio::test]
async fn delete_report_ok_then_404() {
    let state = state_with_location();
    let (status, _headers, _body) = call(
        state.clone(),
        "POST",
        "/api/reports",
        Some(r#"{"kind": "rain"}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    let (status, _headers, body) = call(state.clone(), "DELETE", "/api/reports/1", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(body_json(&body), serde_json::json!({"deleted": 1}));
    let (status, _headers, body) = call(state, "DELETE", "/api/reports/1", None, &[]).await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "report not found"})
    );
}

#[tokio::test]
async fn delete_report_bad_id_422() {
    for raw in ["abc", "0", "+9", "9.0", "09", "1234567890123456789"] {
        let state = state_with_location();
        let (status, _headers, body) =
            call(state, "DELETE", &format!("/api/reports/{raw}"), None, &[]).await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "id {raw:?}");
        let detail = &body_json(&body)["detail"];
        assert_eq!(detail[0]["loc"], serde_json::json!(["path", "report_id"]));
    }
}

#[tokio::test]
async fn delete_current_is_the_id_422() {
    // The reference app answers DELETE /api/reports/current from the id route.
    let state = state_with_location();
    let (status, _headers, body) = call(state, "DELETE", "/api/reports/current", None, &[]).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let detail = &body_json(&body)["detail"];
    assert_eq!(detail[0]["loc"], serde_json::json!(["path", "report_id"]));
}

#[tokio::test]
async fn delete_report_origin_checks() {
    let state = state_with_location();
    let (status, _headers, _body) = call(
        state.clone(),
        "POST",
        "/api/reports",
        Some(r#"{"kind": "rain"}"#),
        SAME_ORIGIN,
    )
    .await;
    assert_eq!(status, StatusCode::CREATED);
    // the id is valid, but the origin is foreign
    let (status, _headers, body) =
        call(state.clone(), "DELETE", "/api/reports/1", None, FOREIGN).await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "cross-site request refused"})
    );
    // a bad id is a 422 even for a foreign origin (validation first)
    let (status, _headers, _body) = call(state, "DELETE", "/api/reports/abc", None, FOREIGN).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}

// -- routing: the GETs fall through to the static files, others are 405 -----

#[tokio::test]
async fn get_report_paths_fall_to_static_404() {
    let state = state_with_location();
    for uri in ["/api/reports", "/api/reports/3"] {
        let (status, _headers, body) = call(state.clone(), "GET", uri, None, &[]).await;
        assert_eq!(status, StatusCode::NOT_FOUND, "GET {uri}");
        assert_eq!(body_json(&body), serde_json::json!({"detail": "Not Found"}));
    }
}

#[tokio::test]
async fn wrong_methods_405() {
    for (method, uri) in [
        ("PUT", "/api/reports"),
        ("POST", "/api/reports/current"),
        ("PUT", "/api/reports/3"),
    ] {
        let state = state_with_location();
        let (status, _headers, body) = call(state.clone(), method, uri, None, &[]).await;
        assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED, "{method} {uri}");
        assert_eq!(
            body_json(&body),
            serde_json::json!({"detail": "Method Not Allowed"})
        );
    }
}
