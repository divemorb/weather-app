//! The `user_reports` table: what the user says the sky really looks like
//! (Python `app/store.py`, `user_reports` methods).
//!
//! `confirms` is stored as 0/1 and `intensity` is NULL when not given
//! (only rain has one), exactly like the Python app, so both backends write
//! the same rows.

use rusqlite::{OptionalExtension, params};

use super::{Store, StoreError};
use crate::reports::{Intensity, ReportKind};

/// The `user_reports` part of the Python `_SCHEMA`, verbatim.
pub const SCHEMA: &str = r"
CREATE TABLE IF NOT EXISTS user_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    intensity   TEXT,
    confirms    INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL
);
";

/// One row of `user_reports` (what the table holds, passed through to the
/// API).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredReport {
    pub id: i64,
    pub kind: String,
    pub intensity: Option<String>,
    pub confirms: bool,
    pub observed_at: String,
}

/// One report for the accuracy comparison (Python `Store.report_rows`'s
/// `(id, kind, confirms, observed_at)`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReportRow {
    pub id: i64,
    pub kind: String,
    pub confirms: bool,
    pub observed_at: String,
}

/// One scored forecast row for the accuracy comparison (Python
/// `Store.scored_forecasts`'s `(model, valid_from, precip_mm)`).
#[derive(Clone, Debug, PartialEq)]
pub struct ScoredRow {
    pub model: String,
    pub valid_from: String,
    pub precip_mm: f64,
}

impl Store {
    /// Save a user report and return its new id (Python `add_report`).
    ///
    /// `intensity` is NULL when not given (only rain has one); `confirms`
    /// is stored as 0/1.
    pub fn add_report(
        &self,
        kind: ReportKind,
        intensity: Option<Intensity>,
        confirms: bool,
        observed_at: &str,
    ) -> Result<i64, StoreError> {
        let conn = self.lock_conn();
        conn.execute(
            "INSERT INTO user_reports (kind, intensity, confirms, observed_at) \
             VALUES (?, ?, ?, ?)",
            params![
                kind.as_str(),
                intensity.map(Intensity::as_str),
                i64::from(confirms),
                observed_at
            ],
        )?;
        Ok(conn.last_insert_rowid())
    }

    /// Delete one report; `true` when the row existed (Python
    /// `delete_report`).
    pub fn delete_report(&self, report_id: i64) -> Result<bool, StoreError> {
        let conn = self.lock_conn();
        let deleted = conn.execute("DELETE FROM user_reports WHERE id = ?", params![report_id])?;
        Ok(deleted > 0)
    }

    /// The newest report observed at or before `until` (Python
    /// `newest_report`); `None` when there is none. Newest = highest
    /// `observed_at`, then id. (A report after `until` exists only if the
    /// clock jumped back; it must not hide the current one.)
    pub fn newest_report(&self, until: &str) -> Result<Option<StoredReport>, StoreError> {
        let conn = self.lock_conn();
        let report = conn
            .query_row(
                "SELECT id, kind, intensity, confirms, observed_at FROM user_reports \
                 WHERE observed_at <= ? ORDER BY observed_at DESC, id DESC LIMIT 1",
                params![until],
                |r| {
                    Ok(StoredReport {
                        id: r.get(0)?,
                        kind: r.get(1)?,
                        intensity: r.get(2)?,
                        confirms: r.get::<_, i64>(3)? != 0,
                        observed_at: r.get(4)?,
                    })
                },
            )
            .optional()?;
        Ok(report)
    }

    /// Drop reports observed before `older_than`, then all but the newest
    /// `keep` (`observed_at`, then id). Runs on every save (Python
    /// `prune_reports`).
    pub fn prune_reports(&self, older_than: &str, keep: i64) -> Result<(), StoreError> {
        let conn = self.lock_conn();
        conn.execute(
            "DELETE FROM user_reports WHERE observed_at < ?",
            params![older_than],
        )?;
        conn.execute(
            "DELETE FROM user_reports WHERE id NOT IN \
             (SELECT id FROM user_reports ORDER BY observed_at DESC, id DESC LIMIT ?)",
            params![keep],
        )?;
        Ok(())
    }

    /// All reports as `(id, kind, confirms, observed_at)` in id order
    /// (Python `report_rows`); the accuracy comparison picks the newest per
    /// hour itself.
    pub fn report_rows(&self) -> Result<Vec<ReportRow>, StoreError> {
        let conn = self.lock_conn();
        let mut stmt =
            conn.prepare("SELECT id, kind, confirms, observed_at FROM user_reports ORDER BY id")?;
        let rows = stmt
            .query_map(params![], |r| {
                Ok(ReportRow {
                    id: r.get(0)?,
                    kind: r.get(1)?,
                    confirms: r.get::<_, i64>(2)? != 0,
                    observed_at: r.get(3)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }

    /// The station's scored rows as `(model, valid_from, precip_mm)`
    /// (Python `scored_forecasts`): the same rows as `compared_forecasts`
    /// (`observed_mm IS NOT NULL`, hour started at or after `since`),
    /// labelled by hour so the user-report comparison can pair each with the
    /// user's report of that hour.
    pub fn scored_forecasts(&self, since: &str) -> Result<Vec<ScoredRow>, StoreError> {
        let conn = self.lock_conn();
        let mut stmt = conn.prepare(
            "SELECT model, valid_from, precip_mm
             FROM forecast_history
             WHERE observed_mm IS NOT NULL AND valid_from >= ?
             ORDER BY model, valid_from",
        )?;
        let rows = stmt
            .query_map(params![since], |r| {
                Ok(ScoredRow {
                    model: r.get(0)?,
                    valid_from: r.get(1)?,
                    precip_mm: r.get(2)?,
                })
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }
}

#[cfg(test)]
mod tests;
