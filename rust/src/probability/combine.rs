//! Signal 3 (ensemble vote), the linear combination of the three signals
//! and the human-readable explanation (Python `app/probability.py`, from
//! `_hour_index_best_overlap` to the end).

use chrono::{DateTime, TimeDelta, Utc};

use crate::config::ProbabilityConfig;
use crate::models::{EnsembleData, EnsembleVote};
use crate::pyfmt::{py_fmt_0f, py_fmt_g, py_sum};

/// Index of the hourly step that overlaps `[now, now + 1 h)` the most.
///
/// Open-Meteo hourly precipitation is a *preceding-hour sum*: the value at
/// time `t` is the rain of the hour `[t - 1 h, t)`. Picking the first stamp
/// *after* `now` would give the clock hour that *contains* `now`: at
/// `now = 10:50` that is the stamp 11:00, covering 10:00-11:00, of which 50
/// minutes are already over. So instead pick the step with the largest
/// overlap with the next 60 minutes, which works out to simply the first
/// stamp `t` with `t >= now + 30 min`:
///
/// - `now = 10:00` -> stamp 11:00 (covers 10:00-11:00, 60 min overlap)
/// - `now = 10:20` -> stamp 11:00 (40 min)
/// - `now = 10:30` -> stamp 11:00 (30 min; tie, the earlier stamp wins)
/// - `now = 10:50` -> stamp 12:00 (covers 11:00-12:00, 50 min)
///
/// Returns None when no stamp is at least 30 minutes ahead of `now` (a
/// stale series).
fn hour_index_best_overlap(times: &[DateTime<Utc>], now: DateTime<Utc>) -> Option<usize> {
    let limit = now + TimeDelta::minutes(30);
    times.iter().position(|t| *t >= limit)
}

/// Share of ensemble members with > `threshold_mm` in the next hour
/// (`[now, now + 1 h)`). The ensemble has hourly data only, so it uses the
/// hourly step that overlaps the next 60 minutes the most (see
/// [`hour_index_best_overlap`]). Returns a None probability when the cached
/// series is stale (no step at least 30 min ahead) or has no usable
/// members.
pub fn ensemble_vote(
    ensemble: Option<&EnsembleData>,
    threshold_mm: f64,
    now: DateTime<Utc>,
) -> EnsembleVote {
    let Some(ensemble) = ensemble else {
        return EnsembleVote {
            probability_pct: None,
            n_members: 0,
            n_rain_members: 0,
        };
    };
    if ensemble.n_members() == 0 {
        return EnsembleVote {
            probability_pct: None,
            n_members: 0,
            n_rain_members: 0,
        };
    }
    let Some(idx) = hour_index_best_overlap(&ensemble.hourly_time, now) else {
        return EnsembleVote {
            probability_pct: None,
            n_members: ensemble.n_members(),
            n_rain_members: 0,
        };
    };
    let mut n = 0_usize;
    let mut n_rain = 0_usize;
    for member in &ensemble.member_precip_mm {
        // A member shorter than `idx` (or a null at `idx`) is skipped: it
        // does not vote, it does not dilute the share either.
        let Some(v) = member.get(idx).copied().flatten() else {
            continue;
        };
        n += 1;
        if v > threshold_mm {
            n_rain += 1;
        }
    }
    if n == 0 {
        return EnsembleVote {
            probability_pct: None,
            n_members: ensemble.n_members(),
            n_rain_members: 0,
        };
    }
    EnsembleVote {
        probability_pct: Some(100.0 * n_rain as f64 / n as f64),
        n_members: ensemble.n_members(),
        n_rain_members: n_rain,
    }
}

/// Combine the available signals into a 0..100 % probability.
///
/// A missing signal (None) drops out and the remaining weights are
/// re-normalized. Returns `(probability_pct, weights_used)`; the weights
/// are in signal order (radar, models, ensemble).
pub fn combine_signals(
    prob_cfg: &ProbabilityConfig,
    radar_available: bool,
    radar_raining: Option<bool>,
    model_pct: Option<f64>,
    ensemble_pct: Option<f64>,
) -> (f64, Vec<(String, f64)>) {
    let mut signals: Vec<(&str, f64)> = Vec::new();
    if radar_available && radar_raining.is_some() {
        signals.push((
            "radar",
            if radar_raining == Some(true) {
                100.0
            } else {
                0.0
            },
        ));
    }
    if let Some(p) = model_pct {
        signals.push(("models", p));
    }
    if let Some(p) = ensemble_pct {
        signals.push(("ensemble", p));
    }
    if signals.is_empty() {
        return (0.0, Vec::new());
    }

    // Python `base`: the radar weight is only used when the radar signal is
    // available, otherwise the models and ensemble weights apply.
    let base_weight = |key: &str| -> f64 {
        match key {
            "radar" if radar_available => prob_cfg.weight_radar,
            "radar" => 0.0,
            "models" => prob_cfg.weight_models,
            _ => prob_cfg.weight_ensemble,
        }
    };
    let mut weights: Vec<f64> = signals.iter().map(|(k, _)| base_weight(k)).collect();
    let mut total = py_sum(weights.iter().copied());
    if total <= 0.0 {
        // Configured weights for all available signals are zero: fall back
        // to equal weighting so the app still produces a number.
        weights = vec![1.0; signals.len()];
        total = signals.len() as f64;
    }
    let weights_used: Vec<(String, f64)> = signals
        .iter()
        .zip(weights.iter())
        .map(|((k, _), w)| (k.to_string(), w / total))
        .collect();
    // Python: `sum(weights[k] * signals[k] for k in signals)` — the
    // normalized weight times the signal, compensated sum.
    let prob = py_sum(
        signals
            .iter()
            .zip(weights.iter())
            .map(|((_, s), w)| (w / total) * s),
    );
    (prob.clamp(0.0, 100.0), weights_used)
}

/// Human-readable derivation for the UI.
///
/// e.g. `Radar: yes; 3 of 6 models predict > 0.1 mm in the next hour,
/// accuracy-weighted; ensemble 42 %`
///
/// `accuracy_weighted` is only True when the accuracy-weighted model signal
/// was actually applied — the flag, not the config switch — so the text
/// never claims weighting that the gate fell back from.
pub fn build_explanation(
    radar_available: bool,
    radar_raining: Option<bool>,
    models_rain: usize,
    models_total: usize,
    ensemble_pct: Option<f64>,
    models_threshold_mm: f64,
    accuracy_weighted: bool,
) -> String {
    let radar_part = if radar_available && radar_raining.is_some() {
        if radar_raining == Some(true) {
            "Radar: yes"
        } else {
            "Radar: no"
        }
    } else {
        "Radar: not available"
    };
    let mut models_part = format!(
        "{models_rain} of {models_total} models predict > {} mm in the next hour",
        py_fmt_g(models_threshold_mm)
    );
    if accuracy_weighted {
        models_part.push_str(", accuracy-weighted");
    }
    let ensemble_part = match ensemble_pct {
        Some(pct) => format!("ensemble {} %", py_fmt_0f(pct)),
        None => "ensemble: n/a".to_string(),
    };
    format!("{radar_part}; {models_part}; {ensemble_part}")
}

#[cfg(test)]
mod tests;

#[cfg(test)]
mod zero_weight_tests;
