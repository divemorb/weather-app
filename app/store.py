"""SQLite persistence: cached source payloads + forecast history.

The cache tables hold the *raw* upstream JSON for each source so the app can
serve page loads instantly and show per-source data age. The history tables
support the optional accuracy extension (stored forecasts compared against
later observations).

All timestamps are UTC ISO-8601 strings.
"""
from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite

_SCHEMA = """
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
-- _migrate_forecast_history(), *after* the one-time cleanup of old rows.

CREATE TABLE IF NOT EXISTS model_accuracy (
    model        TEXT PRIMARY KEY,
    n_samples    INTEGER NOT NULL DEFAULT 0,
    mean_error   REAL,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    """Thin async wrapper around aiosqlite."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        import os
        parent = os.path.dirname(self._db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._migrate_forecast_history()
        await self._db.commit()

    async def _migrate_forecast_history(self) -> None:
        """One-time migration to schema version 2 (tracked in ``app_meta``).

        v2: ``forecast_history`` rows are unique per ``(model, valid_from)``
        (upserted, see :meth:`add_forecasts`) and labelled by hour start.
        All rows written before that are mislabelled, so the table is emptied
        once. Tracked in ``app_meta`` so this is a no-op on every later
        startup. The unique index must only exist once the old rows are gone,
        hence it is created here rather than in ``_SCHEMA``.
        """
        assert self._db is not None
        async with self._db.execute(
            "SELECT value FROM app_meta WHERE key = 'forecast_history_version'"
        ) as cur:
            row = await cur.fetchone()
        if row is not None and row["value"] == "2":
            return
        await self._db.execute("DELETE FROM forecast_history")
        await self._db.execute("DROP INDEX IF EXISTS idx_fh_model_hour")
        await self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_fh_model_from"
            " ON forecast_history (model, valid_from)"
        )
        await self._db.execute(
            "INSERT INTO app_meta (key, value) VALUES ('forecast_history_version', '2')"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # -- cache ---------------------------------------------------------------
    async def put_cache(self, source: str, payload: dict[str, Any]) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            INSERT INTO source_cache (source, fetched_at, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                fetched_at = excluded.fetched_at,
                payload = excluded.payload
            """,
            (source, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), json.dumps(payload)),
        )
        await self._db.commit()

    async def get_cache(self, source: str) -> tuple[dict[str, Any] | None, float | None]:
        """Return (payload, age_in_seconds); (None, None) when missing."""
        assert self._db is not None
        async with self._db.execute(
            "SELECT fetched_at, payload FROM source_cache WHERE source = ?", (source,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None, None
        fetched_at = row["fetched_at"]
        payload = json.loads(row["payload"])
        age = time.time() - _parse_utc(fetched_at)
        return payload, max(age, 0.0)

    # -- history (extension) ---------------------------------------------------
    async def add_forecasts(self, rows: list[dict[str, Any]]) -> None:
        """Upsert this hour's forecasts (idempotent per ``model + valid_from``).

        Re-running the same refresh updates the row in place, keeping the
        *latest* forecast issued before the hour started (the shortest lead
        time — what the next-hour vote uses). A row that already has an
        observation is never touched.
        """
        if not rows:
            return
        assert self._db is not None
        await self._db.executemany(
            """
            INSERT INTO forecast_history
                (model, issued_at, valid_from, valid_to, precip_mm)
            VALUES (:model, :issued_at, :valid_from, :valid_to, :precip_mm)
            ON CONFLICT(model, valid_from) DO UPDATE SET
                issued_at = excluded.issued_at,
                precip_mm = excluded.precip_mm,
                valid_to  = excluded.valid_to
            WHERE forecast_history.observed_mm IS NULL
            """,
            rows,
        )
        await self._db.commit()

    async def set_observation(self, valid_from: str, observed_mm: float) -> None:
        assert self._db is not None
        await self._db.execute(
            """
            UPDATE forecast_history SET observed_mm = ?
            WHERE valid_from = ? AND observed_mm IS NULL
            """,
            (observed_mm, valid_from),
        )
        await self._db.commit()

    async def model_accuracy(self) -> dict[str, dict[str, Any]]:
        """Per-model mean absolute error over compared forecasts."""
        assert self._db is not None
        result: dict[str, dict[str, Any]] = {}
        async with self._db.execute(
            """
            SELECT model,
                   COUNT(*) AS n,
                   AVG(ABS(precip_mm - observed_mm)) AS mae
            FROM forecast_history
            WHERE observed_mm IS NOT NULL
            GROUP BY model
            """
        ) as cur:
            for row in await cur.fetchall():
                result[row["model"]] = {
                    "n_samples": row["n"],
                    "mean_error": row["mae"],
                }
        return result


def _parse_utc(stamp: str) -> float:
    """Parse an ISO-8601 UTC stamp to a unix timestamp."""
    import datetime

    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()
