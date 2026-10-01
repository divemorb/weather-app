//! Ports of `tests/test_geocode.py` (all 10), plus the approved deviation 8
//! (non-finite coordinates are skipped) and the concurrent-throttle case.
//! Python's `httpx2.MockTransport` becomes
//! `testutil::fake_upstream::FakeUpstream` serving `/search`.

use super::*;
use std::sync::{Arc, Mutex};

use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};
use serde_json::json;

/// A real-shaped Nominatim response: "lat"/"lon" are strings; no match -> [].
fn nominatim_sample() -> Value {
    json!([
        {
            "display_name": "Thomass-Eck, 1, Marienplatz, …, München, Bayern, 80331, Deutschland",
            "lat": "48.1374990",
            "lon": "11.5755020",
        },
        {
            "display_name": "Marienplatz, München, Bayern, Deutschland",
            "lat": "48.1386200",
            "lon": "11.5765400",
        },
    ])
}

fn http() -> reqwest::Client {
    upstream::http_client(10.0).expect("building the test client")
}

/// A geocoder against the fake upstream with a constant clock at 1000 s
/// and a sleep that only records (no real waiting).
fn geocoder(fake: &FakeUpstream, sleeps: &Arc<Mutex<Vec<f64>>>) -> Geocoder {
    Geocoder::new_for_test(&fake.base, http(), Monotonic::Fixed(1000.0), sleeps.clone())
}

// ---------------------------------------------------------------------------
// parser (pure)
// ---------------------------------------------------------------------------

#[test]
fn parse_nominatim_real_shaped_sample() {
    assert_eq!(
        parse_nominatim(&nominatim_sample()).expect("the sample is valid"),
        vec![
            GeocodeResult {
                label: "Thomass-Eck, 1, Marienplatz, …, München, Bayern, 80331, Deutschland"
                    .to_string(),
                latitude: 48.1374990,
                longitude: 11.5755020,
            },
            GeocodeResult {
                label: "Marienplatz, München, Bayern, Deutschland".to_string(),
                latitude: 48.1386200,
                longitude: 11.5765400,
            },
        ]
    );
}

#[test]
fn parse_nominatim_no_match_is_empty_list() {
    assert_eq!(
        parse_nominatim(&json!([])).expect("[] is valid"),
        Vec::<GeocodeResult>::new()
    );
}

#[test]
fn parse_nominatim_skips_malformed_entries() {
    let payload = json!([
        {"display_name": "ok"},
        {"lat": "not-a-number", "lon": "11.0", "display_name": "bad lat"},
        {"lat": "48.0"},
        {"display_name": null, "lat": "48.0", "lon": "11.0"},
        "not-even-a-dict",
        {"display_name": "fine", "lat": "48.5", "lon": "11.5"},
    ]);
    assert_eq!(
        parse_nominatim(&payload).expect("a valid list"),
        vec![GeocodeResult {
            label: "fine".to_string(),
            latitude: 48.5,
            longitude: 11.5,
        }]
    );
}

#[test]
fn parse_nominatim_non_list_is_source_error() {
    for payload in [
        json!({"results": []}),
        json!("a list of results"),
        Value::Null,
        json!(42),
    ] {
        assert!(parse_nominatim(&payload).is_err());
    }
}

#[test]
fn parse_nominatim_caps_at_five() {
    let entries: Vec<Value> = (0..8)
        .map(|i| json!({"display_name": format!("place {i}"), "lat": "48.0", "lon": "11.0"}))
        .collect();
    assert_eq!(
        parse_nominatim(&Value::Array(entries))
            .expect("a valid list")
            .len(),
        5
    );
}

#[test]
fn parse_nominatim_floats_like_python() {
    // Verified Python behaviour: " 48.1 " -> 48.1, "1_1" -> 11.0,
    // true -> 1.0, "1e2" -> 100.0, "-0" -> -0.0.
    let payload = json!([
        {"display_name": "a", "lat": " 48.1 ", "lon": "1_1"},
        {"display_name": "b", "lat": true, "lon": "1e2"},
        {"display_name": "c", "lat": "-0", "lon": 48.0},
    ]);
    let results = parse_nominatim(&payload).expect("a valid list");
    assert_eq!(
        results,
        vec![
            GeocodeResult {
                label: "a".to_string(),
                latitude: 48.1,
                longitude: 11.0,
            },
            GeocodeResult {
                label: "b".to_string(),
                latitude: 1.0,
                longitude: 100.0,
            },
            GeocodeResult {
                label: "c".to_string(),
                latitude: -0.0,
                longitude: 48.0,
            },
        ]
    );
}

#[test]
fn parse_nominatim_skips_non_finite_coordinates() {
    // Approved deviation 8: "nan"/"inf" strings, nulls and non-numeric
    // values skip the entry (Python would write invalid JSON later).
    let payload = json!([
        {"display_name": "nan", "lat": "nan", "lon": "11.0"},
        {"display_name": "inf", "lat": "48.0", "lon": "inf"},
        {"display_name": "null lat", "lat": null, "lon": "11.0"},
        {"display_name": "list lon", "lat": "48.0", "lon": [1.0]},
        {"display_name": "ok", "lat": "48.5", "lon": "11.5"},
    ]);
    assert_eq!(
        parse_nominatim(&payload).expect("a valid list"),
        vec![GeocodeResult {
            label: "ok".to_string(),
            latitude: 48.5,
            longitude: 11.5,
        }]
    );
}

