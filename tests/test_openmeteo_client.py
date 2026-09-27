"""Unit tests for the Open-Meteo client (parsers + HTTP layer).

Parser tests use synthetic multi-model / ensemble payloads (no network).
HTTP-layer tests use ``httpx.MockTransport``.
"""
from __future__ import annotations

import pytest
import httpx

from app.openmeteo_client import OpenMeteoClient, parse_forecast, parse_ensemble
from app.brightsky_client import SourceError
from tests.helpers import make_cfg, make_forecast_payload, make_ensemble_payload


HOURS = ["2026-09-25T00:00", "2026-09-25T01:00", "2026-09-25T02:00", "2026-09-25T03:00"]
MIN15 = [
    "2026-09-25T00:00",
    "2026-09-25T00:15",
    "2026-09-25T00:30",
    "2026-09-25T00:45",
    "2026-09-25T01:00",
    "2026-09-25T01:15",
    "2026-09-25T01:30",
    "2026-09-25T01:45",
]


def _forecast_payload():
    return make_forecast_payload(
        model_names=["icon_d2", "icon_eu"],
        hours=HOURS,
        min15=MIN15,
        precip_per_model={
            "icon_d2": [0.0, 0.5, 0.0, 0.0],
            "icon_eu": [0.0, 0.0, 0.0, 0.0],
        },
        min15_precip_per_model={
            "icon_d2": [0.0, 0.2, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0],
            "icon_eu": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        extra_hourly={
            "apparent_temperature": {
                "icon_d2": [5.0, 6.0, 7.0, 8.0],
                "icon_eu": [4.0, 5.0, 6.0, 7.0],
            },
            "wind_speed_10m": {
                "icon_d2": [10.0, 12.0, 14.0, 16.0],
                "icon_eu": [8.0, 9.0, 10.0, 11.0],
            },
            "temperature_2m": {
                "icon_d2": [5.0, 6.0, 7.0, 8.0],
                "icon_eu": [4.0, 5.0, 6.0, 7.0],
            },
            "cloud_cover": {
                "icon_d2": [10.0, 20.0, 30.0, 40.0],
                "icon_eu": [5.0, 6.0, 7.0, 8.0],
            },
        },
    )


# ---------------------------------------------------------------------------
# parse_forecast
# ---------------------------------------------------------------------------
def test_parse_forecast_all_models_present():
    bundle = parse_forecast(_forecast_payload(), ["icon_d2", "icon_eu"])
    names = [m.name for m in bundle.models]
    assert names == ["icon_d2", "icon_eu"]
    assert len(bundle.models) == 2


def test_parse_forecast_maps_hourly_series():
    bundle = parse_forecast(_forecast_payload(), ["icon_d2"])
    m = bundle.by_name("icon_d2")
    assert m.hourly_precip_mm == [0.0, 0.5, 0.0, 0.0]
    assert m.hourly_apparent_c == [5.0, 6.0, 7.0, 8.0]
    assert m.hourly_wind_kmh == [10.0, 12.0, 14.0, 16.0]
    assert m.hourly_cloud_cover_pct == [10.0, 20.0, 30.0, 40.0]
    assert len(m.hourly_time) == 4
    assert m.hourly_time[0].year == 2026


def test_parse_forecast_maps_min15_series():
    bundle = parse_forecast(_forecast_payload(), ["icon_d2"])
    m = bundle.by_name("icon_d2")
    assert m.min15_precip_mm == [0.0, 0.2, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert len(m.min15_time) == 8


def test_parse_forecast_tolerance_for_nulls():
    payload = _forecast_payload()
    payload["hourly"]["precipitation_icon_d2"] = [None, 0.5, None, 0.0]
    bundle = parse_forecast(payload, ["icon_d2"])
    assert bundle.by_name("icon_d2").hourly_precip_mm == [None, 0.5, None, 0.0]


def test_parse_forecast_missing_model_key_gives_empty():
    # Request a model that has no suffixed keys in the payload.
    bundle = parse_forecast(_forecast_payload(), ["gfs_seamless"])
    m = bundle.by_name("gfs_seamless")
    assert m.hourly_precip_mm == []
    assert m.min15_precip_mm == []


def test_parse_forecast_error_flag_raises():
    with pytest.raises(SourceError):
        parse_forecast({"error": True, "reason": "bad lat"}, ["icon_d2"])


# ---------------------------------------------------------------------------
# parse_ensemble
# ---------------------------------------------------------------------------
def _ensemble_payload():
    # 4 hours, control + 3 members (member01..03)
    return make_ensemble_payload(
        hours=HOURS,
        control=[0.0, 0.1, 0.2, 0.3],
        members=[
            [0.0, 0.5, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0],
            [0.2, 0.2, 0.2, 0.2],
        ],
    )


def test_parse_ensemble_member_count_and_order():
    data = parse_ensemble(_ensemble_payload())
    assert data.n_members == 3
    assert data.control_precip_mm == [0.0, 0.1, 0.2, 0.3]
    # members are ordered by number
    assert data.member_precip_mm[0] == [0.0, 0.5, 0.0, 0.0]
    assert data.member_precip_mm[2] == [0.2, 0.2, 0.2, 0.2]
    assert len(data.hourly_time) == 4


def test_parse_ensemble_zero_members():
    payload = make_ensemble_payload(hours=HOURS, control=[0.0, 0.0], members=[])
    data = parse_ensemble(payload)
    assert data.n_members == 0
    assert data.member_precip_mm == []


def test_parse_ensemble_error_flag_raises():
    with pytest.raises(SourceError):
        parse_ensemble({"error": True, "reason": "no ensemble"})


# ---------------------------------------------------------------------------
# HTTP layer (mock transport, no network)
# ---------------------------------------------------------------------------
async def test_client_forecast_builds_correct_params():
    cfg = make_cfg(forecast=("icon_d2", "icon_eu"))
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_forecast_payload())

    client = OpenMeteoClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    bundle = await client.fetch_forecast()
    assert len(bundle.models) == 2
    assert "/forecast" in seen["url"]
    assert seen["params"].get("models") == "icon_d2,icon_eu"
    assert seen["params"].get("timezone") == "UTC"
    # 3 days so 24 *future* hours remain even late in the UTC day (step 6b)
    assert seen["params"].get("forecast_days") == "3"
    await client.aclose()


async def test_client_ensemble_builds_correct_params():
    cfg = make_cfg(ensemble_model="ecmwf_ifs025")
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_ensemble_payload())

    client = OpenMeteoClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    data = await client.fetch_ensemble()
    assert data.n_members == 3
    assert "/ensemble" in seen["url"]
    assert seen["params"].get("models") == "ecmwf_ifs025"
    await client.aclose()


async def test_client_api_error_json_raises_source_error():
    cfg = make_cfg()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": True, "reason": "invalid model"})

    client = OpenMeteoClient(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(SourceError):
        await client.fetch_forecast()
    await client.aclose()
