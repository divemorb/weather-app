//! Tests for the SQLite store: forecast-history upserts + schema migration.
//!
//! Uses a real SQLite database on disk (``tempdir``, Python's ``tmp_path``)
//! so the one-time migration (tracked in ``app_meta``) is exercised across
//! separate ``open()`` calls, as it happens across real app restarts.

use super::*;
use rusqlite::OptionalExtension;
use serde_json::json;

/// One `forecast_history` row (Python's `_row` dict).
fn row(model: &str, issued_at: &str, valid_from: &str, precip_mm: f64) -> HistoryRow {
    HistoryRow {
        model: model.to_string(),
        issued_at: issued_at.to_string(),
        valid_from: valid_from.to_string(),
        valid_to: "2025-01-01T13:00:00Z".to_string(),
        precip_mm,
    }
}

/// Python's `_rows(store)`: all forecast_history rows in stable order
/// `(model, issued_at, valid_from, valid_to, precip_mm, observed_mm)`.
fn rows(store: &Store) -> Vec<(String, String, String, String, f64, Option<f64>)> {
    let conn = store.lock_for_tests();
    let mut stmt = conn
        .prepare(
            "SELECT model, issued_at, valid_from, valid_to, precip_mm, observed_mm
             FROM forecast_history ORDER BY model, valid_from",
        )
        .unwrap();
    stmt.query_map(params![], |r| {
        Ok((
            r.get(0)?,
            r.get(1)?,
            r.get(2)?,
            r.get(3)?,
            r.get(4)?,
            r.get(5)?,
        ))
    })
    .unwrap()
    .collect::<Result<Vec<_>, _>>()
    .unwrap()
}

/// The test fixture: a fresh on-disk database in a temp dir.
fn fresh_store() -> (tempfile::TempDir, Store) {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    let store = Store::open(&db.to_string_lossy()).unwrap();
    (dir, store)
}

fn db_path(dir: &tempfile::TempDir) -> String {
    dir.path().join("weather.db").to_string_lossy().into_owned()
}

// ---------------------------------------------------------------------------
// upsert semantics
// ---------------------------------------------------------------------------

#[test]
fn insert_twice_keeps_one_row_with_newer_value() {
    let (_dir, store) = fresh_store();
    let first = row(
        "icon_d2",
        "2025-01-01T11:00:00Z",
        "2025-01-01T12:00:00Z",
        0.5,
    );
    store.add_forecasts(&[first]).unwrap();
    let second = row(
        "icon_d2",
        "2025-01-01T11:30:00Z",
        "2025-01-01T12:00:00Z",
        0.7,
    );
    store.add_forecasts(&[second]).unwrap();

    let rs = rows(&store);
    assert_eq!(rs.len(), 1);
    assert_eq!(rs[0].1, "2025-01-01T11:30:00Z"); // latest issued before the hour
    assert_eq!(rs[0].4, 0.7);
}

#[test]
fn row_with_observation_is_not_overwritten() {
    let (_dir, store) = fresh_store();
    let first = row(
        "icon_d2",
        "2025-01-01T11:00:00Z",
        "2025-01-01T12:00:00Z",
        0.5,
    );
    store.add_forecasts(&[first]).unwrap();
    store.set_observation("2025-01-01T12:00:00Z", 0.2).unwrap();

    let second = row(
        "icon_d2",
        "2025-01-01T11:30:00Z",
        "2025-01-01T12:00:00Z",
        0.7,
    );
    store.add_forecasts(&[second]).unwrap();

    let rs = rows(&store);
    assert_eq!(rs.len(), 1);
    assert_eq!(rs[0].5, Some(0.2));
    assert_eq!(rs[0].4, 0.5); // forecast untouched once observed
    assert_eq!(rs[0].1, "2025-01-01T11:00:00Z");
}

#[test]
fn newer_observation_replaces_older_one() {
    // a corrected value for the same hour must win (latest observation wins);
    // the forecast of an observed hour stays untouched, other hours untouched
    let (_dir, store) = fresh_store();
    let a = row(
        "icon_d2",
        "2025-01-01T10:00:00Z",
        "2025-01-01T11:00:00Z",
        0.5,
    );
    let b = row(
        "icon_d2",
        "2025-01-01T11:00:00Z",
        "2025-01-01T12:00:00Z",
        0.7,
    );
    store.add_forecasts(&[a, b]).unwrap();
    store.set_observation("2025-01-01T12:00:00Z", 0.2).unwrap();
    store.set_observation("2025-01-01T12:00:00Z", 0.9).unwrap(); // corrected value

    let rs = rows(&store);
    assert_eq!(rs.len(), 2);
    let d2_12 = rs.iter().find(|r| r.2 == "2025-01-01T12:00:00Z").unwrap();
    assert_eq!(d2_12.5, Some(0.9)); // second write won
    assert_eq!(d2_12.4, 0.7); // forecast untouched
    let d2_11 = rs.iter().find(|r| r.2 == "2025-01-01T11:00:00Z").unwrap();
    assert_eq!(d2_11.5, None); // other hour untouched
}

// ---------------------------------------------------------------------------
// compared_forecasts (raw rows for the accuracy scorer)
// ---------------------------------------------------------------------------

