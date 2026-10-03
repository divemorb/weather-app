//! HTTP-layer tests for the upstream clients.

use super::*;
use chrono::{DateTime, Utc};

use crate::config::{
    AccuracyConfig, ApiConfig, AppConfig, LocationConfig, ModelsConfig, ProbabilityConfig,
    RadarConfig, SchedulingConfig,
};
use crate::testutil::fake_upstream::FakeUpstream;

/// A config pointed at the fake upstream (paths `/bs`, `/om/v1`, `/ens/v1`).
fn make_cfg(fake: &FakeUpstream) -> AppConfig {
    AppConfig {
        location: Some(LocationConfig {
            latitude: 52.0,
            longitude: 13.0,
            timezone: "Europe/Berlin".to_string(),
            label: String::new(),
        }),
        radar: RadarConfig::default(),
        probability: ProbabilityConfig::default(),
        models: ModelsConfig {
            forecast: ["icon_d2", "icon_eu"].map(str::to_string).to_vec(),
            ensemble_model: "ecmwf_ifs025".to_string(),
        },
        scheduling: SchedulingConfig::default(),
        accuracy: AccuracyConfig::default(),
        api: ApiConfig {
            brightsky_base_url: format!("{}/bs", fake.base),
            open_meteo_base_url: format!("{}/om/v1", fake.base),
            ensemble_base_url: format!("{}/ens/v1", fake.base),
            nominatim_base_url: String::new(),
            timeout_seconds: 10.0,
        },
        database_path: ":memory:".to_string(),
        use_accuracy_weights: false,
    }
}

fn http() -> reqwest::Client {
    upstream::http_client(10.0).expect("building the test client")
}

fn brightsky(fake: &FakeUpstream) -> BrightSkyClient {
    BrightSkyClient::new(&make_cfg(fake), http())
}

fn openmeteo(fake: &FakeUpstream) -> OpenMeteoClient {
    OpenMeteoClient::new(&make_cfg(fake), http())
}

fn stamp(s: &str) -> DateTime<Utc> {
    times::parse_iso(s).expect("test stamps are valid")
}

mod brightsky;
mod openmeteo;
