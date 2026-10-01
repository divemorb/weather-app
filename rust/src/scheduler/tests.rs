use std::sync::Arc;
use std::time::Duration;

use chrono::TimeDelta;
use serde_json::json;

use super::*;
use crate::aggregator::testkit::{self, *};

#[tokio::test]
async fn scheduled_jobs_run_refreshes_on_event_loop() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let agg = Arc::new(make_aggregator(
        make_cfg(&fake, CfgOpts::default()),
        memory_store(),
    ));
    let scheduler = Arc::new(Scheduler::new());
    scheduler.start_with_periods(
        agg.clone(),
        Duration::from_millis(50),
        Duration::from_millis(50),
    );
    for _ in 0..100 {
        let bs = !fake.requests_to("/bs/current_weather").is_empty();
        let om = !fake.requests_to("/om/v1/forecast").is_empty();
        if bs && om {
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(
        !fake.requests_to("/bs/current_weather").is_empty(),
        "the radar job ran a refresh"
    );
    assert!(
        !fake.requests_to("/om/v1/forecast").is_empty(),
        "the models job ran a refresh"
    );
}

#[tokio::test]
async fn schedule_status_reports_next_runs() {
    let fake = FakeUpstream::start();
    let payloads = make_payloads();
    serve(&fake, &payloads, &[]);
    let cfg = make_cfg(&fake, CfgOpts::default());
    let agg = Arc::new(make_aggregator(cfg.clone(), memory_store()));
    let scheduler = Arc::new(Scheduler::new());
    scheduler.start(agg.clone());
    let status = schedule_status(Some(&scheduler), &cfg, agg.now());
    let radar = &status["jobs"]["radar"];
    let models = &status["jobs"]["models"];
    assert_eq!(radar["sources"], json!(["radar", "current"]));
    assert_eq!(models["sources"], json!(["forecast", "ensemble"]));
    assert_eq!(
        radar["interval_minutes"],
        json!(cfg.scheduling.radar_interval_minutes)
    );
    assert_eq!(
        models["interval_minutes"],
        json!(cfg.scheduling.models_interval_minutes)
    );
    // first run is one interval after start (the test clock is fixed)
    let now = agg.now();
    assert_eq!(
        radar["next_run_utc"],
        json!(to_iso(
            now + TimeDelta::minutes(cfg.scheduling.radar_interval_minutes)
        ))
    );
    assert_eq!(
        models["next_run_utc"],
        json!(to_iso(
            now + TimeDelta::minutes(cfg.scheduling.models_interval_minutes)
        ))
    );
}

#[test]
fn schedule_status_without_running_scheduler() {
    let fake = FakeUpstream::start();
    let cfg = make_cfg(&fake, CfgOpts::default());
    // not started: the jobs have no next run time yet
    let scheduler = Scheduler::new();
    let status = schedule_status(Some(&scheduler), &cfg, testkit::now());
    assert_eq!(status["jobs"]["radar"]["next_run_utc"], json!(null));
    // no scheduler at all (e.g. API tests without the lifespan)
    let status = schedule_status(None, &cfg, testkit::now());
    assert_eq!(status["jobs"]["models"]["next_run_utc"], json!(null));
}
