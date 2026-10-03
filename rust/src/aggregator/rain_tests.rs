//! Tests for `get_rain_probability`; the frozen clock is the test kit's
//! fixed `NOW`.

use super::testkit::*;
use crate::models::RainProbability;
use crate::pyfmt::py_sum;
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

/// The weight of one signal in `weights_used`.
fn weight(prob: &RainProbability, name: &str) -> f64 {
    prob.weights_used
        .iter()
        .find(|(k, _)| k == name)
        .map_or(0.0, |(_, w)| *w)
}

/// n compared forecast rows for one model, all inside the 30-day window.
/// Rows start at `start_hour` so different models can occupy different
/// hours (`set_observation` matches on `valid_from` only, so shared hours
/// would pick up each other's observations).
fn accuracy_rows(model: &str, n: usize, start_hour: usize) -> Vec<HistoryRow> {
    (0..n)
        .map(|i| HistoryRow {
            model: model.to_string(),
            issued_at: "2024-12-20T00:00:00Z".to_string(),
            valid_from: format!("2024-12-20T{:02}:00:00Z", start_hour + i),
            valid_to: format!("2024-12-20T{:02}:00:00Z", start_hour + i + 1),
            precip_mm: 0.4,
        })
        .collect()
}

/// Only the Open-Meteo sources are served (no Bright Sky data).
fn openmeteo_only_payloads() -> Payloads {
    let mut payloads = make_payloads();
    payloads.current = None;
    payloads.radar = None;
    payloads
}

#[tokio::test]
async fn get_rain_probability_all_signals() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_radar().await;
    agg.refresh_models().await;

    let prob = agg.get_rain_probability().unwrap();
    // radar 100, models 50, ensemble 50 -> 0.5*100 + 0.3*50 + 0.2*50 = 75
    assert!(approx(prob.probability_pct, 75.0));
    assert!(prob.radar_available);
    assert_eq!(prob.radar_raining, Some(true));
    assert_eq!((prob.models_rain_count, prob.models_total), (1, 2));
    assert!(approx(prob.ensemble_pct.expect("the ensemble voted"), 50.0));
    let weights_sum = py_sum(prob.weights_used.iter().map(|(_, w)| *w));
    assert!((weights_sum - 1.0).abs() < 1e-9);
    assert!(prob.explanation.contains("1 of 2 models"));
}

#[tokio::test]
async fn get_rain_probability_without_radar() {
    let fake = FakeUpstream::start();
    let payloads = openmeteo_only_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_models().await;

    let prob = agg.get_rain_probability().unwrap();
    // models 50, ensemble 50 -> renormalized 0.6/0.4 -> 50
    assert!(approx(prob.probability_pct, 50.0));
    assert!(!prob.radar_available);
    assert_eq!(prob.radar_raining, None);
    assert!((weight(&prob, "models") - 0.6).abs() < 1e-9);
    assert!((weight(&prob, "ensemble") - 0.4).abs() < 1e-9);
    assert!(prob.explanation.contains("Radar: not available"));
}

#[tokio::test]
async fn get_rain_probability_radar_dry() {
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        radar: Some(radar_payload(&[("2025-01-01T12:00:00Z", &[])])),
        ..make_payloads()
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.refresh_radar().await;
    agg.refresh_models().await;

    let prob = agg.get_rain_probability().unwrap();
    // 0.5*0 + 0.3*50 + 0.2*50 = 25
    assert!(prob.radar_available);
    assert_eq!(prob.radar_raining, Some(false));
    assert!(approx(prob.probability_pct, 25.0));
}

#[test]
fn get_rain_probability_no_data_at_all() {
    let fake = FakeUpstream::start();
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    let prob = agg.get_rain_probability().unwrap();
    assert_eq!(prob.probability_pct, 0.0);
    assert!(prob.weights_used.is_empty());
    assert!(prob.explanation.contains("No data"));
}

