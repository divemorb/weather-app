use super::*;
use crate::models::{ForecastBundle, ModelSeries, RadarCell, RadarFrame, RadarNowcast};
use crate::times::parse_iso;
use chrono::{DateTime, Datelike, TimeDelta, TimeZone, Timelike, Utc};

/// The Python tests' `NOW` constant: 2025-01-01 12:00 UTC.
fn now() -> DateTime<Utc> {
    at(2025, 1, 1, 12, 0)
}

/// A tz-aware UTC stamp with seconds 0 (the Python tests' datetimes).
fn at(year: i32, month: u32, day: u32, hour: u32, minute: u32) -> DateTime<Utc> {
    Utc.with_ymd_and_hms(year, month, day, hour, minute, 0)
        .unwrap()
}

/// The Python tests' `_model`: hourly axis stamped at whole hours from
/// `start` (default `NOW`), values `hourly`.
fn model(name: &str, hourly: Vec<Option<f64>>, start: Option<DateTime<Utc>>) -> ModelSeries {
    let base = start.unwrap_or_else(now);
    let naive = base.naive_utc();
    let base = at(naive.year(), naive.month(), naive.day(), naive.hour(), 0);
    let hourly_time = (0..hourly.len())
        .map(|i| base + TimeDelta::hours(i as i64))
        .collect();
    ModelSeries {
        name: name.to_string(),
        hourly_time,
        hourly_precip_mm: hourly,
        ..ModelSeries::default()
    }
}

fn cell(x: i64, y: i64, mm: f64) -> RadarCell {
    RadarCell { x, y, mm }
}

/// The Python tests' `_frame`: `NOW` + `offset_min` minutes.
fn frame(offset_min: i64, cells: Vec<RadarCell>) -> RadarFrame {
    RadarFrame {
        time_utc: now() + TimeDelta::minutes(offset_min),
        max_mm: cells.iter().map(|c| c.mm).fold(0.0_f64, f64::max),
        cells,
    }
}

/// `RadarNowcast` with the Python helper defaults: bbox (0, 0, 10, 10),
/// location (5.0, 5.0).
fn nowcast(frames: Vec<RadarFrame>, covered: bool) -> RadarNowcast {
    RadarNowcast {
        frames,
        covered,
        grid_width: 0,
        grid_height: 0,
        bbox: (0, 0, 10, 10),
        location_xy: (5.0, 5.0),
    }
}

// ---------------------------------------------------------------------------
// build_24h_series
// ---------------------------------------------------------------------------
#[test]
fn test_24h_series_empty_bundle() {
    let out = build_24h_series(None, now(), 24);
    assert_eq!(out, Series24h::default());
}

#[test]
fn test_24h_series_starts_at_now_and_labels_by_hour_start() {
    // axis stamped 11:00..34:00, now = 10:20
    let now = at(2025, 1, 1, 10, 20);
    let vals: Vec<Option<f64>> = (0..24).map(|i| Some(10.0 + i as f64)).collect();
    let start = at(2025, 1, 1, 11, 0);
    let bundle = ForecastBundle {
        models: vec![
            model("icon_d2", vals.clone(), Some(start)),
            model("gfs", vec![Some(0.0); 24], Some(start)),
        ],
    };
    let out = build_24h_series(Some(&bundle), now, 24);
    assert_eq!(out.hours.len(), 24);
    assert_eq!(out.n_models, 2);
    // first entry is the current hour (10:00), last is the 24th (next day 09:00)
    assert_eq!(out.hours[0], "2025-01-01T10:00:00Z");
    assert_eq!(*out.hours.last().unwrap(), "2025-01-02T09:00:00Z");
    let by_name = |name: &str| -> &Vec<Option<f64>> {
        &out.models
            .iter()
            .find(|m| m.name == name)
            .unwrap()
            .precipitation_mm
    };
    // the value plotted at 10:00 comes from the stamp at 11:00 (vals[0]):
    // the value at stamp t covers [t-1h, t)
    assert_eq!(by_name("icon_d2")[0], vals[0]);
    assert_eq!(by_name("icon_d2")[1], vals[1]);
    assert_eq!(by_name("gfs")[0], Some(0.0));
}

#[test]
fn test_24h_series_excludes_stamped_now() {
    // now exactly on a boundary: the stamp at 12:00 (rain of 11:00-12:00)
    // is already in the past and must not appear
    let bundle = ForecastBundle {
        models: vec![model(
            "icon_d2",
            vec![Some(1.0), Some(2.0), Some(3.0), Some(4.0)],
            None,
        )],
    };
    let out = build_24h_series(Some(&bundle), now(), 24);
    assert_eq!(out.hours[0], "2025-01-01T12:00:00Z"); // from stamp 13:00
    assert_eq!(
        out.models[0].precipitation_mm,
        vec![Some(2.0), Some(3.0), Some(4.0)]
    );
}

