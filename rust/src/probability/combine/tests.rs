//! Tests for `combine_signals`, `ensemble_vote`, and the weighted/explanation
//! model signal.

use super::*;
use std::collections::BTreeMap;

use crate::accuracy::ModelAccuracy;
use crate::models::ModelVote;
use crate::probability::{model_rain_signal, weighted_model_signal};
use crate::times::parse_iso;
use chrono::{DateTime, TimeDelta, Utc};

fn now() -> DateTime<Utc> {
    parse_iso("2025-01-01T12:00:00Z").expect("valid stamp")
}

const PROB: ProbabilityConfig = ProbabilityConfig {
    weight_radar: 0.5,
    weight_models: 0.3,
    weight_ensemble: 0.2,
    model_rain_threshold_mm: 0.1,
    radar_cell_rain_threshold_mm: 0.05,
};

/// `pytest.approx(expected)` with the default tolerances.
fn approx(actual: f64, expected: f64) -> bool {
    let tol = if expected == 0.0 {
        1e-12
    } else {
        1e-6 * expected.abs()
    };
    (actual - expected).abs() <= tol
}

/// Four hourly steps stamped 12:00, 13:00, 14:00, 15:00; `members[i]` is
/// the series of member `i` (index 0 = 12:00).
fn ensemble(members: Vec<Vec<Option<f64>>>) -> EnsembleData {
    EnsembleData {
        hourly_time: (0..4).map(|i| now() + TimeDelta::hours(i as i64)).collect(),
        control_precip_mm: Vec::new(),
        member_precip_mm: members,
    }
}

fn vote(name: &str, mm: Option<f64>) -> ModelVote {
    ModelVote {
        name: name.to_string(),
        precip_next_hour_mm: mm,
    }
}

fn accuracy_row(n_samples: i64, event_accuracy: f64, mae_mm: f64) -> ModelAccuracy {
    ModelAccuracy {
        n_samples,
        mae_mm: Some(mae_mm),
        hits: 0,
        misses: 0,
        false_alarms: 0,
        correct_negatives: 0,
        event_accuracy: Some(event_accuracy),
    }
}

