//! Tests for the user_reports store methods (R1b).
//!
//! Uses a real SQLite database on disk (a ``tempdir``), as the store's own
//! tests do, so the schema applied in ``Store::open`` is what runs.

use super::*;
use crate::series::HistoryRow;

/// The test fixture: a fresh on-disk database in a temp dir.
fn fresh_store() -> (tempfile::TempDir, Store) {
    let dir = tempfile::tempdir().unwrap();
    let db = dir.path().join("weather.db");
    let store = Store::open(&db.to_string_lossy()).unwrap();
    (dir, store)
}

/// All user_reports rows in id order, as `(kind, intensity, confirms,
/// observed_at)` (the SQL of the Python `test_stored_rows`).
fn rows(store: &Store) -> Vec<(String, Option<String>, i64, String)> {
    let conn = store.lock_conn();
    let mut stmt = conn
        .prepare(
            "SELECT kind, intensity, confirms, observed_at \
             FROM user_reports ORDER BY id",
        )
        .unwrap();
    stmt.query_map(params![], |r| {
        Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?))
    })
    .unwrap()
    .collect::<Result<Vec<_>, _>>()
    .unwrap()
}

/// All report ids in id order.
fn ids(store: &Store) -> Vec<i64> {
    let conn = store.lock_conn();
    let mut stmt = conn
        .prepare("SELECT id FROM user_reports ORDER BY id")
        .unwrap();
    stmt.query_map(params![], |r| r.get(0))
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap()
}

#[test]
fn stored_rows_match_the_python_app() {
    let (_dir, store) = fresh_store();
    let first = store
        .add_report(
            ReportKind::Rain,
            Some(Intensity::Light),
            false,
            "2025-01-01T11:45:00Z",
        )
        .unwrap();
    let second = store
        .add_report(ReportKind::Clear, None, true, "2025-01-01T12:00:00Z")
        .unwrap();
    assert_eq!((first, second), (1, 2));
    assert_eq!(
        rows(&store),
        vec![
            (
                "rain".to_string(),
                Some("light".to_string()),
                0,
                "2025-01-01T11:45:00Z".to_string()
            ),
            (
                "clear".to_string(),
                None,
                1,
                "2025-01-01T12:00:00Z".to_string()
            ),
        ]
    );
}

#[test]
fn newest_is_by_observed_at_then_id() {
    let (_dir, store) = fresh_store();
    store
        .add_report(ReportKind::Fog, None, false, "2025-01-01T12:00:00Z")
        .unwrap();
    store
        .add_report(
            ReportKind::Rain,
            Some(Intensity::Heavy),
            false,
            "2025-01-01T11:45:00Z",
        )
        .unwrap();
    // The same `observed_at` as the newest: the later id wins.
    store
        .add_report(ReportKind::Snow, None, true, "2025-01-01T12:00:00Z")
        .unwrap();
    let newest = store
        .newest_report("2025-01-01T12:00:00Z")
        .unwrap()
        .unwrap();
    assert_eq!(newest.id, 3);
    assert_eq!(newest.kind, "snow");
    assert!(newest.confirms);
    assert_eq!(newest.observed_at, "2025-01-01T12:00:00Z");
    let earlier = store
        .newest_report("2025-01-01T11:59:59Z")
        .unwrap()
        .unwrap();
    assert_eq!(earlier.id, 2);
    assert_eq!(earlier.kind, "rain");
    assert_eq!(earlier.intensity, Some("heavy".to_string()));
}

#[test]
fn until_excludes_later_reports() {
    let (_dir, store) = fresh_store();
    store
        .add_report(ReportKind::Clear, None, true, "2025-01-01T10:00:00Z")
        .unwrap();
    // A report after `until` (the clock jumped back) must not hide the
    // current one.
    store
        .add_report(ReportKind::Hail, None, false, "2025-01-01T11:00:00Z")
        .unwrap();
    let newest = store
        .newest_report("2025-01-01T10:30:00Z")
        .unwrap()
        .unwrap();
    assert_eq!(newest.kind, "clear");
    assert_eq!(store.newest_report("2025-01-01T09:59:59Z").unwrap(), None);
}

#[test]
fn delete_report_reports_whether_the_row_existed() {
    let (_dir, store) = fresh_store();
    let id = store
        .add_report(
            ReportKind::Rain,
            Some(Intensity::Light),
            false,
            "2025-01-01T12:00:00Z",
        )
        .unwrap();
    assert!(store.delete_report(id).unwrap());
    assert!(!store.delete_report(id).unwrap());
    assert!(!store.delete_report(999).unwrap());
    assert_eq!(store.newest_report("2025-01-02T00:00:00Z").unwrap(), None);
}

