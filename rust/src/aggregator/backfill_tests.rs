//! The hourly observation backfill fills only already-stored hours, is
//! triggered by the model refresh, never breaks a refresh and is a no-op
//! without observations.

use std::collections::HashMap;

use chrono::TimeDelta;
use serde_json::{Value, json};

use super::testkit::*;
use super::*;
use crate::config::LocationConfig;
use crate::stations::OBSERVATION_STATIONS_KEY;
use crate::times::Clock;

fn loc(latitude: f64, longitude: f64) -> LocationConfig {
    LocationConfig {
        latitude,
        longitude,
        timezone: "Europe/Berlin".to_string(),
        label: String::new(),
    }
}

/// /weather records around the frozen NOW = 2025-01-01 12:00.
///
/// Station 1002 is the "current" observation source; 1001 is the MOSMIX
/// "forecast" source. Stamps 09:00..15:00 cover hours 08:00..14:00
/// (a record stamped T holds the rain of [T-1h, T)).
fn weather_payload_around_now() -> Value {
    let recs: [(&str, i64, Option<f64>); 8] = [
        ("09:00", 1002, Some(0.5)), // hour 08:00-09:00
        ("10:00", 1002, None),      // missing precipitation -> skipped
        ("11:00", 1002, Some(0.0)), // hour 10:00-11:00 (dry)
        ("12:00", 1002, Some(1.3)), // stamped exactly NOW: kept (hour 11:00)
        ("12:00", 1001, Some(9.9)), // same hour, forecast source -> skipped
        ("13:00", 1002, Some(0.2)), // hour 12:00-13:00
        ("14:00", 1002, Some(2.2)), // hour 13:00-14:00
        ("15:00", 1002, Some(3.0)), // future at now=14:00 -> skipped
    ];
    let mut weather = Vec::with_capacity(recs.len());
    for (ts, sid, precip) in recs {
        weather.push(json!({
            "timestamp": format!("2025-01-01T{ts}:00Z"),
            "source_id": sid,
            "precipitation": precip.map(Value::from),
        }));
    }
    json!({
        "weather": weather,
        "sources": [
            {"id": 1002, "observation_type": "current",
             "station_name": "BERLIN", "distance": 5000.0},
            {"id": 1001, "observation_type": "forecast",
             "station_name": "BERLIN", "distance": 3000.0},
        ],
    })
}

/// `valid_from -> observed_mm` for all observed rows (both models carry the
/// same value per hour, so one entry per hour).
fn filled_hours(store: &Store) -> HashMap<String, f64> {
    let conn = store.lock_for_tests();
    let mut stmt = conn
        .prepare(
            "SELECT valid_from, observed_mm FROM forecast_history \
             WHERE observed_mm IS NOT NULL",
        )
        .unwrap();
    let rows = stmt
        .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, f64>(1)?)))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    let mut out = HashMap::new();
    for (valid_from, mm) in rows {
        assert_ne!(mm, 9.9, "the forecast-source value must never land");
        out.insert(valid_from, mm);
    }
    out
}

fn forecast_history_count(store: &Store) -> usize {
    let conn = store.lock_for_tests();
    let n: i64 = conn
        .query_row("SELECT COUNT(*) FROM forecast_history", [], |r| r.get(0))
        .unwrap();
    usize::try_from(n).unwrap()
}

#[tokio::test]
async fn backfill_observations_fills_matching_hours_only() {
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        weather: Some(weather_payload_around_now()),
        ..make_payloads()
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    // History rows are stored with valid_from >= issued_at, so an
    // observation (hour = stamp - 1h) only matches once its hour has
    // started. Freeze the clock at NOW, write history, then advance 2 h
    // (downtime catch-up) and backfill: only the stored hours 12:00 and
    // 13:00 are filled, by their own observations.
    agg.set_clock(Clock::fixed(now()));
    agg.refresh_models().await;
    // at NOW the kept stamps (09..12:00) fill hours 08..11:00, none stored
    assert!(filled_hours(agg.store()).is_empty());

    agg.set_clock(Clock::fixed(now() + TimeDelta::hours(2)));
    agg.backfill_observations().await;
    let filled = filled_hours(agg.store());
    // stamp 13:00 -> hour 12:00, stamp 14:00 -> hour 13:00; hour 11:00
    // (1.3) has no stored row (issued_at = 12:00) and must stay NULL
    assert_eq!(filled.len(), 2);
    assert_eq!(filled.get("2025-01-01T12:00:00Z"), Some(&0.2));
    assert_eq!(filled.get("2025-01-01T13:00:00Z"), Some(&2.2));
}

