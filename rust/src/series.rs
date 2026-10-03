//! Pure helpers that shape parsed model/radar data into API-ready series
//! (no I/O) (Python `app/series.py`).
//!
//! * `build_24h_series` — hourly precipitation per model on a common UTC
//!   grid (24 h chart data)
//! * `build_radar_next_hour_bar` — 12 x 5-min local-rain bar (radar nowcast)
//! * `build_forecast_history_rows` — rows for the forecast_history table
//!   (accuracy comparison)

use std::collections::HashMap;

use chrono::{DateTime, DurationRound, TimeDelta, Utc};

use crate::models::{ForecastBundle, RadarFrame, RadarNowcast};
use crate::probability::max_local_rain_mm;
use crate::pyfmt::py_round;
use crate::times::to_iso;

#[derive(Clone, Debug, PartialEq)]
pub struct ModelHours {
    pub name: String,
    pub precipitation_mm: Vec<Option<f64>>,
}

/// Python `build_24h_series` result: `{"hours", "models", "n_models"}`.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Series24h {
    pub hours: Vec<String>,
    pub models: Vec<ModelHours>,
    pub n_models: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct RadarStep {
    pub start_utc: String,
    pub precip_mm: f64,
}

/// Python `build_radar_next_hour_bar` result: `{"available", "steps"}`.
#[derive(Clone, Debug, PartialEq)]
pub struct RadarBar {
    pub available: bool,
    pub steps: Vec<RadarStep>,
}

/// One `forecast_history` row (Python `build_forecast_history_rows`).
#[derive(Clone, Debug, PartialEq)]
pub struct HistoryRow {
    pub model: String,
    pub issued_at: String,
    pub valid_from: String,
    pub valid_to: String,
    pub precip_mm: f64,
}

/// Hourly precipitation per model for the next `n_hours` hours.
///
/// The axis is relative to `now`, not the UTC calendar day: only stamps
/// `t > now` are kept, so the first entry is always the *current* hour.
///
/// Precipitation convention: the hourly value at stamp `t` is the rain of
/// the preceding hour `[t-1h, t)`. `hours[i]` therefore carries the
/// **start** of that hour — the value plotted at 10:00 comes from the
/// stamp at 11:00.
///
/// All models share the same hourly axis, so the grid is taken from the
/// first model with data; a model whose axis does not match is skipped.
/// `hours` are ISO-8601 UTC strings.
pub fn build_24h_series(
    bundle: Option<&ForecastBundle>,
    now: DateTime<Utc>,
    n_hours: usize,
) -> Series24h {
    let empty = Series24h::default();
    let Some(bundle) = bundle else {
        return empty;
    };
    let Some(reference) = bundle
        .models
        .iter()
        .find(|m| !m.hourly_time.is_empty() && !m.hourly_precip_mm.is_empty())
    else {
        return empty;
    };

    // the window starts at an arbitrary offset into the axis (relative to
    // now); align every model at the same offset as the reference model
    let mut stamps: Vec<DateTime<Utc>> = Vec::new();
    let mut offset = 0_usize;
    for (i, t) in reference.hourly_time.iter().enumerate() {
        if *t > now {
            if stamps.is_empty() {
                offset = i;
            }
            stamps.push(*t);
            if stamps.len() == n_hours {
                break;
            }
        }
    }
    if stamps.is_empty() {
        return empty;
    }
    let n = stamps.len();

    let mut models: Vec<ModelHours> = Vec::new();
    for m in &bundle.models {
        if m.hourly_time.is_empty() || m.hourly_time.len() < offset + n {
            continue;
        }
        if m.hourly_time.get(offset..offset + n) != Some(stamps.as_slice()) {
            continue;
        }
        // the precipitation list may be shorter than the time axis: the
        // slice is then simply shorter, and all-None (incl. empty) skips
        let values: Vec<Option<f64>> = m
            .hourly_precip_mm
            .get(offset..(offset + n).min(m.hourly_precip_mm.len()))
            .map(|s| s.to_vec())
            .unwrap_or_default();
        if values.iter().all(|v| v.is_none()) {
            continue; // model with null data draws nothing -> skip
        }
        models.push(ModelHours {
            name: m.name.clone(),
            precipitation_mm: values,
        });
    }
    if models.is_empty() {
        return empty; // every model has null data -> same empty shape as no bundle
    }
    // label each hour by its START (the value at stamp t covers [t-1h, t))
    let n_models = models.len();
    let hours = stamps
        .iter()
        .map(|t| to_iso(*t - TimeDelta::hours(1)))
        .collect();
    Series24h {
        hours,
        models,
        n_models,
    }
}

