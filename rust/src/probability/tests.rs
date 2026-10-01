use super::*;
use crate::config::{ProbabilityConfig, RadarConfig};
use crate::models::{ForecastBundle, ModelSeries, ModelVote, RadarCell, RadarFrame, RadarNowcast};
use crate::times::parse_iso;
use chrono::{DateTime, TimeDelta, Utc};

/// The Python tests' `NOW` constant: 2025-01-01 12:00 UTC (already on the
/// hour, so it doubles as the `_series` base).
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

const RADAR: RadarConfig = RadarConfig {
    radius_km: 5.0,
    grid_size_km: 1.0,
    step_minutes: 5,
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

fn cell(x: i64, y: i64, mm: f64) -> RadarCell {
    RadarCell { x, y, mm }
}

fn frame(offset_min: i64, cells: Vec<RadarCell>) -> RadarFrame {
    RadarFrame {
        time_utc: now() + TimeDelta::minutes(offset_min),
        max_mm: cells.iter().map(|c| c.mm).fold(0.0_f64, f64::max),
        cells,
    }
}

/// `RadarNowcast` with the Python helper defaults: bbox (0, 0, 10, 10),
/// location (5.0, 5.0), covered.
fn nowcast(frames: Vec<RadarFrame>) -> RadarNowcast {
    RadarNowcast {
        frames,
        covered: true,
        grid_width: 0,
        grid_height: 0,
        bbox: (0, 0, 10, 10),
        location_xy: (5.0, 5.0),
    }
}

fn series(name: &str, min15: &[Option<f64>], hourly: &[Option<f64>]) -> ModelSeries {
    let base = now();
    ModelSeries {
        name: name.to_string(),
        min15_time: (0..min15.len())
            .map(|i| base + TimeDelta::minutes(15 * i as i64))
            .collect(),
        min15_precip_mm: min15.to_vec(),
        hourly_time: (0..hourly.len())
            .map(|i| base + TimeDelta::hours(i as i64))
            .collect(),
        hourly_precip_mm: hourly.to_vec(),
        hourly_temp_c: Vec::new(),
        hourly_apparent_c: Vec::new(),
        hourly_wind_kmh: Vec::new(),
        hourly_cloud_cover_pct: Vec::new(),
    }
}

// ---------------------------------------------------------------------------
// geometry
// ---------------------------------------------------------------------------
#[test]
fn cell_distance_zero_at_location() {
    let nc = nowcast(vec![frame(0, vec![])]); // loc at (5, 5)
    assert_eq!(cell_distance_km(&nc, 5, 5, 1.0), 0.0);
}

#[test]
fn cell_distance_east_is_km() {
    let nc = nowcast(vec![frame(0, vec![])]);
    // 3 cells east, 1 km each -> 3 km
    assert!(approx(cell_distance_km(&nc, 8, 5, 1.0), 3.0));
}

#[test]
fn cell_distance_diagonal() {
    let nc = nowcast(vec![frame(0, vec![])]);
    // 3 east, 4 north -> 5 km (3-4-5 triangle)
    assert!(approx(cell_distance_km(&nc, 8, 9, 1.0), 5.0));
}

#[test]
fn cell_distance_uses_cell_size() {
    let nc = nowcast(vec![frame(0, vec![])]);
    assert!(approx(cell_distance_km(&nc, 6, 5, 2.0), 2.0));
}

// ---------------------------------------------------------------------------
// max local rain per frame (feeds the next-hour bar)
// ---------------------------------------------------------------------------
#[test]
fn max_local_rain_strongest_in_radius() {
    let nc = nowcast(vec![frame(0, vec![])]);
    let frame = frame(0, vec![cell(5, 5, 0.1), cell(6, 5, 0.3), cell(5, 6, 0.2)]);
    assert!(approx(max_local_rain_mm(&nc, &frame, 5.0, 1.0, 0.05), 0.3));
}

#[test]
fn max_local_rain_ignores_outside_radius() {
    let nc = nowcast(vec![frame(0, vec![])]);
    // 0.5 mm at (20,5) is 15 km away (> 5 km radius); 0.2 at location stays
    let frame = frame(0, vec![cell(5, 5, 0.2), cell(20, 5, 0.5)]);
    assert!(approx(max_local_rain_mm(&nc, &frame, 5.0, 1.0, 0.05), 0.2));
}

#[test]
fn max_local_rain_ignores_below_threshold() {
    let nc = nowcast(vec![frame(0, vec![])]);
    // 0.04 <= threshold 0.05 must not count even though it's at the location
    let frame = frame(0, vec![cell(5, 5, 0.04)]);
    assert_eq!(max_local_rain_mm(&nc, &frame, 5.0, 1.0, 0.05), 0.0);
}

#[test]
fn max_local_rain_empty_frame_is_zero() {
    let nc = nowcast(vec![frame(0, vec![])]);
    assert_eq!(
        max_local_rain_mm(&nc, &frame(0, vec![]), 5.0, 1.0, 0.05),
        0.0
    );
}

// ---------------------------------------------------------------------------
// radar signal
// ---------------------------------------------------------------------------
#[test]
fn radar_rain_when_cell_in_radius_exceeds_threshold() {
    let nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.2)])]); // at location, 0.2 > 0.05
    let (available, raining) =
        radar_rain_signal(Some(&nc), now(), &RADAR, &PROB, TimeDelta::hours(1));
    assert!(available);
    assert_eq!(raining, Some(true));
}

