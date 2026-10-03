//! Scheduler wiring: the refresh cadence for the cache (Python
//! `app/scheduler.py`).
//!
//! Radar (Bright Sky) every N minutes (default 5), models (Open-Meteo)
//! every M minutes (default 60) — never on page load. One `tokio::spawn`ed
//! loop per job: the refresh runs inside the loop, so a slow run delays the
//! next tick instead of overlapping it (Python's `max_instances=1` and
//! `coalesce=True`). A failing source never breaks the app: the aggregator
//! keeps the stale cache and records the last error.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use chrono::{DateTime, TimeDelta, Utc};
use serde_json::{Map, Value, json};

use crate::aggregator::{Aggregator, Job};
use crate::config::AppConfig;
use crate::store::Source;
use crate::times::to_iso;

/// The next run time per job (for the `/api/schedule` UI countdown).
#[derive(Default)]
pub struct Scheduler {
    next_runs: Mutex<HashMap<Job, DateTime<Utc>>>,
}

impl Scheduler {
    pub fn new() -> Self {
        Self::default()
    }

    /// The next run of `job`, `None` while it has not started yet.
    pub fn next_run(&self, job: Job) -> Option<DateTime<Utc>> {
        self.next_runs
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .get(&job)
            .copied()
    }

    pub fn set_next_run(&self, job: Job, t: DateTime<Utc>) {
        self.next_runs
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .insert(job, t);
    }

    /// Spawn both refresh jobs with the configured intervals.
    pub fn start(self: &Arc<Self>, agg: Arc<Aggregator>) {
        let cfg = agg.cfg();
        let radar = interval(cfg.scheduling.radar_interval_minutes);
        let models = interval(cfg.scheduling.models_interval_minutes);
        self.start_with_periods(agg, radar, models);
    }

    /// `start` with explicit periods.
    pub fn start_with_periods(
        self: &Arc<Self>,
        agg: Arc<Aggregator>,
        radar: Duration,
        models: Duration,
    ) {
        for (job, period) in [(Job::Radar, radar), (Job::Models, models)] {
            let period_delta = TimeDelta::from_std(period).unwrap_or(TimeDelta::zero());
            // First run one period after start.
            self.set_next_run(job, agg.now() + period_delta);
            let scheduler = Arc::clone(self);
            let agg = Arc::clone(&agg);
            tokio::spawn(async move {
                let mut ticker =
                    tokio::time::interval_at(tokio::time::Instant::now() + period, period);
                ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
                loop {
                    ticker.tick().await;
                    scheduler.set_next_run(job, agg.now() + period_delta);
                    match job {
                        Job::Radar => {
                            tracing::info!("scheduled radar refresh");
                            agg.refresh_radar().await;
                        }
                        Job::Models => {
                            tracing::info!("scheduled models refresh");
                            agg.refresh_models().await;
                        }
                    }
                }
            });
        }
    }
}

/// The job period for a configured interval in minutes. A value <= 0
/// becomes 1 second (APScheduler does this for 0; the config doesn't
/// validate it).
fn interval(minutes: i64) -> Duration {
    u64::try_from(minutes)
        .ok()
        .filter(|m| *m > 0)
        .map_or(Duration::from_secs(1), |m| {
            Duration::from_secs(m.saturating_mul(60))
        })
}

/// Python `schedule_status`: next run per job for the UI countdown.
/// `server_time_utc` lets the browser correct for its own clock offset;
/// `next_run_utc` is null while the scheduler isn't running (a job added
/// before `start()` has no next run time yet).
pub fn schedule_status(
    scheduler: Option<&Scheduler>,
    cfg: &AppConfig,
    now: DateTime<Utc>,
) -> Value {
    let mut jobs = Map::new();
    for job in Job::ALL {
        let interval_minutes = match job {
            Job::Radar => cfg.scheduling.radar_interval_minutes,
            Job::Models => cfg.scheduling.models_interval_minutes,
        };
        let next_run_utc = scheduler.and_then(|s| s.next_run(job)).map(to_iso);
        let sources: Vec<&str> = job.sources().into_iter().map(Source::key).collect();
        jobs.insert(
            job.key().to_string(),
            json!({
                "interval_minutes": interval_minutes,
                "next_run_utc": next_run_utc,
                "sources": sources,
            }),
        );
    }
    json!({
        "server_time_utc": to_iso(now),
        "jobs": jobs,
    })
}

/// Python `initial_refresh`: warm the cache once at startup (radar and
/// models at the same time). A slow or failing source can't delay startup:
/// each refresh handles its own errors.
pub async fn initial_refresh(agg: &Aggregator) {
    tokio::join!(agg.refresh_radar(), agg.refresh_models());
}

#[cfg(test)]
mod tests;
