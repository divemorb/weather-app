"""Unit tests for the pure rain-probability logic (no I/O, no network).

These tests are the core of step 3: they pin down how the radar vote, the
model votes, the ensemble share, and the weighted combination behave —
including every fallback / edge case the aggregator relies on.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import ProbabilityConfig, RadarConfig
from app.models import (
    EnsembleData,
    ForecastBundle,
    ModelSeries,
    ModelVote,
    RadarCell,
    RadarFrame,
    RadarNowcast,
)
from app.probability import (
    build_explanation,
    cell_distance_km,
    combine_signals,
    ensemble_vote,
    max_local_rain_mm,
    model_rain_signal,
    model_votes,
    radar_has_local_rain,
    radar_rain_signal,
    sum_next_hour,
    weighted_model_signal,
)

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)

PROB = ProbabilityConfig(
    weight_radar=0.5,
    weight_models=0.3,
    weight_ensemble=0.2,
    model_rain_threshold_mm=0.1,
    radar_cell_rain_threshold_mm=0.05,
)
RADAR = RadarConfig(radius_km=5.0, grid_size_km=1.0, step_minutes=5)


# ---------------------------------------------------------------------------
# helpers to build normalized objects
# ---------------------------------------------------------------------------
def _cell(x: int, y: int, mm: float) -> RadarCell:
    return RadarCell(x=x, y=y, mm=mm)


def _frame(offset_min: int, cells: list[RadarCell]) -> RadarFrame:
    return RadarFrame(
        time_utc=NOW + timedelta(minutes=offset_min),
        cells=cells,
        max_mm=max((c.mm for c in cells), default=0.0),
    )


def _nowcast(frames, bbox=(0, 0, 10, 10), loc=(5.0, 5.0), covered=True) -> RadarNowcast:
    return RadarNowcast(frames=frames, covered=covered, bbox=bbox, location_xy=loc)


def _series(name: str, min15: list[float | None], hourly: list[float | None]) -> ModelSeries:
    base = NOW.replace(minute=0, second=0)
    return ModelSeries(
        name=name,
        min15_time=[base + timedelta(minutes=15 * i) for i in range(len(min15))],
        min15_precip_mm=min15,
        hourly_time=[base + timedelta(hours=i) for i in range(len(hourly))],
        hourly_precip_mm=hourly,
    )


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------
def test_cell_distance_zero_at_location():
    nc = _nowcast([_frame(0, [])])  # loc at (5, 5)
    assert cell_distance_km(nc, 5, 5, 1.0) == 0.0


def test_cell_distance_east_is_km():
    nc = _nowcast([_frame(0, [])])
    # 3 cells east, 1 km each -> 3 km
    assert cell_distance_km(nc, 8, 5, 1.0) == pytest.approx(3.0)


def test_cell_distance_diagonal():
    nc = _nowcast([_frame(0, [])])
    # 3 east, 4 north -> 5 km (3-4-5 triangle)
    assert cell_distance_km(nc, 8, 9, 1.0) == pytest.approx(5.0)


def test_cell_distance_uses_cell_size():
    nc = _nowcast([_frame(0, [])])
    assert cell_distance_km(nc, 6, 5, 2.0) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# max local rain per frame (feeds the next-hour bar)
# ---------------------------------------------------------------------------
def test_max_local_rain_strongest_in_radius():
    nc = _nowcast([_frame(0, [])])
    frame = _frame(0, [_cell(5, 5, 0.1), _cell(6, 5, 0.3), _cell(5, 6, 0.2)])
    assert max_local_rain_mm(nc, frame, 5.0, 1.0, 0.05) == pytest.approx(0.3)


def test_max_local_rain_ignores_outside_radius():
    nc = _nowcast([_frame(0, [])])
    # 0.5 mm at (20,5) is 15 km away (> 5 km radius); 0.2 at location stays
    frame = _frame(0, [_cell(5, 5, 0.2), _cell(20, 5, 0.5)])
    assert max_local_rain_mm(nc, frame, 5.0, 1.0, 0.05) == pytest.approx(0.2)


def test_max_local_rain_ignores_below_threshold():
    nc = _nowcast([_frame(0, [])])
    # 0.04 <= threshold 0.05 must not count even though it's at the location
    frame = _frame(0, [_cell(5, 5, 0.04)])
    assert max_local_rain_mm(nc, frame, 5.0, 1.0, 0.05) == 0.0


def test_max_local_rain_empty_frame_is_zero():
    nc = _nowcast([_frame(0, [])])
    assert max_local_rain_mm(nc, _frame(0, []), 5.0, 1.0, 0.05) == 0.0


# ---------------------------------------------------------------------------
# radar signal
# ---------------------------------------------------------------------------
def test_radar_rain_when_cell_in_radius_exceeds_threshold():
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.2)])])  # at location, 0.2 > 0.05
    available, raining = radar_rain_signal(nc, NOW, RADAR, PROB)
    assert available is True
    assert raining is True


def test_radar_no_rain_when_cell_below_threshold():
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.03)])])  # 0.03 <= 0.05
    available, raining = radar_rain_signal(nc, NOW, RADAR, PROB)
    assert available is True
    assert raining is False


def test_radar_ignores_cell_outside_radius():
    nc = _nowcast([_frame(0, [_cell(20, 5, 0.5)])])  # 15 km east > 5 km radius
    available, raining = radar_rain_signal(nc, NOW, RADAR, PROB)
    assert raining is False


def test_radar_ignores_frame_outside_horizon():
    # rain in a frame 2 h out (beyond the 1 h nowcast window) must be ignored
    nc = _nowcast([_frame(120, [_cell(5, 5, 0.5)])])
    available, raining = radar_rain_signal(nc, NOW, RADAR, PROB)
    assert raining is False


def test_radar_ignores_past_frame():
    # a frame stamped in the past (stale cache) must not count
    nc = RadarNowcast(
        frames=[RadarFrame(time_utc=NOW - timedelta(minutes=5), cells=[_cell(5, 5, 0.5)])],
        bbox=(0, 0, 10, 10),
        location_xy=(5.0, 5.0),
    )
    _, raining = radar_rain_signal(nc, NOW, RADAR, PROB)
    assert raining is False


def test_radar_unavailable_when_not_covered():
    nc = _nowcast([_frame(0, [_cell(5, 5, 0.5)])], covered=False)
    available, raining = radar_rain_signal(nc, NOW, RADAR, PROB)
    assert available is False
    assert raining is None


def test_radar_unavailable_when_none_or_empty():
    assert radar_rain_signal(None, NOW, RADAR, PROB) == (False, None)
    assert radar_rain_signal(_nowcast([]), NOW, RADAR, PROB) == (False, None)


def test_radar_has_local_rain_scans_all_frames():
    # dry now, rain at +10 min within radius
    nc = _nowcast([_frame(0, []), _frame(10, [_cell(6, 5, 0.3)])])
    assert radar_has_local_rain(nc, NOW, timedelta(hours=1), 5.0, 1.0, 0.05) is True


# ---------------------------------------------------------------------------
# model votes
# ---------------------------------------------------------------------------
def test_sum_next_hour_skips_step_stamped_at_now():
    # minutely_15 value at t covers [t-15min, t): the step stamped NOW
    # (11:45-12:00) is the past quarter hour, so the window [NOW, NOW+1h)
    # is the four steps stamped 12:15..13:00.
    t = [NOW + timedelta(minutes=15 * i) for i in range(5)]
    v = [1.0, 2.0, 3.0, 4.0, 99.0]  # 1.0 is the past step -> not summed
    assert sum_next_hour(t, v, NOW) == pytest.approx(2.0 + 3.0 + 4.0 + 99.0)


def test_sum_next_hour_none_on_missing_value():
    t = [NOW + timedelta(minutes=15 * i) for i in range(4)]
    v = [1.0, None, 3.0, 4.0]
    assert sum_next_hour(t, v, NOW) is None


def test_sum_next_hour_none_when_no_step_in_window():
    # series already stale (all steps before now)
    t = [NOW - timedelta(hours=1) + timedelta(minutes=15 * i) for i in range(4)]
    v = [1.0, 1.0, 1.0, 1.0]
    assert sum_next_hour(t, v, NOW) is None


def test_sum_next_hour_empty_is_none():
    assert sum_next_hour([], [], NOW) is None


def test_model_votes_per_model():
    # steps are stamped NOW..NOW+45min; the step stamped NOW covers the past
    # 15 minutes, so the window [NOW, NOW+1h) is the last three steps.
    bundle = ForecastBundle(
        models=[
            _series("a", [1.0, 1.0, 1.0, 1.0], []),  # 1+1+1 = 3.0 mm in window
            _series("b", [0.0, 0.0, 0.0, 0.0], []),  # 0.0 mm
            _series("c", [1.0, 1.0, None, 1.0], []),  # None in window -> missing
        ]
    )
    votes = model_votes(bundle, NOW)
    assert [v.name for v in votes] == ["a", "b", "c"]
    assert votes[0].precip_next_hour_mm == pytest.approx(3.0)
    assert votes[1].precip_next_hour_mm == pytest.approx(0.0)
    assert votes[2].precip_next_hour_mm is None


def test_model_votes_none_bundle():
    assert model_votes(None, NOW) == []


def test_model_rain_signal_share():
    votes = [
        ModelVote(name="a", precip_next_hour_mm=0.5),  # rain
        ModelVote(name="b", precip_next_hour_mm=0.0),  # dry
        ModelVote(name="c", precip_next_hour_mm=2.0),  # rain
        ModelVote(name="d", precip_next_hour_mm=None),  # doesn't count
    ]
    share, n_rain, n_total = model_rain_signal(votes, 0.1)
    assert n_total == 3
    assert n_rain == 2
    assert share == pytest.approx(200.0 / 3.0)


def test_model_rain_signal_all_missing():
    share, n_rain, n_total = model_rain_signal(
        [ModelVote(name="a", precip_next_hour_mm=None)], 0.1
    )
    assert share is None
    assert (n_rain, n_total) == (0, 0)


def test_model_rain_signal_boundary_at_threshold():
    # exactly == threshold is NOT rain (strict >)
    votes = [ModelVote(name="a", precip_next_hour_mm=0.1)]
    _, n_rain, _ = model_rain_signal(votes, 0.1)
    assert n_rain == 0


# ---------------------------------------------------------------------------
# accuracy-weighted model signal (step 6g)
# ---------------------------------------------------------------------------
def _vote(name: str, mm: float | None) -> ModelVote:
    return ModelVote(name=name, precip_next_hour_mm=mm)


def test_weighted_signal_equal_accuracy_matches_plain_signal():
    # all accuracies 1.0 (>= min_samples) -> equal weights -> same as
    # model_rain_signal: 1 of 3 voting models has rain -> 100/3 %
    votes = [
        _vote("a", 0.5),  # rain
        _vote("b", 0.0),  # dry
        _vote("c", 2.0),  # rain
    ]
    accuracy = {
        n: {"n_samples": 100, "event_accuracy": 1.0, "mae_mm": 0.0} for n in "abc"
    }
    signal, n_rain, n_total, weighted = weighted_model_signal(votes, accuracy, 0.1, 48)
    plain, plain_rain, plain_total = model_rain_signal(votes, 0.1)
    assert weighted is True
    assert signal == pytest.approx(plain)
    assert (n_rain, n_total) == (plain_rain, plain_total) == (2, 3)
    assert signal == pytest.approx(200.0 / 3.0)


def test_weighted_signal_gate_falls_back_below_min_samples():
    # one model has too few samples (and one has no accuracy row at all)
    # -> weighted_applied is False and the plain equal-weight signal is
    # returned (1 of 2 -> 50 %)
    votes = [_vote("a", 0.5), _vote("b", 0.0)]
    accuracy = {"a": {"n_samples": 47, "event_accuracy": 1.0, "mae_mm": 0.0}}
    signal, n_rain, n_total, weighted = weighted_model_signal(votes, accuracy, 0.1, 48)
    assert weighted is False
    assert (n_rain, n_total) == (1, 2)
    assert signal == pytest.approx(50.0)
    assert signal == pytest.approx(model_rain_signal(votes, 0.1)[0])


def test_weighted_signal_more_accurate_model_pulls_share():
    # a: rain, accuracy 0.9 -> weight 0.9
    # b: dry,  accuracy 0.3 -> weight 0.3
    # weighted: 100 * 0.9 / (0.9 + 0.3) = 75  (plain would be 50)
    votes = [_vote("a", 0.5), _vote("b", 0.0)]
    accuracy = {
        "a": {"n_samples": 100, "event_accuracy": 0.9, "mae_mm": 0.1},
        "b": {"n_samples": 100, "event_accuracy": 0.3, "mae_mm": 0.4},
    }
    signal, n_rain, n_total, weighted = weighted_model_signal(votes, accuracy, 0.1, 48)
    assert weighted is True
    assert (n_rain, n_total) == (1, 2)
    assert signal == pytest.approx(75.0)
    assert signal > model_rain_signal(votes, 0.1)[0]  # 75 > 50: pulled toward a's rain vote


def test_weighted_signal_zero_accuracy_uses_0p1_floor():
    # a: rain with event_accuracy 0.0 -> weight floored at 0.1
    # b: dry,  accuracy 0.9 -> weight 0.9
    # weighted: 100 * 0.1 / (0.1 + 0.9) = 10  (a is down-weighted, not muted)
    votes = [_vote("a", 0.5), _vote("b", 0.0)]
    accuracy = {
        "a": {"n_samples": 100, "event_accuracy": 0.0, "mae_mm": 0.5},
        "b": {"n_samples": 100, "event_accuracy": 0.9, "mae_mm": 0.1},
    }
    signal, _n_rain, _n_total, weighted = weighted_model_signal(votes, accuracy, 0.1, 48)
    assert weighted is True
    assert signal == pytest.approx(10.0)


def test_weighted_signal_skips_models_without_data():
    # c has no data -> does not vote and does not trip the gate either
    votes = [_vote("a", 0.5), _vote("b", 0.0), _vote("c", None)]
    accuracy = {
        "a": {"n_samples": 100, "event_accuracy": 0.9, "mae_mm": 0.1},
        "b": {"n_samples": 100, "event_accuracy": 0.3, "mae_mm": 0.4},
    }
    signal, n_rain, n_total, weighted = weighted_model_signal(votes, accuracy, 0.1, 48)
    assert weighted is True
    assert (n_rain, n_total) == (1, 2)
    assert signal == pytest.approx(75.0)


def test_weighted_signal_no_voting_models():
    signal, n_rain, n_total, weighted = weighted_model_signal(
        [_vote("a", None)], {}, 0.1, 48
    )
    assert (signal, n_rain, n_total, weighted) == (None, 0, 0, False)


def test_explanation_accuracy_weighted_flag():
    plain = build_explanation(True, True, 3, 6, 42.0, 0.1)
    assert "accuracy-weighted" not in plain
    weighted = build_explanation(True, True, 3, 6, 42.0, 0.1, accuracy_weighted=True)
    assert "3 of 6 models predict > 0.1 mm in the next hour, accuracy-weighted" in weighted


# ---------------------------------------------------------------------------
# ensemble vote
# ---------------------------------------------------------------------------
def _ensemble(members: list[list[float | None]]) -> EnsembleData:
    hours = [NOW.replace(minute=0, second=0) + timedelta(hours=i) for i in range(4)]
    return EnsembleData(hourly_time=hours, member_precip_mm=members)


def test_ensemble_vote_share():
    # now = 11:30 -> the next hour is [11:30, 12:30); the first step stamped
    # after now is idx0 (stamped 12:00, covering 11:00-12:00, the next hour).
    data = _ensemble(
        [
            [1.0, 0, 0, 0],  # rain at idx0
            [0.0, 0, 0, 0],  # dry at idx0
            [0.05, 0, 0, 0],  # below threshold (0.1)
            [3.0, 0, 0, 0],  # rain at idx0
        ]
    )
    vote = ensemble_vote(data, 0.1, NOW - timedelta(minutes=30))
    assert vote.n_members == 4
    assert vote.n_rain_members == 2
    assert vote.probability_pct == pytest.approx(50.0)


def test_ensemble_vote_now_exactly_on_boundary_selects_next_index():
    # steps are stamped 12:00, 13:00, ...; at now = 12:00 exactly, idx0
    # (stamped 12:00) covers 11:00-12:00 and is the past, so idx1 (stamped
    # 13:00, covering 12:00-13:00) must be selected.
    data = _ensemble(
        [
            [0.0, 5.0, 0, 0],  # dry at idx0 (past), rain at idx1 (next hour)
            [0.0, 5.0, 0, 0],
        ]
    )
    vote = ensemble_vote(data, 0.1, NOW)
    assert vote.n_rain_members == 2
    assert vote.probability_pct == pytest.approx(100.0)


def test_ensemble_vote_uses_current_hour():
    # now = 12:30 -> the next hour is [12:30, 13:30); the first step stamped
    # after now is idx1 (stamped 13:00, covering 12:00-13:00).
    now = NOW + timedelta(minutes=30)
    data = _ensemble(
        [
            [0.0, 5.0, 0, 0],  # dry at idx0, rain at idx1
            [0.0, 0.0, 0, 0],  # dry at idx1
        ]
    )
    vote = ensemble_vote(data, 0.1, now)
    assert vote.n_rain_members == 1
    assert vote.probability_pct == pytest.approx(50.0)


def test_ensemble_vote_stale_is_none():
    # now beyond the series (all hours in the past)
    now = NOW + timedelta(hours=5)
    data = _ensemble([[1.0, 0, 0, 0], [1.0, 0, 0, 0]])
    vote = ensemble_vote(data, 0.1, now)
    assert vote.probability_pct is None


def test_ensemble_vote_none_inputs():
    assert ensemble_vote(None, 0.1, NOW).probability_pct is None
    assert ensemble_vote(EnsembleData(), 0.1, NOW).probability_pct is None


def test_ensemble_vote_skips_null_members():
    # now = 11:30 -> idx0 (stamped 12:00) is the next hour
    data = _ensemble([[1.0, 0, 0, 0], [None, 0, 0, 0]])
    vote = ensemble_vote(data, 0.1, NOW - timedelta(minutes=30))
    # only member 0 is usable; it rains -> 100%
    assert vote.n_rain_members == 1
    assert vote.probability_pct == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# combination
# ---------------------------------------------------------------------------
def test_combine_all_signals_weighted():
    prob, weights = combine_signals(
        PROB,
        radar_available=True,
        radar_raining=True,   # radar = 100
        model_pct=50.0,
        ensemble_pct=25.0,
    )
    # 0.5*100 + 0.3*50 + 0.2*25 = 50 + 15 + 5 = 70
    assert prob == pytest.approx(70.0)
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_combine_radar_dry_lowers_probability():
    prob, _ = combine_signals(
        PROB,
        radar_available=True,
        radar_raining=False,  # radar = 0
        model_pct=100.0,
        ensemble_pct=100.0,
    )
    # 0.5*0 + 0.3*100 + 0.2*100 = 50
    assert prob == pytest.approx(50.0)


def test_combine_without_radar_renormalizes():
    prob, weights = combine_signals(
        PROB,
        radar_available=False,
        radar_raining=None,
        model_pct=100.0,
        ensemble_pct=0.0,
    )
    # models:ensemble = 0.3:0.2 -> 0.6:0.4 ; 0.6*100 + 0.4*0 = 60
    assert prob == pytest.approx(60.0)
    assert abs(weights["models"] - 0.6) < 1e-9
    assert abs(weights["ensemble"] - 0.4) < 1e-9
    assert "radar" not in weights


def test_combine_models_only():
    prob, weights = combine_signals(
        PROB, radar_available=False, radar_raining=None, model_pct=30.0, ensemble_pct=None
    )
    assert prob == pytest.approx(30.0)
    assert weights == {"models": 1.0}


def test_combine_no_signals_is_zero():
    prob, weights = combine_signals(
        PROB, radar_available=False, radar_raining=None, model_pct=None, ensemble_pct=None
    )
    assert prob == 0.0
    assert weights == {}


def test_combine_clamps_to_100():
    prob, _ = combine_signals(
        PROB, radar_available=True, radar_raining=True, model_pct=100.0, ensemble_pct=100.0
    )
    assert prob == 100.0


# ---------------------------------------------------------------------------
# explanation
# ---------------------------------------------------------------------------
def test_explanation_all_sources():
    text = build_explanation(True, True, 3, 6, 42.0, 0.1)
    assert "Radar: yes" in text
    assert "3 of 6 models" in text
    assert "ensemble 42 %" in text


def test_explanation_no_radar():
    text = build_explanation(False, None, 0, 4, None, 0.1)
    assert "Radar: not available" in text
    assert "ensemble: n/a" in text
