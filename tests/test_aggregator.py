"""Integration tests for the aggregator (cache + probability pipeline).

Clients are stubbed (no network); the Store is a real in-memory SQLite db;
the clock is monkeypatched on ``app.aggregator.utcnow`` for determinism.
The stubs and payload builders live in ``tests/aggregator_support.py``;
the ``all_payloads``/``store``/``frozen_now`` fixtures in ``conftest.py``.
"""
from __future__ import annotations

import pytest

from app.aggregator import Aggregator
from tests.aggregator_support import (
    StubBrightSky,
    StubOpenMeteo,
    current_payload,
    make_aggregator,
    make_cfg,
    radar_payload,
)


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


def _accuracy_rows(
    model: str, n: int, start_hour: int = 11, issued_at: str = "2024-12-20T00:00:00Z"
):
    """n compared forecast rows for one model, all inside the 30-day window.

    Rows start at ``start_hour`` so different models can occupy different
    hours (``set_observation`` matches on ``valid_from`` only, so shared
    hours would pick up each other's observations).
    """
    return [
        {
            "model": model,
            "issued_at": issued_at,
            "valid_from": f"2024-12-20T{start_hour + i:02d}:00:00Z",
            "valid_to": f"2024-12-20T{start_hour + i + 1:02d}:00:00Z",
            "precip_mm": 0.4,
        }
        for i in range(n)
    ]


async def test_get_rain_probability_accuracy_weights_applied(store, all_payloads, frozen_now):
    # icon_d2 (rains, vote 0.4 mm): 1 hit + 1 false alarm -> event_accuracy
    # 0.5. icon_eu (dry): 2 false alarms -> event_accuracy 0.0, weight
    # floored at 0.1. Both have >= min_samples=2, so the gate passes and the
    # model signal is weighted: 100 * 0.5 / (0.5 + 0.1) = 83.33 (plain: 50).
    # radar 100, ensemble 50 -> 0.5*100 + 0.3*83.33 + 0.2*50 = 85
    await store.add_forecasts(_accuracy_rows("icon_d2", 2, start_hour=11))
    await store.add_forecasts(_accuracy_rows("icon_eu", 2, start_hour=13))
    await store.set_observation("2024-12-20T11:00:00Z", 0.3)  # icon_d2: hit
    await store.set_observation("2024-12-20T12:00:00Z", 0.0)  # icon_d2: false alarm
    await store.set_observation("2024-12-20T13:00:00Z", 0.0)  # icon_eu: false alarm
    await store.set_observation("2024-12-20T14:00:00Z", 0.0)  # icon_eu: false alarm

    agg = make_aggregator(
        make_cfg(use_accuracy_weights=True, min_samples=2), store, all_payloads, all_payloads
    )
    await agg.refresh_radar()
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    assert prob.probability_pct == pytest.approx(85.0)
    assert "accuracy-weighted" in prob.explanation
    assert prob.accuracy_weighted is True
    # the equal-weight counts still feed the explanation
    assert "1 of 2 models" in prob.explanation


async def test_get_rain_probability_accuracy_gate_falls_back(
    store, all_payloads, frozen_now
):
    # only icon_d2 has compared hours (1 < min_samples=2) -> gate fails,
    # the plain equal-weight model signal (50) is used, no "accuracy-
    # weighted" in the explanation.
    await store.add_forecasts(_accuracy_rows("icon_d2", 1))
    await store.set_observation("2024-12-20T11:00:00Z", 0.3)

    agg = make_aggregator(
        make_cfg(use_accuracy_weights=True, min_samples=2), store, all_payloads, all_payloads
    )
    await agg.refresh_radar()
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    # radar 100, models 50, ensemble 50 -> 0.5*100 + 0.3*50 + 0.2*50 = 75
    assert prob.probability_pct == pytest.approx(75.0)
    assert "accuracy-weighted" not in prob.explanation
    assert prob.accuracy_weighted is False


async def test_get_rain_probability_no_weights_when_disabled(store, all_payloads, frozen_now):
    # flag off + accuracy data present -> equal weights, no mention
    await store.add_forecasts(_accuracy_rows("icon_d2", 2, start_hour=11))
    await store.add_forecasts(_accuracy_rows("icon_eu", 2, start_hour=13))
    await store.set_observation("2024-12-20T11:00:00Z", 0.3)
    await store.set_observation("2024-12-20T12:00:00Z", 0.0)
    await store.set_observation("2024-12-20T13:00:00Z", 0.0)
    await store.set_observation("2024-12-20T14:00:00Z", 0.0)

    agg = make_aggregator(make_cfg(use_accuracy_weights=False), store, all_payloads, all_payloads)
    await agg.refresh_radar()
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    assert prob.probability_pct == pytest.approx(75.0)
    assert "accuracy-weighted" not in prob.explanation
    assert prob.accuracy_weighted is False


async def test_get_rain_probability_accuracy_read_failure_falls_back(
    store, all_payloads, frozen_now, monkeypatch
):
    # flag on + the accuracy read raising (e.g. database error) must not
    # break the headline number: equal weights are used and the explanation
    # does not claim accuracy weighting
    async def _boom(self, since_iso):
        raise RuntimeError("database error")

    monkeypatch.setattr("app.store.Store.compared_forecasts", _boom)

    agg = make_aggregator(
        make_cfg(use_accuracy_weights=True, min_samples=2), store, all_payloads, all_payloads
    )
    await agg.refresh_radar()
    await agg.refresh_models()
    prob = await agg.get_rain_probability()
    # radar 100, models 50 (equal weights), ensemble 50 -> 0.5*100 + 0.3*50 + 0.2*50 = 75
    assert prob.probability_pct == pytest.approx(75.0)
    assert prob.weights_used == {"radar": 0.5, "models": 0.3, "ensemble": 0.2}
    assert "accuracy-weighted" not in prob.explanation
    assert prob.accuracy_weighted is False


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


async def test_get_current_conditions_malformed_cache_returns_none(store):
    # a corrupted/malformed cached payload must degrade to "no data"
    # (None), not raise — the request path must never 500 on bad data
    bad = current_payload()
    bad["weather"]["temperature"] = "not-a-number"
    await store.put_cache("current", bad)
    agg = make_aggregator(make_cfg(), store)
    assert await agg.get_current_conditions() is None
