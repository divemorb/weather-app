//! Test-only payload builders, the Rust version of `tests/helpers.py`.
//! Everything here is compiled only under `#[cfg(test)]`, so it may unwrap.

pub mod fake_upstream;

use serde_json::{Map, Value, json};

/// A width x height grid filled with `value`.
pub fn grid(width: usize, height: usize, value: u16) -> Vec<Vec<u16>> {
    vec![vec![value; width]; height]
}

/// Encode a row-major uint16 grid like Bright Sky does (base64 of the
/// zlib-compressed little-endian bytes).
pub fn encode_grid(rows: &[Vec<u16>]) -> String {
    use base64::Engine;
    use std::io::Write;
    let bytes: Vec<u8> = rows
        .iter()
        .flatten()
        .flat_map(|v| v.to_le_bytes())
        .collect();
    let mut enc = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
    enc.write_all(&bytes).expect("writing to a Vec cannot fail");
    base64::engine::general_purpose::STANDARD
        .encode(enc.finish().expect("writing to a Vec cannot fail"))
}

/// A `/current_weather` payload; `weather` is merged over the default record
/// (Python `w.update(weather)`).
pub fn make_current_payload(weather: Option<Value>) -> Value {
    let mut w: Map<String, Value> = json!({
        "source_id": 96160,
        "timestamp": "2026-09-25T06:00:00+00:00",
        "condition": "dry",
        "dew_point": 3.5,
        "precipitation_10": 0.0,
        "precipitation_30": 0.4,
        "precipitation_60": 0.8,
        "pressure_msl": 1026.0,
        "relative_humidity": 87,
        "visibility": 34801,
        "wind_direction_10": 260,
        "wind_speed_10": 5.0,
        "wind_speed_60": 6.2,
        "wind_gust_speed_60": 11.0,
        "cloud_cover": 88,
        "temperature": 7.4,
        "fallback_source_ids": {"wind_speed_10": 11702},
    })
    .as_object()
    .expect("object literal")
    .clone();
    if let Some(Value::Object(extra)) = weather {
        for (key, value) in extra {
            w.insert(key, value);
        }
    }
    json!({"weather": Value::Object(w), "sources": []})
}

/// A `/weather` payload mirroring the real response shape: observation
/// station 1002 ("current") with a dry hour at 16:00, a null-precipitation
/// hour at 17:00 and 0.4 mm at 18:00; MOSMIX source 1001 ("forecast") with
/// 19:00 and 21:00 records that must never be treated as observations.
pub fn make_weather_payload(weather: Option<Value>, sources: Option<Value>) -> Value {
    let default_weather = json!([
        {"timestamp": "2026-09-27T16:00:00+00:00", "source_id": 1002, "precipitation": 0.0},
        {"timestamp": "2026-09-27T17:00:00+00:00", "source_id": 1002, "precipitation": null},
        {"timestamp": "2026-09-27T18:00:00+00:00", "source_id": 1002, "precipitation": 0.4},
        {"timestamp": "2026-09-27T19:00:00+00:00", "source_id": 1001, "precipitation": 1.2},
        {"timestamp": "2026-09-27T21:00:00+00:00", "source_id": 1001, "precipitation": 2.0},
    ]);
    let default_sources = json!([
        {"id": 1002, "observation_type": "current",
         "station_name": "BERLIN", "distance": 5000.0},
        {"id": 1001, "observation_type": "forecast",
         "station_name": "BERLIN", "distance": 3000.0},
    ]);
    json!({
        "weather": weather.unwrap_or(default_weather),
        "sources": sources.unwrap_or(default_sources),
    })
}

/// Assemble a `/radar` payload. `frames` are (timestamp, grid of raw uint16
/// values); each grid is encoded into `precipitation_5`.
pub fn make_radar_payload(
    frames: &[(&str, Vec<Vec<u16>>)],
    bbox: (i64, i64, i64, i64),
    latlon_position: (f64, f64),
) -> Value {
    let radar: Vec<Value> = frames
        .iter()
        .enumerate()
        .map(|(i, (timestamp, g))| {
            json!({
                "timestamp": timestamp,
                "source": format!("RADOLAN::RV::frame{i}"),
                "precipitation_5": encode_grid(g),
            })
        })
        .collect();
    json!({
        "radar": radar,
        "bbox": [bbox.0, bbox.1, bbox.2, bbox.3],
        "latlon_position": {"x": latlon_position.0, "y": latlon_position.1},
        "geometry": {"type": "Polygon", "coordinates": []},
    })
}

/// One row per model: (model name, its series of values).
type PerModel<'a> = [(&'a str, Vec<Value>)];

/// The extra hourly variables, each with one per-model table.
type ExtraHourly<'a> = [(&'a str, &'a PerModel<'a>)];

fn series<'a>(list: &'a PerModel<'a>, name: &str) -> &'a Vec<Value> {
    &list
        .iter()
        .find(|(n, _)| *n == name)
        .expect("test payload lists are complete")
        .1
}

/// An Open-Meteo multi-model forecast payload with suffixed keys.
pub fn make_forecast_payload(
    model_names: &[&str],
    hours: &[&str],
    min15: &[&str],
    precip_per_model: &PerModel<'_>,
    min15_precip_per_model: &PerModel<'_>,
    extra_hourly: &ExtraHourly<'_>,
) -> Value {
    let mut payload = json!({
        "latitude": 52.0,
        "longitude": 13.0,
        "timezone": "GMT",
        "minutely_15": {"time": min15},
        "hourly": {"time": hours},
    });
    for name in model_names {
        payload["minutely_15"][format!("precipitation_{name}")] =
            Value::Array(series(min15_precip_per_model, name).clone());
        payload["hourly"][format!("precipitation_{name}")] =
            Value::Array(series(precip_per_model, name).clone());
        for (var, per_model) in extra_hourly {
            payload["hourly"][format!("{var}_{name}")] =
                Value::Array(series(per_model, name).clone());
        }
    }
    payload
}

/// An Open-Meteo ensemble payload; the member keys are
/// `precipitation_member01`, …
pub fn make_ensemble_payload(hours: &[&str], control: Vec<Value>, members: &[Vec<Value>]) -> Value {
    let mut payload = json!({
        "latitude": 52.0,
        "longitude": 13.0,
        "timezone": "GMT",
        "hourly_units": {"precipitation": "mm"},
        "hourly": {"time": hours, "precipitation": control},
    });
    for (i, member) in members.iter().enumerate() {
        payload["hourly"][format!("precipitation_member{:02}", i + 1)] =
            Value::Array(member.clone());
    }
    payload
}
