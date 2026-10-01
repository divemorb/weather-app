use chrono::TimeDelta;
use serde_json::json;

use super::testkit::{self, *};
use super::*;
use crate::clients::Location;
use crate::config::LocationConfig;
use crate::location::{self, location_from_json};
use crate::times::Clock;

fn loc(latitude: f64, longitude: f64) -> LocationConfig {
    LocationConfig {
        latitude,
        longitude,
        timezone: "Europe/Berlin".to_string(),
        label: String::new(),
    }
}

// ---------------------------------------------------------------------------
// refresh + cache
// ---------------------------------------------------------------------------

#[tokio::test]
async fn refresh_radar_caches_payloads() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

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
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    let errors = [Source::Current];
    serve(&fake, &payloads, &errors);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

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
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    let errors = [Source::Ensemble];
    serve(&fake, &payloads, &errors);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

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
async fn source_status_marks_stale() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let opts = CfgOpts {
        stale_radar: 0,
        stale_models: 0,
        ..CfgOpts::default()
    };
    let agg = make_aggregator(make_cfg(&fake, opts), memory_store());

    agg.refresh_radar().await;
    // one second later: age 1 > threshold 0 -> stale
    agg.set_clock(Clock::fixed(testkit::now() + TimeDelta::seconds(1)));

    let status = agg.source_status().unwrap();
    assert_eq!(status["radar"]["stale"], json!(true));
    assert!(status["radar"]["age_seconds"].is_i64());
}

// ---------------------------------------------------------------------------
// unconfigured -> no fetch calls (step 8b)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn aggregator_without_location_makes_no_fetch_calls() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let opts = CfgOpts {
        location: None,
        ..CfgOpts::default()
    };
    let agg = make_aggregator(make_cfg(&fake, opts), memory_store());

    agg.refresh_radar().await;
    agg.refresh_models().await;

    assert!(fake.requests().is_empty());
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

// ---------------------------------------------------------------------------
// set_location (step 8b)
// ---------------------------------------------------------------------------

#[tokio::test]
async fn set_location_first_time_stores_without_clearing() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let opts = CfgOpts {
        location: None,
        ..CfgOpts::default()
    };
    let store = memory_store();
    // pre-fill the cache (it belongs to the old location — or to nothing)
    store
        .put_cache(
            Source::Radar,
            payloads.radar.as_ref().unwrap(),
            testkit::now(),
        )
        .unwrap();
    let agg = make_aggregator(make_cfg(&fake, opts), store);

    agg.set_location(loc(52.0, 13.0)).unwrap();

    // nothing was cleared: the first location has no old data to throw away
    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_some()
    );
    assert_eq!(
        location_from_json(
            agg.store()
                .get_meta(location::LOCATION_KEY)
                .unwrap()
                .as_deref()
        ),
        Some(loc(52.0, 13.0))
    );
    assert_eq!(agg.cfg().location, Some(loc(52.0, 13.0)));
    assert_eq!(
        agg.brightsky().location(),
        Some(Location {
            latitude: 52.0,
            longitude: 13.0
        })
    );
    assert_eq!(
        agg.openmeteo().location(),
        Some(Location {
            latitude: 52.0,
            longitude: 13.0
        })
    );
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
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());
    agg.store()
        .put_cache(
            Source::Radar,
            payloads.radar.as_ref().unwrap(),
            testkit::now(),
        )
        .unwrap();

    agg.set_location(loc(52.005, 13.005)).unwrap(); // ~550 m away

    // kept: within the 1 km epsilon
    assert!(
        agg.store()
            .get_cache(Source::Radar, testkit::now())
            .unwrap()
            .is_some()
    );
    assert_eq!(agg.cfg().location, Some(loc(52.005, 13.005)));
}

#[tokio::test]
async fn set_location_moved_clears_location_data() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());
    agg.store()
        .put_cache(
            Source::Radar,
            payloads.radar.as_ref().unwrap(),
            testkit::now(),
        )
        .unwrap();
    agg.store()
        .put_cache(
            Source::Forecast,
            payloads.forecast.as_ref().unwrap(),
            testkit::now(),
        )
        .unwrap();

    agg.set_location(loc(52.52, 13.405)).unwrap(); // Berlin: far away

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
    assert_eq!(
        location_from_json(
            agg.store()
                .get_meta(location::LOCATION_KEY)
                .unwrap()
                .as_deref()
        ),
        Some(loc(52.52, 13.405))
    );
    assert_eq!(agg.cfg().location, Some(loc(52.52, 13.405)));
    assert_eq!(
        agg.brightsky().location(),
        Some(Location {
            latitude: 52.52,
            longitude: 13.405
        })
    );
    assert_eq!(
        agg.openmeteo().location(),
        Some(Location {
            latitude: 52.52,
            longitude: 13.405
        })
    );
}
