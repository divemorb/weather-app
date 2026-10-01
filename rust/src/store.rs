//! SQLite persistence: cached source payloads + forecast history (Python
//! `app/store.py`). The cache tables hold the *raw* upstream JSON for each
//! source so the app can serve page loads instantly and show per-source
//! data age. The history tables support the optional accuracy extension
//! (stored forecasts compared against later observations).
//!
//! All timestamps are UTC ISO-8601 strings.

use std::io;
use std::path::Path;
use std::sync::{Mutex, MutexGuard};

use chrono::{DateTime, Utc};
use rusqlite::{Connection, OptionalExtension, named_params, params};
use serde_json::Value;

use crate::series::HistoryRow;
use crate::times;

/// A database problem (Python lets these exceptions propagate).
#[derive(Debug)]
pub enum StoreError {
    Sqlite(rusqlite::Error),
    /// A cached payload that isn't valid JSON (the file is untrusted).
    Json(serde_json::Error),
    /// Creating the database directory failed.
    Io(io::Error),
}

impl std::fmt::Display for StoreError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StoreError::Sqlite(e) => write!(f, "database error: {e}"),
            StoreError::Json(e) => write!(f, "cached payload is not valid JSON: {e}"),
            StoreError::Io(e) => write!(f, "cannot create the database directory: {e}"),
        }
    }
}

impl std::error::Error for StoreError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            StoreError::Sqlite(e) => Some(e),
            StoreError::Json(e) => Some(e),
            StoreError::Io(e) => Some(e),
        }
    }
}

impl From<rusqlite::Error> for StoreError {
    fn from(e: rusqlite::Error) -> Self {
        StoreError::Sqlite(e)
    }
}

impl From<serde_json::Error> for StoreError {
    fn from(e: serde_json::Error) -> Self {
        StoreError::Json(e)
    }
}

impl From<io::Error> for StoreError {
    fn from(e: io::Error) -> Self {
        StoreError::Io(e)
    }
}

/// The four cached upstream sources (Python's string keys). The database
/// column `source_cache.source` holds `key()`.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Source {
    Radar,
    Current,
    Forecast,
    Ensemble,
}

impl Source {
    /// In Python's `_SOURCES` order (the order of `/api/sources`).
    pub const ALL: [Source; 4] = [
        Source::Radar,
        Source::Current,
        Source::Forecast,
        Source::Ensemble,
    ];

    /// "radar", "current", "forecast", "ensemble"
    pub fn key(self) -> &'static str {
        match self {
            Source::Radar => "radar",
            Source::Current => "current",
            Source::Forecast => "forecast",
            Source::Ensemble => "ensemble",
        }
    }

    /// "DWD (Bright Sky)" for Radar/Current, "Open-Meteo" for Forecast/Ensemble.
    pub fn upstream(self) -> &'static str {
        match self {
            Source::Radar | Source::Current => "DWD (Bright Sky)",
            Source::Forecast | Source::Ensemble => "Open-Meteo",
        }
    }
}

/// Current schema version (tracked in `app_meta`).
pub const SCHEMA_VERSION: &str = "3";

/// Python `_SCHEMA`, verbatim. The unique index on (model, valid_from) is
/// deliberately *not* here: `_migrate` creates it after the one-time
/// cleanup of old rows.
const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS source_cache (
    source      TEXT PRIMARY KEY,   -- 'radar' | 'current' | 'forecast' | 'ensemble'
    fetched_at  TEXT NOT NULL,      -- UTC ISO-8601
    payload     TEXT NOT NULL       -- raw upstream JSON
);

CREATE TABLE IF NOT EXISTS forecast_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model          TEXT NOT NULL,
    issued_at      TEXT NOT NULL,   -- UTC: when the forecast was made
    valid_from     TEXT NOT NULL,   -- UTC: start of the forecast hour
    valid_to       TEXT NOT NULL,   -- UTC: end of the forecast hour
    precip_mm      REAL NOT NULL,   -- model's forecast for that hour
    observed_mm    REAL,            -- NULL until an observation is compared
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
-- NOTE: the unique index on (model, valid_from) is created in
-- _migrate(), *after* the one-time cleanup of old rows.
-- NOTE: the old "model_accuracy" table (unused write-through table) was
-- dropped in schema v3 (step 6e); accuracy is now computed on demand from
-- forecast_history via compared_forecasts() + app.accuracy.model_accuracy.

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"#;

