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
CREATE INDEX IF NOT EXISTS idx_fh_model_hour ON forecast_history (model, valid_from);

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
        await self._db.commit()

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
        if not rows:
            return
        assert self._db is not None
        await self._db.executemany(
            """
            INSERT INTO forecast_history
                (model, issued_at, valid_from, valid_to, precip_mm)
            VALUES (:model, :issued_at, :valid_from, :valid_to, :precip_mm)
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