#[test]
fn compared_forecasts_filters_window_and_null_observations() {
    let (_dir, store) = fresh_store();
    store
        .add_forecasts(&[
            row(
                "icon_d2",
                "2025-01-01T11:00:00Z",
                "2025-01-01T12:00:00Z",
                0.5,
            ), // observed, in window
            row(
                "icon_d2",
                "2024-12-01T11:00:00Z",
                "2024-12-01T12:00:00Z",
                9.0,
            ), // observed, too old
            row(
                "icon_eu",
                "2025-01-01T11:00:00Z",
                "2025-01-01T12:00:00Z",
                0.2,
            ), // observed, in window
            row(
                "icon_eu",
                "2025-01-01T13:00:00Z",
                "2025-01-01T14:00:00Z",
                0.3,
            ), // no observation
        ])
        .unwrap();
    store.set_observation("2025-01-01T12:00:00Z", 0.4).unwrap();
    store.set_observation("2024-12-01T12:00:00Z", 8.0).unwrap();

    assert_eq!(
        store.compared_forecasts("2024-12-15T00:00:00Z").unwrap(),
        vec![
            ("icon_d2".to_string(), 0.5, 0.4),
            ("icon_eu".to_string(), 0.2, 0.4),
        ],
    );
    assert_eq!(
        store.compared_forecasts("2025-01-02T00:00:00Z").unwrap(),
        Vec::<(String, f64, f64)>::new()
    );
}

// ---------------------------------------------------------------------------
// one-time migration (fresh DB -> v2 -> no-op afterwards)
// ---------------------------------------------------------------------------

#[test]
fn migrates_old_db_once() {
    let dir = tempfile::tempdir().unwrap();
    let db = db_path(&dir);

    // --- "old" database: v1 schema + two duplicate (model, valid_from) rows
    //     written by the pre-6b/6c code (hourly re-inserts, mislabelled) ---
    {
        let conn = Connection::open(&db).unwrap();
        conn.execute_batch(
            "CREATE TABLE forecast_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT NOT NULL,
                precip_mm REAL NOT NULL,
                observed_mm REAL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE INDEX idx_fh_model_hour ON forecast_history (model, valid_from);
            CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO forecast_history (model, issued_at, valid_from, valid_to, precip_mm)
            VALUES ('icon_d2', '2025-01-01T11:00:00Z', '2025-01-01T12:00:00Z',
                    '2025-01-01T13:00:00Z', 0.5),
                   ('icon_d2', '2025-01-01T11:30:00Z', '2025-01-01T12:00:00Z',
                    '2025-01-01T13:00:00Z', 0.7);",
        )
        .unwrap();
    }

    // --- first connect on the new code: deletes old rows, records v3 ---
    {
        let store = Store::open(&db).unwrap();
        assert!(rows(&store).is_empty());
        assert_eq!(
            store
                .get_meta("forecast_history_version")
                .unwrap()
                .as_deref(),
            Some(SCHEMA_VERSION)
        );

        // --- a later connect must NOT wipe rows written after the migration ---
        let r = row(
            "icon_d2",
            "2025-01-01T11:00:00Z",
            "2025-01-01T12:00:00Z",
            0.5,
        );
        store.add_forecasts(&[r]).unwrap();
    }

    let store = Store::open(&db).unwrap();
    assert_eq!(rows(&store).len(), 1);
}

// ---------------------------------------------------------------------------
// app meta + location data clearing (step 8b)
// ---------------------------------------------------------------------------

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
    assert!(rows(&store).is_empty());
    // the stored location itself must survive a location change
    assert_eq!(
        store.get_meta("location").unwrap().as_deref(),
        Some("{\"latitude\": 52.0, \"longitude\": 13.0}")
    );
}

#[test]
fn v2_db_migrates_to_v3_dropping_model_accuracy() {
    // A DB written by the 6c code (version 2, with the unused
    // `model_accuracy` table) migrates to v3 once and keeps its data.
    let dir = tempfile::tempdir().unwrap();
    let db = db_path(&dir);
    {
        let conn = Connection::open(&db).unwrap();
        conn.execute_batch(
            "CREATE TABLE forecast_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                issued_at TEXT NOT NULL,
                valid_from TEXT NOT NULL,
                valid_to TEXT NOT NULL,
                precip_mm REAL NOT NULL,
                observed_mm REAL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            CREATE UNIQUE INDEX ux_fh_model_from ON forecast_history (model, valid_from);
            CREATE TABLE model_accuracy (
                model TEXT PRIMARY KEY,
                n_samples INTEGER NOT NULL DEFAULT 0,
                mean_error REAL,
                updated_at TEXT
            );
            CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO app_meta (key, value) VALUES ('forecast_history_version', '2');
            INSERT INTO forecast_history (model, issued_at, valid_from, valid_to, precip_mm)
            VALUES ('icon_d2', '2025-01-01T11:00:00Z', '2025-01-01T12:00:00Z',
                    '2025-01-01T13:00:00Z', 0.5);
            INSERT INTO model_accuracy (model, n_samples) VALUES ('icon_d2', 3);",
        )
        .unwrap();
    }

    {
        let store = Store::open(&db).unwrap();
        // the v2 row survives the v3 migration (only the table is dropped)
        assert_eq!(rows(&store).len(), 1);
        assert_eq!(
            store
                .get_meta("forecast_history_version")
                .unwrap()
                .as_deref(),
            Some(SCHEMA_VERSION)
        );
        let conn = store.lock_for_tests();
        let name: Option<String> = conn
            .query_row(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'model_accuracy'",
                [],
                |r| r.get(0),
            )
            .optional()
            .unwrap();
        assert_eq!(name, None);
    }

    // a later connect is a no-op: data and version unchanged
    let store = Store::open(&db).unwrap();
    assert_eq!(rows(&store).len(), 1);
}
