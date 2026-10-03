use super::*;

const THRESHOLD: f64 = 0.1;

/// pytest.approx(expected) with the default tolerances.
fn approx(actual: f64, expected: f64) -> bool {
    let tol = if expected == 0.0 {
        1e-12
    } else {
        1e-6 * expected.abs()
    };
    (actual - expected).abs() <= tol
}

/// Build `(model, precip_mm, observed_mm)` rows from per-model pairs, in order.
fn rows_for(pairs_by_model: &[(&str, &[(f64, f64)])]) -> Vec<(String, f64, f64)> {
    let mut rows = Vec::new();
    for &(model, pairs) in pairs_by_model {
        for &(precip, observed) in pairs {
            rows.push((model.to_string(), precip, observed));
        }
    }
    rows
}

#[test]
fn confusion_counts_and_mae() {
    let rows = rows_for(&[
        (
            "icon_d2",
            &[
                (0.4, 0.3), // hit (both > 0.1)
                (0.0, 0.2), // miss (dry forecast, rain observed)
                (0.5, 0.0), // false alarm (rain forecast, dry observed)
                (0.0, 0.0), // correct negative
            ],
        ),
        // 0.2 > 0.1 (rain forecast) but 0.1 is NOT > 0.1 (dry observed)
        ("gfs_seamless", &[(0.2, 0.1)]), // -> false alarm
    ]);
    let result = model_accuracy(&rows, THRESHOLD);
    let d2 = &result["icon_d2"];
    assert_eq!(d2.n_samples, 4);
    assert_eq!(
        (d2.hits, d2.misses, d2.false_alarms, d2.correct_negatives),
        (1, 1, 1, 1)
    );
    assert!(approx(d2.event_accuracy.unwrap(), 0.5));
    // MAE: (0.1 + 0.2 + 0.5 + 0.0) / 4
    assert!(approx(d2.mae_mm.unwrap(), 0.2));
    // observed 0.1 is exactly at the threshold -> NOT rain (strict >)
    let gfs = &result["gfs_seamless"];
    assert_eq!((gfs.hits, gfs.false_alarms), (0, 1));
    assert!(approx(gfs.event_accuracy.unwrap(), 0.0));
}

#[test]
fn threshold_is_strict_greater_than() {
    let rows = rows_for(&[("icon_d2", &[(THRESHOLD, THRESHOLD), (THRESHOLD, 0.0)])]);
    let result = model_accuracy(&rows, THRESHOLD);
    // forecast exactly at the threshold counts as "dry" in both rows
    assert_eq!(result["icon_d2"].correct_negatives, 2);
    assert!(approx(result["icon_d2"].event_accuracy.unwrap(), 1.0));
}

#[test]
fn all_dry_spell_scores_perfectly() {
    // The all-dry case: an all-zero model wins on event accuracy during a
    // dry spell (which is correct — it *was* right about no rain).
    let pairs_zero: [(f64, f64); 5] = [(0.0, 0.0); 5];
    let pairs_wet: [(f64, f64); 5] = [(2.0, 0.0); 5];
    let rows = rows_for(&[("always_zero", &pairs_zero), ("always_wet", &pairs_wet)]);
    let result = model_accuracy(&rows, THRESHOLD);
    let zero = &result["always_zero"];
    assert!(approx(zero.event_accuracy.unwrap(), 1.0));
    assert_eq!(zero.correct_negatives, 5);
    assert!(approx(zero.mae_mm.unwrap(), 0.0));
    let wet = &result["always_wet"];
    assert!(approx(wet.event_accuracy.unwrap(), 0.0));
    assert_eq!(wet.false_alarms, 5);
    assert!(approx(wet.mae_mm.unwrap(), 2.0));
}

#[test]
fn mae_favors_zero_model_but_event_accuracy_does_not() {
    // MAE alone would crown the all-zero model; event accuracy separates
    // skill from luck in a dry spell when rain eventually happens.
    let rows = rows_for(&[
        ("always_zero", &[(0.0, 0.0), (0.0, 1.0)]), // MAE 0.5, event accuracy 0.5
        ("always_wet", &[(1.0, 0.0), (1.0, 1.0)]),  // MAE 0.5, event accuracy 0.5
        ("good", &[(0.0, 0.0), (1.2, 1.0)]),        // MAE 0.1, event accuracy 1.0
    ]);
    let result = model_accuracy(&rows, THRESHOLD);
    assert!(approx(result["always_zero"].mae_mm.unwrap(), 0.5));
    assert!(approx(result["always_wet"].mae_mm.unwrap(), 0.5));
    assert!(approx(result["good"].mae_mm.unwrap(), 0.1));
    assert!(approx(result["good"].event_accuracy.unwrap(), 1.0));
    assert!(approx(result["always_zero"].event_accuracy.unwrap(), 0.5));
}

#[test]
fn empty_rows_give_empty_result() {
    assert!(model_accuracy(&[], THRESHOLD).is_empty());
}

#[test]
fn models_without_samples_are_absent() {
    let rows = rows_for(&[("icon_d2", &[(0.2, 0.1)])]);
    let result = model_accuracy(&rows, THRESHOLD);
    assert!(result.contains_key("icon_d2"));
    assert_eq!(result.len(), 1);
}
