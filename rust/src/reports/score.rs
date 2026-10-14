//! The models against the user reports: the `user_reports` block of
//! `GET /api/model-accuracy` (Python `app/reports.py`, section P2).
//!
//! Per UTC hour the newest user report decides (wet when its kind is one of
//! the four wet kinds); the station's scored rows of the same window are
//! compared against it, exactly like the station's own table (strict
//! `> threshold_mm`, models in alphabetical order).

use std::collections::{BTreeMap, BTreeSet};

use chrono::{DateTime, TimeDelta, Utc};
use serde_json::{Map, Value, json};

use super::ReportKind;
use crate::pyfmt::py_round;
use crate::store::{ReportRow, ScoredRow, Store, StoreError};
use crate::times::to_iso;

/// The hour a report belongs to (Python `hour_of`): `observed_at` cut to
/// the hour, the `valid_from` format.
pub fn hour_of(observed_at: &str) -> String {
    let prefix = observed_at.get(0..13).unwrap_or(observed_at);
    format!("{prefix}:00:00Z")
}

/// Per hour, the newest report's `(wet, confirms)` (Python
/// `deciding_reports`). `rows` are the store's report rows; the newest
/// report of an hour (`observed_at`, then id) decides it.
pub fn deciding_reports(rows: &[ReportRow]) -> BTreeMap<String, (bool, bool)> {
    // hour -> (observed_at, id, kind, confirms) of the newest report so far
    let mut newest: BTreeMap<String, (String, i64, String, bool)> = BTreeMap::new();
    for row in rows {
        let hour = hour_of(&row.observed_at);
        let newer = match newest.get(&hour) {
            None => true,
            Some((current_at, current_id, _, _)) => {
                (row.observed_at.as_str(), row.id) > (current_at.as_str(), *current_id)
            }
        };
        if newer {
            newest.insert(
                hour,
                (
                    row.observed_at.clone(),
                    row.id,
                    row.kind.clone(),
                    row.confirms,
                ),
            );
        }
    }
    newest
        .into_iter()
        .map(|(hour, (_observed_at, _id, kind, confirms))| {
            let wet = ReportKind::parse(&kind).is_some_and(ReportKind::is_wet);
            (hour, (wet, confirms))
        })
        .collect()
}

/// Score the models against the user reports (Python `score_user_reports`).
///
/// `deciding` is [`deciding_reports`]; `rows` are the station's scored rows
/// (the window, `observed_mm IS NOT NULL`). Only report hours with at least
/// one such row count (`hours`), `confirmed_hours` those whose deciding
/// report confirms. A model's forecast is wet when `precip_mm >
/// threshold_mm` (strict, as in `crate::accuracy`); the models come out in
/// alphabetical order, like the station's table.
#[expect(
    clippy::cast_precision_loss,
    reason = "hits, misses and correct_negatives count scored hours, far below 2^52"
)]
pub fn score_user_reports(
    deciding: &BTreeMap<String, (bool, bool)>,
    rows: &[ScoredRow],
    threshold_mm: f64,
) -> Value {
    let mut pairs: BTreeMap<String, Vec<(bool, bool)>> = BTreeMap::new();
    let mut scored: BTreeSet<String> = BTreeSet::new();
    for row in rows {
        let Some(&(wet, _confirms)) = deciding.get(&row.valid_from) else {
            continue;
        };
        scored.insert(row.valid_from.clone());
        pairs
            .entry(row.model.clone())
            .or_default()
            .push((row.precip_mm > threshold_mm, wet));
    }
    let confirmed_hours = scored
        .iter()
        .filter(|hour| {
            deciding
                .get(hour.as_str())
                .is_some_and(|(_, confirms)| *confirms)
        })
        .count();
    let mut models: Map<String, Value> = Map::new();
    for (model, model_pairs) in pairs {
        let mut hits = 0_i64;
        let mut misses = 0_i64;
        let mut false_alarms = 0_i64;
        let mut correct_negatives = 0_i64;
        for (forecast_wet, observed_wet) in model_pairs {
            if forecast_wet && observed_wet {
                hits += 1;
            } else if observed_wet {
                misses += 1;
            } else if forecast_wet {
                false_alarms += 1;
            } else {
                correct_negatives += 1;
            }
        }
        let n = hits + misses + false_alarms + correct_negatives;
        // Every model in `pairs` has at least one row, so `n > 0` and the
        // division is defined; the guard mirrors Python's `if n else None`.
        let event_accuracy = if n > 0 {
            Some(py_round((hits + correct_negatives) as f64 / n as f64, 3))
        } else {
            None
        };
        models.insert(
            model,
            json!({
                "n_samples": n,
                "hits": hits,
                "misses": misses,
                "false_alarms": false_alarms,
                "correct_negatives": correct_negatives,
                "event_accuracy": event_accuracy.map_or(Value::Null, Value::from),
            }),
        );
    }
    json!({
        "hours": scored.len(),
        "confirmed_hours": confirmed_hours,
        "models": Value::Object(models),
    })
}

