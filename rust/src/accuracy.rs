//! Pure per-model accuracy scoring (Python `app/accuracy.py`).
//!
//! Scores the *same yes/no event* the next-hour vote uses (precipitation
//! `> threshold_mm`), not the raw millimetres: MAE alone is misleading,
//! because during a dry spell a model that always says 0 mm has a near-zero
//! MAE without ever being right about rain. `mae_mm` is still reported for
//! context; the headline score is `event_accuracy`.

use std::collections::BTreeMap;

/// One model's accuracy (Python: the per-model dict of `model_accuracy`).
#[derive(Clone, Debug, PartialEq)]
pub struct ModelAccuracy {
    pub n_samples: i64,
    pub mae_mm: Option<f64>,
    pub hits: i64,
    pub misses: i64,
    pub false_alarms: i64,
    pub correct_negatives: i64,
    pub event_accuracy: Option<f64>,
}

/// Score forecast-vs-observation pairs, grouped per model.
///
/// `rows` are raw `(model, precip_mm, observed_mm)` triples as returned by
/// the store's `compared_forecasts` (already filtered to compared forecasts
/// inside the accuracy window). Returns one entry per model that has at
/// least one sample; models without samples are absent.
///
/// Per model: `n_samples`, `mae_mm` (mean absolute error), and the
/// confusion counts for the rain event `> threshold_mm` (strict — a value
/// exactly at the threshold counts as "dry", matching the vote):
/// `hits` (rain forecast, rain observed), `misses` (dry forecast, rain
/// observed), `false_alarms` (rain forecast, dry observed),
/// `correct_negatives` (dry forecast, dry observed).
/// `event_accuracy` is `(hits + correct_negatives) / n_samples`.
pub fn model_accuracy(
    rows: &[(String, f64, f64)],
    threshold_mm: f64,
) -> BTreeMap<String, ModelAccuracy> {
    let mut by_model: BTreeMap<String, Vec<(f64, f64)>> = BTreeMap::new();
    for (model, precip, observed) in rows {
        by_model
            .entry(model.clone())
            .or_default()
            .push((*precip, *observed));
    }

    let mut result: BTreeMap<String, ModelAccuracy> = BTreeMap::new();
    for (model, pairs) in by_model {
        let n = pairs.len() as i64;
        let mut abs_error = 0.0_f64;
        let mut hits = 0_i64;
        let mut misses = 0_i64;
        let mut false_alarms = 0_i64;
        let mut correct_negatives = 0_i64;
        for &(precip, observed) in &pairs {
            abs_error += (precip - observed).abs();
            let forecast_rain = precip > threshold_mm;
            let observed_rain = observed > threshold_mm;
            if forecast_rain && observed_rain {
                hits += 1;
            } else if observed_rain {
                misses += 1;
            } else if forecast_rain {
                false_alarms += 1;
            } else {
                correct_negatives += 1;
            }
        }
        // Every model in `by_model` has at least one row, so `n > 0` and the
        // divisions are defined (Python guards them with `if n else None`).
        result.insert(
            model,
            ModelAccuracy {
                n_samples: n,
                mae_mm: Some(abs_error / n as f64),
                hits,
                misses,
                false_alarms,
                correct_negatives,
                event_accuracy: Some((hits + correct_negatives) as f64 / n as f64),
            },
        );
    }
    result
}

#[cfg(test)]
mod tests;