#[test]
fn radar_no_rain_when_cell_below_threshold() {
    let nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.03)])]); // 0.03 <= 0.05
    let (available, raining) =
        radar_rain_signal(Some(&nc), now(), &RADAR, &PROB, TimeDelta::hours(1));
    assert!(available);
    assert_eq!(raining, Some(false));
}

#[test]
fn radar_ignores_cell_outside_radius() {
    let nc = nowcast(vec![frame(0, vec![cell(20, 5, 0.5)])]); // 15 km east > 5 km radius
    let (_, raining) = radar_rain_signal(Some(&nc), now(), &RADAR, &PROB, TimeDelta::hours(1));
    assert_eq!(raining, Some(false));
}

#[test]
fn radar_ignores_frame_outside_horizon() {
    // rain in a frame 2 h out (beyond the 1 h nowcast window) must be ignored
    let nc = nowcast(vec![frame(120, vec![cell(5, 5, 0.5)])]);
    let (_, raining) = radar_rain_signal(Some(&nc), now(), &RADAR, &PROB, TimeDelta::hours(1));
    assert_eq!(raining, Some(false));
}

#[test]
fn radar_ignores_past_frame() {
    // a frame stamped in the past (stale cache) must not count
    let nc = nowcast(vec![RadarFrame {
        time_utc: now() - TimeDelta::minutes(5),
        cells: vec![cell(5, 5, 0.5)],
        max_mm: 0.5,
    }]);
    let (_, raining) = radar_rain_signal(Some(&nc), now(), &RADAR, &PROB, TimeDelta::hours(1));
    assert_eq!(raining, Some(false));
}

#[test]
fn radar_unavailable_when_not_covered() {
    let mut nc = nowcast(vec![frame(0, vec![cell(5, 5, 0.5)])]);
    nc.covered = false;
    let (available, raining) =
        radar_rain_signal(Some(&nc), now(), &RADAR, &PROB, TimeDelta::hours(1));
    assert!(!available);
    assert_eq!(raining, None);
}

#[test]
fn radar_unavailable_when_none_or_empty() {
    assert_eq!(
        radar_rain_signal(None, now(), &RADAR, &PROB, TimeDelta::hours(1)),
        (false, None)
    );
    assert_eq!(
        radar_rain_signal(
            Some(&nowcast(vec![])),
            now(),
            &RADAR,
            &PROB,
            TimeDelta::hours(1)
        ),
        (false, None)
    );
}

#[test]
fn radar_has_local_rain_scans_all_frames() {
    // dry now, rain at +10 min within radius
    let nc = nowcast(vec![frame(0, vec![]), frame(10, vec![cell(6, 5, 0.3)])]);
    assert!(radar_has_local_rain(
        &nc,
        now(),
        TimeDelta::hours(1),
        5.0,
        1.0,
        0.05
    ));
}

