"""Integration tests for the aggregator (cache + probability pipeline).

Clients are stubbed (no network); the Store is a real in-memory SQLite db;
the clock is monkeypatched on ``app.aggregator.utcnow`` for determinism.
"""
from __future__ import annotations

import base64
import zlib
from array import array
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.aggregator import Aggregator
from app.brightsky_client import SourceError
from app.config import (
    AccuracyConfig,
    ApiConfig,
    AppConfig,
    LocationConfig,
    ModelsConfig,
    ProbabilityConfig,
    RadarConfig,
    SchedulingConfig,
)
from app.store import Store

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


def make_cfg(stale_radar: int = 10, stale_models: int = 120) -> AppConfig:
    return AppConfig(
        location=LocationConfig(latitude=52.0, longitude=13.0),
        radar=RadarConfig(radius_km=5.0, grid_size_km=1.0, step_minutes=5),
        probability=ProbabilityConfig(
            weight_radar=0.5,
            weight_models=0.3,
            weight_ensemble=0.2,
            model_rain_threshold_mm=0.1,
            radar_cell_rain_threshold_mm=0.05,
        ),
        models=ModelsConfig(
            forecast=("icon_d2", "icon_eu"), ensemble_model="ecmwf_ifs025"
        ),
        scheduling=SchedulingConfig(stale_radar_minutes=stale_radar, stale_models_minutes=stale_models),
        accuracy=AccuracyConfig(window_days=30, min_samples=48),
        api=ApiConfig(),
        database_path=":memory:",
    )


class StubBrightSky:
    """Bright Sky stand-in: canned payloads, optional forced failures."""

    def __init__(self, payloads: dict, errors: tuple = ()):
        self._p = payloads
        self._e = set(errors)

    async def fetch_current_payload(self):
        if "current" in self._e:
            raise SourceError("current down")
        return self._p["current"]

    async def fetch_radar_payload(self):
        if "radar" in self._e:
            raise SourceError("radar down")
        return self._p["radar"]

    async def fetch_weather_payload(self, start, end):
        if "weather" in self._e:
            raise SourceError("weather down")
        if "weather" in self._p:
            return self._p["weather"]
        raise SourceError("weather not configured")


class StubOpenMeteo:
    def __init__(self, payloads: dict, errors: tuple = ()):
        self._p = payloads
        self._e = set(errors)

    async def fetch_forecast_payload(self):
        if "forecast" in self._e:
            raise SourceError("forecast down")
        return self._p["forecast"]

    async def fetch_ensemble_payload(self):
        if "ensemble" in self._e:
            raise SourceError("ensemble down")
        return self._p["ensemble"]


def radar_payload(frames: list[tuple[str, list[tuple[int, int, int]]]]) -> dict:
    """Bright Sky /radar payload; frames = (iso, [(x, y, raw 0.01mm), ...])."""
    w = h = 10
    out = []
    for iso, cells in frames:
        grid = [0] * (w * h)
        for x, y, v in cells:
            grid[y * w + x] = v
        enc = base64.b64encode(zlib.compress(array("H", grid).tobytes())).decode()
        out.append({"timestamp": iso, "precipitation_5": enc})
    return {"radar": out, "bbox": [0, 0, h - 1, w - 1], "latlon_position": {"x": 5.0, "y": 5.0}}


def current_payload() -> dict:
    return {"weather": {
        "timestamp": "2025-01-01T12:00:00Z", "source_id": 1,
        "temperature": 5.0, "wind_speed_10": 3.0, "wind_direction_10": 180.0,
        "wind_gust_speed_60": 6.0, "cloud_cover": 75.0, "relative_humidity": 80.0,
        "pressure_msl": 1015.0, "dew_point": 3.0,
        "precipitation_10": 0.0, "precipitation_30": 0.1, "precipitation_60": 0.2,
        "condition": "Rain",
    }}


