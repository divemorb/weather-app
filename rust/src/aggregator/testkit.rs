//! Test helpers for the aggregator (the Rust version of
//! `tests/aggregator_support.py`): the fixed instant, the payload builders,
//! the canned-upstream wiring and the aggregator builder. Compiled only
//! under `#[cfg(test)]`, so it may expect.

use chrono::{DateTime, TimeDelta, Utc};
use serde_json::{Value, json};

use crate::clients::{BrightSkyClient, OpenMeteoClient};
use crate::config::{
    AccuracyConfig, AppConfig, LocationConfig, ModelsConfig, ProbabilityConfig, RadarConfig,
    SchedulingConfig,
};
use crate::store::{Source, Store};
use crate::times;

/// Re-exported so tests can write `use super::testkit::*;` only.
pub use crate::testutil::fake_upstream::{FakeResponse, FakeUpstream};

/// Python `NOW` in `tests/aggregator_support.py`.
pub const NOW: &str = "2025-01-01T12:00:00Z";

/// The fixed test instant (the aggregator's clock starts here).
pub fn now() -> DateTime<Utc> {
    times::parse_iso(NOW).expect("the fixed test instant parses")
}

/// One radar frame: (timestamp, [(x, y, raw 0.01 mm)]).
type Frame<'a> = (&'a str, &'a [(i64, i64, u16)]);

