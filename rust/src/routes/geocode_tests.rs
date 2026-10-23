//! Endpoint tests for `GET /api/geocode`, against the fake upstream's
//! `/nom/search`: the results, a failed lookup, the query's length limits.

use axum::http::StatusCode;

use crate::aggregator::testkit::{CfgOpts, FakeResponse, FakeUpstream};

use super::api_tests::api_state;
use super::location_tests::{body_json, call};

/// the geocoder points at the fake's `/nom/search`.
#[tokio::test]
async fn get_geocode_returns_results() {
    let fake = FakeUpstream::start();
    fake.set(
        "/nom/search",
        FakeResponse::Json(serde_json::json!([
            {"display_name": "Marienplatz, München", "lat": 48.138, "lon": 11.577},
        ])),
    );
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(
        state,
        "GET",
        "/api/geocode?q=Marienplatz%20M%C3%BCnchen",
        None,
        &[],
    )
    .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        body_json(&body),
        serde_json::json!({
            "results": [
                {"label": "Marienplatz, München", "latitude": 48.138, "longitude": 11.577}
            ]
        })
    );
    // the query reached the geocoder, percent-decoded
    let requests = fake.requests_to("/nom/search");
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].param("q"), Some("Marienplatz München"));
}

/// a failed lookup is a 502, never a 500.
#[tokio::test]
async fn get_geocode_source_error_is_502() {
    let fake = FakeUpstream::start();
    fake.set("/nom/search", FakeResponse::Status(500));
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(
        state,
        "GET",
        "/api/geocode?q=Marienplatz%20M%C3%BCnchen",
        None,
        &[],
    )
    .await;
    assert_eq!(status, StatusCode::BAD_GATEWAY);
    assert_eq!(
        body_json(&body),
        serde_json::json!({"detail": "address lookup failed"})
    );
}

/// no request goes out.
#[tokio::test]
async fn get_geocode_query_too_short_is_422() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, body) = call(state, "GET", "/api/geocode?q=ab", None, &[]).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body_json(&body)["detail"][0]["loc"],
        serde_json::json!(["query", "q"])
    );
    assert_eq!(fake.requests_to("/nom/search"), []);
}

#[tokio::test]
async fn get_geocode_query_of_3_characters_is_accepted() {
    let fake = FakeUpstream::start();
    fake.set(
        "/nom/search",
        FakeResponse::Json(serde_json::json!([
            {"display_name": "Marienplatz, München", "lat": 48.138, "lon": 11.577},
        ])),
    );
    let state = api_state(&fake, CfgOpts::default());
    let (status, _headers, _body) = call(state, "GET", "/api/geocode?q=abc", None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(fake.requests_to("/nom/search").len(), 1);
}

#[tokio::test]
async fn get_geocode_query_of_200_characters_is_accepted() {
    let fake = FakeUpstream::start();
    fake.set(
        "/nom/search",
        FakeResponse::Json(serde_json::json!([
            {"display_name": "Marienplatz, München", "lat": 48.138, "lon": 11.577},
        ])),
    );
    let state = api_state(&fake, CfgOpts::default());
    let q = "a".repeat(200);
    let (status, _headers, _body) =
        call(state, "GET", &format!("/api/geocode?q={q}"), None, &[]).await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(fake.requests_to("/nom/search").len(), 1);
}

#[tokio::test]
async fn get_geocode_query_of_201_characters_is_422() {
    let fake = FakeUpstream::start();
    let state = api_state(&fake, CfgOpts::default());
    let q = "a".repeat(201);
    let (status, _headers, body) =
        call(state, "GET", &format!("/api/geocode?q={q}"), None, &[]).await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(
        body_json(&body)["detail"][0]["loc"],
        serde_json::json!(["query", "q"])
    );
    assert_eq!(fake.requests_to("/nom/search"), []);
}
