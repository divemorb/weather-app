"""The weather stations behind the data (station steps S1 and S5).

S1: ``/api/now`` names the station its values come from (``station``) and,
per value, the station Bright Sky took it from instead (``fallback``).
S5: the observation backfill remembers which stations its observations came
from, and ``/api/model-accuracy`` lists them (``stations``).

The API runs on a real Aggregator with an in-memory Store and stubbed
clients, so these tests fix the JSON contract, not internal names.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from tests.aggregator_support import (
    NOW,
    current_payload,
    make_aggregator,
    make_cfg,
    make_payloads,
)

TEMPELHOF = {
    "id": 96160, "station_name": "Berlin-Tempelhof", "observation_type": "synop",
    "distance": 5837.0, "lat": 52.4676, "lon": 13.402, "height": 47.7,
    "dwd_station_id": "00433", "wmo_station_id": "10384",
}
POTSDAM = {
    "id": 11702, "station_name": "Potsdam", "observation_type": "synop",
    "distance": 27915.0, "lat": 52.3813, "lon": 13.0622, "height": 80.9,
    "dwd_station_id": "03987", "wmo_station_id": "10379",
}


def now_payload(sources: list[dict], source_id=96160, fallback: dict | None = None) -> dict:
    p = current_payload()
    p["weather"]["source_id"] = source_id
    if fallback is not None:
        p["weather"]["fallback_source_ids"] = fallback
    p["sources"] = sources
    return p


async def get_now(store, client, payload: dict) -> dict:
    payloads = dict(make_payloads(), current=payload)
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    await agg.refresh_radar()
    await agg.refresh_models()
    r = client(agg).get("/api/now")
    assert r.status_code == 200
    return r.json()["conditions"]


# ---------------------------------------------------------------------------
# S1: /api/now station + fallback
# ---------------------------------------------------------------------------
async def test_now_names_its_station(store, client, frozen_now):
    cond = await get_now(store, client, now_payload([TEMPELHOF, POTSDAM]))
    assert cond["station"] == {
        "name": "Berlin-Tempelhof", "distance_m": 5837.0, "lat": 52.4676, "lon": 13.402,
        "height_m": 47.7, "dwd_station_id": "00433",
    }
    assert cond["fallback"] == {}
    assert cond["source_id"] == 96160  # unchanged


async def test_now_fallback_per_shown_value(store, client, frozen_now):
    """``fallback`` is keyed by the API's own field names; a fallback for a
    Bright Sky field the API doesn't carry (solar_60) is left out, and so is
    one pointing at a source that isn't listed."""
    fallback = {"wind_speed_10": 11702, "cloud_cover": 11702, "precipitation_60": 11702,
                "solar_60": 11702, "dew_point": 424242}
    cond = await get_now(store, client, now_payload([TEMPELHOF, POTSDAM], fallback=fallback))
    potsdam = {"name": "Potsdam", "distance_m": 27915.0}
    assert cond["fallback"] == {
        "wind_speed_ms": potsdam, "cloud_cover_pct": potsdam, "precipitation_60mm": potsdam,
    }


@pytest.mark.parametrize("bs_key, api_key", [
    ("temperature", "temperature_c"),
    ("wind_speed_10", "wind_speed_ms"),
    ("wind_direction_10", "wind_direction_deg"),
    ("wind_gust_speed_60", "wind_gust_ms"),
    ("cloud_cover", "cloud_cover_pct"),
    ("relative_humidity", "humidity_pct"),
    ("pressure_msl", "pressure_hpa"),
    ("dew_point", "dew_point_c"),
    ("precipitation_10", "precipitation_10mm"),
    ("precipitation_30", "precipitation_30mm"),
    ("precipitation_60", "precipitation_60mm"),
    ("condition", "condition"),
])
async def test_now_fallback_field_names(store, client, frozen_now, bs_key, api_key):
    cond = await get_now(store, client, now_payload([TEMPELHOF, POTSDAM], fallback={bs_key: 11702}))
    assert cond["fallback"] == {api_key: {"name": "Potsdam", "distance_m": 27915.0}}


async def test_now_station_null_without_its_source(store, client, frozen_now):
    """No source with the weather's ``source_id``: no station (and the
    fallback ids point nowhere either)."""
    cond = await get_now(store, client, now_payload([POTSDAM], source_id=1, fallback={"cloud_cover": 7}))
    assert cond["station"] is None
    assert cond["fallback"] == {}
    cond = await get_now(store, client, now_payload([], source_id=1))
    assert cond["station"] is None


async def test_now_station_missing_fields_are_null(store, client, frozen_now):
    cond = await get_now(store, client, now_payload([{"id": 96160, "station_name": "Görlitz"}]))
    assert cond["station"] == {
        "name": "Görlitz", "distance_m": None, "lat": None, "lon": None,
        "height_m": None, "dwd_station_id": None,
    }


async def test_now_without_sources_key(store, client, frozen_now):
    """Older payloads (and the test helpers') may lack ``sources``."""
    p = current_payload()
    p.pop("sources", None)
    cond = await get_now(store, client, p)
    assert cond["station"] is None
    assert cond["fallback"] == {}


# ---------------------------------------------------------------------------
# S5: the observation stations
# ---------------------------------------------------------------------------
LATER = NOW + timedelta(hours=3)


def weather_payload(records: list[tuple[str, int, float | None]], sources: list[dict]) -> dict:
    return {
        "weather": [{"timestamp": f"2025-01-01T{ts}:00Z", "source_id": sid, "precipitation": p}
                    for ts, sid, p in records],
        "sources": sources,
    }


