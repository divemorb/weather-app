"""The weather icon behind the page's sky (sky step A1).

``/api/now`` passes Bright Sky's ``current_weather`` ``icon`` through as
``conditions.icon``: one of the twelve values Bright Sky documents, or null
when the payload has none or an unknown value. The page picks its animated
sky from it.

The API runs on a real Aggregator with an in-memory Store and stubbed
clients, so these tests fix the JSON contract, not internal names.
"""
from __future__ import annotations

import pytest

from tests.aggregator_support import current_payload, make_aggregator, make_cfg, make_payloads

# Bright Sky's documented values (https://api.brightsky.dev/openapi.json, 2026-10-03)
ICONS = [
    "clear-day", "clear-night", "partly-cloudy-day", "partly-cloudy-night", "cloudy", "fog",
    "wind", "rain", "sleet", "snow", "hail", "thunderstorm",
]
MISSING = object()


async def get_now(store, client, icon) -> dict:
    payload = current_payload()
    if icon is not MISSING:
        payload["weather"]["icon"] = icon
    payloads = dict(make_payloads(), current=payload)
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    await agg.refresh_radar()
    await agg.refresh_models()
    r = client(agg).get("/api/now")
    assert r.status_code == 200
    return r.json()["conditions"]


@pytest.mark.parametrize("icon", ICONS)
async def test_now_icon_passed_through(store, client, frozen_now, icon):
    cond = await get_now(store, client, icon)
    assert cond["icon"] == icon
    assert cond["condition"] == "Rain"  # unchanged


@pytest.mark.parametrize("icon", [MISSING, None, "", "tornado", "Rain", "CLEAR-DAY", 5, ["rain"]])
async def test_now_icon_null_when_missing_or_unknown(store, client, frozen_now, icon):
    cond = await get_now(store, client, icon)
    assert "icon" in cond
    assert cond["icon"] is None


async def test_now_without_observation_has_no_conditions(store, client, frozen_now):
    """No cached observation: ``conditions`` stays null (no icon key to read)."""
    payloads = dict(make_payloads(), current=None)
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    r = client(agg).get("/api/now")
    assert r.status_code == 200
    assert r.json()["conditions"] is None