pub struct Store {
    conn: Mutex<Connection>,
}

impl Store {
    /// Open (or create) the database, applying the schema and the
    /// one-time migrations. `":memory:"` opens an in-memory database,
    /// exactly like Python's `Store(":memory:")`.
    pub fn open(path: &str) -> Result<Store, StoreError> {
        if let Some(parent) = Path::new(path).parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut conn = Connection::open(path)?;
        conn.execute_batch(SCHEMA)?;
        migrate(&mut conn)?;
        Ok(Store {
            conn: Mutex::new(conn),
        })
    }

    fn lock_conn(&self) -> MutexGuard<'_, Connection> {
        self.conn
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    /// Test-only access to the connection (Python tests read `store._db`).
    #[cfg(test)]
    pub fn lock_for_tests(&self) -> MutexGuard<'_, Connection> {
        self.lock_conn()
    }

    // -- app meta (step 8b: the location lives here at runtime) ---------------

    pub fn get_meta(&self, key: &str) -> Result<Option<String>, StoreError> {
        let conn = self.lock_conn();
        let value: Option<Option<String>> = conn
            .query_row("SELECT value FROM app_meta WHERE key = ?", [key], |r| {
                r.get(0)
            })
            .optional()?;
        Ok(value.flatten())
    }

    pub fn set_meta(&self, key: &str, value: &str) -> Result<(), StoreError> {
        let conn = self.lock_conn();
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params![key, value],
        )?;
        Ok(())
    }

    /// Drop all cached payloads and forecast history (step 8b).
    ///
    /// Called when the location changes: both tables belong to the *old*
    /// location, so they must not be served for the new one. (The accuracy
    /// window shrinks accordingly; there is nothing to re-compute.)
    pub fn clear_location_data(&self) -> Result<(), StoreError> {
        let conn = self.lock_conn();
        conn.execute("DELETE FROM source_cache", [])?;
        conn.execute("DELETE FROM forecast_history", [])?;
        Ok(())
    }

    // -- cache ---------------------------------------------------------------

    pub fn put_cache(
        &self,
        source: Source,
        payload: &Value,
        now: DateTime<Utc>,
    ) -> Result<(), StoreError> {
        let conn = self.lock_conn();
        conn.execute(
            "INSERT INTO source_cache (source, fetched_at, payload)
             VALUES (?, ?, ?)
             ON CONFLICT(source) DO UPDATE SET
                 fetched_at = excluded.fetched_at, payload = excluded.payload",
            params![source.key(), times::to_iso(now), payload.to_string()],
        )?;
        Ok(())
    }

    /// (payload, age in seconds); `None` when the source was never cached.
    pub fn get_cache(
        &self,
        source: Source,
        now: DateTime<Utc>,
    ) -> Result<Option<(Value, f64)>, StoreError> {
        let conn = self.lock_conn();
        let row: Option<(String, String)> = conn
            .query_row(
                "SELECT fetched_at, payload FROM source_cache WHERE source = ?",
                [source.key()],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        let Some((fetched_at, payload)) = row else {
            return Ok(None);
        };
        let payload: Value = serde_json::from_str(&payload)?;
        // Python falls back to "now" when fetched_at doesn't parse, i.e.
        // age 0; a clock skew would give a negative age, clamped the same way.
        let age = match times::parse_iso(&fetched_at) {
            Ok(fetched) => (now - fetched).as_seconds_f64(),
            Err(_) => 0.0,
        };
        Ok(Some((payload, age.max(0.0))))
    }

    // -- history (extension) ---------------------------------------------------

    /// Upsert this hour's forecasts (idempotent per `model + valid_from`).
    ///
    /// Re-running the same refresh updates the row in place, keeping the
    /// *latest* forecast issued before the hour started (the shortest lead
    /// time — what the next-hour vote uses). A row that already has an
    /// observation is never touched.
    pub fn add_forecasts(&self, rows: &[HistoryRow]) -> Result<(), StoreError> {
        if rows.is_empty() {
            return Ok(());
        }
        let mut conn = self.lock_conn();
        let tx = conn.transaction()?;
        {
            let mut stmt = tx.prepare(
                "INSERT INTO forecast_history
                 (model, issued_at, valid_from, valid_to, precip_mm)
                 VALUES (:model, :issued_at, :valid_from, :valid_to, :precip_mm)
                 ON CONFLICT(model, valid_from) DO UPDATE SET
                     issued_at = excluded.issued_at,
                     precip_mm = excluded.precip_mm,
                     valid_to  = excluded.valid_to
                 WHERE forecast_history.observed_mm IS NULL",
            )?;
            for row in rows {
                stmt.execute(named_params! {
                    ":model": row.model,
                    ":issued_at": row.issued_at,
                    ":valid_from": row.valid_from,
                    ":valid_to": row.valid_to,
                    ":precip_mm": row.precip_mm,
                })?;
            }
        }
        tx.commit()?;
        Ok(())
    }

    /// Set the observation for the hour starting at `valid_from`.
    ///
    /// The *latest* observation for the hour wins: Bright Sky may publish a
    /// corrected value for an already-seen hour, and the backfill re-reads
    /// the last 48 h on every hourly refresh, so an unconditional update is
    /// what we want here. (The guard in `add_forecasts` is different —
    /// it protects the *forecast* of an already observed hour.)
    pub fn set_observation(&self, valid_from: &str, observed_mm: f64) -> Result<(), StoreError> {
        let conn = self.lock_conn();
        conn.execute(
            "UPDATE forecast_history SET observed_mm = ?
             WHERE valid_from = ?",
            params![observed_mm, valid_from],
        )?;
        Ok(())
    }

    /// Raw `(model, precip_mm, observed_mm)` rows for scored forecasts.
    ///
    /// Only rows that already have an observation and whose hour started
    /// at or after `since_iso` (UTC ISO-8601, lexicographic comparison is
    /// safe for this fixed format) are returned. All the math (MAE,
    /// event counts, accuracy) is done by `crate::accuracy` — the store
    /// only moves data.
    pub fn compared_forecasts(
        &self,
        since_iso: &str,
    ) -> Result<Vec<(String, f64, f64)>, StoreError> {
        let conn = self.lock_conn();
        let mut stmt = conn.prepare(
            "SELECT model, precip_mm, observed_mm
             FROM forecast_history
             WHERE observed_mm IS NOT NULL AND valid_from >= ?
             ORDER BY model, valid_from",
        )?;
        let rows = stmt
            .query_map(params![since_iso], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?))
            })?
            .collect::<Result<Vec<_>, _>>()?;
        Ok(rows)
    }
}

