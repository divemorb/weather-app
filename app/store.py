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
-- _migrate(), *after* the one-time cleanup of old rows.
-- NOTE: the old "model_accuracy" table (unused write-through table) was
-- dropped in schema v3 (step 6e); accuracy is now computed on demand from
-- forecast_history via compared_forecasts() + app.accuracy.model_accuracy.

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
        await self._migrate()
        await self._db.commit()

    #: current schema version (tracked in ``app_meta``)
    SCHEMA_VERSION = "3"

    async def _migrate(self) -> None:
        """Run the one-time schema migrations, tracked in ``app_meta``.

        v2 (step 6b/6c): ``forecast_history`` rows are unique per
        ``(model, valid_from)`` (upserted, see :meth:`add_forecasts`) and
        labelled by hour start. All rows written before that are
        mislabelled, so the table is emptied once. The unique index must
        only exist once the old rows are gone, hence it is created here
        rather than in ``_SCHEMA``.
        v3 (step 6e): drop the unused ``model_accuracy`` table; accuracy
        is now computed on demand from ``forecast_history``.
        Each step runs at most once; the key is updated in place, so this
        is a no-op on every later startup.
        """
        assert self._db is not None
        async with self._db.execute(
            "SELECT value FROM app_meta WHERE key = 'forecast_history_version'"
        ) as cur:
            row = await cur.fetchone()
        version = int(row["value"]) if row is not None and row["value"].isdigit() else 1
        if version < 2:
            await self._db.execute("DELETE FROM forecast_history")
            await self._db.execute("DROP INDEX IF EXISTS idx_fh_model_hour")
            await self._db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_fh_model_from"
                " ON forecast_history (model, valid_from)"
            )
            version = 2
        if version < 3:
            await self._db.execute("DROP TABLE IF EXISTS model_accuracy")
            version = 3
        await self._db.execute(
            "INSERT INTO app_meta (key, value) VALUES ('forecast_history_version', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(version),),
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
        """Set the observation for the hour starting at ``valid_from``.

        The *latest* observation for the hour wins: Bright Sky may publish a
        corrected value for an already-seen hour, and the backfill re-reads
        the last 48 h on every hourly refresh, so an unconditional update is
        what we want here. (The guard in :meth:`add_forecasts` is different —
        it protects the *forecast* of an already observed hour.)
        """
        assert self._db is not None
        await self._db.execute(
            """
            UPDATE forecast_history SET observed_mm = ?
            WHERE valid_from = ?
            """,
            (observed_mm, valid_from),
        )
        await self._db.commit()

    async def compared_forecasts(
        self, since_iso: str
    ) -> list[tuple[str, float, float]]:
        """Raw ``(model, precip_mm, observed_mm)`` rows for scored forecasts.

        Only rows that already have an observation and whose hour started
        at or after ``since_iso`` (UTC ISO-8601, lexicographic comparison is
        safe for this fixed format) are returned. All the math (MAE,
        event counts, accuracy) is done in Python by
        :func:`app.accuracy.model_accuracy` — the store only moves data.
        """
        assert self._db is not None
        async with self._db.execute(
            """
            SELECT model, precip_mm, observed_mm
            FROM forecast_history
            WHERE observed_mm IS NOT NULL AND valid_from >= ?
            ORDER BY model, valid_from
            """,
            (since_iso,),
        ) as cur:
            rows = await cur.fetchall()
        return [(row["model"], row["precip_mm"], row["observed_mm"]) for row in rows]


def _parse_utc(stamp: str) -> float:
    """Parse an ISO-8601 UTC stamp to a unix timestamp."""
    import datetime

    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()
