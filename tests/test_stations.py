"""Unit tests for the pure station parsers (``app/stations.py``, step P1).

The spec tests (``tests/test_station.py``, ``test_now_*``) fix the JSON
contract through the API; these pin the parser's behaviour on untrusted
payload shapes (missing ``sources`` key, missing/mistyped entry keys).
"""
from __future__ import annotations

from app.stations import CURRENT_FIELDS, parse_station, station_and_fallback


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
