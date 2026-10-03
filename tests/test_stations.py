"""Unit tests for the pure station parsers (``app/stations.py``).

The API-level tests (``tests/test_station.py``) fix the JSON contract
through the API; these pin the parsers' behaviour on untrusted
payload shapes (missing ``sources`` key, missing/mistyped entry keys) and on
the stored-value round trip (canonical JSON, broken values read as empty).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.brightsky_client import parse_hourly_observations
from app.stations import (
    CURRENT_FIELDS,
    OBSERVATION_STATIONS_KEY,
    observation_stations,
    parse_station,
    station_and_fallback,
    stations_from_json,
    stations_to_json,
)

NOW15 = datetime(2025, 1, 1, 15, 0, tzinfo=timezone.utc)

BACKFILL_PAYLOAD = {
    "weather": [
        {"timestamp": "2025-01-01T09:00:00Z", "source_id": 1, "precipitation": 0.0},
        {"timestamp": "2025-01-01T10:00:00Z", "source_id": 1, "precipitation": 0.5},
        {"timestamp": "2025-01-01T11:00:00Z", "source_id": 1, "precipitation": None},
        {"timestamp": "2025-01-01T12:00:00Z", "source_id": 2, "precipitation": 0.2},
        {"timestamp": "2025-01-01T14:00:00Z", "source_id": 3, "precipitation": 9.9},  # MOSMIX
        {"timestamp": "2025-01-01T15:00:00Z", "source_id": 4, "precipitation": 0.3},
        {"timestamp": "2025-01-01T16:00:00Z", "source_id": 4, "precipitation": 0.0},  # future
        {"timestamp": "2025-01-01T12:00:00Z", "source_id": 99, "precipitation": 0.4},  # unknown
    ],
    "sources": [
        {"id": 4, "station_name": "Far", "observation_type": "historical", "distance": 17000.0,
         "lat": 52.4, "lon": 13.6, "dwd_station_id": "00410"},
        {"id": 2, "station_name": "Mid", "observation_type": "current", "distance": 5576.0,
         "lat": 52.47, "lon": 13.4, "dwd_station_id": "00433"},
        {"id": 3, "station_name": "MOSMIX", "observation_type": "forecast", "distance": 1016.0,
         "lat": 52.52, "lon": 13.42, "dwd_station_id": "00399"},
        {"id": 1, "station_name": "Near", "observation_type": "historical", "distance": 1860.0,
         "lat": 52.51, "lon": 13.427, "dwd_station_id": "17473"},
    ],
}


def test_parse_station_missing_keys_are_null():
    assert parse_station({"id": 96160, "station_name": "Görlitz"}) == {
        "name": "Görlitz", "distance_m": None, "lat": None, "lon": None,
        "height_m": None, "dwd_station_id": None,
    }


def test_parse_station_mistyped_values_are_null():
    assert parse_station({"station_name": 5, "distance": "far", "lat": True,
                          "lon": [1.0], "height": None, "dwd_station_id": 433}) == {
        "name": None, "distance_m": None, "lat": None, "lon": None,
        "height_m": None, "dwd_station_id": None,
    }


def test_parse_station_keeps_json_numbers_as_is():
    s = parse_station({"station_name": "A", "distance": 5837.0, "lat": 52.5,
                       "lon": 13.4, "height": 47.7, "dwd_station_id": "00433"})
    assert s == {"name": "A", "distance_m": 5837.0, "lat": 52.5, "lon": 13.4,
                 "height_m": 47.7, "dwd_station_id": "00433"}


def test_station_and_fallback_without_sources():
    """No ``sources`` key (older payloads) or no payload at all."""
    assert station_and_fallback(None) == (None, {})
    assert station_and_fallback({}) == (None, {})
    assert station_and_fallback({"weather": {"source_id": 1}}) == (None, {})


def test_station_and_fallback_malformed_sources_key():
    payload = {"weather": {"source_id": 1, "fallback_source_ids": {"cloud_cover": 1}},
               "sources": "not a list"}
    assert station_and_fallback(payload) == (None, {})
    payload["sources"] = [{"id": 1, "station_name": "A", "distance": 2.0}, "junk"]
    assert station_and_fallback(payload) == (
        {"name": "A", "distance_m": 2.0, "lat": None, "lon": None,
         "height_m": None, "dwd_station_id": None},
        {"cloud_cover_pct": {"name": "A", "distance_m": 2.0}},
    )


def test_station_and_fallback_unlisted_and_uncarried_ids_left_out():
    payload = {
        "weather": {"source_id": 1, "fallback_source_ids": {
            "cloud_cover": 7,      # unlisted source
            "solar_60": 2,         # the API doesn't carry solar_60
            "dew_point": "x",      # mistyped id
            "temperature": True,   # a bool is not an id
        }},
        "sources": [{"id": 1, "station_name": "A", "distance": 1.0},
                    {"id": 2, "station_name": "B", "distance": 2.0}],
    }
    assert station_and_fallback(payload) == (
        {"name": "A", "distance_m": 1.0, "lat": None, "lon": None,
         "height_m": None, "dwd_station_id": None},
        {},
    )


def test_station_and_fallback_lists_every_carried_field():
    """One fallback entry per API field the payload's sources can cover."""
    fallback = {bs: 2 for bs in CURRENT_FIELDS}
    payload = {"weather": {"source_id": 1, "fallback_source_ids": fallback},
               "sources": [{"id": 1, "station_name": "A", "distance": 1.0},
                           {"id": 2, "station_name": "B", "distance": 2.0}]}
    station, got = station_and_fallback(payload)
    assert station is not None
    assert got == {api: {"name": "B", "distance_m": 2.0} for api in CURRENT_FIELDS.values()}
    # the API's own field names, in the order the mapping defines them
    assert list(got) == list(CURRENT_FIELDS.values())


