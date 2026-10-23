//! The app meta rows (the stored location), and clearing the location's
//! data on a location change: the cache and the history go, the meta stays.

use serde_json::json;

use super::tests::{db_path, fresh_store, row, rows};
use super::*;

#[test]
fn meta_round_trip_and_missing_key() {
    let (_dir, store) = fresh_store();
    assert_eq!(store.get_meta("location").unwrap(), None);
    store.set_meta("location", "{\"latitude\": 52.0}").unwrap();
    assert_eq!(
        store.get_meta("location").unwrap().as_deref(),
        Some("{\"latitude\": 52.0}")
    );
    store.set_meta("location", "{\"latitude\": 52.52}").unwrap();
    assert_eq!(
        store.get_meta("location").unwrap().as_deref(),
        Some("{\"latitude\": 52.52}")
    );
}

#[test]
fn meta_persists_across_connections() {
    let dir = tempfile::tempdir().unwrap();
    let db = db_path(&dir);
    {
        let store = Store::open(&db).unwrap();
        store
            .set_meta("location", "{\"latitude\": 52.0, \"longitude\": 13.0}")
            .unwrap();
    }
    let store = Store::open(&db).unwrap();
    assert_eq!(
        store.get_meta("location").unwrap().as_deref(),
        Some("{\"latitude\": 52.0, \"longitude\": 13.0}")
    );
}

#[test]
fn clear_location_data_wipes_cache_and_history_only() {
    let (_dir, store) = fresh_store();
    let now = times::parse_iso("2025-01-01T12:00:00Z").unwrap();
    store
        .put_cache(Source::Radar, &json!({"radar": []}), now)
        .unwrap();
    store
        .put_cache(Source::Current, &json!({"weather": {}}), now)
        .unwrap();
    store
        .add_forecasts(&[
            row(
                "icon_d2",
                "2025-01-01T11:00:00Z",
                "2025-01-01T12:00:00Z",
                0.5,
            ),
            row(
                "icon_eu",
                "2025-01-01T11:00:00Z",
                "2025-01-01T12:00:00Z",
                0.2,
            ),
        ])
        .unwrap();
    store.set_observation("2025-01-01T12:00:00Z", 0.3).unwrap();
    store
        .set_meta("location", "{\"latitude\": 52.0, \"longitude\": 13.0}")
        .unwrap();

    store.clear_location_data().unwrap();

    assert!(store.get_cache(Source::Radar, now).unwrap().is_none());
    assert!(store.get_cache(Source::Current, now).unwrap().is_none());
    assert_eq!(
        rows(&store),
        &[] as &[(String, String, String, String, f64, Option<f64>)]
    );
    // the stored location itself must survive a location change
    assert_eq!(
        store.get_meta("location").unwrap().as_deref(),
        Some("{\"latitude\": 52.0, \"longitude\": 13.0}")
    );
}