#[tokio::test]
async fn refresh_models_triggers_backfill() {
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        weather: Some(weather_payload_around_now()),
        ..make_payloads()
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.set_clock(Clock::fixed(now()));
    agg.refresh_models().await; // history rows written; no observation match yet
    assert!(filled_hours(agg.store()).is_empty());
    // the *next* hourly refresh (clock advanced) must run the backfill itself
    agg.set_clock(Clock::fixed(now() + TimeDelta::hours(2)));
    agg.refresh_models().await;
    assert_eq!(filled_hours(agg.store()).len(), 2); // hours 12:00 + 13:00
}

#[tokio::test]
async fn backfill_never_breaks_model_refresh() {
    // A failing /weather fetch must not break the model refresh: the
    // weather source is not served, so the fake answers 404.
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.set_clock(Clock::fixed(now()));
    agg.refresh_models().await; // stub fails: no 'weather' payload configured
    assert_eq!(forecast_history_count(agg.store()), 48); // history still written
    assert!(filled_hours(agg.store()).is_empty());
}

#[tokio::test]
async fn backfill_without_observations_is_noop() {
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        weather: Some(json!({"weather": [], "sources": []})),
        ..make_payloads()
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.set_clock(Clock::fixed(now()));
    agg.backfill_observations().await; // must not raise
    assert!(filled_hours(agg.store()).is_empty());
}

// observation stations: stored on success, kept otherwise

#[tokio::test]
async fn failed_or_empty_backfill_keeps_the_stations() {
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        weather: Some(weather_payload_around_now()),
        ..make_payloads()
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.set_clock(Clock::fixed(now()));
    agg.backfill_observations().await;
    let stored = agg
        .store()
        .get_meta(OBSERVATION_STATIONS_KEY)
        .unwrap()
        .expect("the backfill with observations stored the stations");

    // a backfill without any observation leaves the list as it was
    let only_forecast = json!({
        "weather": [
            {"timestamp": "2025-01-01T12:00:00Z", "source_id": 1001, "precipitation": 1.0}
        ],
        "sources": [
            {"id": 1001, "observation_type": "forecast",
             "station_name": "BERLIN", "distance": 3000.0}
        ],
    });
    fake.set("/bs/weather", FakeResponse::Json(only_forecast));
    agg.backfill_observations().await;
    assert_eq!(
        agg.store().get_meta(OBSERVATION_STATIONS_KEY).unwrap(),
        Some(stored.clone()),
        "an empty backfill must keep the stored stations"
    );

    // and so does a failing fetch
    fake.set("/bs/weather", FakeResponse::Status(500));
    agg.backfill_observations().await;
    assert_eq!(
        agg.store().get_meta(OBSERVATION_STATIONS_KEY).unwrap(),
        Some(stored),
        "a failing backfill must keep the stored stations"
    );
}

#[tokio::test]
async fn moving_clears_the_stations_the_same_place_keeps_them() {
    // The stations belong to the old location: a far move deletes them with
    // the cache and the history, a move within ~1 km keeps them.
    let fake = FakeUpstream::start();
    let payloads = Payloads {
        weather: Some(weather_payload_around_now()),
        ..make_payloads()
    };
    serve(&fake, &payloads, &[]);
    let agg = make_aggregator(make_cfg(&fake, CfgOpts::default()), memory_store());

    agg.set_clock(Clock::fixed(now()));
    agg.backfill_observations().await;
    let stored = agg
        .store()
        .get_meta(OBSERVATION_STATIONS_KEY)
        .unwrap()
        .expect("the backfill stored the stations");

    agg.set_location(loc(52.001, 13.001)).unwrap(); // make_cfg: 52.0/13.0
    assert_eq!(
        agg.store().get_meta(OBSERVATION_STATIONS_KEY).unwrap(),
        Some(stored.clone()),
        "a near move keeps the stored stations"
    );

    agg.set_location(loc(48.137, 11.575)).unwrap(); // Munich: far away
    assert_eq!(
        agg.store().get_meta(OBSERVATION_STATIONS_KEY).unwrap(),
        None,
        "a far move clears the stored stations"
    );
}