# ---------------------------------------------------------------------------
# the observation stations
# ---------------------------------------------------------------------------

def test_observation_stations_counts_kept_records_nearest_first():
    got = observation_stations(BACKFILL_PAYLOAD, NOW15)
    assert got == [
        {"name": "Near", "distance_m": 1860.0, "lat": 52.51, "lon": 13.427,
         "dwd_station_id": "17473", "hours": 2},
        {"name": "Mid", "distance_m": 5576.0, "lat": 52.47, "lon": 13.4,
         "dwd_station_id": "00433", "hours": 1},
        {"name": "Far", "distance_m": 17000.0, "lat": 52.4, "lon": 13.6,
         "dwd_station_id": "00410", "hours": 1},
    ]


def test_observation_stations_counts_the_same_records_as_the_backfill():
    """The kept-record filter must agree with the backfill's, record for record."""
    assert sum(e["hours"] for e in observation_stations(BACKFILL_PAYLOAD, NOW15)) == len(
        parse_hourly_observations(BACKFILL_PAYLOAD, NOW15)
    )
    assert observation_stations({}, NOW15) == []
    assert parse_hourly_observations({}, NOW15) == []


def test_observation_stations_missing_keys_are_null():
    payload = {"weather": [{"timestamp": "2025-01-01T12:00:00Z", "source_id": 1, "precipitation": 0.1}],
               "sources": [{"id": 1, "station_name": 5, "distance": "far", "lat": True}]}
    assert observation_stations(payload, NOW15) == [
        {"name": None, "distance_m": None, "lat": None, "lon": None,
         "dwd_station_id": None, "hours": 1},
    ]


def test_observation_stations_malformed_payloads_are_empty():
    assert observation_stations(None, NOW15) == []
    assert observation_stations({"weather": "nope", "sources": [1]}, NOW15) == []
    payload = {"weather": [1, {"timestamp": "2025-01-01T12:00:00Z", "source_id": 1,
                               "precipitation": 0.1, "junk": 1}],
               "sources": "not a list"}
    assert observation_stations(payload, NOW15) == []
    # an unhashable id matches nothing but must not raise
    payload = {"weather": [{"timestamp": "2025-01-01T12:00:00Z", "source_id": [1], "precipitation": 0.1},
                           {"timestamp": "2025-01-01T13:00:00Z", "source_id": 2, "precipitation": 0.1}],
               "sources": [{"id": [1], "station_name": "A"}, {"id": 2, "station_name": "B",
                                                               "distance": 1.0}]}
    assert [e["name"] for e in observation_stations(payload, NOW15)] == ["B"]


def test_observation_stations_sorts_distanceless_last_and_ties_by_name():
    payload = {
        "weather": [
            {"timestamp": f"2025-01-01T{h}:00:00Z", "source_id": i + 1, "precipitation": 0.1}
            for i, h in enumerate(("10", "11", "12", "13"))
        ],
        "sources": [
            {"id": 1, "station_name": "B", "distance": 10.0},
            {"id": 2, "station_name": "A", "distance": 10.0},
            {"id": 3, "station_name": "NoDistance"},
            {"id": 4, "station_name": "Z", "distance": None},
        ],
    }
    assert [e["name"] for e in observation_stations(payload, NOW15)] == ["A", "B", "NoDistance", "Z"]


def test_stations_to_json_is_canonical():
    assert OBSERVATION_STATIONS_KEY == "observation_stations"
    stations = [{"name": "Berlin-Müggelsee", "distance_m": 17000.0, "lat": 52.44,
                 "lon": 13.65, "dwd_station_id": "00410", "hours": 1}]
    raw = stations_to_json(stations)
    assert raw == json.dumps(stations, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert raw.startswith('[{"distance_m":17000.0,"dwd_station_id":"00410"')
    assert "Müggelsee" in raw
    assert stations_from_json(raw) == stations
    assert stations_from_json(None) == []


def test_stations_from_json_broken_values_read_as_empty():
    ok = {"name": "A", "distance_m": 1.0, "lat": 0.0, "lon": 0.0, "dwd_station_id": "1", "hours": 1}
    assert stations_from_json(json.dumps([ok])) == [ok]
    assert stations_from_json(None) == []
    assert stations_from_json("{not json") == []
    assert stations_from_json("{}") == []
    assert stations_from_json('"a string"') == []
    assert stations_from_json("[1]") == []
    bad = [
        {**ok, "hours": -1},          # negative
        {**ok, "hours": True},        # a bool is not an integer
        {**ok, "hours": 1.0},         # a float is not an integer
        {**ok, "hours": "1"},
        {**ok} | {"hours": None},
        {**ok, "name": 1},            # mistyped name
        {**ok, "distance_m": "far"},
        {**ok, "dwd_station_id": 433},
        {"name": "A"},                # hours is required
    ]
    for entry in bad:
        assert stations_from_json(json.dumps([entry])) == [], entry
    # a missing optional key reads as null (full six-key shape)
    assert stations_from_json('[{"name": "A", "hours": 0}]') == [
        {"name": "A", "distance_m": None, "lat": None, "lon": None, "dwd_station_id": None, "hours": 0}
    ]