FRIEDRICHSHAIN = {"id": 312070, "station_name": "Berlin-Friedrichshain/Spree",
                  "observation_type": "historical", "distance": 1860.0, "lat": 52.51,
                  "lon": 13.427, "height": 34.91, "dwd_station_id": "17473"}
TEMPELHOF_CUR = {"id": 6150, "station_name": "BERLIN-TEMPELHOF", "observation_type": "current",
                 "distance": 5576.0, "lat": 52.47, "lon": 13.4, "height": 50.0,
                 "dwd_station_id": "00433"}
MUEGGELSEE = {"id": 777, "station_name": "Berlin-Müggelsee", "observation_type": "historical",
             "distance": 17000.0, "lat": 52.44, "lon": 13.65, "height": 39.0,
             "dwd_station_id": "00410"}
ALEX_MOSMIX = {"id": 2382, "station_name": "BERLIN-ALEX.", "observation_type": "forecast",
               "distance": 1016.0, "lat": 52.52, "lon": 13.42, "height": 37.0,
               "dwd_station_id": "00399"}

RECORDS = [
    ("09:00", 312070, 0.0),
    ("10:00", 312070, 0.5),
    ("11:00", 312070, None),   # no precipitation: not an observation, not counted
    ("12:00", 6150, 0.2),
    ("13:00", 6150, 0.0),
    ("14:00", 6150, 1.1),
    ("14:00", 2382, 9.9),      # MOSMIX: never an observation
    ("15:00", 777, 0.3),
    ("16:00", 777, 0.0),       # stamped after LATER (15:00): future, not counted
    ("12:00", 424242, 0.4),    # unknown source: skipped
]
SOURCES = [MUEGGELSEE, TEMPELHOF_CUR, ALEX_MOSMIX, FRIEDRICHSHAIN]

EXPECTED = [  # nearest first
    {"name": "Berlin-Friedrichshain/Spree", "distance_m": 1860.0, "lat": 52.51, "lon": 13.427,
     "dwd_station_id": "17473", "hours": 2},
    {"name": "BERLIN-TEMPELHOF", "distance_m": 5576.0, "lat": 52.47, "lon": 13.4,
     "dwd_station_id": "00433", "hours": 3},
    {"name": "Berlin-Müggelsee", "distance_m": 17000.0, "lat": 52.44, "lon": 13.65,
     "dwd_station_id": "00410", "hours": 1},
]


async def backfilled(store, monkeypatch, payload: dict | None, errors=()):
    payloads = dict(make_payloads())
    if payload is not None:
        payloads["weather"] = payload
    agg = make_aggregator(make_cfg(), store, payloads, payloads, errors=errors)
    monkeypatch.setattr("app.aggregator.utcnow", lambda: LATER)
    await agg.backfill_observations()
    return agg


async def test_accuracy_lists_the_observation_stations(store, client, monkeypatch):
    agg = await backfilled(store, monkeypatch, weather_payload(RECORDS, SOURCES))
    body = client(agg).get("/api/model-accuracy").json()
    assert body["stations"] == EXPECTED


async def test_observation_stations_stored_as_canonical_json(store, client, monkeypatch):
    """Stored in ``app_meta`` under ``observation_stations``, as compact JSON
    with sorted keys and raw UTF-8: the Rust backend writes the same bytes
    (the lockstep compares ``app_meta`` as text)."""
    await backfilled(store, monkeypatch, weather_payload(RECORDS, SOURCES))
    raw = await store.get_meta("observation_stations")
    assert raw == json.dumps(EXPECTED, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert "Müggelsee" in raw


async def test_accuracy_stations_empty_before_any_backfill(store, client, monkeypatch):
    payloads = make_payloads()
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    assert client(agg).get("/api/model-accuracy").json()["stations"] == []


async def test_failed_or_empty_backfill_keeps_the_stations(store, client, monkeypatch):
    agg = await backfilled(store, monkeypatch, weather_payload(RECORDS, SOURCES))
    # a backfill without any observation leaves the list as it was
    agg = await backfilled(store, monkeypatch, weather_payload([("12:00", 2382, 1.0)], [ALEX_MOSMIX]))
    assert client(agg).get("/api/model-accuracy").json()["stations"] == EXPECTED
    # and so does a failing fetch
    agg = await backfilled(store, monkeypatch, None, errors=("weather",))
    assert client(agg).get("/api/model-accuracy").json()["stations"] == EXPECTED


async def test_broken_stored_value_reads_as_empty(store, client, monkeypatch):
    await store.set_meta("observation_stations", "{not json")
    payloads = make_payloads()
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    assert client(agg).get("/api/model-accuracy").json()["stations"] == []


async def test_moving_clears_the_stations(store, client, monkeypatch):
    """A new location deletes the cached data and the history; the stations
    belong to the old place and go with them. The same place keeps them."""
    from app.config import LocationConfig

    agg = await backfilled(store, monkeypatch, weather_payload(RECORDS, SOURCES))
    await agg.set_location(LocationConfig(52.001, 13.001, "Europe/Berlin"))  # make_cfg: 52.0/13.0
    assert client(agg).get("/api/model-accuracy").json()["stations"] == EXPECTED
    await agg.set_location(LocationConfig(48.137, 11.575, "Europe/Berlin"))
    assert client(agg).get("/api/model-accuracy").json()["stations"] == []
    assert await store.get_meta("observation_stations") is None
