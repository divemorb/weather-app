//! Tests for `wetter::snapshot`: the source databases are built with
//! `Store::open` and its methods, so they have the schema the app writes.

use super::*;
use crate::series::HistoryRow;
use crate::store::{Source, Store};
use chrono::{TimeDelta, Utc};
use serde_json::json;

fn row(valid_from: &str) -> HistoryRow {
    let from = chrono::DateTime::parse_from_rfc3339(valid_from).unwrap();
    HistoryRow {
        model: "icon_d2".to_string(),
        issued_at: "2026-10-01T09:00:00Z".to_string(),
        valid_from: valid_from.to_string(),
        valid_to: (from + TimeDelta::hours(1))
            .format("%Y-%m-%dT%H:%M:%SZ")
            .to_string(),
        precip_mm: 1.0,
    }
}

#[test]
fn snapshot_copies_db_and_reports_stats() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    let store = Store::open(db.to_str().unwrap()).unwrap();
    store.set_meta("location", "52.52,13.405").unwrap();
    store
        .put_cache(Source::Radar, &json!({"ok": true}), Utc::now())
        .unwrap();
    store
        .put_cache(Source::Current, &json!({"ok": true}), Utc::now())
        .unwrap();
    store
        .add_forecasts(&[
            row("2026-10-01T10:00:00Z"),
            row("2026-10-01T11:00:00Z"),
            row("2026-10-01T12:00:00Z"),
        ])
        .unwrap();
    store.set_observation("2026-10-01T10:00:00Z", 2.5).unwrap();

    let target = dir.path().join("copy.db");
    let stats = snapshot(&db, &target).unwrap();
    assert!(target.exists());
    assert_eq!(stats.schema_version, Some("3".to_string()));
    assert!(stats.location_stored);
    assert_eq!(stats.history_rows, 3);
    assert_eq!(stats.with_observation, 1);
    assert_eq!(stats.history_from.as_deref(), Some("2026-10-01T10:00:00Z"));
    assert_eq!(stats.history_to.as_deref(), Some("2026-10-01T12:00:00Z"));
    assert_eq!(stats.cached_sources, ["current", "radar"]);
    assert_eq!(
        report(&stats),
        r"  integrity:        ok
  schema version:   3
  location stored:  yes
  history rows:     3
  with observation: 1
  history from:     2026-10-01T10:00:00Z
  history to:       2026-10-01T12:00:00Z
  cached sources:   current,radar"
    );

    // The copy is a usable database with the same stored location.
    let copy = Store::open(target.to_str().unwrap()).unwrap();
    assert_eq!(
        copy.get_meta("location").unwrap(),
        Some("52.52,13.405".to_string())
    );
}

#[test]
fn snapshot_refuses_existing_target() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    Store::open(db.to_str().unwrap()).unwrap();
    let target = dir.path().join("copy.db");
    std::fs::write(&target, "keep me").unwrap();

    let err = snapshot(&db, &target).unwrap_err();
    assert!(matches!(
        err,
        SnapshotError::TargetExists(path) if path == target
    ));
    assert_eq!(std::fs::read_to_string(&target).unwrap(), "keep me");
}

#[test]
fn snapshot_of_missing_db_fails_without_creating_it() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    let target = dir.path().join("copy.db");

    let err = snapshot(&db, &target).unwrap_err();
    assert!(matches!(err, SnapshotError::Sqlite(_)));
    assert!(!db.exists());
    assert!(!target.exists());
}

#[test]
fn snapshot_leaves_out_uncommitted_writes() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    let store = Store::open(db.to_str().unwrap()).unwrap();
    store
        .add_forecasts(&[
            row("2026-10-01T10:00:00Z"),
            row("2026-10-01T11:00:00Z"),
            row("2026-10-01T12:00:00Z"),
        ])
        .unwrap();

    // A second connection holds an uncommitted write transaction...
    let writer = rusqlite::Connection::open(&db).unwrap();
    writer
        .execute_batch("BEGIN IMMEDIATE; DELETE FROM forecast_history;")
        .unwrap();

    // ...the snapshot succeeds and still counts the committed rows...
    let target = dir.path().join("copy.db");
    let stats = snapshot(&db, &target).unwrap();
    assert_eq!(stats.history_rows, 3);

    // ...and the rollback restores them in the live database.
    writer.execute_batch("ROLLBACK").unwrap();
    let stats = snapshot(&db, &dir.path().join("copy2.db")).unwrap();
    assert_eq!(stats.history_rows, 3);
}

#[test]
fn snapshot_of_empty_db_reports_none() {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    Store::open(db.to_str().unwrap()).unwrap();

    let stats = snapshot(&db, &dir.path().join("copy.db")).unwrap();
    assert_eq!(stats.schema_version, Some("3".to_string()));
    assert!(!stats.location_stored);
    assert_eq!(stats.history_rows, 0);
    assert_eq!(stats.with_observation, 0);
    assert_eq!(stats.history_from, None);
    assert_eq!(stats.history_to, None);
    assert!(stats.cached_sources.is_empty());
    assert_eq!(
        report(&stats),
        r"  integrity:        ok
  schema version:   3
  location stored:  no
  history rows:     0
  with observation: 0
  history from:     (none)
  history to:       (none)
  cached sources:   "
    );
}