/// Bright Sky `/radar` payload; `frames` are (iso, [(x, y, raw 0.01 mm)]).
pub fn radar_payload(frames: &[Frame<'_>]) -> Value {
    const W: usize = 10;
    let mut out = Vec::new();
    for (iso, cells) in frames {
        let mut rows: Vec<Vec<u16>> = vec![vec![0; W]; W];
        for &(x, y, value) in *cells {
            let x = usize::try_from(x).expect("test grid coordinate fits");
            let y = usize::try_from(y).expect("test grid coordinate fits");
            let row = rows.get_mut(y).expect("test grid coordinate fits");
            *row.get_mut(x).expect("test grid coordinate fits") = value;
        }
        out.push(json!({
            "timestamp": iso,
            "precipitation_5": crate::testutil::encode_grid(&rows),
        }));
    }
    json!({
        "radar": out,
        "bbox": [0, 0, 9, 9],
        "latlon_position": {"x": 5.0, "y": 5.0},
    })
}

/// Bright Sky `/current_weather` payload (5 °C, raining).
pub fn current_payload() -> Value {
    json!({
        "weather": {
            "timestamp": "2025-01-01T12:00:00Z",
            "source_id": 1,
            "temperature": 5.0,
            "wind_speed_10": 3.0,
            "wind_direction_10": 180.0,
            "wind_gust_speed_60": 6.0,
            "cloud_cover": 75.0,
            "relative_humidity": 80.0,
            "pressure_msl": 1015.0,
            "dew_point": 3.0,
            "precipitation_10": 0.0,
            "precipitation_30": 0.1,
            "precipitation_60": 0.2,
            "condition": "Rain",
        }
    })
}

/// icon_d2 rains 0.4 mm in the next hour; icon_eu stays dry; gfs null.
///
/// The minutely_15 steps are stamped 12:15..13:00, i.e. strictly inside
/// `[NOW, NOW+1h)` (a minutely_15 value at t covers [t-15min, t)), so at
/// now = 12:00 all four steps fall in the next-hour window.
///
/// The hourly axis is stamped NOW..NOW+71h (3-day fetch): with now = 12:00
/// the first *future* stamp is 13:00 (rain of 12:00-13:00), so icon_d2's
/// 0.4 mm lands in the chart's first hour (labelled 12:00) and in the
/// next-hour sum. gfs carries all-null precipitation to cover the "model
/// with null data is skipped" path.
pub fn forecast_payload() -> Value {
    let m15: Vec<String> = (0..4)
        .map(|i| times::to_iso(now() + TimeDelta::minutes(15 + 15 * i as i64)))
        .collect();
    let h72: Vec<String> = (0..72)
        .map(|i| times::to_iso(now() + TimeDelta::hours(i as i64)))
        .collect();
    let mut icon_d2 = vec![0.0; 72];
    *icon_d2.get_mut(1).expect("hourly axis has 72 entries") = 0.4;
    json!({
        "minutely_15": {
            "time": m15,
            "precipitation_icon_d2": [0.1, 0.1, 0.1, 0.1],
            "precipitation_icon_eu": [0.0, 0.0, 0.0, 0.0],
        },
        "hourly": {
            "time": h72,
            "precipitation_icon_d2": icon_d2,
            "precipitation_icon_eu": vec![0.0_f64; 72],
            "precipitation_gfs": vec![Value::Null; 72],
            "temperature_2m_icon_d2": vec![5.0_f64; 72],
            "apparent_temperature_icon_d2": vec![3.5_f64; 72],
            "wind_speed_10m_icon_d2": vec![10.0_f64; 72],
            "cloud_cover_icon_d2": vec![70.0_f64; 72],
            "temperature_2m_icon_eu": vec![4.0_f64; 72],
            "apparent_temperature_icon_eu": vec![2.0_f64; 72],
            "wind_speed_10m_icon_eu": vec![8.0_f64; 72],
            "cloud_cover_icon_eu": vec![60.0_f64; 72],
        },
    })
}

/// member01 rains (1 mm) in the next hour; member02 stays dry. The steps
/// are stamped 13:00..16:00, so at now = 12:00 the first step after now
/// (13:00, covering 12:00-13:00) is the next hour.
pub fn ensemble_payload() -> Value {
    let h4: Vec<String> = (0..4)
        .map(|i| times::to_iso(now() + TimeDelta::hours(1 + i as i64)))
        .collect();
    json!({
        "hourly": {
            "time": h4,
            "precipitation": [0.5, 0.0, 0.0, 0.0],
            "precipitation_member01": [1.0, 0.0, 0.0, 0.0],
            "precipitation_member02": [0.0, 0.0, 0.0, 0.0],
        }
    })
}

/// The four (or five) cached payloads (Python `make_payloads`).
pub struct Payloads {
    pub current: Option<Value>,
    pub radar: Option<Value>,
    pub forecast: Option<Value>,
    pub ensemble: Option<Value>,
    pub weather: Option<Value>,
}

/// All four cache payloads (same as Python's `all_payloads` fixture).
pub fn make_payloads() -> Payloads {
    Payloads {
        current: Some(current_payload()),
        radar: Some(radar_payload(&[("2025-01-01T12:00:00Z", &[(5, 5, 20)])])),
        forecast: Some(forecast_payload()),
        ensemble: Some(ensemble_payload()),
        weather: None,
    }
}

/// Wire the fake upstream: each set payload goes to its path; a source
/// named in `errors` answers HTTP 500 instead. An unset source is left
/// unrouted (the fake answers 404, which is a `SourceError`).
pub fn serve(fake: &FakeUpstream, payloads: &Payloads, errors: &[Source]) {
    for (source, path, payload) in [
        (
            Source::Current,
            "/bs/current_weather",
            payloads.current.as_ref(),
        ),
        (Source::Radar, "/bs/radar", payloads.radar.as_ref()),
        (
            Source::Forecast,
            "/om/v1/forecast",
            payloads.forecast.as_ref(),
        ),
        (
            Source::Ensemble,
            "/ens/v1/ensemble",
            payloads.ensemble.as_ref(),
        ),
    ] {
        if let Some(value) = payload {
            let response = if errors.contains(&source) {
                FakeResponse::Status(500)
            } else {
                FakeResponse::Json(value.clone())
            };
            fake.set(path, response);
        }
    }
    if let Some(value) = &payloads.weather {
        fake.set("/bs/weather", FakeResponse::Json(value.clone()));
    }
}

/// The options Python `make_cfg` takes.
pub struct CfgOpts {
    pub stale_radar: i64,
    pub stale_models: i64,
    pub use_accuracy_weights: bool,
    pub min_samples: i64,
    pub location: Option<LocationConfig>,
}

impl Default for CfgOpts {
    fn default() -> Self {
        Self {
            stale_radar: 10,
            stale_models: 120,
            use_accuracy_weights: false,
            min_samples: 48,
            location: Some(LocationConfig {
                latitude: 52.0,
                longitude: 13.0,
                timezone: "Europe/Berlin".to_string(),
                label: String::new(),
            }),
        }
    }
}

/// Python `make_cfg`: the app defaults plus the fixed test values and the
/// fake upstream's URLs.
pub fn make_cfg(fake: &FakeUpstream, opts: CfgOpts) -> AppConfig {
    let mut cfg = crate::config::load_config(None, &|_| None).expect("the defaults load");
    let base = fake.base.clone();
    cfg.location = opts.location;
    cfg.radar = RadarConfig {
        radius_km: 5.0,
        grid_size_km: 1.0,
        step_minutes: 5,
    };
    cfg.probability = ProbabilityConfig {
        weight_radar: 0.5,
        weight_models: 0.3,
        weight_ensemble: 0.2,
        model_rain_threshold_mm: 0.1,
        radar_cell_rain_threshold_mm: 0.05,
    };
    cfg.models = ModelsConfig {
        forecast: vec!["icon_d2".to_string(), "icon_eu".to_string()],
        ensemble_model: "ecmwf_ifs025".to_string(),
    };
    cfg.scheduling = SchedulingConfig {
        stale_radar_minutes: opts.stale_radar,
        stale_models_minutes: opts.stale_models,
        ..SchedulingConfig::default()
    };
    cfg.accuracy = AccuracyConfig {
        min_samples: opts.min_samples,
        ..AccuracyConfig::default()
    };
    cfg.use_accuracy_weights = opts.use_accuracy_weights;
    cfg.api.brightsky_base_url = format!("{base}/bs");
    cfg.api.open_meteo_base_url = format!("{base}/om/v1");
    cfg.api.ensemble_base_url = format!("{base}/ens/v1");
    cfg.api.nominatim_base_url = format!("{base}/nom");
    cfg
}

/// The aggregator over the fake upstream: both clients built from `cfg`, a
/// 5 s timeout and the fixed clock at `NOW`.
pub fn make_aggregator(cfg: AppConfig, store: Store) -> super::Aggregator {
    let http = crate::upstream::http_client(5.0).expect("the http client builds");
    let brightsky = BrightSkyClient::new(&cfg, http.clone());
    let openmeteo = OpenMeteoClient::new(&cfg, http);
    super::Aggregator::new(cfg, store, brightsky, openmeteo, times::Clock::fixed(now()))
}

/// Python's in-memory test store.
pub fn memory_store() -> Store {
    Store::open(":memory:").expect("the in-memory store opens")
}
