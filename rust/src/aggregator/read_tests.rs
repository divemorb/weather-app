//! Read-model tests. The frozen clock is the test kit's fixed `NOW`.

use std::collections::{BTreeMap, BTreeSet};

use serde_json::json;

use super::testkit::{self, *};
use super::*;
use crate::series::HistoryRow;

/// `pytest.approx(expected)` with the default tolerances.
fn approx(actual: f64, expected: f64) -> bool {
    let tol = if expected == 0.0 {
        1e-12
    } else {
        1e-6 * expected.abs()
    };
    (actual - expected).abs() <= tol
}

fn row(
    model: &str,
    issued_at: &str,
    valid_from: &str,
    valid_to: &str,
    precip_mm: f64,
) -> HistoryRow {
    HistoryRow {
        model: model.to_string(),
        issued_at: issued_at.to_string(),
        valid_from: valid_from.to_string(),
        valid_to: valid_to.to_string(),
        precip_mm,
    }
}

/// Only the Open-Meteo sources are served (no Bright Sky data).
fn openmeteo_only_payloads() -> Payloads {
    let mut payloads = make_payloads();
    payloads.current = None;
    payloads.radar = None;
    payloads
}

#[tokio::test]
async fn get_current_conditions_with_feels_like() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_radar().await;
    agg.refresh_models().await;

    let cond = agg
        .get_current_conditions()
        .unwrap()
        .expect("the cached conditions parse");
    assert_eq!(cond.temperature_c, Some(5.0));
    assert_eq!(cond.condition, json!("Rain"));
    // from icon_d2 apparent_temperature
    assert_eq!(cond.feels_like_c, Some(3.5));
}

#[test]
fn get_current_conditions_empty_cache() {
    let fake = FakeUpstream::start();
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());
    assert!(agg.get_current_conditions().unwrap().is_none());
}

#[tokio::test]
async fn get_model_votes() {
    let fake = FakeUpstream::start();
    let payloads = openmeteo_only_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_models().await;

    let votes = agg.get_model_votes().unwrap();
    let by_name: BTreeMap<&str, Option<f64>> = votes
        .iter()
        .map(|v| (v.name.as_str(), v.precip_next_hour_mm))
        .collect();
    assert_eq!(by_name.len(), 2);
    let icon_d2 = by_name.get("icon_d2").copied().expect("icon_d2 voted");
    let icon_eu = by_name.get("icon_eu").copied().expect("icon_eu voted");
    assert!(approx(icon_d2.expect("icon_d2 has data"), 0.4));
    assert!(approx(icon_eu.expect("icon_eu has data"), 0.0));
}

#[tokio::test]
async fn get_ensemble_vote() {
    let fake = FakeUpstream::start();
    let payloads = openmeteo_only_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_models().await;

    let vote = agg.get_ensemble_vote().unwrap();
    assert!(approx(
        vote.probability_pct.expect("the ensemble votes"),
        50.0
    ));
    assert_eq!((vote.n_members, vote.n_rain_members), (2, 1));
}

#[tokio::test]
async fn get_24h_model_comparison() {
    let fake = FakeUpstream::start();
    let payloads = openmeteo_only_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_models().await;

    let series = agg.get_24h_model_comparison().unwrap();
    // the axis is relative to now: first hour = current hour (12:00),
    // 24 entries; the model with null data (gfs) is skipped
    assert_eq!(series.hours.len(), 24);
    assert_eq!(series.hours[0], "2025-01-01T12:00:00Z");
    assert_eq!(series.hours[1], "2025-01-01T13:00:00Z");
    assert_eq!(series.n_models, 2);
    let names: BTreeSet<&str> = series.models.iter().map(|m| m.name.as_str()).collect();
    assert_eq!(names, BTreeSet::from(["icon_d2", "icon_eu"]));
    let icon_d2 = series
        .models
        .iter()
        .find(|m| m.name == "icon_d2")
        .expect("icon_d2 is in the series");
    // the value at hour 12:00 comes from the stamp at 13:00 (rain of
    // 12:00-13:00) -> the 0.4 mm is in the first bucket
    assert!(approx(
        icon_d2.precipitation_mm[0].expect("hour 0 has data"),
        0.4
    ));
    assert!(approx(
        icon_d2.precipitation_mm[1].expect("hour 1 has data"),
        0.0
    ));
}

