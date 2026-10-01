//! Pure (network-free) rain-probability logic for the next 60 minutes
//! (Python `app/probability.py`).
//!
//! Every decision the aggregator makes lives here as a plain function on
//! the normalized models: no I/O, no hidden clock. Three independent
//! signals (radar nowcast, model votes, ensemble) are combined linearly.

pub mod combine;

use std::collections::BTreeMap;

use chrono::{DateTime, TimeDelta, Utc};

use crate::accuracy::ModelAccuracy;
use crate::config::{ProbabilityConfig, RadarConfig};
use crate::models::{ForecastBundle, ModelVote, RadarFrame, RadarNowcast};
use crate::pyfmt::py_hypot;

pub use combine::*;

/// Location in full-grid (x, y) cell coordinates (Python
/// `_location_full_xy`). The sub-grid's origin is at `bbox` =
/// (top, left, bottom, right); the requested point is `location_xy` =
/// (px, py) measured from that origin (fractional — the location sits
/// inside a cell).
fn location_full_xy(nowcast: &RadarNowcast) -> (f64, f64) {
    let (top, left) = (nowcast.bbox.0, nowcast.bbox.1);
    (
        left as f64 + nowcast.location_xy.0,
        top as f64 + nowcast.location_xy.1,
    )
}

/// Distance (km) from the location to the radar cell `(cell_x, cell_y)`.
///
/// The grid is a uniform ~1 km physical grid, so the cell offset in grid
/// units times the cell size is the physical offset; a plain Euclidean
/// distance is accurate at this scale.
pub fn cell_distance_km(nowcast: &RadarNowcast, cell_x: i64, cell_y: i64, cell_km: f64) -> f64 {
    let (loc_x, loc_y) = location_full_xy(nowcast);
    py_hypot(
        (cell_x as f64 - loc_x) * cell_km,
        (cell_y as f64 - loc_y) * cell_km,
    )
}

/// True if any cell within `radius_km` of the location exceeds the rain
/// threshold in any frame with `now <= frame_time < now + horizon`.
pub fn radar_has_local_rain(
    nowcast: &RadarNowcast,
    now: DateTime<Utc>,
    horizon: TimeDelta,
    radius_km: f64,
    cell_km: f64,
    cell_rain_threshold_mm: f64,
) -> bool {
    let end = now + horizon;
    for frame in &nowcast.frames {
        if !(now <= frame.time_utc && frame.time_utc < end) {
            continue;
        }
        for cell in &frame.cells {
            if cell.mm <= cell_rain_threshold_mm {
                continue;
            }
            if cell_distance_km(nowcast, cell.x, cell.y, cell_km) <= radius_km {
                return true;
            }
        }
    }
    false
}

/// Strongest rain (max mm) within `radius_km` of the location in one frame.
///
/// Only cells whose 5-minute amount exceeds `threshold_mm` count
/// (consistent with the radar signal's definition of "rain"), so the
/// next-hour bar and the binary radar vote agree on what counts as local
/// rain. Returns 0.0 when no qualifying cell lies within the radius.
pub fn max_local_rain_mm(
    nowcast: &RadarNowcast,
    frame: &RadarFrame,
    radius_km: f64,
    cell_km: f64,
    threshold_mm: f64,
) -> f64 {
    let mut best = 0.0_f64;
    for cell in &frame.cells {
        if cell.mm <= threshold_mm || cell.mm <= best {
            continue;
        }
        if cell_distance_km(nowcast, cell.x, cell.y, cell_km) <= radius_km {
            best = cell.mm;
        }
    }
    best
}

/// Signal 1: return `(radar_available, raining)`.
///
/// `raining` is None when radar is unavailable or does not cover the
/// location — the combined probability then falls back to models +
/// ensemble.
pub fn radar_rain_signal(
    nowcast: Option<&RadarNowcast>,
    now: DateTime<Utc>,
    radar_cfg: &RadarConfig,
    prob_cfg: &ProbabilityConfig,
    horizon: TimeDelta,
) -> (bool, Option<bool>) {
    let Some(nowcast) = nowcast else {
        return (false, None);
    };
    if !nowcast.covered || nowcast.frames.is_empty() {
        return (false, None);
    }
    let raining = radar_has_local_rain(
        nowcast,
        now,
        horizon,
        radar_cfg.radius_km,
        radar_cfg.grid_size_km,
        prob_cfg.radar_cell_rain_threshold_mm,
    );
    (true, Some(raining))
}

