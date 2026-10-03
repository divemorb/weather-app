"""Pure per-model accuracy scoring.

Scores the *same yes/no event* the next-hour vote uses (precipitation
``> threshold_mm``), not the raw millimetres: MAE alone is misleading,
because during a dry spell a model that always says 0 mm has a near-zero
MAE without ever being right about rain. ``mae_mm`` is still reported for
context; the headline score is ``event_accuracy``.
"""
from __future__ import annotations

Row = tuple[str, float, float]  # (model, precip_mm, observed_mm)


def model_accuracy(
    rows: list[Row], threshold_mm: float
) -> dict[str, dict[str, float | int | None]]:
    """Score forecast-vs-observation pairs, grouped per model.

    ``rows`` are ``(model, precip_mm, observed_mm)`` triples from
    :meth:`app.store.Store.compared_forecasts`; models without samples are
    absent from the result. The rain event is ``> threshold_mm`` (strict:
    a value at the threshold counts as "dry", matching the vote).
    """
    by_model: dict[str, list[tuple[float, float]]] = {}
    for model, precip, observed in rows:
        by_model.setdefault(model, []).append((precip, observed))

    result: dict[str, dict[str, float | int | None]] = {}
    for model, pairs in by_model.items():
        n = len(pairs)
        abs_error = 0.0
        hits = misses = false_alarms = correct_negatives = 0
        for precip, observed in pairs:
            abs_error += abs(precip - observed)
            forecast_rain = precip > threshold_mm
            observed_rain = observed > threshold_mm
            if forecast_rain and observed_rain:
                hits += 1
            elif observed_rain:
                misses += 1
            elif forecast_rain:
                false_alarms += 1
            else:
                correct_negatives += 1
        result[model] = {
            "n_samples": n,
            "mae_mm": abs_error / n if n else None,
            "hits": hits,
            "misses": misses,
            "false_alarms": false_alarms,
            "correct_negatives": correct_negatives,
            "event_accuracy": (hits + correct_negatives) / n if n else None,
        }
    return result
