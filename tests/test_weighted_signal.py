"""Unit tests for the accuracy-weighted model signal."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models import ModelVote
from app.probability import build_explanation, model_rain_signal, weighted_model_signal

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)


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