#[test]
fn test_24h_series_truncates_to_n_hours() {
    let bundle = ForecastBundle {
        models: vec![model(
            "icon_d2",
            vec![Some(1.0), Some(2.0), Some(3.0), Some(4.0)],
            Some(at(2025, 1, 1, 12, 0)),
        )],
    };
    let out = build_24h_series(Some(&bundle), now(), 3);
    assert_eq!(out.hours.len(), 3);
    assert_eq!(
        out.models[0].precipitation_mm,
        vec![Some(2.0), Some(3.0), Some(4.0)]
    );
}

#[test]
fn test_24h_series_skips_misaligned_model() {
    let bundle = ForecastBundle {
        models: vec![
            model(
                "icon_d2",
                vec![Some(1.0), Some(2.0), Some(3.0), Some(4.0)],
                Some(at(2025, 1, 1, 12, 0)),
            ),
            model("gfs", vec![Some(9.0); 4], Some(at(2025, 1, 2, 12, 0))),
        ],
    };
    let out = build_24h_series(Some(&bundle), now(), 24);
    assert_eq!(out.n_models, 1);
    assert_eq!(out.models[0].name, "icon_d2");
}

#[test]
fn test_24h_series_empty_when_no_future_hours() {
    let bundle = ForecastBundle {
        models: vec![model(
            "icon_d2",
            vec![Some(1.0), Some(2.0)],
            Some(at(2025, 1, 1, 10, 0)),
        )],
    };
    let out = build_24h_series(Some(&bundle), now(), 24);
    assert_eq!(out, Series24h::default());
}

#[test]
fn test_24h_series_empty_when_all_models_null() {
    let bundle = ForecastBundle {
        models: vec![
            model("icon_d2", vec![None; 4], Some(at(2025, 1, 1, 12, 0))),
            model("gfs", vec![None; 4], Some(at(2025, 1, 1, 12, 0))),
        ],
    };
    let out = build_24h_series(Some(&bundle), now(), 24);
    assert_eq!(out, Series24h::default());
}

// ---------------------------------------------------------------------------
// build_forecast_history_rows
// ---------------------------------------------------------------------------
#[test]
fn test_history_rows_labelled_by_hour_start_and_future_only() {
    // axis stamped 12:00..35:00, issued at 10:20
    let issued_at = at(2025, 1, 1, 10, 20);
    let vals = vec![Some(1.0), Some(2.0), Some(3.0), Some(4.0)];
    let bundle = ForecastBundle {
        models: vec![model("icon_d2", vals, Some(at(2025, 1, 1, 12, 0)))],
    };
    let rows = build_forecast_history_rows(&bundle, issued_at, 24);
    assert_eq!(
        rows.iter()
            .map(|r| r.valid_from.as_str())
            .collect::<Vec<_>>(),
        [
            "2025-01-01T11:00:00Z",
            "2025-01-01T12:00:00Z",
            "2025-01-01T13:00:00Z",
            "2025-01-01T14:00:00Z",
        ]
    );
    assert_eq!(
        rows.iter().map(|r| r.valid_to.as_str()).collect::<Vec<_>>(),
        [
            "2025-01-01T12:00:00Z",
            "2025-01-01T13:00:00Z",
            "2025-01-01T14:00:00Z",
            "2025-01-01T15:00:00Z",
        ]
    );
    assert_eq!(
        rows.iter().map(|r| r.precip_mm).collect::<Vec<_>>(),
        [1.0, 2.0, 3.0, 4.0]
    );
    for r in &rows {
        // each row covers exactly one hour and has not started yet
        let vf = parse_iso(&r.valid_from).unwrap();
        let vt = parse_iso(&r.valid_to).unwrap();
        assert_eq!(vt - vf, TimeDelta::hours(1));
        assert!(vf >= issued_at);
        assert_eq!(r.issued_at, "2025-01-01T10:20:00Z");
    }
}

#[test]
fn test_history_rows_skip_past_hours() {
    // issued exactly on an hour boundary: the hour ending at 12:00
    // (11:00-12:00, stamp 12:00) has just finished -> not stored
    let vals = vec![Some(1.0), Some(2.0), Some(3.0)];
    let bundle = ForecastBundle {
        models: vec![model("icon_d2", vals, None)],
    };
    let rows = build_forecast_history_rows(&bundle, now(), 24);
    // stamp 12:00 covers [11:00, 12:00) -> valid_from 11:00 < 12:00 -> dropped
    assert_eq!(
        rows.iter()
            .map(|r| r.valid_from.as_str())
            .collect::<Vec<_>>(),
        ["2025-01-01T12:00:00Z", "2025-01-01T13:00:00Z"]
    );
}

#[test]
fn test_history_rows_keep_24_future_hours_when_issued_late() {
    // 3-day axis, issued at 10:20: 24 future hours span two calendar days
    let issued_at = at(2025, 1, 1, 10, 20);
    let bundle = ForecastBundle {
        models: vec![model(
            "icon_d2",
            vec![Some(0.1); 72],
            Some(at(2025, 1, 1, 12, 0)),
        )],
    };
    let rows = build_forecast_history_rows(&bundle, issued_at, 24);
    assert_eq!(rows.len(), 24);
    assert_eq!(rows[0].valid_from, "2025-01-01T11:00:00Z");
    assert_eq!(rows[23].valid_from, "2025-01-02T10:00:00Z");
    assert!(
        rows.iter()
            .all(|r| parse_iso(&r.valid_from).unwrap() >= issued_at)
    );
}

