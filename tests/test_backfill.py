"""Integration tests for the hourly observation backfill (step 6d).

The clients are stubbed (no network); the Store is a real in-memory SQLite
db. The clock is monkeypatched on ``app.aggregator.utcnow``: history is
written at NOW, then the clock is advanced 2 h to simulate the downtime
catch-up in which stored hours finally receive their observations.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio

from app.store import Store
from tests.test_aggregator import (
    NOW,
    current_payload,
    ensemble_payload,
    forecast_payload,
    make_aggregator,
    make_cfg,
    radar_payload,
)

NOW_2H = NOW + timedelta(hours=2)


def weather_payload_around_now() -> dict:
    """/weather records around the frozen NOW = 2025-01-01 12:00.

    Station 1002 is the "current" observation source; 1001 is the MOSMIX
    "forecast" source. Stamps 09:00..15:00 cover hours 08:00..14:00
    (a record stamped T holds the rain of [T-1h, T)).
    """
    recs = [
        ("09:00", 1002, 0.5),   # hour 08:00-09:00
        ("10:00", 1002, None),  # missing precipitation -> skipped
        ("11:00", 1002, 0.0),   # hour 10:00-11:00 (dry)
        ("12:00", 1002, 1.3),   # stamped exactly NOW: complete, kept (hour 11:00)
        ("12:00", 1001, 9.9),    # same hour from the forecast source -> skipped
        ("13:00", 1002, 0.2),   # hour 12:00-13:00
        ("14:00", 1002, 2.2),   # hour 13:00-14:00
        ("15:00", 1002, 3.0),   # future at now=14:00 -> skipped
    ]
    return {
        "weather": [
            {"timestamp": f"2025-01-01T{ts}:00Z", "source_id": sid, "precipitation": p}
            for ts, sid, p in recs
        ],
        "sources": [
            {"id": 1002, "observation_type": "current",
             "station_name": "BERLIN", "distance": 5000.0},
            {"id": 1001, "observation_type": "forecast",
             "station_name": "BERLIN", "distance": 3000.0},
        ],
    }


async def _filled_hours(store) -> dict[str, float]:
    """``valid_from -> observed_mm`` for all observed rows (both models
    carry the same value per hour, so one dict entry per hour)."""
    async with store._db.execute(
        "SELECT valid_from, observed_mm FROM forecast_history WHERE observed_mm IS NOT NULL"
    ) as cur:
        rows = await cur.fetchall()
    out: dict[str, float] = {}
    for r in rows:
        assert r["observed_mm"] != 9.9  # forecast-source value must never land
        out[r["valid_from"]] = r["observed_mm"]
    return out


@pytest_asyncio.fixture
async def store() -> Store:
    s = Store(":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def all_payloads() -> dict:
    return {
        "current": current_payload(),
        "radar": radar_payload([("2025-01-01T12:00:00Z", [(5, 5, 20)])]),
        "forecast": forecast_payload(),
        "ensemble": ensemble_payload(),
    }


async def test_backfill_observations_fills_matching_hours_only(
    store, all_payloads, monkeypatch
):
    """History rows are stored with valid_from >= issued_at, so an
    observation (hour = stamp - 1h) only matches once its hour has started.
    Freeze the clock at NOW, write history, then advance 2 h (downtime
    catch-up) and backfill: only the stored hours 12:00 and 13:00 are filled,
    by their own observations."""
    payloads = dict(all_payloads, weather=weather_payload_around_now())
    agg = make_aggregator(make_cfg(), store, payloads, payloads)

    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW)
    await agg.refresh_models()
    # at NOW the kept stamps (09..12:00) fill hours 08..11:00, none stored
    assert await _filled_hours(store) == {}

    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW_2H)
    await agg.backfill_observations()
    filled = await _filled_hours(store)
    # stamp 13:00 -> hour 12:00, stamp 14:00 -> hour 13:00; hour 11:00 (1.3)
    # has no stored row (issued_at = 12:00) and must stay NULL
    assert filled == {
        "2025-01-01T12:00:00Z": 0.2,
        "2025-01-01T13:00:00Z": 2.2,
    }


async def test_refresh_models_triggers_backfill(store, all_payloads, monkeypatch):
    payloads = dict(all_payloads, weather=weather_payload_around_now())
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW)
    await agg.refresh_models()  # history rows written; no observation match yet
    assert await _filled_hours(store) == {}
    # the *next* hourly refresh (clock advanced) must run the backfill itself
    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW_2H)
    await agg.refresh_models()
    assert len(await _filled_hours(store)) == 2  # both models, hours 12:00+13:00


async def test_backfill_never_breaks_model_refresh(
    store, all_payloads, monkeypatch
):
    """A failing /weather fetch must not break the model refresh."""
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads)
    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW)
    await agg.refresh_models()  # stub raises: no 'weather' payload configured
    async with store._db.execute(
        "SELECT COUNT(*) AS n FROM forecast_history"
    ) as cur:
        row = await cur.fetchone()
    assert row["n"] == 48  # forecast history still written
    assert await _filled_hours(store) == {}


async def test_backfill_without_observations_is_noop(store, all_payloads, monkeypatch):
    payloads = dict(all_payloads, weather={"weather": [], "sources": []})
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW)
    await agg.backfill_observations()  # must not raise
    assert await _filled_hours(store) == {}
