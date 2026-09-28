"""Tests for the SQLite store: forecast-history upserts + schema migration.

Uses a real SQLite database on disk (``tmp_path``) so the one-time
migration (tracked in ``app_meta``) is exercised across separate
``connect()`` calls, as it happens across real app restarts.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.store import Store


def _row(model: str, issued_at: str, valid_from: str, precip_mm: float) -> dict:
    return {
        "model": model,
        "issued_at": issued_at,
        "valid_from": valid_from,
        "valid_to": "2025-01-01T13:00:00Z",
        "precip_mm": precip_mm,
    }


async def _rows(store: Store) -> list:
    async with store._db.execute(
        "SELECT model, issued_at, valid_from, valid_to, precip_mm, observed_mm"
        " FROM forecast_history ORDER BY model, valid_from"
    ) as cur:
        return await cur.fetchall()


@pytest_asyncio.fixture
async def store(tmp_path) -> Store:
    s = Store(str(tmp_path / "weather.db"))
    await s.connect()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# upsert semantics
# ---------------------------------------------------------------------------
async def test_insert_twice_keeps_one_row_with_newer_value(store):
    await store.add_forecasts([_row("icon_d2", "2025-01-01T11:00:00Z", "2025-01-01T12:00:00Z", 0.5)])
    await store.add_forecasts([_row("icon_d2", "2025-01-01T11:30:00Z", "2025-01-01T12:00:00Z", 0.7)])

    rows = await _rows(store)
    assert len(rows) == 1
    assert rows[0]["issued_at"] == "2025-01-01T11:30:00Z"  # latest issued before the hour
    assert rows[0]["precip_mm"] == 0.7


async def test_row_with_observation_is_not_overwritten(store):
    await store.add_forecasts([_row("icon_d2", "2025-01-01T11:00:00Z", "2025-01-01T12:00:00Z", 0.5)])
    await store.set_observation("2025-01-01T12:00:00Z", 0.2)

    await store.add_forecasts([_row("icon_d2", "2025-01-01T11:30:00Z", "2025-01-01T12:00:00Z", 0.7)])

    rows = await _rows(store)
    assert len(rows) == 1
    assert rows[0]["observed_mm"] == 0.2
    assert rows[0]["precip_mm"] == 0.5  # forecast untouched once observed
    assert rows[0]["issued_at"] == "2025-01-01T11:00:00Z"


# ---------------------------------------------------------------------------
# compared_forecasts (raw rows for the accuracy scorer)
# ---------------------------------------------------------------------------
async def test_compared_forecasts_filters_window_and_null_observations(store):
    await store.add_forecasts(
        [
            _row("icon_d2", "2025-01-01T11:00:00Z", "2025-01-01T12:00:00Z", 0.5),  # observed, in window
            _row("icon_d2", "2024-12-01T11:00:00Z", "2024-12-01T12:00:00Z", 9.0),  # observed, too old
            _row("icon_eu", "2025-01-01T11:00:00Z", "2025-01-01T12:00:00Z", 0.2),  # observed, in window
            _row("icon_eu", "2025-01-01T13:00:00Z", "2025-01-01T14:00:00Z", 0.3),  # no observation
        ]
    )
    await store.set_observation("2025-01-01T12:00:00Z", 0.4)
    await store.set_observation("2024-12-01T12:00:00Z", 8.0)

    rows = await store.compared_forecasts("2024-12-15T00:00:00Z")
    assert rows == [
        ("icon_d2", 0.5, 0.4),
        ("icon_eu", 0.2, 0.4),
    ]
    assert await store.compared_forecasts("2025-01-02T00:00:00Z") == []


# ---------------------------------------------------------------------------
# one-time migration (fresh DB -> v2 -> no-op afterwards)
# ---------------------------------------------------------------------------
async def test_migrates_old_db_once(tmp_path):
    import aiosqlite

    db = str(tmp_path / "weather.db")

    # --- "old" database: v1 schema + two duplicate (model, valid_from) rows
    #     written by the pre-6b/6c code (hourly re-inserts, mislabelled) ---
    async with aiosqlite.connect(db) as db1:
        await db1.executescript(
            """
            CREATE TABLE forecast_history (
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
            INSERT INTO forecast_history
                (model, issued_at, valid_from, valid_to, precip_mm)
            VALUES ('icon_d2', '2025-01-01T11:00:00Z', '2025-01-01T12:00:00Z',
                    '2025-01-01T13:00:00Z', 0.5),
                   ('icon_d2', '2025-01-01T11:30:00Z', '2025-01-01T12:00:00Z',
                    '2025-01-01T13:00:00Z', 0.7);
            """
        )
        await db1.commit()

    # --- first connect on the new code: deletes old rows, records v3 ---
    s2 = Store(db)
    try:
        await s2.connect()
        assert await _rows(s2) == []
        async with s2._db.execute(
            "SELECT value FROM app_meta WHERE key = 'forecast_history_version'"
        ) as cur:
            assert (await cur.fetchone())["value"] == Store.SCHEMA_VERSION

        # --- a later connect must NOT wipe rows written after the migration ---
        await s2.add_forecasts(
            [_row("icon_d2", "2025-01-01T11:00:00Z", "2025-01-01T12:00:00Z", 0.5)]
        )
    finally:
        await s2.close()

    s3 = Store(db)
    try:
        await s3.connect()
        assert len(await _rows(s3)) == 1
    finally:
        await s3.close()


async def test_v2_db_migrates_to_v3_dropping_model_accuracy(tmp_path):
    """A DB written by the 6c code (version 2, with the unused
    ``model_accuracy`` table) migrates to v3 once and keeps its data."""
    import aiosqlite

    db = str(tmp_path / "weather.db")
    async with aiosqlite.connect(db) as db1:
        await db1.executescript(
            """
            CREATE TABLE forecast_history (
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
            INSERT INTO forecast_history
                (model, issued_at, valid_from, valid_to, precip_mm)
            VALUES ('icon_d2', '2025-01-01T11:00:00Z', '2025-01-01T12:00:00Z',
                    '2025-01-01T13:00:00Z', 0.5);
            INSERT INTO model_accuracy (model, n_samples) VALUES ('icon_d2', 3);
            """
        )
        await db1.commit()

    s2 = Store(db)
    try:
        await s2.connect()
        # the v2 row survives the v3 migration (only the table is dropped)
        assert len(await _rows(s2)) == 1
        async with s2._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'model_accuracy'"
        ) as cur:
            assert await cur.fetchone() is None
        async with s2._db.execute(
            "SELECT value FROM app_meta WHERE key = 'forecast_history_version'"
        ) as cur:
            assert (await cur.fetchone())["value"] == Store.SCHEMA_VERSION
    finally:
        await s2.close()

    # a later connect is a no-op: data and version unchanged
    s3 = Store(db)
    try:
        await s3.connect()
        assert len(await _rows(s3)) == 1
    finally:
        await s3.close()