#[test]
fn test_history_rows_skip_null_precipitation() {
    let bundle = ForecastBundle {
        models: vec![model(
            "icon_d2",
            vec![None, Some(2.0), None],
            Some(at(2025, 1, 1, 12, 0)),
        )],
    };
    let rows = build_forecast_history_rows(&bundle, now(), 24);
    assert_eq!(rows.iter().map(|r| r.precip_mm).collect::<Vec<_>>(), [2.0]);
}

#[test]
fn test_history_rows_skip_model_with_null_data() {
    let bundle = ForecastBundle {
        models: vec![
            // axis 12:00..14:00: the hour ending at 12:00 is past at NOW
            model(
                "icon_d2",
                vec![Some(1.0), Some(2.0), Some(3.0)],
                Some(at(2025, 1, 1, 12, 0)),
            ),
            model("gfs", vec![None; 3], Some(at(2025, 1, 1, 12, 0))),
        ],
    };
    let rows = build_forecast_history_rows(&bundle, now(), 24);
    assert_eq!(
        rows.iter().map(|r| r.model.as_str()).collect::<Vec<_>>(),
        ["icon_d2", "icon_d2"]
    );
    assert_eq!(
        rows.iter().map(|r| r.precip_mm).collect::<Vec<_>>(),
        [2.0, 3.0]
    );
}

// ---------------------------------------------------------------------------
// build_radar_next_hour_bar
// ---------------------------------------------------------------------------
#[test]
fn test_bar_none_nowcast_is_unavailable() {
    let out = build_radar_next_hour_bar(None, now(), 5.0, 1.0, 0.05, 12);
    assert!(!out.available);
    assert_eq!(out.steps.len(), 12);
    assert!(out.steps.iter().all(|s| s.precip_mm == 0.0));
}

#[test]
fn test_bar_not_covered_is_unavailable() {
    let nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.3)])], false);
    let out = build_radar_next_hour_bar(Some(&nc), now(), 5.0, 1.0, 0.05, 12);
    assert!(!out.available);
}

#[test]
fn test_bar_matches_frames_on_grid() {
    // frames at +0, +5, +10 min; rain only in the +5 bucket at the location
    let nc = nowcast(
        vec![
            frame(0, vec![]),
            frame(5, vec![cell(5, 5, 0.3)]),
            frame(10, vec![]),
        ],
        true,
    );
    let out = build_radar_next_hour_bar(Some(&nc), now(), 5.0, 1.0, 0.05, 12);
    assert!(out.available);
    let steps = &out.steps;
    assert_eq!(steps[0].start_utc, "2025-01-01T12:00:00Z");
    assert_eq!(steps[0].precip_mm, 0.0);
    assert_eq!(steps[1].start_utc, "2025-01-01T12:05:00Z");
    assert_eq!(steps[1].precip_mm, 0.3);
    assert_eq!(steps[2].precip_mm, 0.0);
    // the remaining 9 buckets have no radar frame yet -> dry
    assert!(steps[3..].iter().all(|s| s.precip_mm == 0.0));
}

#[test]
fn test_bar_ignores_cells_outside_radius() {
    // 0.5 mm 15 km away (outside the 5 km radius) must not show in the bar
    let nc = nowcast(
        vec![frame(0, vec![cell(5, 5, 0.1), cell(20, 5, 0.5)])],
        true,
    );
    let out = build_radar_next_hour_bar(Some(&nc), now(), 5.0, 1.0, 0.05, 12);
    assert_eq!(out.steps[0].precip_mm, 0.1); // only the local cell
}

#[test]
fn test_bar_ignores_below_threshold() {
    // 0.04 mm at the location is below the 0.05 mm threshold -> not rain
    let nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.04)])], true);
    let out = build_radar_next_hour_bar(Some(&nc), now(), 5.0, 1.0, 0.05, 12);
    assert_eq!(out.steps[0].precip_mm, 0.0);
}

#[test]
fn test_bar_floors_now_to_grid() {
    // now = 12:03 -> floored to 12:00; a frame at 12:00 lands in bucket 0
    let now = now() + TimeDelta::minutes(3);
    let nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.2)])], true); // frame at 12:00
    let out = build_radar_next_hour_bar(Some(&nc), now, 5.0, 1.0, 0.05, 12);
    assert_eq!(out.steps[0].start_utc, "2025-01-01T12:00:00Z");
    assert_eq!(out.steps[0].precip_mm, 0.2);
}

#[test]
fn test_bar_custom_step_count() {
    let nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.2)])], true);
    let out = build_radar_next_hour_bar(Some(&nc), now(), 5.0, 1.0, 0.05, 4);
    assert_eq!(out.steps.len(), 4);
    assert_eq!(out.steps[0].precip_mm, 0.2);
    assert!(out.steps[1..].iter().all(|s| s.precip_mm == 0.0));
}