// ---------------------------------------------------------------------------
// Geocoder client (FakeUpstream, fake clock + sleep)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn search_request_carries_user_agent_and_jsonv2_params() {
    let fake = FakeUpstream::start();
    fake.set("/search", FakeResponse::Json(nominatim_sample()));
    let sleeps = Arc::new(Mutex::new(Vec::new()));
    let g = geocoder(&fake, &sleeps);
    let results = g
        .search("Marienplatz 1, München")
        .await
        .expect("the search succeeds");
    assert_eq!(results.len(), 2);
    let requests = fake.requests();
    assert_eq!(requests.len(), 1);
    let req = &requests[0];
    assert_eq!(req.path, "/search");
    assert_eq!(
        req.user_agent,
        "WetterLocal/1.0 (self-hosted home weather app)"
    );
    assert_eq!(req.param("format"), Some("jsonv2"));
    assert_eq!(req.param("q"), Some("Marienplatz 1, München"));
    assert_eq!(req.param("limit"), Some("5"));
    assert_eq!(req.param("addressdetails"), Some("0"));
}

#[tokio::test]
async fn search_caches_identical_query_including_case() {
    let fake = FakeUpstream::start();
    fake.set("/search", FakeResponse::Json(nominatim_sample()));
    let sleeps = Arc::new(Mutex::new(Vec::new()));
    let g = geocoder(&fake, &sleeps);
    let first = g
        .search("münchen")
        .await
        .expect("the first search succeeds");
    let second = g
        .search("MÜNCHEN")
        .await
        .expect("the second search succeeds");
    assert_eq!(first, second);
    assert_eq!(fake.requests().len(), 1); // the second call was a cache hit
    assert!(sleeps.lock().unwrap().is_empty());
}

#[tokio::test]
async fn search_throttles_two_different_queries() {
    let fake = FakeUpstream::start();
    fake.set("/search", FakeResponse::Json(nominatim_sample()));
    let sleeps = Arc::new(Mutex::new(Vec::new()));
    let g = geocoder(&fake, &sleeps);
    g.search("query one")
        .await
        .expect("the first search succeeds");
    g.search("query two")
        .await
        .expect("the second search succeeds");
    assert_eq!(fake.requests().len(), 2);
    // Constant clock -> the second request waited the full spacing.
    let sleeps = sleeps.lock().unwrap();
    assert_eq!(sleeps.len(), 1);
    assert!(sleeps[0] > 1.0);
    assert!(sleeps[0] <= 1.1);
}

#[tokio::test]
async fn search_first_request_never_sleeps() {
    let fake = FakeUpstream::start();
    fake.set("/search", FakeResponse::Json(nominatim_sample()));
    let sleeps = Arc::new(Mutex::new(Vec::new()));
    let g = geocoder(&fake, &sleeps);
    g.search("only one").await.expect("the search succeeds");
    assert_eq!(fake.requests().len(), 1);
    assert!(sleeps.lock().unwrap().is_empty());
}

#[tokio::test]
async fn search_upstream_error_is_source_error_and_not_cached() {
    let fake = FakeUpstream::start();
    fake.set("/search", FakeResponse::Status(503));
    let sleeps = Arc::new(Mutex::new(Vec::new()));
    let g = geocoder(&fake, &sleeps);
    assert!(g.search("boom street").await.is_err());
    // The failed query was not cached: a retry goes out again.
    fake.set("/search", FakeResponse::Json(nominatim_sample()));
    let g2 = geocoder(&fake, &sleeps);
    let results = g2.search("boom street").await.expect("the retry succeeds");
    assert_eq!(results.len(), 2);
    assert_eq!(fake.requests().len(), 2);
}

#[tokio::test]
async fn search_throttles_concurrent_searches() {
    // Real clock and real sleep (the one test that really waits ~1.1 s):
    // two concurrent searches must still be spaced by the full spacing.
    let fake = FakeUpstream::start();
    fake.set("/search", FakeResponse::Json(nominatim_sample()));
    let g = Arc::new(Geocoder::new(&fake.base, http()));
    let g2 = g.clone();
    let start = std::time::Instant::now();
    let (first, second) = tokio::join!(g.search("concurrent one"), g2.search("concurrent two"));
    let elapsed = start.elapsed().as_secs_f64();
    assert_eq!(first.expect("the first search succeeds").len(), 2);
    assert_eq!(second.expect("the second search succeeds").len(), 2);
    assert_eq!(fake.requests().len(), 2);
    assert!(
        elapsed >= 1.05,
        "the second search must wait the spacing, took {elapsed} s"
    );
    assert!(
        elapsed <= 2.0,
        "only the second search may wait, took {elapsed} s"
    );
}