/// 12 five-minute buckets of the *local* (within `radius_km`) radar rain
/// for the next hour, for the 60-minute bar in the UI.
///
/// Returns exactly `n_steps` buckets (oldest first). `precip_mm` is the
/// strongest rain cell within the radius in that bucket (0.0 for dry, and
/// for a bucket with no radar frame yet). `available` is false when radar
/// is missing or does not cover the location (the frontend then falls back
/// to a models-only display).
///
/// `now` is floored to the 5-minute grid before the buckets are laid out,
/// so every bucket start sits on the same grid as the radar frame
/// timestamps (the client floors its request the same way) — this is what
/// makes frame-to-bucket matching exact rather than approximate.
pub fn build_radar_next_hour_bar(
    nowcast: Option<&RadarNowcast>,
    now: DateTime<Utc>,
    radius_km: f64,
    cell_km: f64,
    cell_rain_threshold_mm: f64,
    n_steps: usize,
) -> RadarBar {
    let grid_now = now.duration_trunc(TimeDelta::minutes(5)).unwrap_or(now);
    let bucket_starts: Vec<DateTime<Utc>> = (0..i64::try_from(n_steps).unwrap_or(0))
        .map(|i| grid_now + TimeDelta::minutes(5 * i))
        .collect();
    let mut steps: Vec<RadarStep> = bucket_starts
        .iter()
        .map(|t| RadarStep {
            start_utc: to_iso(*t),
            precip_mm: 0.0,
        })
        .collect();

    let Some(nowcast) = nowcast else {
        return RadarBar {
            available: false,
            steps,
        };
    };
    if !nowcast.covered || nowcast.frames.is_empty() {
        return RadarBar {
            available: false,
            steps,
        };
    }

    // a later frame with the same time replaces an earlier one (Python dict)
    let frames_by_time: HashMap<DateTime<Utc>, &RadarFrame> =
        nowcast.frames.iter().map(|f| (f.time_utc, f)).collect();
    for (step, start) in steps.iter_mut().zip(&bucket_starts) {
        if let Some(frame) = frames_by_time.get(start) {
            let mm = max_local_rain_mm(nowcast, frame, radius_km, cell_km, cell_rain_threshold_mm);
            step.precip_mm = py_round(mm, 2);
        }
    }

    RadarBar {
        available: true,
        steps,
    }
}

/// One row per model per hour that has *not started yet* at `issued_at`.
///
/// Precipitation convention: the hourly value at stamp `t` covers the
/// preceding hour `[t-1h, t)` — so `valid_from = t - 1h` and
/// `valid_to = t` (not `t + 1h`, which would be one hour late). Only rows
/// with `valid_from >= issued_at` are kept: an hour that is already in
/// progress is not a forecast, and its value would be partially observed,
/// so storing it would bias the accuracy comparison.
///
/// Rows with null precipitation are skipped (nothing to verify later).
/// `issued_at` is the moment the forecast was fetched.
///
/// The cap is on *future* hours: with the 3-day forecast axis, the raw
/// slice would drop next-day hours when issued late in the UTC day, so we
/// filter first and keep the first `n_hours` remaining rows per model.
pub fn build_forecast_history_rows(
    bundle: &ForecastBundle,
    issued_at: DateTime<Utc>,
    n_hours: usize,
) -> Vec<HistoryRow> {
    let issued_iso = to_iso(issued_at);
    let mut rows: Vec<HistoryRow> = Vec::new();
    for m in &bundle.models {
        if m.hourly_time.is_empty() {
            continue;
        }
        let mut model_rows: Vec<HistoryRow> = Vec::new();
        for (t, v) in m.hourly_time.iter().zip(&m.hourly_precip_mm) {
            let Some(v) = v else {
                continue; // null precipitation: nothing to verify later
            };
            let valid_from = *t - TimeDelta::hours(1);
            if valid_from < issued_at {
                continue; // hour already started: not a (future) forecast
            }
            model_rows.push(HistoryRow {
                model: m.name.clone(),
                issued_at: issued_iso.clone(),
                valid_from: to_iso(valid_from),
                valid_to: to_iso(*t),
                precip_mm: *v,
            });
            if model_rows.len() == n_hours {
                break;
            }
        }
        rows.extend(model_rows);
    }
    rows
}

#[cfg(test)]
mod tests;
