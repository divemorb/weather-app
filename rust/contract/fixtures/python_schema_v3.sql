-- The Python app's (v1) database schema, frozen from app/store.py at tag
-- python-last: run.py seeds a v1 database with it (the takeover test).
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

CREATE TABLE IF NOT EXISTS user_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    intensity   TEXT,
    confirms    INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL
);
