use chrono::TimeDelta;
use serde_json::json;

use super::testkit::{self, *};
use super::*;
use crate::clients::Location;
use crate::config::LocationConfig;
use crate::location::{self, location_from_json};
use crate::times::Clock;

/// The location stored in the meta (the `set_location` result).
fn stored_location(agg: &Aggregator) -> Option<LocationConfig> {
    location_from_json(
        agg.store()
            .get_meta(location::LOCATION_KEY)
            .unwrap()
            .as_deref(),
    )
}

/// `set_location` propagated: the meta, the config and both clients agree.
fn location_everywhere(agg: &Aggregator, latitude: f64, longitude: f64) {
    let loc = location(latitude, longitude);
    assert_eq!(stored_location(agg), Some(loc.clone()));
    assert_eq!(agg.cfg().location, Some(loc));
    let client_location = Location {
        latitude,
        longitude,
    };
    assert_eq!(agg.brightsky().location(), Some(client_location));
    assert_eq!(agg.openmeteo().location(), Some(client_location));
}

#[tokio::test]
async fn refresh_radar_caches_payloads() {
    let (_fake, agg) = standard_aggregator(CfgOpts::default());

    agg.refresh_radar().await;

    let (current, age_c) = agg
        .store()
        .get_cache(Source::Current, testkit::now())
        .unwrap()
        .expect("current was cached");
    let (radar, age_r) = agg
        .store()
        .get_cache(Source::Radar, testkit::now())
        .unwrap()
        .expect("radar was cached");
    assert_eq!(current["weather"]["temperature"].as_f64(), Some(5.0));
    assert_eq!(radar["bbox"], json!([0, 0, 9, 9]));
    assert!(age_c >= 0.0 && age_r >= 0.0);
}

#[tokio::test]
async fn refresh_radar_tolerates_one_failing_source() {
    let (_fake, agg) = standard_aggregator_with_errors(CfgOpts::default(), [Source::Current]);

    agg.refresh_radar().await; // must not raise
    assert!(
        agg.store()
            .get_cache(Source::Current, testkit::now())
            .unwrap()
            .is_none()
    );
    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_some()
    );

    let status = agg.source_status().unwrap();
    assert_eq!(status["current"]["available"], json!(false));
    assert!(
        status["current"]["last_error"].is_string(),
        "the failure is recorded"
    );
    assert_eq!(status["radar"]["available"], json!(true));
    assert!(status["radar"]["last_error"].is_null());
    assert_eq!(status["radar"]["stale"], json!(false));
}

#[tokio::test]
async fn refresh_models_tolerates_ensemble_failure() {
    let (_fake, agg) = standard_aggregator_with_errors(CfgOpts::default(), [Source::Ensemble]);

    agg.refresh_models().await; // must not raise
    assert!(
        agg.store()
            .get_cache(Source::Forecast, testkit::now())
            .unwrap()
            .is_some()
    );
    assert!(
        agg.store()
            .get_cache(Source::Ensemble, testkit::now())
            .unwrap()
            .is_none()
    );

    let status = agg.source_status().unwrap();
    assert!(
        status["ensemble"]["last_error"].is_string(),
        "the failure is recorded"
    );
}

#[tokio::test]
async fn refresh_models_writes_forecast_history() {
    let (_fake, agg) = standard_aggregator(CfgOpts::default());

    agg.refresh_models().await;

    let conn = agg.store().lock_for_tests();
    let rows: Vec<(String, String, String)> = {
        let mut stmt = conn
            .prepare("SELECT model, valid_from, valid_to FROM forecast_history")
            .unwrap();
        stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
    };
    // icon_d2 + icon_eu: 24 *future* hours each (gfs has null data -> 0
    // rows); the hour ending at NOW (11:00-12:00, stamp 12:00) is past
    // and not stored
    assert_eq!(rows.len(), 48);
    let models: std::collections::HashSet<&str> = rows.iter().map(|r| r.0.as_str()).collect();
    assert_eq!(models, ["icon_d2", "icon_eu"].into_iter().collect());
    for (model, valid_from, valid_to) in &rows {
        // each row covers one hour that has not started yet at issued_at
        assert!(
            valid_from.as_str() >= "2025-01-01T12:00:00Z",
            "{model} {valid_from}"
        );
        assert!(
            valid_to.as_str() > valid_from.as_str(),
            "{model} {valid_from} {valid_to}"
        );
    }
}

