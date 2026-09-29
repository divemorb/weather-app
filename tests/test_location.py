"""Tests for the runtime location state (step 8b).

Covers the pure helpers in :mod:`app.location` (JSON round trip, ``moved``)
and the startup resolution (stored value wins, env/YAML is adopted), plus
the aggregator's unconfigured behaviour (no fetch calls) and
``Aggregator.set_location`` (clears data only when the location moved).
The fakes come from ``tests/aggregator_support.py``.
"""
from __future__ import annotations

import pytest_asyncio

from app.config import LocationConfig
from app.location import (
    LOCATION_KEY,
    location_from_json,
    location_to_json,
    moved,
    resolve_startup_location,
)
from app.store import Store
from tests.aggregator_support import make_aggregator, make_cfg, make_payloads


@pytest_asyncio.fixture
async def store(tmp_path) -> Store:
    s = Store(str(tmp_path / "weather.db"))
    await s.connect()
    yield s
    await s.close()


def loc(lat=52.0, lon=13.0, tz="Europe/Berlin", label="") -> LocationConfig:
    return LocationConfig(latitude=lat, longitude=lon, timezone=tz, label=label)


# ---------------------------------------------------------------------------
# JSON round trip (app_meta value)
# ---------------------------------------------------------------------------
def test_location_json_round_trip():
    l = loc(52.52, 13.405, "Europe/Berlin", "Berlin")
    assert location_from_json(location_to_json(l)) == l


def test_location_json_garbage_returns_none_never_raises():
    for bad in (None, "", "not json", "[1, 2]", '"str"', "42",
                '{"latitude": 52.0}',                       # missing longitude
                '{"latitude": 52.0, "longitude": "x"}',     # wrong type
                '{"latitude": true, "longitude": 13.0}',    # bool is not a number
                '{"latitude": 52.0, "longitude": 13.0}',    # missing timezone
                ):
        assert location_from_json(bad) is None


def test_location_json_defaults_missing_label():
    l = location_from_json('{"latitude": 52.0, "longitude": 13.0, "timezone": "UTC"}')
    assert l is not None
    assert l.label == ""
    assert (l.latitude, l.longitude) == (52.0, 13.0)


# ---------------------------------------------------------------------------
# moved()
# ---------------------------------------------------------------------------
def test_moved_none_old_is_not_a_move():
    assert moved(None, loc()) is False


def test_moved_same_location_is_not_a_move():
    assert moved(loc(), loc()) is False


def test_moved_within_epsilon_is_not_a_move():
    # 0.005 degrees ~ 550 m: the same place, e.g. a re-pick from a search
    assert moved(loc(52.0, 13.0), loc(52.005, 13.005)) is False


def test_moved_beyond_epsilon_is_a_move():
    # 0.02 degrees ~ 2 km: a different place, data must be cleared
    assert moved(loc(52.0, 13.0), loc(52.02, 13.0)) is True
    assert moved(loc(52.0, 13.0), loc(52.0, 13.02)) is True


# ---------------------------------------------------------------------------
# resolve_startup_location
# ---------------------------------------------------------------------------
async def test_startup_stored_location_wins_over_cfg(store):
    stored = loc(52.52, 13.405)
    await store.set_meta(LOCATION_KEY, location_to_json(stored))
    cfg = make_cfg()  # env/YAML location 52.0/13.0
    got = await resolve_startup_location(store, cfg)
    assert got == stored
    # the stored value must not have been overwritten by the cfg one
    assert location_from_json(await store.get_meta(LOCATION_KEY)) == stored


async def test_startup_adopts_cfg_location_into_db(store):
    cfg = make_cfg()  # location 52.0/13.0
    got = await resolve_startup_location(store, cfg)
    assert got == cfg.location
    assert location_from_json(await store.get_meta(LOCATION_KEY)) == cfg.location


async def test_startup_nothing_everywhere_is_unconfigured(store):
    cfg = make_cfg(location=None)
    got = await resolve_startup_location(store, cfg)
    assert got is None
    assert await store.get_meta(LOCATION_KEY) is None


# ---------------------------------------------------------------------------
# aggregator: unconfigured -> no fetch calls
# ---------------------------------------------------------------------------
async def test_aggregator_without_location_makes_no_fetch_calls(store):
    cfg = make_cfg(location=None)
    agg = make_aggregator(cfg, store)
    await agg.refresh_radar()
    await agg.refresh_models()
    assert await store.get_cache("radar") == (None, None)
    assert await store.get_cache("current") == (None, None)
    assert await store.get_cache("forecast") == (None, None)
    assert await store.get_cache("ensemble") == (None, None)


# ---------------------------------------------------------------------------
# aggregator: set_location
# ---------------------------------------------------------------------------
async def test_set_location_first_time_stores_without_clearing(store):
    cfg = make_cfg(location=None)
    payloads = make_payloads()
    agg = make_aggregator(cfg, store, payloads, payloads)
    # pre-fill the cache (it belongs to the old location — or to nothing)
    await store.put_cache("radar", payloads["radar"])

    await agg.set_location(loc(52.0, 13.0))

    # nothing was cleared: the first location has no old data to throw away
    payload, _age = await store.get_cache("radar")
    assert payload is not None
    assert location_from_json(await store.get_meta(LOCATION_KEY)) == loc(52.0, 13.0)
    assert agg.cfg.location == loc(52.0, 13.0)
    assert agg._brightsky._lat == 52.0 and agg._openmeteo._lat == 52.0
    # the skip flag is reset: the next refresh fetches again
    await agg.refresh_radar()
    payload, _age = await store.get_cache("current")
    assert payload is not None


async def test_set_location_near_same_is_not_a_move(store):
    cfg = make_cfg()  # 52.0/13.0
    agg = make_aggregator(cfg, store)
    await store.put_cache("radar", make_payloads()["radar"])

    await agg.set_location(loc(52.005, 13.005))  # ~550 m away

    payload, _age = await store.get_cache("radar")
    assert payload is not None  # kept: within the 1 km epsilon
    assert agg.cfg.location == loc(52.005, 13.005)


async def test_set_location_moved_clears_location_data(store):
    cfg = make_cfg()  # 52.0/13.0
    agg = make_aggregator(cfg, store)
    payloads = make_payloads()
    await store.put_cache("radar", payloads["radar"])
    await store.put_cache("forecast", payloads["forecast"])

    await agg.set_location(loc(52.52, 13.405))  # Berlin: far away

    assert await store.get_cache("radar") == (None, None)
    assert await store.get_cache("forecast") == (None, None)
    assert location_from_json(await store.get_meta(LOCATION_KEY)) == loc(52.52, 13.405)
    assert agg.cfg.location == loc(52.52, 13.405)
    assert agg._brightsky._lon == 13.405 and agg._openmeteo._lon == 13.405
