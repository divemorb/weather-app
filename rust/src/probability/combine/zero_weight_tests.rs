//! Zero-weight fallback of [`combine_signals`]: when the configured weights
//! of the available signals sum to <= 0, every available signal gets weight
//! 1.0 (Python `app/probability.py`, `combine_signals`).
//!
//! The expected values were obtained by running the Python function.

use super::*;

/// A `ProbabilityConfig` with the given weights and the thresholds used by
/// the other combine tests.
fn prob_cfg(weight_radar: f64, weight_models: f64, weight_ensemble: f64) -> ProbabilityConfig {
    ProbabilityConfig {
        weight_radar,
        weight_models,
        weight_ensemble,
        model_rain_threshold_mm: 0.1,
        radar_cell_rain_threshold_mm: 0.05,
    }
}

#[test]
fn combine_all_weights_zero_uses_equal_weights() {
    let cfg = prob_cfg(0.0, 0.0, 0.0);
    let (prob, weights) = combine_signals(&cfg, true, Some(true), Some(30.0), Some(0.0));
    // (100 + 30 + 0) / 3
    assert_eq!(prob, 43.33333333333333);
    assert_eq!(
        weights,
        vec![
            ("radar".to_string(), 0.3333333333333333),
            ("models".to_string(), 0.3333333333333333),
            ("ensemble".to_string(), 0.3333333333333333),
        ]
    );
}

#[test]
fn combine_all_weights_zero_single_signal() {
    let cfg = prob_cfg(0.0, 0.0, 0.0);
    let (prob, weights) = combine_signals(&cfg, false, None, Some(30.0), None);
    assert_eq!(prob, 30.0);
    assert_eq!(weights, vec![("models".to_string(), 1.0)]);
}

#[test]
fn combine_negative_weight_sum_uses_equal_weights() {
    let cfg = prob_cfg(0.5, -1.0, 0.2);
    let (prob, weights) = combine_signals(&cfg, true, Some(false), Some(90.0), Some(60.0));
    // (0 + 90 + 60) / 3
    assert_eq!(prob, 50.0);
    assert_eq!(
        weights,
        vec![
            ("radar".to_string(), 0.3333333333333333),
            ("models".to_string(), 0.3333333333333333),
            ("ensemble".to_string(), 0.3333333333333333),
        ]
    );
}

#[test]
fn combine_radar_weight_ignored_without_radar() {
    // Radar unavailable, so its weight does not count: the remaining weights
    // sum to 0 and the fallback applies to models and ensemble.
    let cfg = prob_cfg(0.5, 0.0, 0.0);
    let (prob, weights) = combine_signals(&cfg, false, None, Some(30.0), Some(10.0));
    // (30 + 10) / 2
    assert_eq!(prob, 20.0);
    assert_eq!(
        weights,
        vec![("models".to_string(), 0.5), ("ensemble".to_string(), 0.5),]
    );
}