#[tokio::test]
async fn source_status_marks_stale() {
    let opts = CfgOpts {
        stale_radar: 0,
        stale_models: 0,
        ..CfgOpts::default()
    };
    let (_fake, agg) = standard_aggregator(opts);

    agg.refresh_radar().await;
    // one second later: age 1 > threshold 0 -> stale
    agg.set_clock(Clock::fixed(testkit::now() + TimeDelta::seconds(1)));

    let status = agg.source_status().unwrap();
    assert_eq!(status["radar"]["stale"], json!(true));
    assert!(status["radar"]["age_seconds"].is_i64());
}

#[tokio::test]
async fn source_status_stale_boundary_is_exclusive() {
    let opts = CfgOpts {
        stale_radar: 1,
        ..CfgOpts::default()
    };
    let (_fake, agg) = standard_aggregator(opts);

    agg.refresh_radar().await;
    // exactly at the threshold (age 60 s == 1 min) the cache is fresh
    agg.set_clock(Clock::fixed(testkit::now() + TimeDelta::seconds(60)));
    let status = agg.source_status().unwrap();
    assert_eq!(status["radar"]["stale"], json!(false));
    // one second beyond the threshold it is stale
    agg.set_clock(Clock::fixed(testkit::now() + TimeDelta::seconds(61)));
    let status = agg.source_status().unwrap();
    assert_eq!(status["radar"]["stale"], json!(true));
}

#[tokio::test]
async fn aggregator_without_location_makes_no_fetch_calls() {
    let opts = CfgOpts {
        location: None,
        ..CfgOpts::default()
    };
    let (fake, agg) = standard_aggregator(opts);

    agg.refresh_radar().await;
    agg.refresh_models().await;

    assert_eq!(fake.requests(), []);
    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_none()
    );
    assert!(
        agg.store()
            .get_cache(Source::Current, testkit::now())
            .unwrap()
            .is_none()
    );
    assert!(
        agg.store()
            .get_cache(Source::Forecast, testkit::now())
            .unwrap()
            .is_none()
    );
    assert!(
        agg.store()
            .get_cache(Source::Ensemble, testkit::now())
            .unwrap()
            .is_none()
    );
}

#[tokio::test]
async fn set_location_first_time_stores_without_clearing() {
    let opts = CfgOpts {
        location: None,
        ..CfgOpts::default()
    };
    let store = memory_store();
    // pre-fill the cache (it belongs to the old location — or to nothing)
    store
        .put_cache(Source::Radar, &standard_radar_payload(), testkit::now())
        .unwrap();
    let (_fake, agg) = standard_aggregator_with_store(opts, store);

    agg.set_location(location(52.0, 13.0)).unwrap();

    // nothing was cleared: the first location has no old data to throw away
    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_some()
    );
    location_everywhere(&agg, 52.0, 13.0);
    // the skip flag is reset: the next refresh fetches again
    agg.refresh_radar().await;
    assert!(
        agg.store()
            .get_cache(Source::Current, testkit::now())
            .unwrap()
            .is_some()
    );
}

#[tokio::test]
async fn set_location_near_same_is_not_a_move() {
    let (_fake, agg) = standard_aggregator(CfgOpts::default());
    agg.store()
        .put_cache(Source::Radar, &standard_radar_payload(), testkit::now())
        .unwrap();

    agg.set_location(location(52.005, 13.005)).unwrap(); // ~550 m away

    // kept: within the 1 km epsilon
    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_some()
    );
    assert_eq!(agg.cfg().location, Some(location(52.005, 13.005)));
}

#[tokio::test]
async fn set_location_moved_clears_location_data() {
    let (_fake, agg) = standard_aggregator(CfgOpts::default());
    agg.store()
        .put_cache(Source::Radar, &standard_radar_payload(), testkit::now())
        .unwrap();
    agg.store()
        .put_cache(Source::Forecast, &forecast_payload(), testkit::now())
        .unwrap();

    agg.set_location(location(52.52, 13.405)).unwrap(); // Berlin: far away

    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_none()
    );
    assert!(
        agg.store()
            .get_cache(Source::Forecast, testkit::now())
            .unwrap()
            .is_none()
    );
    location_everywhere(&agg, 52.52, 13.405);
}