#[test]
fn get_model_accuracy_scores_window_only() {
    let fake = FakeUpstream::start();
    let store = memory_store();
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), store);
    agg.store()
        .add_forecasts(&[
            // inside the 30-day window: hit (0.4 vs 0.3) + false alarm (0.2 vs 0.0)
            row(
                "icon_d2",
                "2024-12-20T10:00:00Z",
                "2024-12-20T11:00:00Z",
                "2024-12-20T12:00:00Z",
                0.4,
            ),
            row(
                "icon_d2",
                "2024-12-20T12:00:00Z",
                "2024-12-20T13:00:00Z",
                "2024-12-20T14:00:00Z",
                0.2,
            ),
            // outside the window: must NOT be scored
            row(
                "icon_eu",
                "2024-11-01T10:00:00Z",
                "2024-11-01T11:00:00Z",
                "2024-11-01T12:00:00Z",
                9.0,
            ),
            // no observation yet (15:00 is never observed): must NOT be scored
            row(
                "icon_eu",
                "2024-12-20T14:00:00Z",
                "2024-12-20T15:00:00Z",
                "2024-12-20T16:00:00Z",
                1.0,
            ),
        ])
        .unwrap();
    agg.store()
        .set_observation("2024-12-20T11:00:00Z", 0.3)
        .unwrap();
    agg.store()
        .set_observation("2024-12-20T13:00:00Z", 0.0)
        .unwrap();
    agg.store()
        .set_observation("2024-11-01T11:00:00Z", 8.0)
        .unwrap();

    let accuracy = agg.get_model_accuracy().unwrap();
    let keys: BTreeSet<&str> = accuracy.keys().map(String::as_str).collect();
    assert_eq!(keys, BTreeSet::from(["icon_d2"])); // icon_eu has no in-window comparison
    let d2 = accuracy.get("icon_d2").expect("icon_d2 is scored");
    assert_eq!(d2.n_samples, 2);
    // > 0.1 mm event: (0.4 vs 0.3) = hit, (0.2 vs 0.0) = false alarm
    assert_eq!(
        (d2.hits, d2.false_alarms, d2.misses, d2.correct_negatives),
        (1, 1, 0, 0)
    );
    assert!(approx(d2.event_accuracy.expect("icon_d2 has samples"), 0.5));
    assert!(approx(d2.mae_mm.expect("icon_d2 has samples"), 0.15)); // (0.1 + 0.2) / 2
}

#[test]
fn get_model_accuracy_empty_history() {
    let fake = FakeUpstream::start();
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());
    assert!(agg.get_model_accuracy().unwrap().is_empty());
}

#[tokio::test]
async fn get_radar_nowcast_parses_frames() {
    let fake = FakeUpstream::start();
    let mut payloads = make_payloads();
    payloads.forecast = None;
    payloads.ensemble = None;
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_radar().await;

    let nowcast = agg
        .get_radar_nowcast()
        .unwrap()
        .expect("the cached radar parses");
    assert!(nowcast.covered);
    assert_eq!(nowcast.frames.len(), 1);
    assert!(approx(nowcast.frames[0].max_mm, 0.2));
}

#[tokio::test]
async fn get_radar_next_hour_builds_bar() {
    // rain (0.3 mm) only in the +5 min frame, at the location
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        current: Some(current_payload()),
        radar: Some(radar_payload(&[
            ("2025-01-01T12:00:00Z", &[]),
            ("2025-01-01T12:05:00Z", &[(5, 5, 30)]),
        ])),
        forecast: None,
        ensemble: None,
        weather: None,
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_radar().await;

    let bar = agg.get_radar_next_hour().unwrap();
    assert!(bar.available);
    assert_eq!(bar.steps.len(), 12);
    assert!(approx(bar.steps[0].precip_mm, 0.0));
    assert!(approx(bar.steps[1].precip_mm, 0.3));
    assert_eq!(bar.steps[1].start_utc, "2025-01-01T12:05:00Z");
}

#[test]
fn get_radar_next_hour_empty_cache() {
    let fake = FakeUpstream::start();
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    let bar = agg.get_radar_next_hour().unwrap();
    assert!(!bar.available);
    assert_eq!(bar.steps.len(), 12);
    assert!(bar.steps.iter().all(|s| approx(s.precip_mm, 0.0)));
}

#[test]
fn get_current_conditions_malformed_cache_returns_none() {
    // a corrupted/malformed cached payload must degrade to "no data"
    // (None), not error — the request path must never 500 on bad data
    let fake = FakeUpstream::start();
    let mut bad = current_payload();
    bad["weather"]["temperature"] = json!("not-a-number");
    let store = memory_store();
    store
        .put_cache(Source::Current, &bad, testkit::now())
        .unwrap();
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), store);

    assert!(agg.get_current_conditions().unwrap().is_none());
}
