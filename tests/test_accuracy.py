"""Unit tests for the pure per-model accuracy scorer.

The scorer evaluates the same yes/no event the next-hour vote uses
(``> threshold_mm``), so a model that is always dry during a dry spell
scores well on event accuracy (and its low MAE is not mistaken for skill).
"""
from __future__ import annotations

import pytest

from app.accuracy import model_accuracy

THRESHOLD = 0.1


def rows_for(pairs_by_model: dict[str, list[tuple[float, float]]]) -> list[tuple[str, float, float]]:
    """Build (model, precip_mm, observed_mm) rows from per-model pairs."""
    return [
        (model, precip, observed)
        for model, pairs in pairs_by_model.items()
        for precip, observed in pairs
    ]


def test_confusion_counts_and_mae():
    rows = rows_for(
        {
            "icon_d2": [
                (0.4, 0.3),   # hit (both > 0.1)
                (0.0, 0.2),   # miss (dry forecast, rain observed)
                (0.5, 0.0),   # false alarm (rain forecast, dry observed)
                (0.0, 0.0),   # correct negative
            ],
            # 0.2 > 0.1 (rain forecast) but 0.1 is NOT > 0.1 (dry observed)
            "gfs_seamless": [(0.2, 0.1)],  # -> false alarm
        }
    )
    result = model_accuracy(rows, THRESHOLD)
    d2 = result["icon_d2"]
    assert d2["n_samples"] == 4
    assert (d2["hits"], d2["misses"], d2["false_alarms"], d2["correct_negatives"]) == (1, 1, 1, 1)
    assert d2["event_accuracy"] == pytest.approx(0.5)
    # MAE: (0.1 + 0.2 + 0.5 + 0.0) / 4
    assert d2["mae_mm"] == pytest.approx(0.2)
    # observed 0.1 is exactly at the threshold -> NOT rain (strict >)
    gfs = result["gfs_seamless"]
    assert (gfs["hits"], gfs["false_alarms"]) == (0, 1)
    assert gfs["event_accuracy"] == pytest.approx(0.0)


def test_threshold_is_strict_greater_than():
    rows = rows_for({"icon_d2": [(THRESHOLD, THRESHOLD), (THRESHOLD, 0.0)]})
    result = model_accuracy(rows, THRESHOLD)
    # forecast exactly at the threshold counts as "dry" in both rows
    assert result["icon_d2"]["correct_negatives"] == 2
    assert result["icon_d2"]["event_accuracy"] == pytest.approx(1.0)


def test_all_dry_spell_scores_perfectly():
    """The all-dry case: an all-zero model wins on event accuracy during a
    dry spell (which is correct — it *was* right about no rain)."""
    rows = rows_for(
        {
            "always_zero": [(0.0, 0.0)] * 5,
            "always_wet": [(2.0, 0.0)] * 5,
        }
    )
    result = model_accuracy(rows, THRESHOLD)
    zero = result["always_zero"]
    assert zero["event_accuracy"] == pytest.approx(1.0)
    assert zero["correct_negatives"] == 5
    assert zero["mae_mm"] == pytest.approx(0.0)
    wet = result["always_wet"]
    assert wet["event_accuracy"] == pytest.approx(0.0)
    assert wet["false_alarms"] == 5
    assert wet["mae_mm"] == pytest.approx(2.0)


def test_mae_favors_zero_model_but_event_accuracy_does_not():
    """MAE alone would crown the all-zero model; event accuracy separates
    skill from luck in a dry spell when rain eventually happens."""
    rows = rows_for(
        {
            "always_zero": [(0.0, 0.0), (0.0, 1.0)],   # MAE 0.5, event accuracy 0.5
            "always_wet": [(1.0, 0.0), (1.0, 1.0)],    # MAE 0.5, event accuracy 0.5
            "good": [(0.0, 0.0), (1.2, 1.0)],          # MAE 0.1, event accuracy 1.0
        }
    )
    result = model_accuracy(rows, THRESHOLD)
    assert result["always_zero"]["mae_mm"] == pytest.approx(0.5)
    assert result["always_wet"]["mae_mm"] == pytest.approx(0.5)
    assert result["good"]["mae_mm"] == pytest.approx(0.1)
    assert result["good"]["event_accuracy"] == pytest.approx(1.0)
    assert result["always_zero"]["event_accuracy"] == pytest.approx(0.5)


def test_empty_rows_give_empty_result():
    assert model_accuracy([], THRESHOLD) == {}


def test_models_without_samples_are_absent():
    rows = rows_for({"icon_d2": [(0.2, 0.1)]})
    result = model_accuracy(rows, THRESHOLD)
    assert set(result) == {"icon_d2"}
