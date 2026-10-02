//! `wetter snapshot PATH`: a consistent copy of the live database for the
//! Raspberry Pi deployment. The distroless image has no shell and no
//! Python, so the backup script runs
//! `podman exec weather-app-rust /app/wetter snapshot /data/.snapshot.db`
//! while the server keeps running in the same container; the copy must be
//! consistent although the server may be writing.
//!
//! The copy is made with SQLite's `VACUUM INTO` on a *read-only*
//! connection to the live database: one read transaction, so the copy
//! contains no other connections' uncommitted writes, a missing database
//! is an error (not a new empty file), and the server keeps running.

use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

use rusqlite::{Connection, OpenFlags, OptionalExtension};

/// A snapshot failure.
#[derive(Debug)]
pub enum SnapshotError {
    /// The target file already exists; it is left untouched.
    TargetExists(PathBuf),
    /// SQLite failed (opening the live database read-only, `VACUUM INTO`,
    /// opening the copy or the integrity check).
    Sqlite(rusqlite::Error),
    /// The copy's `PRAGMA integrity_check` reported a problem; the copy has
    /// been removed again.
    Integrity(String),
    /// A filesystem problem (removing a corrupt copy).
    Io(io::Error),
}

impl std::fmt::Display for SnapshotError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SnapshotError::TargetExists(path) => {
                write!(f, "target file already exists: {}", path.display())
            }
            SnapshotError::Sqlite(e) => write!(f, "sqlite: {e}"),
            SnapshotError::Integrity(result) => write!(f, "integrity check failed: {result}"),
            SnapshotError::Io(e) => write!(f, "i/o error: {e}"),
        }
    }
}

impl std::error::Error for SnapshotError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            SnapshotError::Sqlite(e) => Some(e),
            SnapshotError::Io(e) => Some(e),
            _ => None,
        }
    }
}

impl From<rusqlite::Error> for SnapshotError {
    fn from(e: rusqlite::Error) -> Self {
        SnapshotError::Sqlite(e)
    }
}

impl From<io::Error> for SnapshotError {
    fn from(e: io::Error) -> Self {
        SnapshotError::Io(e)
    }
}

/// What the report says about the *copy*.
#[derive(Debug)]
pub struct Stats {
    /// `app_meta` value of `forecast_history_version` (None when unset).
    pub schema_version: Option<String>,
    /// `app_meta` has a row with key `location`.
    pub location_stored: bool,
    /// `count(*)` of `forecast_history`.
    pub history_rows: i64,
    /// `count(observed_mm)` of `forecast_history`.
    pub with_observation: i64,
    /// `min(valid_from)` / `max(valid_from)` of `forecast_history`
    /// (None while the table is empty).
    pub history_from: Option<String>,
    pub history_to: Option<String>,
    /// `source_cache.source` values, sorted (empty when none are cached).
    pub cached_sources: Vec<String>,
}

/// Copy the live database at `source` to `target` (`VACUUM INTO` on a
/// read-only connection, so the copy is one consistent read transaction)
/// and verify the copy with `PRAGMA integrity_check`.
///
/// `target` must not exist; a missing `source` is an error, not a new
/// empty file. On an integrity failure the copy is removed again.
pub fn snapshot(source: &Path, target: &Path) -> Result<Stats, SnapshotError> {
    if target.exists() {
        return Err(SnapshotError::TargetExists(target.to_path_buf()));
    }
    vacuum_into(source, target)?;
    verify(target)
}

/// One `VACUUM INTO` against the live database (read-only connection).
fn vacuum_into(source: &Path, target: &Path) -> Result<(), SnapshotError> {
    let conn = Connection::open_with_flags(source, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    // The server may hold a write lock for a moment.
    conn.busy_timeout(Duration::from_secs(5))?;
    // The target path is bound as a parameter, never formatted into the SQL.
    conn.execute("VACUUM INTO ?1", [target.to_string_lossy().into_owned()])?;
    Ok(())
}

/// Open the copy read-only, require `PRAGMA integrity_check` to say `ok`
/// (removing the copy otherwise) and read the statistics from it.
fn verify(target: &Path) -> Result<Stats, SnapshotError> {
    let conn = Connection::open_with_flags(target, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let result: String = conn.query_row("PRAGMA integrity_check", [], |r| r.get(0))?;
    if result != "ok" {
        std::fs::remove_file(target)?;
        return Err(SnapshotError::Integrity(result));
    }
    collect_stats(&conn)
}

/// The report values, read from the copy.
fn collect_stats(conn: &Connection) -> Result<Stats, SnapshotError> {
    let version: Option<Option<String>> = conn
        .query_row(
            "SELECT value FROM app_meta WHERE key = 'forecast_history_version'",
            [],
            |r| r.get(0),
        )
        .optional()?;
    let location_row = conn
        .query_row("SELECT 1 FROM app_meta WHERE key = 'location'", [], |_| {
            Ok(())
        })
        .optional()?;
    let history_rows: i64 =
        conn.query_row("SELECT count(*) FROM forecast_history", [], |r| r.get(0))?;
    let with_observation: i64 =
        conn.query_row("SELECT count(observed_mm) FROM forecast_history", [], |r| {
            r.get(0)
        })?;
    let history_from: Option<String> =
        conn.query_row("SELECT min(valid_from) FROM forecast_history", [], |r| {
            r.get(0)
        })?;
    let history_to: Option<String> =
        conn.query_row("SELECT max(valid_from) FROM forecast_history", [], |r| {
            r.get(0)
        })?;
    let mut stmt = conn.prepare("SELECT source FROM source_cache ORDER BY source")?;
    let cached_sources = stmt
        .query_map([], |r| r.get::<_, String>(0))?
        .collect::<Result<Vec<_>, _>>()?;
    Ok(Stats {
        schema_version: version.flatten(),
        location_stored: location_row.is_some(),
        history_rows,
        with_observation,
        history_from,
        history_to,
        cached_sources,
    })
}

/// The report: exactly 8 lines, each two spaces, the label (with its colon)
/// padded to 18 characters and the value; no trailing newline.
pub fn report(stats: &Stats) -> String {
    [
        format!("  {:<18}{}", "integrity:", "ok"),
        format!(
            "  {:<18}{}",
            "schema version:",
            stats.schema_version.as_deref().unwrap_or("(none)")
        ),
        format!(
            "  {:<18}{}",
            "location stored:",
            if stats.location_stored { "yes" } else { "no" }
        ),
        format!("  {:<18}{}", "history rows:", stats.history_rows),
        format!("  {:<18}{}", "with observation:", stats.with_observation),
        format!(
            "  {:<18}{}",
            "history from:",
            stats.history_from.as_deref().unwrap_or("(none)")
        ),
        format!(
            "  {:<18}{}",
            "history to:",
            stats.history_to.as_deref().unwrap_or("(none)")
        ),
        format!(
            "  {:<18}{}",
            "cached sources:",
            stats.cached_sources.join(",")
        ),
    ]
    .join("\n")
}

#[cfg(test)]
mod tests;
