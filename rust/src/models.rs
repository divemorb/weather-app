//! Normalized data models shared by the parsers, the logic and the
//! serializers (Python `app/models.py`).

use chrono::{DateTime, Utc};
use serde_json::Value;

/// The "Now" tile (Bright Sky `/current_weather`). The `Value` fields are
/// passed through from the upstream JSON untouched; `Value::Null` when missing.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct CurrentConditions {
    pub timestamp_utc: Value,
    pub source_id: Value,
    pub temperature_c: Option<f64>,
    pub feels_like_c: Option<f64>,
    pub wind_speed_ms: Option<f64>,
    pub wind_direction_deg: Option<f64>,
    pub wind_gust_ms: Option<f64>,
    pub cloud_cover_pct: Option<f64>,
    pub humidity_pct: Option<f64>,
    pub pressure_hpa: Option<f64>,
    pub dew_point_c: Option<f64>,
    pub precipitation_10mm: Option<f64>,
    pub precipitation_30mm: Option<f64>,
    pub precipitation_60mm: Option<f64>,
    pub condition: Value,
    /// Bright Sky's weather icon for the page's animated sky: one of the
    /// twelve values Bright Sky documents, `None` when absent or unknown.
    pub icon: Option<String>,
}

/// One raining grid cell (value already in millimetres).
#[derive(Clone, Debug, PartialEq)]
pub struct RadarCell {
    pub x: i64,
    pub y: i64,
    pub mm: f64,
}

/// One 5-minute step of the radar nowcast.
#[derive(Clone, Debug, PartialEq)]
pub struct RadarFrame {
    pub time_utc: DateTime<Utc>,
    pub cells: Vec<RadarCell>,
    pub max_mm: f64,
}

/// 5-minute frames, oldest first. `bbox` = (top, left, bottom, right);
/// `location_xy` = (x, y) of the location inside the sub-grid.
#[derive(Clone, Debug, PartialEq)]
pub struct RadarNowcast {
    pub frames: Vec<RadarFrame>,
    pub covered: bool,
    pub grid_width: i64,
    pub grid_height: i64,
    pub bbox: (i64, i64, i64, i64),
    pub location_xy: (f64, f64),
}

/// One Open-Meteo model's series (the lists may be shorter or longer than
/// the time axis, exactly as the upstream sent them).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ModelSeries {
    pub name: String,
    pub min15_time: Vec<DateTime<Utc>>,
    pub min15_precip_mm: Vec<Option<f64>>,
    pub hourly_time: Vec<DateTime<Utc>>,
    pub hourly_precip_mm: Vec<Option<f64>>,
    pub hourly_temp_c: Vec<Option<f64>>,
    pub hourly_apparent_c: Vec<Option<f64>>,
    pub hourly_wind_kmh: Vec<Option<f64>>,
    pub hourly_cloud_cover_pct: Vec<Option<f64>>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ForecastBundle {
    pub models: Vec<ModelSeries>,
}

impl ForecastBundle {
    pub fn by_name(&self, name: &str) -> Option<&ModelSeries> {
        self.models.iter().find(|m| m.name == name)
    }
}

/// Ensemble precipitation (mm per hour): control run + members.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct EnsembleData {
    pub hourly_time: Vec<DateTime<Utc>>,
    pub control_precip_mm: Vec<Option<f64>>,
    pub member_precip_mm: Vec<Vec<Option<f64>>>,
}

impl EnsembleData {
    pub fn n_members(&self) -> usize {
        self.member_precip_mm.len()
    }
}

/// One model's vote on rain in the next 60 minutes.
#[derive(Clone, Debug, PartialEq)]
pub struct ModelVote {
    pub name: String,
    pub precip_next_hour_mm: Option<f64>,
}

/// Ensemble rain probability: share of members > threshold (0..100).
#[derive(Clone, Debug, PartialEq)]
pub struct EnsembleVote {
    pub probability_pct: Option<f64>,
    pub n_members: usize,
    pub n_rain_members: usize,
}

/// Combined next-hour rain probability + human-readable derivation.
/// `weights_used` keeps Python's key order (radar, models, ensemble).
#[derive(Clone, Debug, PartialEq)]
pub struct RainProbability {
    pub probability_pct: f64,
    pub radar_available: bool,
    pub radar_raining: Option<bool>,
    pub models_rain_count: usize,
    pub models_total: usize,
    pub ensemble_pct: Option<f64>,
    pub weights_used: Vec<(String, f64)>,
    pub explanation: String,
    /// True only when the accuracy weights were applied (the gate passed).
    pub accuracy_weighted: bool,
}