/// Run the one-time schema migrations, tracked in `app_meta`.
///
/// v2 (step 6b/6c): `forecast_history` rows are unique per
/// `(model, valid_from)` (upserted, see [`Store::add_forecasts`]) and
/// labelled by hour start. All rows written before that are mislabelled,
/// so the table is emptied once. The unique index must only exist once
/// the old rows are gone, hence it is created here rather than in `SCHEMA`.
/// v3 (step 6e): drop the unused `model_accuracy` table.
/// Each step runs at most once, so this is a no-op on later startups.
fn migrate(conn: &mut Connection) -> Result<(), StoreError> {
    let tx = conn.transaction()?;
    let value: Option<Option<String>> = tx
        .query_row(
            "SELECT value FROM app_meta WHERE key = 'forecast_history_version'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    let mut version = schema_version(value);
    if version < 2 {
        tx.execute("DELETE FROM forecast_history", [])?;
        tx.execute("DROP INDEX IF EXISTS idx_fh_model_hour", [])?;
        tx.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_fh_model_from ON forecast_history (model, valid_from)",
            [],
        )?;
        version = 2;
    }
    if version < 3 {
        tx.execute("DROP TABLE IF EXISTS model_accuracy", [])?;
        version = 3;
    }
    tx.execute(
        "INSERT INTO app_meta (key, value) VALUES ('forecast_history_version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![version.to_string()],
    )?;
    tx.commit()?;
    Ok(())
}

/// Python `_migrate`'s version read: the number if the stored value is
/// non-empty and all ASCII digits, else 1 (a missing row, a NULL value
/// or non-numeric text all mean 1).
fn schema_version(value: Option<Option<String>>) -> i64 {
    let Some(text) = value.flatten() else {
        return 1;
    };
    if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
        return 1;
    }
    text.parse::<i64>().unwrap_or(i64::MAX)
}

#[cfg(test)]
mod tests;