#[test]
fn ensemble_vote_share() {
    // now = 11:30 -> the next hour is [11:30, 12:30); the first step stamped
    // after now is idx0 (stamped 12:00, covering 11:00-12:00, the next hour).
    let data = ensemble(vec![
        vec![Some(1.0), Some(0.0), Some(0.0), Some(0.0)], // rain at idx0
        vec![Some(0.0), Some(0.0), Some(0.0), Some(0.0)], // dry at idx0
        vec![Some(0.05), Some(0.0), Some(0.0), Some(0.0)], // below threshold (0.1)
        vec![Some(3.0), Some(0.0), Some(0.0), Some(0.0)], // rain at idx0
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() - TimeDelta::minutes(30));
    assert_eq!(vote.n_members, 4);
    assert_eq!(vote.n_rain_members, 2);
    assert!(approx(vote.probability_pct.unwrap(), 50.0));
}

#[test]
fn ensemble_vote_now_exactly_on_boundary_selects_next_index() {
    // steps are stamped 12:00, 13:00, ...; at now = 12:00 exactly, idx0
    // (stamped 12:00) covers 11:00-12:00 and is the past, so idx1 (stamped
    // 13:00, covering 12:00-13:00) must be selected.
    let data = ensemble(vec![
        vec![Some(0.0), Some(5.0), Some(0.0), Some(0.0)], // dry at idx0 (past), rain at idx1
        vec![Some(0.0), Some(5.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now());
    assert_eq!(vote.n_rain_members, 2);
    assert!(approx(vote.probability_pct.unwrap(), 100.0));
}

#[test]
fn ensemble_vote_uses_current_hour() {
    // now = 12:30 -> the next hour is [12:30, 13:30); the first step stamped
    // after now is idx1 (stamped 13:00, covering 12:00-13:00).
    let now = now() + TimeDelta::minutes(30);
    let data = ensemble(vec![
        vec![Some(0.0), Some(5.0), Some(0.0), Some(0.0)], // dry at idx0, rain at idx1
        vec![Some(0.0), Some(0.0), Some(0.0), Some(0.0)], // dry at idx1
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now);
    assert_eq!(vote.n_rain_members, 1);
    assert!(approx(vote.probability_pct.unwrap(), 50.0));
}

#[test]
fn ensemble_vote_stale_is_none() {
    // now beyond the series (all hours in the past)
    let now = now() + TimeDelta::hours(5);
    let data = ensemble(vec![
        vec![Some(1.0), Some(0.0), Some(0.0), Some(0.0)],
        vec![Some(1.0), Some(0.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now);
    assert_eq!(vote.probability_pct, None);
}

#[test]
fn ensemble_vote_none_inputs() {
    assert_eq!(ensemble_vote(None, 0.1, now()).probability_pct, None);
    let empty = EnsembleData::default();
    assert_eq!(
        ensemble_vote(Some(&empty), 0.1, now()).probability_pct,
        None
    );
}

#[test]
fn ensemble_vote_skips_null_members() {
    // now = 11:30 -> idx0 (stamped 12:00) is the next hour
    let data = ensemble(vec![
        vec![Some(1.0), Some(0.0), Some(0.0), Some(0.0)],
        vec![None, Some(0.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() - TimeDelta::minutes(30));
    // only member 0 is usable; it rains -> 100%
    assert_eq!(vote.n_rain_members, 1);
    assert!(approx(vote.probability_pct.unwrap(), 100.0));
}

// Best-overlap hour selection: the picked stamp is the first one with
// t >= now + 30 min. Stamps here are 12:00, 13:00, 14:00, 15:00. Each test
// puts rain in exactly one index, so the result proves which index was
// picked (50% = picked, 0% = a different index was picked).
#[test]
fn ensemble_vote_best_overlap_now_11h00_picks_12h00() {
    // now = 11:00 -> 12:00 covers 11:00-12:00 entirely (60 min overlap)
    let data = ensemble(vec![
        vec![Some(5.0), Some(0.0), Some(0.0), Some(0.0)],
        vec![Some(0.0), Some(0.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() - TimeDelta::hours(1));
    assert_eq!(vote.n_rain_members, 1);
    assert!(approx(vote.probability_pct.unwrap(), 50.0));
}

#[test]
fn ensemble_vote_best_overlap_now_11h20_picks_12h00() {
    // now = 11:20 -> 12:00 covers 11:00-12:00 (40 min overlap with the next
    // 60 min, more than 13:00's 20)
    let data = ensemble(vec![
        vec![Some(5.0), Some(0.0), Some(0.0), Some(0.0)],
        vec![Some(0.0), Some(0.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() - TimeDelta::minutes(40));
    assert_eq!(vote.n_rain_members, 1);
    assert!(approx(vote.probability_pct.unwrap(), 50.0));
}

#[test]
fn ensemble_vote_best_overlap_now_11h30_tie_prefers_earlier_stamp() {
    // now = 11:30 -> 12:00 and 13:00 each overlap by exactly 30 min; the
    // earlier stamp (12:00) wins.
    let data = ensemble(vec![
        vec![Some(5.0), Some(0.0), Some(0.0), Some(0.0)],
        vec![Some(0.0), Some(0.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() - TimeDelta::minutes(30));
    assert_eq!(vote.n_rain_members, 1);
    assert!(approx(vote.probability_pct.unwrap(), 50.0));
}

#[test]
fn ensemble_vote_best_overlap_now_11h50_picks_13h00() {
    // now = 11:50 -> 13:00 covers 12:00-13:00 (50 min overlap with the next
    // 60 min, more than 12:00's 10).
    let data = ensemble(vec![
        vec![Some(0.0), Some(5.0), Some(0.0), Some(0.0)],
        vec![Some(0.0), Some(0.0), Some(0.0), Some(0.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() - TimeDelta::minutes(10));
    assert_eq!(vote.n_rain_members, 1);
    assert!(approx(vote.probability_pct.unwrap(), 50.0));
}

#[test]
fn ensemble_vote_best_overlap_stale_under_30_min_is_none() {
    // now = 14:45 -> the last stamp (15:00) is only 15 min ahead, less than
    // 30 min: the series is stale, no hour qualifies -> None.
    let data = ensemble(vec![
        vec![Some(0.0), Some(0.0), Some(0.0), Some(5.0)],
        vec![Some(0.0), Some(0.0), Some(0.0), Some(5.0)],
    ]);
    let vote = ensemble_vote(Some(&data), 0.1, now() + TimeDelta::minutes(165));
    assert_eq!(vote.probability_pct, None);
}

#[test]
fn weighted_signal_equal_accuracy_matches_plain_signal() {
    // all accuracies 1.0 (>= min_samples) -> equal weights -> same as
    // model_rain_signal: 1 of 3 voting models has rain -> 100/3 %
    let votes = vec![
        vote("a", Some(0.5)), // rain
        vote("b", Some(0.0)), // dry
        vote("c", Some(2.0)), // rain
    ];
    let mut accuracy = BTreeMap::new();
    for n in ["a", "b", "c"] {
        accuracy.insert(n.to_string(), accuracy_row(100, 1.0, 0.0));
    }
    let (signal, n_rain, n_total, weighted) = weighted_model_signal(&votes, &accuracy, 0.1, 48);
    let (plain, plain_rain, plain_total) = model_rain_signal(&votes, 0.1);
    assert!(weighted);
    assert!(approx(signal.unwrap(), plain.unwrap()));
    assert_eq!((n_rain, n_total), (plain_rain, plain_total));
    assert_eq!((plain_rain, plain_total), (2, 3));
    assert!(approx(signal.unwrap(), 200.0 / 3.0));
}

#[test]
fn weighted_signal_gate_falls_back_below_min_samples() {
    // one model has too few samples (and one has no accuracy row at all)
    // -> weighted_applied is False and the plain equal-weight signal is
    // returned (1 of 2 -> 50 %)
    let votes = vec![vote("a", Some(0.5)), vote("b", Some(0.0))];
    let mut accuracy = BTreeMap::new();
    accuracy.insert("a".to_string(), accuracy_row(47, 1.0, 0.0));
    let (signal, n_rain, n_total, weighted) = weighted_model_signal(&votes, &accuracy, 0.1, 48);
    assert!(!weighted);
    assert_eq!((n_rain, n_total), (1, 2));
    assert!(approx(signal.unwrap(), 50.0));
    assert!(approx(
        signal.unwrap(),
        model_rain_signal(&votes, 0.1).0.unwrap()
    ));
}

#[test]
fn weighted_signal_more_accurate_model_pulls_share() {
    // a: rain, accuracy 0.9 -> weight 0.9
    // b: dry,  accuracy 0.3 -> weight 0.3
    // weighted: 100 * 0.9 / (0.9 + 0.3) = 75  (plain would be 50)
    let votes = vec![vote("a", Some(0.5)), vote("b", Some(0.0))];
    let mut accuracy = BTreeMap::new();
    accuracy.insert("a".to_string(), accuracy_row(100, 0.9, 0.1));
    accuracy.insert("b".to_string(), accuracy_row(100, 0.3, 0.4));
    let (signal, n_rain, n_total, weighted) = weighted_model_signal(&votes, &accuracy, 0.1, 48);
    assert!(weighted);
    assert_eq!((n_rain, n_total), (1, 2));
    assert!(approx(signal.unwrap(), 75.0));
    assert!(signal.unwrap() > model_rain_signal(&votes, 0.1).0.unwrap());
}

#[test]
fn weighted_signal_zero_accuracy_uses_0p1_floor() {
    // a: rain with event_accuracy 0.0 -> weight floored at 0.1
    // b: dry,  accuracy 0.9 -> weight 0.9
    // weighted: 100 * 0.1 / (0.1 + 0.9) = 10  (a is down-weighted, not muted)
    let votes = vec![vote("a", Some(0.5)), vote("b", Some(0.0))];
    let mut accuracy = BTreeMap::new();
    accuracy.insert("a".to_string(), accuracy_row(100, 0.0, 0.5));
    accuracy.insert("b".to_string(), accuracy_row(100, 0.9, 0.1));
    let (signal, _n_rain, _n_total, weighted) = weighted_model_signal(&votes, &accuracy, 0.1, 48);
    assert!(weighted);
    assert!(approx(signal.unwrap(), 10.0));
}

#[test]
fn weighted_signal_skips_models_without_data() {
    // c has no data -> does not vote and does not trip the gate either
    let votes = vec![vote("a", Some(0.5)), vote("b", Some(0.0)), vote("c", None)];
    let mut accuracy = BTreeMap::new();
    accuracy.insert("a".to_string(), accuracy_row(100, 0.9, 0.1));
    accuracy.insert("b".to_string(), accuracy_row(100, 0.3, 0.4));
    let (signal, n_rain, n_total, weighted) = weighted_model_signal(&votes, &accuracy, 0.1, 48);
    assert!(weighted);
    assert_eq!((n_rain, n_total), (1, 2));
    assert!(approx(signal.unwrap(), 75.0));
}

#[test]
fn weighted_signal_no_voting_models() {
    let (signal, n_rain, n_total, weighted) =
        weighted_model_signal(&[vote("a", None)], &BTreeMap::new(), 0.1, 48);
    assert_eq!(signal, None);
    assert_eq!((n_rain, n_total, weighted), (0, 0, false));
}

#[test]
fn explanation_accuracy_weighted_flag() {
    let plain = build_explanation(true, Some(true), 3, 6, Some(42.0), 0.1, false);
    assert!(!plain.contains("accuracy-weighted"));
    let weighted = build_explanation(true, Some(true), 3, 6, Some(42.0), 0.1, true);
    assert!(
        weighted.contains("3 of 6 models predict > 0.1 mm in the next hour, accuracy-weighted")
    );
}

#[test]
fn combine_all_signals_weighted() {
    let (prob, weights) = combine_signals(&PROB, true, Some(true), Some(50.0), Some(25.0));
    // 0.5*100 + 0.3*50 + 0.2*25 = 50 + 15 + 5 = 70
    assert!(approx(prob, 70.0));
    let total = py_sum(weights.iter().map(|(_, w)| *w));
    assert!((total - 1.0).abs() < 1e-9);
}

#[test]
fn combine_radar_dry_lowers_probability() {
    let (prob, _) = combine_signals(&PROB, true, Some(false), Some(100.0), Some(100.0));
    // 0.5*0 + 0.3*100 + 0.2*100 = 50
    assert!(approx(prob, 50.0));
}

#[test]
fn combine_without_radar_renormalizes() {
    let (prob, weights) = combine_signals(&PROB, false, None, Some(100.0), Some(0.0));
    // models:ensemble = 0.3:0.2 -> 0.6:0.4 ; 0.6*100 + 0.4*0 = 60
    assert!(approx(prob, 60.0));
    let weight =
        |name: &str| -> Option<f64> { weights.iter().find(|(k, _)| k == name).map(|(_, w)| *w) };
    assert!(approx(weight("models").unwrap(), 0.6));
    assert!(approx(weight("ensemble").unwrap(), 0.4));
    assert_eq!(weight("radar"), None);
}

#[test]
fn combine_models_only() {
    let (prob, weights) = combine_signals(&PROB, false, None, Some(30.0), None);
    assert!(approx(prob, 30.0));
    assert_eq!(weights, vec![("models".to_string(), 1.0)]);
}

#[test]
fn combine_no_signals_is_zero() {
    let (prob, weights) = combine_signals(&PROB, false, None, None, None);
    assert_eq!(prob, 0.0);
    assert!(weights.is_empty());
}

#[test]
fn combine_clamps_to_100() {
    let (prob, _) = combine_signals(&PROB, true, Some(true), Some(100.0), Some(100.0));
    assert_eq!(prob, 100.0);
}

#[test]
fn explanation_all_sources() {
    let text = build_explanation(true, Some(true), 3, 6, Some(42.0), 0.1, false);
    assert!(text.contains("Radar: yes"));
    assert!(text.contains("3 of 6 models"));
    assert!(text.contains("ensemble 42 %"));
}

#[test]
fn explanation_no_radar() {
    let text = build_explanation(false, None, 0, 4, None, 0.1, false);
    assert!(text.contains("Radar: not available"));
    assert!(text.contains("ensemble: n/a"));
}