def forecast_payload() -> dict:
    """icon_d2 rains 0.4 mm in the next hour; icon_eu stays dry; gfs null.

    The minutely_15 steps are stamped 12:15..13:00, i.e. strictly inside
    ``[NOW, NOW+1h)`` (a minutely_15 value at t covers [t-15min, t)), so at
    now = 12:00 all four steps fall in the next-hour window.

    The hourly axis is stamped NOW..NOW+71h (3-day fetch, see step 6b): with
    now = 12:00 the first *future* stamp is 13:00 (rain of 12:00-13:00), so
    icon_d2's 0.4 mm lands in the chart's first hour (labelled 12:00) and in
    the next-hour sum. gfs carries all-null precipitation to cover the
    "model with null data is skipped" path.
    """
    m15 = [
        (NOW + timedelta(minutes=15 + 15 * i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for i in range(4)
    ]
    h72 = [(NOW + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(72)]
    return {
        "minutely_15": {
            "time": m15,
            "precipitation_icon_d2": [0.1, 0.1, 0.1, 0.1],
            "precipitation_icon_eu": [0.0, 0.0, 0.0, 0.0],
        },
        "hourly": {
            "time": h72,
            "precipitation_icon_d2": [0.0] + [0.4] + [0.0] * 70,
            "precipitation_icon_eu": [0.0] * 72,
            "precipitation_gfs": [None] * 72,
            "temperature_2m_icon_d2": [5.0] * 72,
            "apparent_temperature_icon_d2": [3.5] * 72,
            "wind_speed_10m_icon_d2": [10.0] * 72,
            "cloud_cover_icon_d2": [70.0] * 72,
            "temperature_2m_icon_eu": [4.0] * 72,
            "apparent_temperature_icon_eu": [2.0] * 72,
            "wind_speed_10m_icon_eu": [8.0] * 72,
            "cloud_cover_icon_eu": [60.0] * 72,
        },
    }


def ensemble_payload() -> dict:
    """member01 rains (1 mm) in the next hour; member02 stays dry. The steps
    are stamped 13:00..16:00, so at now = 12:00 the first step after now
    (13:00, covering 12:00-13:00) is the next hour."""
    h4 = [(NOW + timedelta(hours=1 + i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(4)]
    return {"hourly": {
        "time": h4,
        "precipitation": [0.5, 0.0, 0.0, 0.0],
        "precipitation_member01": [1.0, 0.0, 0.0, 0.0],
        "precipitation_member02": [0.0, 0.0, 0.0, 0.0],
    }}


@pytest.fixture
def all_payloads() -> dict:
    return {
        "current": current_payload(),
        "radar": radar_payload([("2025-01-01T12:00:00Z", [(5, 5, 20)])]),  # 0.2 mm at location
        "forecast": forecast_payload(),
        "ensemble": ensemble_payload(),
    }


@pytest_asyncio.fixture
async def store() -> Store:
    s = Store(":memory:")
    await s.connect()
    yield s
    await s.close()


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr("app.aggregator.utcnow", lambda: NOW)


def make_aggregator(cfg, store, bs=None, om=None, errors=()) -> Aggregator:
    return Aggregator(cfg, store, StubBrightSky(bs or {}, errors), StubOpenMeteo(om or {}, errors))


# ---------------------------------------------------------------------------
# refresh + cache
# ---------------------------------------------------------------------------
async def test_refresh_radar_caches_payloads(store, all_payloads):
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads)
    await agg.refresh_radar()
    current, age_c = await store.get_cache("current")
    radar, age_r = await store.get_cache("radar")
    assert current["weather"]["temperature"] == 5.0
    assert radar["bbox"] == [0, 0, 9, 9]
    assert age_c is not None and age_r is not None


async def test_refresh_radar_tolerates_one_failing_source(store, all_payloads):
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads, errors=("current",))
    await agg.refresh_radar()  # must not raise
    _p, age_c = await store.get_cache("current")
    _p, age_r = await store.get_cache("radar")
    assert age_c is None  # current never fetched
    assert age_r is not None  # radar still cached

    status = await agg.get_source_status()
    assert status["current"]["available"] is False
    assert status["current"]["last_error"] == "current down"
    assert status["radar"]["available"] is True
    assert status["radar"]["last_error"] is None
    assert status["radar"]["stale"] is False


async def test_refresh_models_writes_forecast_history(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads)
    await agg.refresh_models()
    async with store._db.execute(
        "SELECT model, valid_from, valid_to FROM forecast_history"
    ) as cur:
        rows = await cur.fetchall()
    # icon_d2 + icon_eu: 24 *future* hours each (gfs has null data -> 0 rows);
    # the hour ending at NOW (11:00-12:00, stamp 12:00) is past and not stored
    assert len(rows) == 48
    assert {r["model"] for r in rows} == {"icon_d2", "icon_eu"}
    for r in rows:
        # each row covers one hour that has not started yet at issued_at
        assert r["valid_from"] >= "2025-01-01T12:00:00Z"
        assert r["valid_to"] > r["valid_from"]


async def test_refresh_models_tolerates_ensemble_failure(store, all_payloads):
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads, errors=("ensemble",))
    await agg.refresh_models()  # must not raise
    _p, age_f = await store.get_cache("forecast")
    _p, age_e = await store.get_cache("ensemble")
    assert age_f is not None
    assert age_e is None
    status = await agg.get_source_status()
    assert status["ensemble"]["last_error"] == "ensemble down"


async def test_source_status_marks_stale(store, all_payloads):
    agg = make_aggregator(make_cfg(stale_radar=0, stale_models=0), store, all_payloads, all_payloads)
    await agg.refresh_radar()
    status = await agg.get_source_status()
    assert status["radar"]["stale"] is True  # age > 0 with threshold 0
    assert status["radar"]["age_seconds"] is not None


# ---------------------------------------------------------------------------
# read model
# ---------------------------------------------------------------------------
async def test_get_current_conditions_with_feels_like(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads)
    await agg.refresh_radar()
    await agg.refresh_models()
    cond = await agg.get_current_conditions()
    assert cond is not None
    assert cond.temperature_c == 5.0
    assert cond.condition == "Rain"
    assert cond.feels_like_c == 3.5  # from icon_d2 apparent_temperature


async def test_get_current_conditions_empty_cache(store):
    agg = make_aggregator(make_cfg(), store)
    assert await agg.get_current_conditions() is None


async def test_get_rain_probability_all_signals(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, all_payloads, all_payloads)
    await agg.refresh_radar()
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    # radar 100, models 50, ensemble 50 -> 0.5*100 + 0.3*50 + 0.2*50 = 75
    assert prob.probability_pct == pytest.approx(75.0)
    assert prob.radar_available is True
    assert prob.radar_raining is True
    assert (prob.models_rain_count, prob.models_total) == (1, 2)
    assert prob.ensemble_pct == pytest.approx(50.0)
    assert abs(sum(prob.weights_used.values()) - 1.0) < 1e-9
    assert "1 of 2 models" in prob.explanation


async def test_get_rain_probability_without_radar(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, None, all_payloads)  # no radar
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    # models 50, ensemble 50 -> renormalized 0.6/0.4 -> 50
    assert prob.probability_pct == pytest.approx(50.0)
    assert prob.radar_available is False
    assert prob.radar_raining is None
    assert abs(prob.weights_used["models"] - 0.6) < 1e-9
    assert abs(prob.weights_used["ensemble"] - 0.4) < 1e-9
    assert "Radar: not available" in prob.explanation


async def test_get_rain_probability_radar_dry(store, all_payloads, frozen_now):
    payloads = dict(all_payloads, radar=radar_payload([("2025-01-01T12:00:00Z", [])]))
    agg = make_aggregator(make_cfg(), store, payloads, payloads)
    await agg.refresh_radar()
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    # 0.5*0 + 0.3*50 + 0.2*50 = 25
    assert prob.radar_available is True
    assert prob.radar_raining is False
    assert prob.probability_pct == pytest.approx(25.0)


async def test_get_rain_probability_no_data_at_all(store, frozen_now):
    agg = make_aggregator(make_cfg(), store)
    prob = await agg.get_rain_probability()
    assert prob.probability_pct == 0.0
    assert prob.weights_used == {}
    assert "No data" in prob.explanation


async def test_get_model_votes(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, None, all_payloads)
    await agg.refresh_models()
    votes = await agg.get_model_votes()
    by_name = {v.name: v.precip_next_hour_mm for v in votes}
    assert by_name == {"icon_d2": pytest.approx(0.4), "icon_eu": pytest.approx(0.0)}


async def test_get_ensemble_vote(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, None, all_payloads)
    await agg.refresh_models()
    vote = await agg.get_ensemble_vote()
    assert vote.probability_pct == pytest.approx(50.0)
    assert (vote.n_members, vote.n_rain_members) == (2, 1)


async def test_get_24h_model_comparison(store, all_payloads, frozen_now):
    agg = make_aggregator(make_cfg(), store, None, all_payloads)
    await agg.refresh_models()
    series = await agg.get_24h_model_comparison()
    # the axis is relative to now: first hour = current hour (12:00),
    # 24 entries; the model with null data (gfs) is skipped
    assert len(series["hours"]) == 24
    assert series["hours"][0] == "2025-01-01T12:00:00Z"
    assert series["hours"][1] == "2025-01-01T13:00:00Z"
    assert series["n_models"] == 2
    names = {m["name"] for m in series["models"]}
    assert names == {"icon_d2", "icon_eu"}
    icon_d2 = next(m for m in series["models"] if m["name"] == "icon_d2")
    # the value at hour 12:00 comes from the stamp at 13:00 (rain of
    # 12:00-13:00) -> the 0.4 mm is in the first bucket
    assert icon_d2["precipitation_mm"][0] == pytest.approx(0.4)
    assert icon_d2["precipitation_mm"][1] == pytest.approx(0.0)


async def test_get_model_accuracy_scores_window_only(store, all_payloads, frozen_now):
    await store.add_forecasts(
        [
            # inside the 30-day window: hit (0.4 vs 0.3) + false alarm (0.2 vs 0.0)
            {"model": "icon_d2", "issued_at": "2024-12-20T10:00:00Z",
             "valid_from": "2024-12-20T11:00:00Z", "valid_to": "2024-12-20T12:00:00Z",
             "precip_mm": 0.4},
            {"model": "icon_d2", "issued_at": "2024-12-20T12:00:00Z",
             "valid_from": "2024-12-20T13:00:00Z", "valid_to": "2024-12-20T14:00:00Z",
             "precip_mm": 0.2},
            # outside the window: must NOT be scored
            {"model": "icon_eu", "issued_at": "2024-11-01T10:00:00Z",
             "valid_from": "2024-11-01T11:00:00Z", "valid_to": "2024-11-01T12:00:00Z",
             "precip_mm": 9.0},
            # no observation yet (15:00 is never observed): must NOT be scored
            {"model": "icon_eu", "issued_at": "2024-12-20T14:00:00Z",
             "valid_from": "2024-12-20T15:00:00Z", "valid_to": "2024-12-20T16:00:00Z",
             "precip_mm": 1.0},
        ]
    )
    await store.set_observation("2024-12-20T11:00:00Z", 0.3)
    await store.set_observation("2024-12-20T13:00:00Z", 0.0)
    await store.set_observation("2024-11-01T11:00:00Z", 8.0)

    accuracy = await Aggregator(
        make_cfg(), store, StubBrightSky({}, ()), StubOpenMeteo({}, ())
    ).get_model_accuracy()
    assert set(accuracy) == {"icon_d2"}  # icon_eu has no in-window comparison
    d2 = accuracy["icon_d2"]
    assert d2["n_samples"] == 2
    # > 0.1 mm event: (0.4 vs 0.3) = hit, (0.2 vs 0.0) = false alarm
    assert (d2["hits"], d2["false_alarms"], d2["misses"], d2["correct_negatives"]) == (1, 1, 0, 0)
    assert d2["event_accuracy"] == pytest.approx(0.5)
    assert d2["mae_mm"] == pytest.approx(0.15)  # (0.1 + 0.2) / 2


async def test_get_model_accuracy_empty_history(store, frozen_now):
    agg = Aggregator(make_cfg(), store, StubBrightSky({}, ()), StubOpenMeteo({}, ()))
    assert await agg.get_model_accuracy() == {}


async def test_get_radar_nowcast_parses_frames(store, all_payloads):
    agg = make_aggregator(make_cfg(), store, all_payloads, None)
    await agg.refresh_radar()
    nowcast = await agg.get_radar_nowcast()
    assert nowcast is not None
    assert nowcast.covered is True
    assert len(nowcast.frames) == 1
    assert nowcast.frames[0].max_mm == pytest.approx(0.2)


async def test_get_radar_next_hour_builds_bar(store, frozen_now):
    # rain (0.3 mm) only in the +5 min frame, at the location
    bs = {
        "current": current_payload(),
        "radar": radar_payload([
            ("2025-01-01T12:00:00Z", []),
            ("2025-01-01T12:05:00Z", [(5, 5, 30)]),
        ]),
    }
    agg = make_aggregator(make_cfg(), store, bs, None)
    await agg.refresh_radar()
    bar = await agg.get_radar_next_hour()
    assert bar["available"] is True
    assert len(bar["steps"]) == 12
    assert bar["steps"][0]["precip_mm"] == 0.0
    assert bar["steps"][1]["precip_mm"] == pytest.approx(0.3)
    assert bar["steps"][1]["start_utc"] == "2025-01-01T12:05:00Z"


async def test_get_radar_next_hour_empty_cache(store):
    agg = make_aggregator(make_cfg(), store)
    bar = await agg.get_radar_next_hour()
    assert bar["available"] is False
    assert len(bar["steps"]) == 12
    assert all(s["precip_mm"] == 0.0 for s in bar["steps"])