/// Sum of the 15-min steps ending in the window `[now, now + 1 h)`.
///
/// Open-Meteo minutely_15 precipitation is a *preceding-interval sum*: the
/// value at timestamp `t` is the rain of `[t - 15 min, t)`. So the steps
/// that make up the next hour are those with `now < t <= now + 1 h`; a
/// step stamped exactly `now` already covers the past 15 minutes and is
/// skipped.
///
/// Returns None when no step falls in that window (stale/missing series)
/// or when any involved value is missing: a model without data does not
/// vote "dry", it simply does not vote.
pub fn sum_next_hour(
    min15_time: &[DateTime<Utc>],
    values: &[Option<f64>],
    now: DateTime<Utc>,
) -> Option<f64> {
    if min15_time.is_empty() {
        return None;
    }
    let end = now + TimeDelta::hours(1);
    let mut total = 0.0_f64;
    let mut count = 0_usize;
    for (t, v) in min15_time.iter().zip(values) {
        if *t <= now {
            continue;
        }
        if *t > end {
            break;
        }
        let v = (*v)?;
        total += v;
        count += 1;
    }
    (count > 0).then_some(total)
}

/// One `ModelVote` per model in the bundle (bundle order).
pub fn model_votes(bundle: Option<&ForecastBundle>, now: DateTime<Utc>) -> Vec<ModelVote> {
    let Some(bundle) = bundle else {
        return Vec::new();
    };
    bundle
        .models
        .iter()
        .map(|m| ModelVote {
            name: m.name.clone(),
            precip_next_hour_mm: sum_next_hour(&m.min15_time, &m.min15_precip_mm, now),
        })
        .collect()
}

/// Return `(share 0..100 | None, models_with_rain, models_total)`.
///
/// Models whose next-hour sum is None (no data) do not count at all.
pub fn model_rain_signal(votes: &[ModelVote], threshold_mm: f64) -> (Option<f64>, usize, usize) {
    let available: Vec<&ModelVote> = votes
        .iter()
        .filter(|v| v.precip_next_hour_mm.is_some())
        .collect();
    if available.is_empty() {
        return (None, 0, 0);
    }
    let n_rain = available
        .iter()
        .filter(|v| v.precip_next_hour_mm.is_some_and(|p| p > threshold_mm))
        .count();
    let share = 100.0 * n_rain as f64 / available.len() as f64;
    (Some(share), n_rain, available.len())
}

/// Accuracy-weighted model signal (optional).
///
/// Instead of counting the share of voting models with rain, each voting
/// model's *vote* (100 if it forecasts > `threshold_mm`, else 0) is
/// weighted by its `event_accuracy` and the signal is
/// `100 * sum(w_i * rain_i) / sum(w_i)`. A more accurate model pulls the
/// number toward its vote.
///
/// Rules:
///
/// - Models without a next-hour sum (no data) do not count at all, same as
///   `model_rain_signal`.
/// - Weight of a model is `max(event_accuracy, 0.1)` — the 0.1 floor keeps
///   a (poor) model from being silenced entirely. A model with no accuracy
///   row gets the floor.
/// - **Gate:** if *any* voting model has fewer than `min_samples` compared
///   hours (or no accuracy row at all), the scores are not trustworthy yet
///   and the function reports `weighted_applied = false` — the caller must
///   fall back to `model_rain_signal` (equal weights).
///
/// Returns the same `(signal | None, n_rain, n_total)` as
/// `model_rain_signal` (`n_rain`/`n_total` are always the equal-weight
/// counts, for the explanation) plus `weighted_applied`.
pub fn weighted_model_signal(
    votes: &[ModelVote],
    accuracy: &BTreeMap<String, ModelAccuracy>,
    threshold_mm: f64,
    min_samples: i64,
) -> (Option<f64>, usize, usize, bool) {
    let available: Vec<&ModelVote> = votes
        .iter()
        .filter(|v| v.precip_next_hour_mm.is_some())
        .collect();
    if available.is_empty() {
        return (None, 0, 0, false);
    }
    let n_rain = available
        .iter()
        .filter(|v| v.precip_next_hour_mm.is_some_and(|p| p > threshold_mm))
        .count();
    let weighted_applied = available.iter().all(|v| {
        accuracy
            .get(&v.name)
            .is_some_and(|a| a.n_samples >= min_samples)
    });
    if !weighted_applied {
        let share = 100.0 * n_rain as f64 / available.len() as f64;
        return (Some(share), n_rain, available.len(), false);
    }
    let mut total_weight = 0.0_f64;
    let mut weighted_rain = 0.0_f64;
    for v in &available {
        // The gate above guarantees a row for every voting model.
        let Some(row) = accuracy.get(&v.name) else {
            continue;
        };
        let weight = row.event_accuracy.unwrap_or(0.0).max(0.1);
        total_weight += weight;
        if v.precip_next_hour_mm.is_some_and(|p| p > threshold_mm) {
            weighted_rain += weight;
        }
    }
    let signal = (total_weight > 0.0).then_some(100.0 * weighted_rain / total_weight);
    (signal, n_rain, available.len(), true)
}

#[cfg(test)]
mod tests;