#[test]
fn prune_drops_old_reports_then_keeps_only_the_newest() {
    let (_dir, store) = fresh_store();
    for t in [
        "2025-01-01T08:00:00Z",
        "2025-01-01T09:00:00Z",
        "2025-01-01T10:00:00Z",
        "2025-01-01T11:00:00Z",
        "2025-01-01T12:00:00Z",
    ] {
        store
            .add_report(ReportKind::Cloudy, None, false, t)
            .unwrap();
    }
    // Age: everything observed before 10:00 goes (ids 1 and 2).
    store.prune_reports("2025-01-01T10:00:00Z", 500).unwrap();
    assert_eq!(ids(&store), vec![3, 4, 5]);
    // Count: of the rest, all but the newest two go (the oldest first).
    store.prune_reports("2025-01-01T00:00:00Z", 2).unwrap();
    assert_eq!(ids(&store), vec![4, 5]);
}

#[test]
fn prune_count_ties_break_to_the_higher_id() {
    let (_dir, store) = fresh_store();
    for _ in 0..3 {
        store
            .add_report(ReportKind::Fog, None, false, "2025-01-01T12:00:00Z")
            .unwrap();
    }
    store.prune_reports("2025-01-01T00:00:00Z", 2).unwrap();
    assert_eq!(ids(&store), vec![2, 3]);
}

#[test]
fn clear_location_data_removes_every_report() {
    let (_dir, store) = fresh_store();
    store
        .add_report(
            ReportKind::Rain,
            Some(Intensity::Light),
            false,
            "2025-01-01T12:00:00Z",
        )
        .unwrap();
    store.clear_location_data().unwrap();
    assert_eq!(ids(&store), &[] as &[i64]);
    assert_eq!(store.newest_report("2025-01-02T00:00:00Z").unwrap(), None);
}

#[test]
fn report_rows_lists_every_report_in_id_order() {
    let (_dir, store) = fresh_store();
    store
        .add_report(
            ReportKind::Rain,
            Some(Intensity::Heavy),
            false,
            "2025-01-01T12:00:00Z",
        )
        .unwrap();
    store
        .add_report(ReportKind::Clear, None, true, "2025-01-01T11:00:00Z")
        .unwrap();
    // A deleted report does not come back.
    store.delete_report(1).unwrap();
    store
        .add_report(ReportKind::Snow, None, false, "2025-01-01T13:00:00Z")
        .unwrap();
    assert_eq!(
        store.report_rows().unwrap(),
        vec![
            ReportRow {
                id: 2,
                kind: "clear".to_string(),
                confirms: true,
                observed_at: "2025-01-01T11:00:00Z".to_string(),
            },
            ReportRow {
                id: 3,
                kind: "snow".to_string(),
                confirms: false,
                observed_at: "2025-01-01T13:00:00Z".to_string(),
            },
        ]
    );
    assert_eq!(Store::open(":memory:").unwrap().report_rows().unwrap(), []);
}

#[test]
fn scored_forecasts_returns_the_scored_rows_labelled_by_hour() {
    let (_dir, store) = fresh_store();
    let hour = |model: &str, valid_from: &str, precip_mm: f64| HistoryRow {
        model: model.to_string(),
        issued_at: "2025-01-01T08:55:00Z".to_string(),
        valid_from: valid_from.to_string(),
        valid_to: "2025-01-01T10:00:00Z".to_string(),
        precip_mm,
    };
    let scored = |model: &str, valid_from: &str, precip_mm: f64| ScoredRow {
        model: model.to_string(),
        valid_from: valid_from.to_string(),
        precip_mm,
    };
    store
        .add_forecasts(&[
            hour("a_model", "2025-01-01T08:00:00Z", 0.5),
            hour("a_model", "2025-01-01T09:00:00Z", 0.4),
            hour("b_model", "2025-01-01T09:00:00Z", 1.5),
            // Still without an observation: not scored yet.
            hour("a_model", "2025-01-01T10:00:00Z", 0.2),
        ])
        .unwrap();
    store.set_observation("2025-01-01T08:00:00Z", 0.2).unwrap();
    store.set_observation("2025-01-01T09:00:00Z", 1.0).unwrap();
    // The window is `valid_from >= since`: the row exactly at `since`
    // counts, the one before does not, the unscored row never does.
    let rows = store.scored_forecasts("2025-01-01T09:00:00Z").unwrap();
    assert_eq!(
        rows,
        vec![
            scored("a_model", "2025-01-01T09:00:00Z", 0.4),
            scored("b_model", "2025-01-01T09:00:00Z", 1.5),
        ]
    );
    // An earlier cut lets the 08:00 row join (model order first, then the
    // hour, like `compared_forecasts`).
    let rows = store.scored_forecasts("2025-01-01T08:00:00Z").unwrap();
    assert_eq!(
        rows,
        vec![
            scored("a_model", "2025-01-01T08:00:00Z", 0.5),
            rows[1].clone(),
            rows[2].clone(),
        ]
    );
    assert_eq!(store.scored_forecasts("2025-01-02T00:00:00Z").unwrap(), []);
}