/// The `user_reports` block of `GET /api/model-accuracy` (Python
/// `user_report_accuracy`): the same scored rows the station uses (the
/// window from `now`), paired with the newest user report of each hour.
pub fn user_report_accuracy(
    store: &Store,
    window_days: i64,
    now: DateTime<Utc>,
    threshold_mm: f64,
) -> Result<Value, StoreError> {
    let since = to_iso(now - TimeDelta::days(window_days));
    let deciding = deciding_reports(&store.report_rows()?);
    let rows = store.scored_forecasts(&since)?;
    Ok(score_user_reports(&deciding, &rows, threshold_mm))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report(id: i64, kind: &str, confirms: bool, observed_at: &str) -> ReportRow {
        ReportRow {
            id,
            kind: kind.to_string(),
            confirms,
            observed_at: observed_at.to_string(),
        }
    }

    fn scored(model: &str, valid_from: &str, precip_mm: f64) -> ScoredRow {
        ScoredRow {
            model: model.to_string(),
            valid_from: valid_from.to_string(),
            precip_mm,
        }
    }

    #[test]
    fn hour_of_cuts_to_the_hour() {
        assert_eq!(hour_of("2026-09-30T10:59:59Z"), "2026-09-30T10:00:00Z");
        assert_eq!(hour_of("2026-09-30T10:00:00Z"), "2026-09-30T10:00:00Z");
        // A mangled stamp keeps Python's behaviour (`[:13]` of the whole).
        assert_eq!(hour_of("abc"), "abc:00:00Z");
    }

    #[test]
    fn the_newest_report_decides_its_hour() {
        let rows = [
            report(1, "rain", false, "2026-09-30T10:10:00Z"),
            // The newer report of the hour is dry, so the hour is dry
            // despite the earlier rain.
            report(2, "cloudy", false, "2026-09-30T10:40:00Z"),
            // Same timestamp: the higher id wins.
            report(3, "rain", true, "2026-09-30T11:00:00Z"),
            report(4, "fog", false, "2026-09-30T11:00:00Z"),
            // Same timestamp: the higher id wins, and its confirms sticks.
            report(5, "rain", false, "2026-09-30T12:00:00Z"),
            report(6, "clear", true, "2026-09-30T12:00:00Z"),
        ];
        let deciding = deciding_reports(&rows);
        assert_eq!(
            deciding,
            BTreeMap::from([
                ("2026-09-30T10:00:00Z".to_string(), (false, false)),
                ("2026-09-30T11:00:00Z".to_string(), (false, false)),
                ("2026-09-30T12:00:00Z".to_string(), (false, true)),
            ])
        );
    }

    #[test]
    fn hours_without_a_scored_row_are_not_counted() {
        // A report hour without a frozen row and a scored row without a
        // report: neither is scored.
        let deciding = deciding_reports(&[report(1, "rain", true, "2026-09-30T13:00:00Z")]);
        let rows = [scored("icon_d2", "2026-09-30T14:00:00Z", 2.0)];
        assert_eq!(
            score_user_reports(&deciding, &rows, 0.1),
            json!({"hours": 0, "confirmed_hours": 0, "models": {}})
        );
    }

    #[test]
    fn a_model_without_rows_in_a_report_hour_is_absent() {
        let deciding = deciding_reports(&[
            report(1, "rain", true, "2026-09-30T10:00:00Z"),
            report(2, "cloudy", false, "2026-09-30T11:00:00Z"),
        ]);
        let rows = [
            scored("a_model", "2026-09-30T10:00:00Z", 1.0),
            scored("a_model", "2026-09-30T11:00:00Z", 0.0),
            // Only rows in report hours count for a model; this one is
            // outside, so `b_model` never appears.
            scored("b_model", "2026-09-30T12:00:00Z", 5.0),
        ];
        assert_eq!(
            score_user_reports(&deciding, &rows, 0.1),
            json!({
                "hours": 2,
                "confirmed_hours": 1,
                "models": {
                    "a_model": {
                        "n_samples": 2,
                        "hits": 1,
                        "misses": 0,
                        "false_alarms": 0,
                        "correct_negatives": 1,
                        "event_accuracy": 1.0,
                    },
                },
            })
        );
    }

    #[test]
    fn the_threshold_is_strict() {
        // Exactly at the threshold the forecast is dry (a miss against a
        // wet hour); above it, a hit.
        let deciding = deciding_reports(&[report(1, "rain", false, "2026-09-30T10:00:00Z")]);
        let rows = [scored("a_model", "2026-09-30T10:00:00Z", 0.1)];
        assert_eq!(
            score_user_reports(&deciding, &rows, 0.1),
            json!({
                "hours": 1,
                "confirmed_hours": 0,
                "models": {
                    "a_model": {
                        "n_samples": 1,
                        "hits": 0,
                        "misses": 1,
                        "false_alarms": 0,
                        "correct_negatives": 0,
                        "event_accuracy": 0.0,
                    },
                },
            })
        );
        let rows = [scored("a_model", "2026-09-30T10:00:00Z", 0.11)];
        let block = score_user_reports(&deciding, &rows, 0.1);
        assert_eq!(block["models"]["a_model"]["hits"], json!(1));
        assert_eq!(block["models"]["a_model"]["misses"], json!(0));
    }

    #[test]
    fn event_accuracy_rounds_like_python() {
        // 2 of 3 right: 0.666… rounds to 0.667 (Python's round(x, 3)).
        let deciding = deciding_reports(&[
            report(1, "rain", true, "2026-09-30T10:00:00Z"),
            report(2, "clear", false, "2026-09-30T11:00:00Z"),
            report(3, "cloudy", false, "2026-09-30T12:00:00Z"),
        ]);
        let rows = [
            scored("a_model", "2026-09-30T10:00:00Z", 2.0), // hit
            scored("a_model", "2026-09-30T11:00:00Z", 0.0), // correct negative
            scored("a_model", "2026-09-30T12:00:00Z", 3.0), // false alarm
        ];
        let block = score_user_reports(&deciding, &rows, 0.1);
        assert_eq!(block["hours"], json!(3));
        assert_eq!(block["confirmed_hours"], json!(1));
        assert_eq!(block["models"]["a_model"]["event_accuracy"], json!(0.667));
        assert_eq!(block["models"]["a_model"]["n_samples"], json!(3));
    }
}