// ---------------------------------------------------------------------------
// model votes
// ---------------------------------------------------------------------------
#[test]
fn sum_next_hour_skips_step_stamped_at_now() {
    // minutely_15 value at t covers [t-15min, t): the step stamped NOW
    // (11:45-12:00) is the past quarter hour, so the window [NOW, NOW+1h)
    // is the four steps stamped 12:15..13:00.
    let t: Vec<DateTime<Utc>> = (0..5)
        .map(|i| now() + TimeDelta::minutes(15 * i as i64))
        .collect();
    let v: Vec<Option<f64>> = [1.0, 2.0, 3.0, 4.0, 99.0].into_iter().map(Some).collect();
    // 1.0 is the past step -> not summed
    assert!(approx(
        sum_next_hour(&t, &v, now()).unwrap(),
        2.0 + 3.0 + 4.0 + 99.0
    ));
}

#[test]
fn sum_next_hour_none_on_missing_value() {
    let t: Vec<DateTime<Utc>> = (0..4)
        .map(|i| now() + TimeDelta::minutes(15 * i as i64))
        .collect();
    let v = vec![Some(1.0), None, Some(3.0), Some(4.0)];
    assert_eq!(sum_next_hour(&t, &v, now()), None);
}

#[test]
fn sum_next_hour_none_when_no_step_in_window() {
    // series already stale (all steps before now)
    let t: Vec<DateTime<Utc>> = (0..4)
        .map(|i| now() - TimeDelta::hours(1) + TimeDelta::minutes(15 * i as i64))
        .collect();
    let v: Vec<Option<f64>> = vec![Some(1.0); 4];
    assert_eq!(sum_next_hour(&t, &v, now()), None);
}

#[test]
fn sum_next_hour_empty_is_none() {
    let t: Vec<DateTime<Utc>> = vec![];
    let v: Vec<Option<f64>> = vec![];
    assert_eq!(sum_next_hour(&t, &v, now()), None);
}

#[test]
fn model_votes_per_model() {
    // steps are stamped NOW..NOW+45min; the step stamped NOW covers the past
    // 15 minutes, so the window [NOW, NOW+1h) is the last three steps.
    let bundle = ForecastBundle {
        models: vec![
            series("a", &[Some(1.0); 4], &[]), // 1+1+1 = 3.0 mm in window
            series("b", &[Some(0.0); 4], &[]), // 0.0 mm
            series("c", &[Some(1.0), Some(1.0), None, Some(1.0)], &[]), // None in window -> missing
        ],
    };
    let votes = model_votes(Some(&bundle), now());
    let names: Vec<&str> = votes.iter().map(|v| v.name.as_str()).collect();
    assert_eq!(names, vec!["a", "b", "c"]);
    assert!(approx(votes[0].precip_next_hour_mm.unwrap(), 3.0));
    assert!(approx(votes[1].precip_next_hour_mm.unwrap(), 0.0));
    assert_eq!(votes[2].precip_next_hour_mm, None);
}

#[test]
fn model_votes_none_bundle() {
    assert!(model_votes(None, now()).is_empty());
}

#[test]
fn model_rain_signal_share() {
    let votes = vec![
        ModelVote {
            name: "a".into(),
            precip_next_hour_mm: Some(0.5),
        }, // rain
        ModelVote {
            name: "b".into(),
            precip_next_hour_mm: Some(0.0),
        }, // dry
        ModelVote {
            name: "c".into(),
            precip_next_hour_mm: Some(2.0),
        }, // rain
        ModelVote {
            name: "d".into(),
            precip_next_hour_mm: None,
        }, // doesn't count
    ];
    let (share, n_rain, n_total) = model_rain_signal(&votes, 0.1);
    assert_eq!(n_total, 3);
    assert_eq!(n_rain, 2);
    assert!(approx(share.unwrap(), 200.0 / 3.0));
}

#[test]
fn model_rain_signal_all_missing() {
    let votes = vec![ModelVote {
        name: "a".into(),
        precip_next_hour_mm: None,
    }];
    let (share, n_rain, n_total) = model_rain_signal(&votes, 0.1);
    assert_eq!(share, None);
    assert_eq!((n_rain, n_total), (0, 0));
}

#[test]
fn model_rain_signal_boundary_at_threshold() {
    // exactly == threshold is NOT rain (strict >)
    let votes = vec![ModelVote {
        name: "a".into(),
        precip_next_hour_mm: Some(0.1),
    }];
    let (_, n_rain, _) = model_rain_signal(&votes, 0.1);
    assert_eq!(n_rain, 0);
}