#[tokio::test]
async fn get_rain_probability_accuracy_weights_applied() {
    // icon_d2 (rains, vote 0.4 mm): 1 hit + 1 false alarm -> event_accuracy
    // 0.5. icon_eu (dry): 2 false alarms -> event_accuracy 0.0, weight
    // floored at 0.1. Both have >= min_samples=2, so the gate passes and the
    // model signal is weighted: 100 * 0.5 / (0.5 + 0.1) = 83.33 (plain: 50).
    // radar 100, ensemble 50 -> 0.5*100 + 0.3*83.33 + 0.2*50 = 85
    let store = memory_store();
    store
        .add_forecasts(&accuracy_rows("icon_d2", 2, 11))
        .unwrap();
    store
        .add_forecasts(&accuracy_rows("icon_eu", 2, 13))
        .unwrap();
    store.set_observation("2024-12-20T11:00:00Z", 0.3).unwrap(); // icon_d2: hit
    store.set_observation("2024-12-20T12:00:00Z", 0.0).unwrap(); // icon_d2: false alarm
    store.set_observation("2024-12-20T13:00:00Z", 0.0).unwrap(); // icon_eu: false alarm
    store.set_observation("2024-12-20T14:00:00Z", 0.0).unwrap(); // icon_eu: false alarm

    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let opts = CfgOpts {
        use_accuracy_weights: true,
        min_samples: 2,
        ..CfgOpts::default()
    };
    let agg = make_aggregator(make_cfg(&fake, opts), store);

    agg.refresh_radar().await;
    agg.refresh_models().await;

    let prob = agg.get_rain_probability().unwrap();
    assert!(approx(prob.probability_pct, 85.0));
    assert!(prob.explanation.contains("accuracy-weighted"));
    // the equal-weight counts still feed the explanation
    assert!(prob.explanation.contains("1 of 2 models"));
}

#[tokio::test]
async fn get_rain_probability_accuracy_gate_falls_back() {
    // only icon_d2 has compared hours (1 < min_samples=2) -> gate fails,
    // the plain equal-weight model signal (50) is used, no "accuracy-
    // weighted" in the explanation.
    let store = memory_store();
    store
        .add_forecasts(&accuracy_rows("icon_d2", 1, 11))
        .unwrap();
    store.set_observation("2024-12-20T11:00:00Z", 0.3).unwrap();

    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let opts = CfgOpts {
        use_accuracy_weights: true,
        min_samples: 2,
        ..CfgOpts::default()
    };
    let agg = make_aggregator(make_cfg(&fake, opts), store);

    agg.refresh_radar().await;
    agg.refresh_models().await;

    let prob = agg.get_rain_probability().unwrap();
    // radar 100, models 50, ensemble 50 -> 0.5*100 + 0.3*50 + 0.2*50 = 75
    assert!(approx(prob.probability_pct, 75.0));
    assert!(!prob.explanation.contains("accuracy-weighted"));
}

#[tokio::test]
async fn get_rain_probability_no_weights_when_disabled() {
    // flag off + accuracy data present -> equal weights, no mention
    let store = memory_store();
    store
        .add_forecasts(&accuracy_rows("icon_d2", 2, 11))
        .unwrap();
    store
        .add_forecasts(&accuracy_rows("icon_eu", 2, 13))
        .unwrap();
    store.set_observation("2024-12-20T11:00:00Z", 0.3).unwrap();
    store.set_observation("2024-12-20T12:00:00Z", 0.0).unwrap();
    store.set_observation("2024-12-20T13:00:00Z", 0.0).unwrap();
    store.set_observation("2024-12-20T14:00:00Z", 0.0).unwrap();

    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    // flag explicitly off
    let opts = CfgOpts {
        use_accuracy_weights: false,
        ..CfgOpts::default()
    };
    let agg = make_aggregator(make_cfg(&fake, opts), store);

    agg.refresh_radar().await;
    agg.refresh_models().await;

    let prob = agg.get_rain_probability().unwrap();
    assert!(approx(prob.probability_pct, 75.0));
    assert!(!prob.explanation.contains("accuracy-weighted"));
}

#[tokio::test]
async fn get_rain_probability_accuracy_read_failure_falls_back() {
    // flag on + the accuracy read failing (e.g. database error) must not
    // break the headline number: equal weights are used and the explanation
    // does not claim accuracy weighting
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let opts = CfgOpts {
        use_accuracy_weights: true,
        min_samples: 2,
        ..CfgOpts::default()
    };
    let agg = make_aggregator(make_cfg(&fake, opts), memory_store());

    agg.refresh_radar().await;
    agg.refresh_models().await;
    // make the read fail for real:
    agg.store()
        .lock_for_tests()
        .execute_batch("DROP TABLE forecast_history")
        .unwrap();

    let prob = agg.get_rain_probability().unwrap();
    // radar 100, models 50 (equal weights), ensemble 50 -> 0.5*100 + 0.3*50 + 0.2*50 = 75
    assert!(approx(prob.probability_pct, 75.0));
    assert_eq!(
        prob.weights_used,
        vec![
            ("radar".to_string(), 0.5),
            ("models".to_string(), 0.3),
            ("ensemble".to_string(), 0.2),
        ]
    );
    assert!(!prob.explanation.contains("accuracy-weighted"));
}
